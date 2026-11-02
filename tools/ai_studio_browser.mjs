/** Google AI Studio browser driver. Use only with the tab and inventory from cua_repl.
 * No browser launch, login, private API call, polling timer or auto-submit at import.
 */
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const activeTabs = new Set();
const sha = value => createHash('sha256').update(value).digest('hex');
const fingerprint = request => sha(JSON.stringify(Object.fromEntries(
  Object.keys(request).filter(k => k !== 'request_sha256').sort().map(k => [k, request[k]])
)));

async function pageState(tab) {
  // Read only visible controls and their associated rendered media; never cookies,
  // page internals, access tokens or network endpoints. Audio data is not logged.
  return tab.playwright.evaluate(() => ({
    buttons: [...document.querySelectorAll('button')].map(e => ({
      label: e.getAttribute('aria-label') || '', text: e.innerText,
      disabled: e.disabled || e.getAttribute('aria-disabled') === 'true',
    })),
    text: [...document.querySelectorAll('textarea[aria-label="Speech block text"]')]
      .map(e => e.value),
    body: document.body.innerText,
    alerts: [...document.querySelectorAll('[role="alert"], [role="alertdialog"]')]
      .filter(e => e.getClientRects().length).map(e => e.innerText),
    playerDuration: Number(document.querySelector('input[aria-label="Seek audio position"]')?.getAttribute('max')),
    audio: [...document.querySelectorAll('audio')].map(e => ({
      // Browser-tool string results have size limits. Never request the whole URI.
      src: (e.currentSrc || e.getAttribute('src') || '').slice(0, 128),
      length: (e.currentSrc || e.getAttribute('src') || '').length, ready: e.readyState,
    })),
  }));
}

async function captureVisibleIssue(tab, request, state, evidenceDir) {
  const issue = /error|failed|captcha|verify (?:you are|that you are) human|not a robot|forbidden|permission denied|quota|too many requests|오류|실패|보안 인증|로봇이 아닙니다/i;
  const body = String(state.body || '').replace(request.text, '').replace(request.style, '');
  const text = [...new Set([
    ...(state.alerts || []).filter(value => issue.test(value)),
    ...(body.match(/Http response[^\n]*http status code:\s*[45]\d{2}[^\n]*|(?:verify (?:you are|that you are) human|I'm not a robot|로봇이 아닙니다|보안 인증|captcha)[^\n]*/gi) || []),
  ])].join('\n');
  if (!text) return null;
  const observedAt = new Date().toISOString();
  let bytes, capturedAt, captureError;
  // First browser operation after detecting the issue: do not read the page again
  // or click anything before capturing a potentially transient notification.
  try { bytes = await tab.screenshot({fullPage: false}); capturedAt = new Date().toISOString(); }
  catch (error) { captureError = String(error.message || error); }
  const directory = evidenceDir || join(fileURLToPath(new URL('../data/ai-studio-errors/', import.meta.url)), sha(String(request.request_id || request.request_sha256)).slice(0, 16));
  await mkdir(directory, {recursive: true});
  const stem = `${Date.now()}-${randomUUID()}`;
  const screenshotPath = bytes ? join(directory, stem + '.jpg') : null;
  if (bytes) await writeFile(screenshotPath, bytes, {flag: 'wx'});
  const evidence = {request_id: request.request_id, text_sha256: request.text_sha256,
    observed_at: observedAt, captured_at: capturedAt || null,
    recorded_at: new Date().toISOString(), observed_text: text,
    screenshot_path: screenshotPath, screenshot_sha256: bytes ? sha(bytes) : null,
    ...(captureError ? {capture_error: captureError} : {}),
    evidence_path: join(directory, stem + '.json'),
    scope: 'Visible issue text and the next screenshot; inspect pixels before claiming the text remains visible. No retry or challenge solving.'};
  await writeFile(evidence.evidence_path, JSON.stringify(evidence, null, 2), {flag: 'wx'});
  return evidence;
}

function visibleIssueError(evidence) {
  return Object.assign(new Error('Visible AI Studio issue; inspect the saved evidence before continuing'),
    {error_evidence: evidence});
}

export async function readRenderedWav(tab) {
  const info = await tab.playwright.evaluate(() => {
    const nodes = [...document.querySelectorAll('audio')];
    const src = nodes[0]?.currentSrc || nodes[0]?.getAttribute('src') || '';
    return { count: nodes.length, length: src.length, prefix: src.slice(0, 128) };
  });
  const header = 'data:audio/wav;base64,';
  if (info.count !== 1 || !info.prefix.startsWith(header) || info.length <= header.length)
    throw new Error('Unverified audio source format; inspect before saving');
  const pieces = [];
  for (let offset = header.length; offset < info.length; offset += 64000) {
    const part = await tab.playwright.evaluate(({offset}) => {
      const e = document.querySelector('audio');
      const src = e?.currentSrc || e?.getAttribute('src') || '';
      return {length: src.length, prefix: src.slice(0, 128), part: src.slice(offset, offset + 64000)};
    }, {offset});
    if (part.length !== info.length || part.prefix !== info.prefix ||
        part.part.length !== Math.min(64000, info.length - offset))
      throw new Error('Rendered audio changed or was truncated during export');
    pieces.push(part.part);
  }
  const encoded = pieces.join('');
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || encoded.length % 4 !== 0)
    throw new Error('Rendered WAV base64 is incomplete');
  return Buffer.from(encoded, 'base64');
}

function checkSettings(state, request) {
  const { buttons } = state;
  if (!buttons.some(b => b.label.startsWith(`Google 계정: ${request.profile_name}(`)))
    throw new Error('Expected logged-in 사원2 Google account is not visible');
  if (!buttons.some(b => b.text.split(/\s+/).includes(request.model)))
    throw new Error('Selected AI Studio model differs from the prepared request');
  if (!buttons.some(b => b.text.trim() === `Speaker 1 - ${request.voice_name}\narrow_drop_down`))
    throw new Error('Selected AI Studio voice differs from the prepared request');
  if (!buttons.some(b => b.label === 'Style' &&
      b.text.replace(/\s*arrow_drop_down\s*$/, '').trim() === request.style))
    throw new Error('AI Studio delivery style differs from the prepared request');
  if (!state.body.includes(request.voice_description))
    throw new Error('Custom voice description differs from the prepared request');
  if (state.text.length !== 1)
    throw new Error('Exactly one whole-script speech block is required');
}

export async function inspectSpeech(tab, browserInfo, request, {evidenceDir} = {}) {
  if (evidenceDir && !isAbsolute(evidenceDir)) throw new Error('An absolute evidenceDir is required');
  if (browserInfo.family !== 'chrome' || browserInfo.profileName !== '사원2' ||
      request.profile_name !== '사원2')
    throw new Error('Use the existing 사원2 Chrome profile');
  const url = new URL(await tab.url());
  if (url.origin !== 'https://aistudio.google.com' || url.pathname !== '/generate-speech')
    throw new Error('Expected the AI Studio generate-speech page');
  if (!tab.id || request.provider !== 'google-ai-studio-browser' || !request.text?.trim() ||
      !/^[a-f0-9]{64}$/.test(request.request_sha256 || '') ||
      sha(request.text) !== request.text_sha256 || fingerprint(request) !== request.request_sha256)
    throw new Error('Invalid prepared browser request');
  const state = await pageState(tab);
  const error_evidence = await captureVisibleIssue(tab, request, state, evidenceDir);
  if (error_evidence) return {state, error_evidence};
  checkSettings(state, request);
  return { state, run: tab.playwright.getByRole('button', { name: /^Run\b/ }) };
}

export async function submitSpeech(tab, browserInfo, request, { replaceExistingText = false, evidenceDir } = {}) {
  if (activeTabs.has(tab.id)) throw new Error('This tab already has a submitted request; do not resubmit');
  // Lock before the first await so concurrent callers cannot both press Run.
  activeTabs.add(tab.id);
  let mayHaveSubmitted = false;
  try {
    const { state, run, error_evidence } = await inspectSpeech(tab, browserInfo, request, {evidenceDir});
    if (error_evidence) throw visibleIssueError(error_evidence);
    if (state.text[0] && !(await run.isEnabled()))
      throw new Error('AI Studio is busy or Run is unavailable');
    if (state.text[0] && state.text[0] !== request.text && !replaceExistingText)
      throw new Error('Existing script preserved; use a dedicated prepared tab');
    await tab.playwright.getByRole('textbox', { name: 'Speech block text', exact: true })
      .fill(request.text);
    const ready = await pageState(tab);
    const readyIssue = await captureVisibleIssue(tab, request, ready, evidenceDir);
    if (readyIssue) throw visibleIssueError(readyIssue);
    checkSettings(ready, request);
    if (ready.text[0] !== request.text) throw new Error('Whole script did not reach the speech block');
    if (!(await run.isEnabled())) throw new Error('Run is unavailable after script preparation');
    const beforeAudio = ready.audio.length ? sha(await readRenderedWav(tab)) : null;
    // A click timeout may still have submitted. Keep the lock on every such error.
    mayHaveSubmitted = true;
    await run.click();
    return { tab, browserInfo, request: structuredClone(request), beforeAudio,
      submittedAt: Date.now(), finished: false, evidenceDir };
  } catch (error) {
    if (!mayHaveSubmitted) activeTabs.delete(tab.id);
    throw error;
  }
}

export async function pollSpeech(handle, { timeoutMs = 300000 } = {}) {
  if (handle.finished) throw new Error('Request already downloaded');
  if (handle.errorOutcome) return handle.errorOutcome;
  const { state, run, error_evidence } = await inspectSpeech(handle.tab, handle.browserInfo, handle.request,
    {evidenceDir: handle.evidenceDir});
  if (error_evidence) {
    const idle = state.audio.length === 0 && state.buttons.some(button => /^Run\b/.test(button.text.trim()) && !button.disabled);
    handle.errorOutcome = {status: idle ? 'failed_no_audio' : 'blocked', error_evidence};
    return handle.errorOutcome;
  }
  if (state.text[0] !== handle.request.text) throw new Error('Submitted script changed; stop here');
  if (handle.publicDownload) {
    const data = await verifiedPublicDownload(handle, state, handle.publicDownload);
    return {status: 'ready', audio_sha256: sha(data), route: 'public-download-control'};
  }
  if (state.audio.length === 0 && await run.isEnabled())
    return { status: 'failed_no_audio' };
  if (state.audio.length === 1 && state.audio[0].src &&
      state.audio[0].ready >= 2 && await run.isEnabled()) {
    const audio_sha256 = sha(await readRenderedWav(handle.tab));
    if (audio_sha256 !== handle.beforeAudio) return { status: 'ready', audio_sha256 };
  }
  if (Date.now() - handle.submittedAt >= timeoutMs)
    throw new Error('AI Studio outcome is uncertain; inspect the same tab, do not resubmit');
  return { status: 'pending' };
}

function pcmDuration(data) {
  if (data.length < 44 || data.toString('ascii',0,4) !== 'RIFF' ||
      data.toString('ascii',8,12) !== 'WAVE' || data.readUInt32LE(4) + 8 !== data.length)
    throw new Error('Public download is not a complete RIFF WAV');
  let format, size;
  for (let offset=12; offset+8<=data.length;) {
    const length=data.readUInt32LE(offset+4), end=offset+8+length;
    if (end>data.length) throw new Error('Public WAV chunk is truncated');
    const kind=data.toString('ascii',offset,offset+4);
    if (kind==='fmt ') {
      if (length<16) throw new Error('Public WAV format is truncated');
      format=[data.readUInt16LE(offset+8),data.readUInt16LE(offset+10),
        data.readUInt32LE(offset+12),data.readUInt16LE(offset+20),data.readUInt16LE(offset+22)];
    }
    if (kind==='data') { if (size!==undefined) throw new Error('Multiple WAV payloads'); size=length; }
    offset=end+(length%2);
  }
  if (!format || format.join(',')!=='1,1,24000,2,16' || !size || size%2)
    throw new Error('Expected complete mono PCM16 24kHz public WAV');
  return size/48000;
}

async function verifiedPublicDownload(handle, state, proof) {
  if (!proof || !isAbsolute(proof.path || '') || !/^[a-f0-9]{64}$/.test(proof.sha256 || '') ||
      !Array.isArray(proof.clickWindow) || proof.clickWindow.length!==2 ||
      !proof.clickWindow.every(Number.isFinite) || proof.clickWindow[0]<handle.submittedAt ||
      proof.clickWindow[1]<proof.clickWindow[0] || proof.clickWindow[1]>Date.now())
    throw new Error('Public download needs its observed click window and file SHA');
  if (state.buttons.some(b=>b.text.trim()==='Stop') ||
      !state.buttons.some(b=>b.label==='Download' && b.disabled===false) ||
      !(state.playerDuration>0))
    throw new Error('Matching player has not exposed a completed public download');
  const meta=await stat(proof.path), data=await readFile(proof.path);
  if (meta.mtimeMs<proof.clickWindow[0] || meta.mtimeMs>proof.clickWindow[1] ||
      sha(data)!==proof.sha256 || sha(data)===handle.beforeAudio)
    throw new Error('Public download is stale or differs from the observed file');
  if (Math.abs(pcmDuration(data)-state.playerDuration)>1/24000+1e-6)
    throw new Error('Public WAV duration differs from the visible player');
  return data;
}

export async function registerPublicDownload(handle, proof) {
  if (handle.finished) throw new Error('Request already downloaded');
  const {state, error_evidence}=await inspectSpeech(handle.tab,handle.browserInfo,handle.request,
    {evidenceDir: handle.evidenceDir});
  if (error_evidence) throw visibleIssueError(error_evidence);
  if (state.text[0]!==handle.request.text) throw new Error('Submitted script changed; stop here');
  await verifiedPublicDownload(handle,state,proof);
  handle.publicDownload=structuredClone(proof);
  return pollSpeech(handle);
}

export async function finishNoAudio(handle) {
  // Explicitly acknowledge the observed terminal UI state; never retry Run here.
  if ((await pollSpeech(handle)).status !== 'failed_no_audio')
    throw new Error('Only an idle, matching request with no rendered audio can be closed');
  handle.finished = true;
  activeTabs.delete(handle.tab.id);
  return {status: 'failed_no_audio', request_id: handle.request.request_id};
}

export async function downloadSpeech(handle, { outputPath } = {}) {
  if (!outputPath || !isAbsolute(outputPath)) throw new Error('An absolute WAV outputPath is required');
  const ready = await pollSpeech(handle);
  if (ready.status !== 'ready') throw new Error('New audio is not ready');
  // The page renders a data URI. Read its existing DOM bytes in bounded chunks;
  // download events and downloadMedia are unavailable on the observed Chrome route.
  let data;
  if (handle.publicDownload) {
    const {state, error_evidence} = await inspectSpeech(handle.tab,handle.browserInfo,handle.request,
      {evidenceDir: handle.evidenceDir});
    if (error_evidence) throw visibleIssueError(error_evidence);
    data = await verifiedPublicDownload(handle, state, handle.publicDownload);
  } else data = await readRenderedWav(handle.tab);
  const audio_sha256 = sha(data);
  if (audio_sha256 !== ready.audio_sha256)
    throw new Error('Downloaded file differs from the newly observed audio; stop here');
  await writeFile(outputPath, data, {flag: 'wx'});
  handle.finished = true;
  activeTabs.delete(handle.tab.id);
  const { text, ...identity } = handle.request;
  return { path: outputPath, receipt: { ...identity, fresh_audio: true, audio_sha256,
    ...(handle.publicDownload ? {download_route:'public-download-control',
      public_download:handle.publicDownload} : {}) } };
}

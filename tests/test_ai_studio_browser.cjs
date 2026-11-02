const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { mkdtemp, readFile, writeFile, utimes, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const driver = import('../tools/ai_studio_browser.mjs');
const sha = value => createHash('sha256').update(value).digest('hex');
let nextTab = 0;

function fixture() {
  const request = { provider: 'google-ai-studio-browser', profile_name: '사원2',
    request_id: 'one', text: '전체 원고. 끝 문장.',
    model: 'gemini-3.8-flash-tts', voice_name: 'test voice',
    voice_description: 'Synthetic Korean voice', style: 'Warm and clear' };
  request.text_sha256 = sha(request.text);
  request.request_sha256 = sha(JSON.stringify(Object.fromEntries(
    Object.keys(request).sort().map(k => [k, request[k]]))));
  const info = { family: 'chrome', profileName: '사원2' };
  const state = { buttons: [
    {label: 'Google 계정: 사원2(test)', text: ''},
    {label: '', text: `Gemini 3.8 Flash TTS\n${request.model}`},
    {label: '', text: 'Speaker 1 - test voice\narrow_drop_down'},
    {label: 'Style', text: 'Warm and clear\narrow_drop_down'},
  ], text: [''], body: request.voice_description, audio: [{src:'data:audio/wav;base64,b2xk',ready:4}] };
  const calls = { run: 0, fill: 0, download: 0 };
  const tab = {
    id: String(++nextTab),
    url: async () => 'https://aistudio.google.com/generate-speech',
    playwright: {
      evaluate: async (fn, arg) => {
        const src = state.audio[0]?.src || '';
        if (arg && 'offset' in arg) return {length:src.length,prefix:src.slice(0,128),
          part:src.slice(arg.offset,arg.offset+64000)};
        if (String(fn).includes('const nodes')) return {count:state.audio.length,
          length:src.length,prefix:src.slice(0,128)};
        return structuredClone(state);
      },
      getByRole: (role, options) => ({
        fill: async value => { calls.fill++; state.text = [value]; },
        isEnabled: async () => true,
        click: async () => {
          if (String(options.name).includes('Run')) calls.run++;
          else calls.download++;
        },
      }),
    },
  };
  return { request, info, state, calls, tab };
}

test('inspection does not fill, submit or download', async () => {
  const f = fixture();
  await (await driver).inspectSpeech(f.tab, f.info, f.request);
  assert.deepEqual(f.calls, {run:0,fill:0,download:0});
});

test('transient HTTP error is captured before a second page read and is never resubmitted', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ai-studio-error-capture-'));
  try {
    const f = fixture(), d = await driver;
    const h = await d.submitSpeech(f.tab, f.info, f.request, {evidenceDir: dir});
    f.state.audio = [];
    f.state.buttons.push({label:'', text:'Run\nCtrl', disabled:false});
    const errorText = 'Http response at 400 or 500 level, error: , http status code: 403';
    f.state.body += '\n' + errorText;
    let reads = 0, shots = 0;
    const evaluate = f.tab.playwright.evaluate;
    f.tab.playwright.evaluate = async (...args) => {
      if (++reads > 1) f.state.body = f.request.voice_description;
      return evaluate(...args);
    };
    const bytes = Buffer.from('screenshot fixture: visible403');
    f.tab.screenshot = async () => {
      assert.equal(reads, 1, 'capture must precede another DOM observation');
      assert.ok(f.state.body.includes(errorText));
      shots++;
      f.state.body = f.request.voice_description;
      return bytes;
    };
    const result = await d.pollSpeech(h);
    assert.equal(result.status, 'failed_no_audio');
    assert.equal(result.error_evidence.observed_text, errorText);
    assert.deepEqual(await readFile(result.error_evidence.screenshot_path), bytes);
    const record = JSON.parse(await readFile(result.error_evidence.evidence_path, 'utf8'));
    assert.equal(record.request_id, f.request.request_id);
    assert.equal(record.text_sha256, f.request.text_sha256);
    assert.equal(record.screenshot_sha256, sha(bytes));
    assert.ok(record.captured_at >= record.observed_at);
    await d.pollSpeech(h);
    await d.finishNoAudio(h);
    assert.equal(reads, 1);
    assert.equal(shots, 1);
    assert.equal(f.calls.run, 1);
  } finally { await rm(dir, {recursive:true, force:true}); }
});

test('visible challenge is captured before any script fill or Run', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ai-studio-challenge-capture-'));
  try {
    const f = fixture(), d = await driver;
    f.state.alerts = ['Verify you are human'];
    f.tab.screenshot = async () => {
      assert.equal(f.calls.fill, 0);
      assert.equal(f.calls.run, 0);
      return Buffer.from('challenge screenshot fixture');
    };
    await assert.rejects(d.submitSpeech(f.tab, f.info, f.request, {evidenceDir:dir}), error => {
      assert.ok(error.error_evidence.screenshot_path);
      assert.equal(error.error_evidence.observed_text, 'Verify you are human');
      return true;
    });
    assert.equal(f.calls.fill, 0);
    assert.equal(f.calls.run, 0);
    assert.equal(f.calls.download, 0);
  } finally { await rm(dir, {recursive:true, force:true}); }
});

test('failed screenshot preserves observed error without claiming an image or retrying', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ai-studio-capture-failed-'));
  try {
    const f = fixture(), d = await driver;
    const h = await d.submitSpeech(f.tab, f.info, f.request, {evidenceDir:dir});
    f.state.audio = [];
    f.state.buttons.push({label:'', text:'Run', disabled:false});
    f.state.alerts = ['Permission denied'];
    f.tab.screenshot = async () => { throw new Error('capture unavailable'); };
    const result = await d.pollSpeech(h);
    const record = JSON.parse(await readFile(result.error_evidence.evidence_path, 'utf8'));
    assert.equal(record.screenshot_path, null);
    assert.equal(record.screenshot_sha256, null);
    assert.equal(record.observed_text, 'Permission denied');
    assert.equal(record.capture_error, 'capture unavailable');
    assert.equal(f.calls.run, 1);
    await d.finishNoAudio(h);
  } finally { await rm(dir, {recursive:true, force:true}); }
});

test('mutated request rejected before any browser submission', async () => {
  const f = fixture();
  f.request.style = 'changed';
  await assert.rejects((await driver).submitSpeech(f.tab, f.info, f.request), /Invalid/);
  assert.equal(f.calls.run, 0);
  assert.equal(f.calls.fill, 0);
});

test('wrong profile, model, voice, style and multiple blocks stop before Run', async () => {
  for (const mutate of [
    f => f.info.profileName = '돌',
    f => f.state.buttons[0].label = 'Google 계정: 돌(test)',
    f => f.state.buttons[1].text = 'other model',
    f => f.state.buttons[2].text = 'other voice',
    f => f.state.buttons[3].text = 'other style',
    f => f.state.body = 'other custom voice',
    f => f.state.text.push('second block'),
  ]) {
    const f = fixture(); mutate(f);
    await assert.rejects((await driver).submitSpeech(f.tab, f.info, f.request));
    assert.equal(f.calls.run, 0);
    assert.equal(f.calls.fill, 0);
  }
});

test('existing script preserved; concurrent submission runs only once', async () => {
  const f = fixture();
  f.state.text = ['user work'];
  await assert.rejects((await driver).submitSpeech(f.tab, f.info, f.request), /Existing script/);
  const outcomes = await Promise.allSettled([1,2].map(() =>
    driver.then(d => d.submitSpeech(f.tab, f.info, f.request, {replaceExistingText:true}))));
  assert.equal(outcomes.filter(o => o.status === 'fulfilled').length, 1);
  assert.equal(f.calls.run, 1);
  assert.equal(f.state.text[0], f.request.text);
});

test('empty tab may be filled while Run is disabled, then must become enabled before submission', async () => {
  const f = fixture(), get = f.tab.playwright.getByRole;
  f.state.audio = [];
  f.tab.playwright.getByRole = (role,options) => ({...get(role,options),
    isEnabled:async () => Boolean(f.state.text[0])});
  await (await driver).submitSpeech(f.tab,f.info,f.request);
  assert.equal(f.calls.run,1);
  assert.equal(f.state.text[0],f.request.text);
});

test('stale audio and timeout cannot download or automatically resubmit', async () => {
  const f = fixture(), d = await driver;
  const h = await d.submitSpeech(f.tab, f.info, f.request);
  assert.equal((await d.pollSpeech(h)).status, 'pending');
  await assert.rejects(d.downloadSpeech(h,{outputPath:join(tmpdir(),'not-written.wav')}), /not ready/);
  h.submittedAt = 0;
  await assert.rejects(d.pollSpeech(h), /uncertain/);
  await assert.rejects(d.submitSpeech(f.tab, f.info, f.request), /already/);
  assert.equal(f.calls.run, 1);
  assert.equal(f.calls.download, 0);
});

test('empty terminal result is acknowledged explicitly without retrying; busy request stays locked', async () => {
  const f = fixture(),d = await driver;
  const h = await d.submitSpeech(f.tab,f.info,f.request);
  await assert.rejects(d.finishNoAudio(h),/Only an idle/);
  f.state.audio = [];
  const get = f.tab.playwright.getByRole;
  f.tab.playwright.getByRole = (role,options) => ({...get(role,options),isEnabled:async()=>false});
  assert.equal((await d.pollSpeech(h)).status,'pending');
  await assert.rejects(d.finishNoAudio(h),/Only an idle/);
  f.tab.playwright.getByRole = get;
  assert.equal((await d.pollSpeech(h)).status,'failed_no_audio');
  await assert.rejects(d.submitSpeech(f.tab,f.info,f.request),/already/);
  assert.equal((await d.finishNoAudio(h)).status,'failed_no_audio');
  assert.equal(f.calls.run,1);
  assert.equal(f.calls.download,0);
  await assert.rejects(d.pollSpeech(h),/already/);
});

test('export bytes match newly observed audio; existing output preserved and receipt binds identity', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'voicebench-ai-studio-'));
  try {
    const f = fixture(), d = await driver;
    const h = await d.submitSpeech(f.tab, f.info, f.request);
    const path = join(dir, 'result.wav'), data = Buffer.from('new audio fixture');
    f.state.audio = [{src:`data:audio/wav;base64,${data.toString('base64')}`,ready:4}];
    const result = await d.downloadSpeech(h,{outputPath:path});
    assert.deepEqual(await readFile(path),data);
    assert.equal(result.receipt.request_sha256, f.request.request_sha256);
    assert.equal(result.receipt.audio_sha256, sha(data));
    assert.equal(result.receipt.fresh_audio, true);
    assert.equal(result.receipt.text, undefined);
    await assert.rejects(d.downloadSpeech(h,{outputPath:path}), /already/);
    assert.equal(f.calls.run, 1);
    const g = fixture(), second = await d.submitSpeech(g.tab,g.info,g.request);
    g.state.audio = f.state.audio;
    await assert.rejects(d.downloadSpeech(second,{outputPath:path}), /EEXIST/);
    assert.deepEqual(await readFile(path),data);
  } finally { await rm(dir, {recursive:true,force:true}); }
});

test('large rendered audio is read in bounded DOM chunks without truncation', async () => {
  const f = fixture(), data = Buffer.alloc(1600000,42);
  f.state.audio = [{src:`data:audio/wav;base64,${data.toString('base64')}`,ready:4}];
  assert.deepEqual(await (await driver).readRenderedWav(f.tab),data);
  const evaluate = f.tab.playwright.evaluate;
  f.tab.playwright.evaluate = async (fn,arg) => {
    const result = await evaluate(fn,arg);
    if (arg && 'offset' in arg) result.part = result.part.slice(0,-1);
    return result;
  };
  await assert.rejects((await driver).readRenderedWav(f.tab), /truncated/);
});

test('manual script changes and uncertain clicks keep original submission protected', async () => {
  const f = fixture(), d = await driver;
  const h = await d.submitSpeech(f.tab, f.info, f.request);
  f.state.text = ['changed'];
  await assert.rejects(d.pollSpeech(h), /changed/);
  const g = fixture();
  g.tab.playwright.getByRole = () => ({fill:async v => g.state.text = [v],
    isEnabled:async () => true, click:async () => {throw new Error('click timed out');}});
  await assert.rejects(d.submitSpeech(g.tab, g.info, g.request), /timed out/);
  await assert.rejects(d.submitSpeech(g.tab, g.info, g.request), /already/);
});

test('public Download accepts only fresh complete matching-player PCM and preserves one submission', async () => {
  const dir=await mkdtemp(join(tmpdir(),'ai-studio-public-'));
  try {
    const f=fixture(),d=await driver;
    f.state.audio=[];
    const h=await d.submitSpeech(f.tab,f.info,f.request);
    h.submittedAt=Date.now()-10000;
    const get=f.tab.playwright.getByRole;
    f.tab.playwright.getByRole=(r,o)=>({...get(r,o),isEnabled:async()=>false});
    f.state.audio=[{src:'data:audio/wav;base64,cGxhY2Vob2xkZXI=',ready:4}];
    f.state.playerDuration=1;
    f.state.buttons.push({label:'Download',text:'download',disabled:false});
    assert.equal((await d.pollSpeech(h)).status,'pending');
    const wav=Buffer.alloc(48044);
    wav.write('RIFF'); wav.writeUInt32LE(wav.length-8,4); wav.write('WAVEfmt ',8);
    wav.writeUInt32LE(16,16); wav.writeUInt16LE(1,20); wav.writeUInt16LE(1,22);
    wav.writeUInt32LE(24000,24); wav.writeUInt32LE(48000,28);
    wav.writeUInt16LE(2,32); wav.writeUInt16LE(16,34);
    wav.write('data',36); wav.writeUInt32LE(48000,40);
    const path=join(dir,'download.wav'),outputPath=join(dir,'accepted.wav');
    await writeFile(path,wav);
    await utimes(path,new Date(Date.now()-1000),new Date(Date.now()-1000));
    const proof={path,sha256:sha(wav),clickWindow:[h.submittedAt,Date.now()]};
    f.state.playerDuration=32;
    await assert.rejects(d.registerPublicDownload(h,proof),/duration/);
    f.state.playerDuration=1;
    await utimes(path,new Date(0),new Date(0));
    await assert.rejects(d.registerPublicDownload(h,proof),/stale/);
    await utimes(path,new Date(Date.now()-1000),new Date(Date.now()-1000));
    f.state.text=['other request'];
    await assert.rejects(d.registerPublicDownload(h,proof),/changed/);
    f.state.text=[f.request.text];
    const ready=await d.registerPublicDownload(h,proof);
    assert.equal(ready.status,'ready');
    assert.equal(ready.route,'public-download-control');
    const result=await d.downloadSpeech(h,{outputPath});
    assert.deepEqual(await readFile(outputPath),wav);
    assert.equal(result.receipt.audio_sha256,sha(wav));
    assert.equal(result.receipt.request_sha256,f.request.request_sha256);
    assert.equal(result.receipt.download_route,'public-download-control');
    assert.equal(f.calls.run,1);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

/* 오늘의 터진 게시물 - 서버 판정 결과를 표시하고 기준을 저장한다. */
(async function () {
  'use strict';
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  let R = window.HOTPOST_REPORT;
  const dailyRanking = () => R?.ranking_mode === 'views_per_follower_72h';
  async function loadCollectionHealth() {
    const el=$('#collection-health');if(!el)return;
    try{
      const responses=await Promise.all([fetch('/api/collection-status',{cache:'no-store'}),fetch('/api/accounts',{cache:'no-store'})]);
      if(responses.some(r=>!r.ok))throw new Error('수집 상태 조회 실패');
      const [data,accounts]=await Promise.all(responses.map(r=>r.json()));
      window.CollectionNotifications.update(window.HotpostNotices.collection(data,accounts.accounts,R||{}));
    }catch(_){
      window.CollectionNotifications.update({title:'수집 상태를 확인하지 못했습니다.',tone:'warning',
        solution:'서버 연결을 확인하고 상태를 다시 조회하세요. 계속 실패하면 서버 실행 상태를 확인하세요.',
        actions:[{label:'상태 다시 확인',run:loadCollectionHealth},{label:'서버 확인 방법',href:'accounts.html#help-server'}]});
    }
  }
  loadCollectionHealth();
  setInterval(loadCollectionHealth, 60000);

  // ---------- 유틸 ----------
  const fmt = (n) => {
    if (n === null || n === undefined) return '–';
    if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, '') + '억';
    if (n >= 1e4) return (n / 1e4).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, '') + '만';
    return Math.round(n).toLocaleString('ko-KR');
  };
  const ago = (h) => (h < 1 ? '방금' : h < 24 ? Math.round(h) + '시간 전' : h < 24 * 14 ? Math.round(h / 24) + '일 전' : Math.round(h / 24 / 7) + '주 전');
  const dateStr = (ts) => new Date(ts * 1000).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',timeZone:'Asia/Seoul' });
  const ratioCls = (r) => (r == null ? 'flat' : r >= 2.5 ? 'up' : r >= 1.5 ? 'mid' : r >= 0.8 ? 'flat' : 'down');
  const ratioTxt = (r) => (r == null ? '' : '×' + (r >= 10 ? Math.round(r) : r.toFixed(1)));
  const tierTxt = (t) => ({ 0: '', 1: '🔥', 2: '🔥🔥', 3: '🔥🔥🔥' })[t];
  const kindTxt = (k) => ({ reel: '릴스', video: '동영상', image: '사진', carousel: '캐러셀' })[k] || k;
  const flagTxt = { comments_spike: '💬 댓글 급증', views_spike: '👀 조회수 급증', likes_spike: '❤️ 좋아요 급증', fresh: '🆕 48시간 내', rising: '📈 상승 중',
    ad_candidate: '광고 후보', sponsored_candidate: '협찬 후보', group_buy_candidate: '공동구매 후보', event_candidate: '이벤트 후보' };
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const initials = (u) => (u || '?').replace(/[^a-z0-9가-힣]/gi, '').slice(0, 2).toUpperCase();
  const isVideo = (p) => p.kind === 'reel' || p.kind === 'video';
  const store = {
    get: (k, d) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };

  // ---------- 테마 ----------
  const themeBtn = $('#theme-toggle');
  const applyTheme = (t) => {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    themeBtn.textContent = cur === 'dark' ? '☀️' : '🌙';
  };
  applyTheme(store.get('hp-theme', ''));
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark'; applyTheme(next); store.set('hp-theme', next);
  });

  if (!R) {
    $('#meta').textContent = '아직 리포트가 없습니다.';
    $('#app').innerHTML = '<div class="empty" style="margin-top:24px">데이터가 없습니다. 터미널에서 <code>python -m hotpost run</code> 을 실행한 뒤 새로고침하세요.</div>';
    return;
  }

  // ---------- 판정 기준 ----------
  let acctMap = Object.fromEntries((R.accounts || []).map((account) => [account.username, account]));
  let POSTS=[];
  function recompute(){POSTS=R.posts.slice();}
  // ---------- 헤더 / 배너 ----------
  function renderReportMetadata(){
  $('#meta').textContent = `${R.generated_at_kst} 기준 · 판정 v${R.criteria.version} · ${R.summary.accounts}개 계정 · 최근 ${R.settings.recent_days}일 게시물 ${R.posts.length}개 분석`;
  const sb = $('#source-badge'); sb.classList.remove('sample','live');
  if (R.is_sample) { sb.textContent = '샘플 데이터'; sb.classList.add('sample'); }
  else { sb.textContent = { instaloader: '실데이터 · 세션 수집', web: '실데이터 · 웹 수집', dump: '실데이터 · 브라우저 덤프' }[R.source] || '실데이터'; sb.classList.add('live'); }
  if(R.is_sample)window.HotpostNotices.show($('#banner'),{title:'샘플 게시물이 표시되고 있습니다.',tone:'info',
    solution:'전용 Instagram 로그인 상태를 확인한 뒤 수집을 실행하면 실제 게시물로 바뀝니다.',
    actions:[{label:'실제 데이터 수집 방법',href:'accounts.html#help-collect'}]});
  }
  renderReportMetadata();

  // ---------- 상태 ----------
  let saved;
  try {saved=await window.HotpostDisplay.load();} catch(e){saved={...window.HotpostDisplay.defaults};window.HotpostNotices.show($('#banner'),{title:'저장된 화면 설정을 불러오지 못해 기본 조건을 표시합니다.',tone:'warning',solution:'설정 페이지에서 서버 연결과 저장된 조건을 확인한 뒤 다시 열어 주세요.',actions:[{label:'설정 확인',href:'settings.html'}]});}
  const state={...saved,q:'',topic:null,production:'all'};
  if(dailyRanking())Object.assign(state,{sort:'rank',assessment:'all',detection:'all',period:72});
  const linkedAccount=new URLSearchParams(location.search).get('account');if(linkedAccount)state.account=linkedAccount;
  function currentSettings(){
    const c=R.criteria.values;
    if(dailyRanking()) {
      $('#current-settings').innerHTML=`<p>최근 72시간 게시물 · 팔로워 대비 조회수순</p><p>조회수 ${fmt(c.minViews)} 이상 · 팔로워 대비 ${esc(c.t1)}배 이상</p><p>표시 게시물 <strong id="result-count">0</strong>개</p><p id="result-context" hidden></p>`;
      return;
    }
    const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true">${({filter:'<path d="M4 6h16M7 12h10M10 18h4"/>',calendar:'<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 11h16"/>',sort:'<path d="M7 4v16m-4-4 4 4 4-4M14 5h7m-7 5h5m-5 5h3"/>',video:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4Z"/>',settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>'})[name]}</svg>`;
    const period=state.detection==='today'?['오늘',window.HotpostDetection.dateKey(Date.now()/1000).slice(5).replace('-','/')]:state.period===24?['24','시간']:[state.period/24,'일'];
    const sort={rank:'급상승순',views:'조회수순',comments:'댓글순',likes:'좋아요순',recent:'최근 발견순'}[state.sort];
    const full=window.HotpostDisplay.describe(state).split(' · ');
    const expanded=$('#current-settings details')?.open;
    $('#current-settings').innerHTML=`<div class="discovery-summary-head"><span>${icon('filter')}현재 보기</span><a href="settings.html" class="icon-button" aria-label="보기 설정 변경" title="보기 설정 변경">${icon('settings')}</a></div>
      <div class="discovery-numbers"><div class="discovery-count"><span class="summary-label">표시 게시물</span><div><strong id="result-count" aria-live="polite">0</strong><span>개</span></div></div><div class="discovery-period"><span class="summary-label">${icon('calendar')}${state.detection==='today'?'발견 시각':'발견 시각 · 최근'}</span><div><strong>${period[0]}</strong><span>${period[1]}</span></div></div></div>
      <div class="discovery-badges"><span>${icon('sort')}${sort}</span><span>${icon('video')}${{all:'전체 유형',video:'릴스',image:'사진'}[state.kind]}</span><span>${state.tier?'🔥'.repeat(state.tier)+' 이상':'전체 등급'}</span></div>
      <p id="result-context" class="result-context" hidden></p>
      <details class="discovery-conditions" ${expanded?'open':''}><summary>세부 조건</summary><div class="condition-tags">${full.map(v=>`<span>${esc(v)}</span>`).join('')}</div><div class="threshold-caption">급상승 등급 기준</div><ol class="threshold-scale" aria-label="급상승 등급 기준">${[1,2,3].map(n=>`<li class="${n===state.tier?'selected':''}"><span class="threshold-mark" aria-hidden="true"></span><strong>${esc(c['t'+n])}<small>배</small></strong><span>${'🔥'.repeat(n)}</span></li>`).join('')}</ol></details>`;
  }
  currentSettings();
  function showSearch(open){$('#search-box').hidden=!open;$('#search-toggle').setAttribute('aria-expanded',String(open));$('#search-toggle').setAttribute('aria-label',open?'검색창 닫기':'검색창 열기');if(open)$('#q').focus();}
  $('#search-toggle').onclick=()=>{const open=$('#search-box').hidden;showSearch(open);if(!open){$('#q').value='';state.q='';renderAll();}};
  $('#q').addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();showSearch(false);$('#q').value='';state.q='';renderAll();$('#search-toggle').focus();}});
  let qt;$('#q').addEventListener('input',e=>{const query=e.target.value.trim().toLowerCase();clearTimeout(qt);qt=setTimeout(()=>{state.q=query;renderAll();},150);});
  $$('[data-production-filter]').forEach(button=>button.addEventListener('click',()=>{
    state.production=button.dataset.productionFilter;
    $$('[data-production-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    renderAll();
  }));
  // Query rules are independent of rendering and can be tested without a browser.
  const discovery=window.HotpostDiscovery.create(window.HotpostDetection);
  const topicsEl = $('#topics');
  function renderTopics(base) {
    const list = discovery.topics(base,state);
    topicsEl.innerHTML = list.length ? '' : '<span class="hint">이 조건에서는 주제를 뽑을 만큼 핫 게시물이 없습니다.</span>';
    list.forEach((t) => {
      const el = document.createElement('button');
      el.className = 'chip' + (t.kind === 'keyword' ? ' kw' : '') + (state.topic === t.label ? ' on' : '');
      el.innerHTML = `${esc(t.label)} <span class="n">${t.posts}</span>`;
      el.title = `${t.accounts}개 계정 · ${t.posts}개 게시물`;
      el.addEventListener('click', () => { state.topic = state.topic === t.label ? null : t.label; renderAll(); });
      topicsEl.appendChild(el);
    });
  }

  // ---------- 통계 ----------
  function renderStats() {
    if(dailyRanking()) {
      const eligible=POSTS.filter(p=>p.eligible);
      $('#stats').innerHTML=[['기준 통과',eligible.length],['확인한 게시물',POSTS.length],['확인한 계정',R.accounts.length]]
        .map(([label,value])=>`<div class="stat"><div class="k">${label}</div><div class="v">${value}<small>개</small></div></div>`).join('');
      return;
    }
    const summary=discovery.dailyStats(POSTS);
    const stats=$('#stats');
    stats.dataset.day=summary.day;
    stats.innerHTML = [
      ['hot', '🔥 오늘 기준 통과', summary.total, '개'],
      ['hot', '오늘 성과 확인', summary.confirmed, '개'],
      ['hot', '오늘 잠정 후보', summary.provisional, '개'],
      ['', '오늘 발견 계정', summary.accounts, '개'],
      ['', '오늘 릴스 비중', summary.videoPercent, '%'],
    ].map(([c, k, v, u]) => `<div class="stat ${c}"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div></div>`).join('');
  }
  // ---------- 카드 ----------
  const productionByCode = new Map();
  const studioByCode = new Map();
  let studioLoaded=false,studioOnline=true,studioSyncedAt=0;
  const studioSelected = new Set();
  document.addEventListener('click', async e => {
    const choice = e.target.closest('.studio-choice');
    if (choice) {
      e.stopPropagation();
      if (e.target.type === 'checkbox') {
        const code = e.target.dataset.studioCode;
        if (e.target.checked) studioSelected.add(code); else studioSelected.delete(code);
        $('#studio-selection').hidden = studioSelected.size === 0;
        $('#studio-selected-count').textContent = `${studioSelected.size}개 선택`;
      }
      return;
    }
    if (e.target.id !== 'studio-add-selected') return;
    e.stopPropagation(); e.target.disabled = true;
    try {
      const response = await fetch('/api/studio', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({shortcodes:[...studioSelected]})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '제작실 추가 실패');
      location.href = 'studio.html?work=' + encodeURIComponent(result.tasks[0].id);
    } catch (error) { e.target.textContent = error.message; e.target.disabled = false; }
  }, true);
  function productionMarkup(code) {
    if(dailyRanking())return `<span>${esc(productionState(code).label)}</span>`;
    return window.AgentStatus.markup(agentState(code));
  }
  function agentState(code) {
    return window.AgentStatus.model(studioByCode.get(code),{legacy:productionByCode.get(code),loaded:studioLoaded,online:studioOnline&&(!studioSyncedAt||Date.now()-studioSyncedAt<15000)});
  }
  function productionState(code) {
    if(dailyRanking()) {
      const production=R.posts.find(p=>p.shortcode===code)?.production||{};
      if(production.state==='completed'&&!production.completed_video_ready)
        return {state:'attention',label:'완성본 확인 필요',action:'상태 확인'};
      const states={completed:{state:'completed',label:'완성',action:'완성 영상 보기'},
        not_started:{state:'idle',label:'미제작',action:'상세 보기'},
        in_progress:{state:'working',label:'제작 중',action:'진행 확인'},
        paused:{state:'attention',label:'중지',action:'상태 확인'},
        blocked:{state:'attention',label:'보류',action:'상태 확인'},
        unknown:{state:'attention',label:'제작 이력 미확인',action:'상태 확인'}};
      return states[production.state]||states.unknown;
    }
    const work = studioByCode.get(code);
    if (work) {
      const view = window.StudioBoard.describe(work), ready = work._summary?work.completed_video_ready:window.PostResult.model(work).active?.video_url;
      if (view.complete && ready) return {state:'completed',label:'완성',action:'완성 영상 보기',reason:'완성 영상을 재생하고 다운로드할 수 있어요.'};
      if(work.video_agent?.activity?.phase==='attention')return {state:'attention',label:'확인필요',action:'진행 확인',reason:work.video_agent.activity.detail};
      if (view.complete || view.attention || view.review || ['paused','unknown'].includes(view.state)) return {state:'attention',label:'확인필요',action:'상세 보기',reason:view.complete?'완성 영상 파일을 확인해 주세요.':view.message};
      return {state:'working',label:'제작중',action:'제작 보기',reason:view.message};
    }
    const job = productionByCode.get(code);
    if (job) {
      if (job.status === 'done' && job.variants?.some(v=>v.download_url)) return {state:'completed',label:'완성',action:'완성 영상 보기',reason:'이전 제작 결과를 다운로드할 수 있어요.'};
      if (['error','missing','done'].includes(job.status)) return {state:'attention',label:'확인필요',action:'상세 보기',reason:job.error||'제작 결과를 확인해 주세요.'};
      return {state:'working',label:'제작중',action:'제작 보기',reason:job.message||'자동 제작을 진행하고 있어요.'};
    }
    return {state:'idle',label:'제작 전',action:'상세 보기',reason:'아직 제작 작업이 등록되지 않았어요.'};
  }
  function legacyProductionMarkup(code) {
    const job = productionByCode.get(code);
    if (!job) return '';
    const source = job.source || {}, transcript = job.transcript || {};
    const link = (url, label) => url ? `<a class="production-link" href="${esc(url)}" onclick="event.stopPropagation()">${label}</a>` : `<span>${label}</span>`;
    const states = {queued:'대기',voice:'음성 생성 중',building:'프로젝트 생성 중',draft_ready:'프로젝트 완료',exporting:'내보내기 중',done:'완료',error:'실패 · 재시도 필요',missing:'결과 파일 없음'};
    const stageLabel = (status, runningLabel) => job.status === 'queued' && !['done','draft_ready','missing'].includes(status)
      ? '대기' : status === 'running' ? runningLabel : states[status] || '대기';
    return `<div>${link(source.download_url, source.download_url ? `소스 영상 다운로드 완료 · ${source.count}개 ↓` : '소스 영상 · ' + stageLabel(source.status, '찾는 중'))}</div>
      <div>${link(transcript.download_url, transcript.download_url ? '대본 다운로드 완료 ↓' : '대본 · ' + stageLabel(transcript.status, '추출 중'))}</div>
      ${(job.variants || []).map(v => `<div>${link(v.download_url, `쇼츠 V${v.version} · ${v.download_url ? '다운로드 ↓' : stageLabel(v.status, '제작 중')}`)} ${v.script_url ? link(v.script_url, '재작성 대본 ↓') : ''}</div>`).join('')}
      <small class="${job.status === 'error' ? 'production-error' : ''}">${esc(job.status === 'queued' ? '자동 제작 대기' : job.error || job.message)}</small>
      ${job.status === 'error' ? `<button class="btn ghost production-retry" data-code="${esc(code)}">중단 단계부터 다시 시도</button>` : ''}`;
  }
  let productionsRefreshing=false;
  async function refreshProductions() {
    if(dailyRanking()){studioLoaded=true;return;}
    if(productionsRefreshing)return;productionsRefreshing=true;
    try{
    const responses = await Promise.allSettled([
      fetch('/api/studio?view=list', {cache:'no-store',signal:AbortSignal.timeout(9000)}).then(r=>r.ok?r.json():null),
      fetch('/api/legacy-productions', {cache:'no-store',signal:AbortSignal.timeout(9000)}).then(r=>r.ok?r.json():null)
    ]);
    studioLoaded=true;
    studioOnline=responses[0].status==='fulfilled'&&Array.isArray(responses[0].value?.tasks);
    if (responses[0].status==='fulfilled' && responses[0].value?.tasks) {
      studioSyncedAt=Date.now();
      studioByCode.clear();
      for (const item of responses[0].value.tasks) studioByCode.set(item.shortcode,item);
    }
    try {
      const data = responses[1].status==='fulfilled'?responses[1].value:null;
      for (const item of data?.productions||[]) productionByCode.set(item.shortcode, item);
      if(state.production!=='all'){
        const next=visiblePosts(discovery.baseFiltered(POSTS,state));
        if(next.length!==current.length||next.some((post,i)=>post.shortcode!==current[i]?.shortcode))renderAll();
      }
      $$('#cards .card').forEach(card => {
        const code=card.dataset.code, status=productionState(code), badge=$('.production-status',card);
        if(!badge)return;
        card.dataset.productionState=status.state;
        card.dataset.agentLive=String(agentState(code).live);
        const markup=productionMarkup(code);if(badge.innerHTML!==markup)badge.innerHTML=markup;
        $('.card-open-production',card).textContent=status.action+' →';
      });
    } catch (_) { /* Keep verified last state while the server reconnects. */ }
    }finally{productionsRefreshing=false;}
  }
  document.addEventListener('click', async e => {
    const button = e.target.closest('.production-retry');
    if (!button) return;
    e.stopPropagation(); button.disabled = true;
    try {
      const response = await fetch(`/api/legacy-productions/${encodeURIComponent(button.dataset.code)}/retry`, {method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '재시도 실패');
      if(data.id?.startsWith('work-')) { location.href='studio.html?work='+encodeURIComponent(data.id); return; } productionByCode.set(data.shortcode, data); await refreshProductions();
    } catch (error) { button.textContent = error.message; button.disabled = false; }
  }, true);
  refreshProductions();
  setInterval(refreshProductions, 4000);
  // Stop activity motion even when a reconnecting request has not returned yet.
  setInterval(()=>{
    if(studioSyncedAt&&Date.now()-studioSyncedAt>=15000){
      $$('#cards .production-status').forEach(el=>{const code=el.dataset.code;el.closest('.card').dataset.agentLive='false';const next=productionMarkup(code);if(el.innerHTML!==next)el.innerHTML=next;});
    }
  },3000);
  function metric(label, val, ratio, na) {
    return `<div class="m ${na ? 'na' : ''}"><div class="k">${label}</div><div class="v">${na ? '–' : fmt(val)}</div><div class="r ${ratioCls(ratio)}">${na ? '' : ratioTxt(ratio) + (ratio != null ? ' 평소 대비' : '')}</div></div>`;
  }
  function card(p, i) {
    const thumb = p.thumb ? `<img loading="lazy" src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`;
    const status = productionState(p.shortcode);
    return `<article class="card" data-code="${esc(p.shortcode)}" ${isVideo(p) ? `data-production-state="${status.state}" data-agent-live="${agentState(p.shortcode).live}"` : ''}>
      <div class="thumb">${thumb}
        <div class="tl">${p.tier ? `<span class="pill t${p.tier}">${tierTxt(p.tier)} ×${p.multiplier.toFixed(1)}</span>` : `<span class="pill">×${p.multiplier.toFixed(1)}</span>`}</div>
        <div class="tr"><span class="pill kind">${kindTxt(p.kind)}${p.video_duration ? ' · ' + Math.round(p.video_duration) + 's' : ''}</span></div>
        <div class="rank">#${dailyRanking() ? p.rank : i + 1}</div>
      </div>
      <div class="body">
        <div class="who"><span class="avatar">${initials(p.username)}</span><span class="name">@${esc(p.username)}</span><span class="time" title="업로드 ${dateStr(p.taken_at)}">업로드 ${ago(Math.max(0,Date.now()/1000-p.taken_at)/3600)}</span></div>
        <div class="metrics benchmark-metrics">
          ${dailyRanking() ? `<div class="m"><div class="k">조회수 / 팔로워</div><div class="v">${esc(p.views_display||fmt(p.views))} / ${esc(p.followers_display||fmt(p.followers))}</div><div class="r">팔로워 대비 약 ${p.rank_score.toFixed(2)}배</div></div>` : isVideo(p) ? metric('조회수', p.views, p.ratios.views, p.views == null) : metric('좋아요', p.likes, p.ratios.likes, false)}
        </div>
        ${isVideo(p) ? `<div class="production-status" data-code="${esc(p.shortcode)}">${productionMarkup(p.shortcode)}</div>` : ''}
        <div class="foot"><button class="card-open-production">${isVideo(p) ? status.action+' →' : '게시물 보기 →'}</button><a href="${esc(p.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">원본 보기 ↗</a></div>
      </div>
    </article>`;
  }
  let current = [];
  function visiblePosts(base){
    return discovery.filtered(base,state).filter(post=>state.production==='all'||
      (isVideo(post)&&productionState(post.shortcode).state===state.production));
  }
  function render() {
    const base = discovery.baseFiltered(POSTS,state);
    current = visiblePosts(base);
    $('#cards').innerHTML = current.map(card).join('');
    const emp = $('#empty'); emp.hidden = current.length > 0;
    if (!current.length) emp.textContent = dailyRanking() ? '최근 72시간 게시물 중 현재 조건을 통과한 게시물이 없습니다.' : state.detection === 'today' ? '오늘 새로 발견한 게시물 중 현재 조건에 맞는 게시물이 없습니다. 오늘은 한국 시간 00시부터입니다.' : '선택한 기간에 새로 발견한 게시물 중 현재 조건에 맞는 게시물이 없습니다. 설정에서 발견 기간이나 다른 조건을 확인하세요.';
    if(!current.length&&state.production!=='all')emp.textContent=!studioLoaded?'영상 제작 상태를 확인하고 있어요…':
      state.production==='completed'?'현재 조건에 맞는 완성 영상이 없습니다.':'현재 조건에 맞는 제작 중 영상이 없습니다.';
    $('#result-count').textContent = current.length;
    $('#result-count').setAttribute('aria-label',`현재 표시 게시물 ${current.length}개`);
    const context=[state.production!=='all'?{completed:'완성',working:'제작 중'}[state.production]:'',state.topic,state.q?`검색: ${state.q}`:'',state.account?'@'+state.account:'',state.assessment!=='all'?{confirmed:'성과 확인',provisional:'잠정 후보'}[state.assessment]:''].filter(Boolean).join(' · ');
    $('#result-context').textContent=context;$('#result-context').hidden=!context;
    return base;
  }
  function renderAll() { recompute(); renderStats(); const base = render(); renderTopics(base); }

  // ---------- 상세 모달 ----------
  const modal = $('#modal');
  $('#cards').addEventListener('click', (e) => { const c = e.target.closest('.card'); if (c) openDetail(POSTS.find((p) => p.shortcode === c.dataset.code)); });
  modal.addEventListener('click', (e) => { if (e.target.dataset.close !== undefined) closeDetail(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDetail(); });
  modal.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const items = Array.from(modal.querySelectorAll('button:not(:disabled),a[href],input,textarea,video[controls]')).filter(el=>el.getClientRects().length);
    const first = items[0], last = items[items.length-1];
    if (e.shiftKey && document.activeElement===first) { e.preventDefault(); last?.focus(); }
    else if (!e.shiftKey && document.activeElement===last) { e.preventDefault(); first?.focus(); }
  });
  let flowTimer, flowCode;
  let preparationView = null, detailTrigger = null;
  function openDetail(p) {
    if (!p) return;
    preparationView?.close();
    clearTimeout(flowTimer); flowCode = null;
    modal.querySelectorAll('video,audio').forEach(v=>v.pause());
    detailTrigger = document.activeElement;
    const body = $('#modal-body');
    preparationView = window.PostPreparation.mount(body, p);
    modal.hidden = false; document.body.style.overflow = 'hidden';
    const dialog = $('.modal-card', modal);
    dialog.setAttribute('aria-label', '게시물 준비'); dialog.scrollTop = 0;
    $('[data-close].modal-close',modal).focus?.();
  }
  function closeDetail() { preparationView?.close(); preparationView=null; detailTrigger?.focus?.(); clearTimeout(flowTimer); flowCode=null; modal.querySelectorAll('video,audio').forEach(v=>v.pause()); modal.hidden = true; document.body.style.overflow = ''; }
  async function refreshProduction(code) {
    clearTimeout(flowTimer);
    if(flowCode!==code||modal.hidden)return;
    const root=$('#production-flow',modal);if(!root)return;
    try {
      const known=studioByCode.get(code);
      const data=known?{tasks:[known]}:await window.ProductionFlow.api('?view=list');
      if(flowCode!==code)return;
      const item=data.tasks.find(t=>t.shortcode===code);
      const task=item?._summary?await window.ProductionFlow.api('/'+item.id):item;
      if(flowCode!==code)return;
      if(task)window.PostResult.mount(root,task);
      else {
        window.PostResult.mountEmpty(root);
        const legacy=legacyProductionMarkup(code);
        if(legacy)root.insertAdjacentHTML('beforeend',`<section class="legacy-production-results"><h4>이전 제작 결과</h4>${legacy}</section>`);
        root.insertAdjacentHTML('beforeend','<button id="begin-auto" class="linkbtn">자동 제작 시작</button>');
        $('#begin-auto',root).onclick=async e=>{e.target.disabled=true;try{await window.ProductionFlow.api('',{shortcodes:[code],automatic:true});refreshProduction(code);}catch(err){e.target.disabled=false;root.append(document.createTextNode(err.message));}};
      }
    }catch(e){if(root._postId)window.PostResult.connectionError(root);else window.PostResult.mountEmpty(root,'제작 상태를 불러오지 못했어요. 잠시 후 자동으로 다시 확인합니다.');}
    if(flowCode===code)flowTimer=setTimeout(()=>refreshProduction(code),3000);
  }
  function bar(label, val, base, ratio) {
    return `<div class="detail-metric"><span>${label}</span><strong>${fmt(val)}</strong><small>평소 ${fmt(base)}</small><b class="r ${ratioCls(ratio)}">${ratio == null ? '비교 정보 없음' : ratioTxt(ratio)+' 평소 대비'}</b></div>`;
  }
  function openLegacyDetail(p) {
    if (!p) return;
    clearTimeout(flowTimer); flowCode=p.shortcode;
    const a = acctMap[p.username] || {};
    $('#modal-body').innerHTML = `<div class="detail production-detail"><div class="detail-body">
      <div class="benchmark-header">
      <div class="thumb">${p.thumb ? `<img src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`}</div>
      <div class="benchmark-summary">
        <span class="hint">벤치마크 원본 · ${kindTxt(p.kind)}</span>
        <h3>${p.tier ? '🔥 터진 ' : ''}${isVideo(p) ? '영상' : '게시물'}</h3>
        <div class="who"><span class="name">@${esc(p.username)}</span></div>
        <div class="benchmark-performance">${isVideo(p) ? `조회수 <strong>${fmt(p.views)}</strong>${p.ratios.views != null ? `<span>평소 조회수 대비 ${ratioTxt(p.ratios.views)}</span>` : ''}` : `좋아요 <strong>${fmt(p.likes)}</strong>${p.ratios.likes != null ? `<span>평소 좋아요 대비 ${ratioTxt(p.ratios.likes)}</span>` : ''}`}</div>
        <a href="${esc(p.url)}" target="_blank" rel="noopener">Instagram에서 원본 보기 ↗</a>
      </div></div>
        ${isVideo(p) ? '<div id="production-flow"></div>' : ''}
        <section class="video-info" aria-labelledby="video-info-title"><h4 id="video-info-title" class="video-info-title">${isVideo(p) ? '영상' : '게시물'} 정보</h4><div class="video-info-body">
        <p class="hint">게시일 ${dateStr(p.taken_at)} · ${ago(p.age_hours)}${a.full_name ? ' · '+esc(a.full_name) : ''}</p>
        <div class="fullcap">${esc(p.caption) || '(캡션 없음)'}</div>
        ${p.hashtags.length ? `<div class="tags">${p.hashtags.map((h) => `<span data-tag="${esc(h)}">#${esc(h)}</span>`).join('')}</div>` : ''}
        <div class="cmp">
          ${bar('조회수', p.views, p.baseline.views, p.ratios.views)}
          ${bar('좋아요', p.likes, p.baseline.likes, p.ratios.likes)}
          ${bar('댓글', p.comments, p.baseline.comments, p.ratios.comments)}
        </div>
        <div class="kv">
          <div>처음 발견한 시각 (한국 시간)<b>${p.hot_detected_at == null ? (p.tier ? '기록 없음' : '미발견') : dateStr(p.hot_detected_at)}</b></div>
          <div>팔로워<b>${fmt(a.followers)}</b></div>
          <div>비교 게시물<b>${p.baseline.peers}개</b></div>
        </div>
        ${p.flags.filter((f) => flagTxt[f]).length ? `<div class="flags">${p.flags.filter((f) => flagTxt[f]).map((f) => `<span class="flag">${flagTxt[f]}</span>`).join('')}</div>` : ''}
      </div></section></div></div>`;
    // Reference metadata stays visible below the production result.
    const benchmark=$('.benchmark-header',modal), info=$('.video-info-body',modal);
    if(isVideo(p)&&benchmark&&info)info.prepend(benchmark);
    $$('.tags span', modal).forEach((s) => s.addEventListener('click', () => { closeDetail(); state.q = '#' + s.dataset.tag; $('#q').value = state.q; showSearch(true); renderAll(); }));
    modal.hidden = false; document.body.style.overflow = 'hidden';
    if(isVideo(p)){window.PostResult.mountEmpty($('#production-flow',modal),'제작 상태를 확인하고 있어요.');refreshProduction(p.shortcode);}
  }

  const reportRefresh=window.HotpostReportRefresh.create({
    initial:R,
    fetchReport:async()=>{
      const response=await fetch('/api/report',{cache:'no-store'});
      if(!response.ok)throw new Error('수집 결과 조회 실패');
      return response.json();
    },
    onReport:report=>{
      R=report;window.HOTPOST_REPORT=report;
      if(dailyRanking())Object.assign(state,{sort:'rank',assessment:'all',detection:'all',period:72});
      acctMap=Object.fromEntries((R.accounts||[]).map(account=>[account.username,account]));
      renderReportMetadata();
    }
  });
  async function refreshDashboard(refreshSettings=false){
    const updates=[reportRefresh.refresh()];
    if(refreshSettings)updates.push(window.HotpostDisplay.load().then(fresh=>{
      Object.assign(state,fresh);if(linkedAccount)state.account=linkedAccount;
    }));
    // Failed fetches preserve the last verified report. Calendar filters still advance.
    await Promise.allSettled(updates);
    currentSettings();renderAll();
  }
  window.addEventListener('focus',()=>refreshDashboard(true));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshDashboard(true);});
  renderAll();
  const linkedPost = new URLSearchParams(location.search).get('post');
  if (linkedPost) openDetail(POSTS.find(p=>p.shortcode===linkedPost));
  // Calendar and rolling discovery windows both advance while this page stays open.
  setInterval(()=>refreshDashboard(), 60000);
})();

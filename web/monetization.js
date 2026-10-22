(() => {
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let timer;
  let publicationSupported = false;
  let automaticInputsSupported = false;
  let accountRolesSupported = false;
  let coupangReady = false;
  let savedAccount = '';
  let savedDiscoveryAccount = '';
  let tasks = [];
  let inputRequest = 0;
  const message = text => { $('#message').textContent = text; };
  async function request(path, data) {
    const response = await fetch('/api/monetization/' + path, data === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '요청을 완료하지 못했습니다.');
    return result;
  }
  async function connections() {
    const status = await request('connections');
    publicationSupported = status.publication_supported === true;
    automaticInputsSupported = status.automatic_inputs_supported === true && status.comment_keyword === '나도';
    accountRolesSupported = status.account_roles_supported === true;
    savedAccount = status.automation.account || '';
    savedDiscoveryAccount = status.automation.discovery_account || savedAccount;
    coupangReady = status.coupang.configured === true && status.coupang.eligible === true && Boolean(status.coupang.account_ref);
    $('#coupang-setup-notice').hidden = coupangReady;
    $('#connections').textContent = `쿠팡 API ${status.coupang.configured?'연결 값 저장됨':'연결 필요'} · 기존 수집 Chrome ${status.existing_browser_connected?'연결됨':'연결 필요'}`;
    $('#automation').elements.account.value = status.automation.account || '';
    $('#automation').elements.discovery_account.value = savedDiscoveryAccount;
    $('#automation').elements.enabled.checked = status.automation.enabled;
    updateStart();
    message(coupangReady ? '영상 완료 상태는 후속 작업 오류와 별도로 보존합니다.' : '설정에서 쿠팡파트너스 API를 먼저 설정해 주세요.');
  }
  function updateStart(state) {
    const task = tasks.find(row => row.id === $('#work').elements.task.value);
    $('#work button[type=submit]').disabled = !coupangReady || !automaticInputsSupported || !savedAccount || !task ||
      task.keyword !== '나도' || Boolean(state && (state.worker_live || state.external_result_uncertain ||
      state.status==='error' || state.account !== savedAccount || (state.discovery_account || state.account) !== savedDiscoveryAccount || ['awaiting_post','awaiting_delivery','completed'].includes(state.stage)));
  }
  function showInputs() {
    const task = tasks.find(row => row.id === $('#work').elements.task.value);
    $('#saved-account').textContent = savedAccount ? `상품 확인 댓글·DM: @${savedDiscoveryAccount} · 게시·리틀리: @${savedAccount}` : '위에서 우리 인스타 계정을 한 번 저장하세요.';
    $('#reference-keyword').textContent = task ? '댓글 요청 문구: ‘나도’ · 고정' : '선택할 완성 영상이 없습니다.';
    $('#binding-check').textContent = '';
    updateStart();
  }
  async function verifyBinding() {
    const task = $('#work').elements.task.value;
    if (!task || !automaticInputsSupported) return;
    const result = await request(encodeURIComponent(task)+'/preview');
    if (task !== $('#work').elements.task.value || result.account !== savedAccount) return;
    $('#binding-check').textContent = result.verified ? `연결 확인 완료: ${result.title} · 상품 확인 @${result.execution_discovery_account || result.execution_account} · 리틀리 @${result.execution_account} · 댓글 ‘${result.keyword}’` : `완성 영상·댓글 ‘${result.keyword}’ 확인됨. ${result.reason}`;
  }
  async function loadInputs(preferred) {
    const version = ++inputRequest;
    clearTimeout(timer);
    if (!automaticInputsSupported) {
      $('#work').elements.task.innerHTML = '<option value="">자동 입력 기능의 서버 적용이 필요합니다.</option>';
      showInputs(); return;
    }
    const data = await request('inputs' + (preferred ? '?task='+encodeURIComponent(preferred) : ''));
    if (version !== inputRequest) return;
    tasks = data.tasks;
    $('#work').elements.task.innerHTML = tasks.length ? tasks.map(task => `<option value="${esc(task.id)}">${esc(task.title)}</option>`).join('') : '<option value="">완성 영상이 아직 없습니다.</option>';
    $('#work').elements.task.value = data.selected_task_id;
    showInputs();
    if (data.selection_error) message(data.selection_error);
  }
  async function refresh() {
    clearTimeout(timer);
    const task = $('#work').elements.task.value.trim();
    if (!task) return;
    try {
      const {state} = await request(encodeURIComponent(task));
      if (task !== $('#work').elements.task.value) return;
      updateStart(state);
      if (!state) { $('#result').textContent = '아직 후속 작업을 시작하지 않았습니다.'; return; }
      const labels = {product:'상품 확인',affiliate:'제휴 링크 발급',caption:'게시글 본문',littly:'리틀리 설정',awaiting_post:'다음 게시물 연결 대기',awaiting_delivery:'댓글·DM 발송 확인 대기',completed:'후속 작업 완료'};
      const waiting = String(state.status||'').startsWith('waiting_') ? state.status : state.automatic_followup?.status;
      const waits = {waiting_slot:'앞선 상품 연결 대기',waiting_connections:'계정·API 연결 대기'};
      const phases = {uploading:'영상·표지 업로드 중',submitting:'게시 제출 중',platform_processing:'인스타 처리 대기',awaiting_confirmation:'게시 결과 확인 대기',post_connected:'게시물·리틀리 연결 확인됨'};
      const status = state.status==='error'?'오류':state.worker_live?'진행 중':state.external_result_uncertain?'실행 결과 미확인':waits[waiting]|| (state.stage==='awaiting_post'?'등록 설정 확인됨':state.stage==='awaiting_delivery'?'실제 발송 확인 대기':state.stage==='completed'?'완료':'준비');
      $('#result').innerHTML = `<h3>${esc(labels[state.stage]||state.stage)} · ${esc(status)}</h3>${state.error?`<p role="alert">${esc(state.error)}</p>`:''}${state.external_result_uncertain?'<p>외부 동작의 결과가 불명확합니다. 중복 댓글·등록을 보내지 않습니다.</p>':''}${state.package?`<h3>게시글 본문</h3><textarea readonly aria-label="게시글 본문">${esc(state.package.caption)}</textarea><h3>자동 DM</h3><pre>${esc(state.package.dm_message)}</pre><p>버튼: ${esc(state.package.button_text)}</p>`:''}${state.littly?'<p>실제 댓글에 대한 DM 전달 검증은 게시물 연결 후 별도로 확인합니다.</p>':''}`;
      const uploaded = state.effects?.some(effect => effect.kind==='instagram_publish');
      if (state.product_observation?.dm_received) $('#result').insertAdjacentHTML('beforeend', `<p>‘나도’ 댓글 1개 전송·원작성자 DM 수신 확인됨.</p>${state.product_observation.status==='awaiting_follow_confirmation'?`<p>현재 웹 DM에는 팔로우 확인 버튼이 보이지 않습니다. 인스타 앱의 @${esc(state.product_observation.source_account)} 대화에서 확인해 주세요. 댓글은 다시 달지 않습니다.</p>`:''}`);
      if (state.stage==='littly' && state.external_result_uncertain) $('#result').insertAdjacentHTML('beforeend', `<form data-inspect-littly><label>기존 리틀리 자동화 상세 주소<input type="url" name="automation_url" required placeholder="https://app.litt.ly/automations/…"></label><button ${state.worker_live?'disabled':''}>기존 리틀리 등록 결과 조회</button></form>${state.littly_check?`<p>${esc(state.littly_check.reason||'')}</p>`:''}`);
      if (state.publication) $('#result').insertAdjacentHTML('beforeend', `<p>${esc(phases[state.publication.phase]||'게시 확인 대기')}</p><p>공개 게시물의 영상·표지 일치는 별도 확인이 필요합니다.</p>`);
      if (state.stage==='awaiting_post') {
        if (!uploaded && state.status==='ready' && state.package?.media?.cover && publicationSupported) $('#result').insertAdjacentHTML('beforeend', `<p>게시 계정: ${esc(state.account)} · 상품: ${esc(state.package.product_name)}</p><button type="button" data-publish ${state.worker_live?'disabled':''}>준비한 영상·표지·본문으로 인스타 게시</button>`);
        else if (!uploaded && state.package?.media?.cover && !publicationSupported) $('#result').insertAdjacentHTML('beforeend', '<p>이 서버는 인스타 업로드 기능의 운영 적용을 기다리고 있습니다.</p>');
        else if (!uploaded && !state.package?.media?.cover) $('#result').insertAdjacentHTML('beforeend', '<p>인스타 자동 게시에는 최종 표지가 포함된 새 게시 패키지가 필요합니다.</p>');
        $('#result').insertAdjacentHTML('beforeend', `<form data-inspect-post><label>게시한 우리 영상 주소<input type="url" name="post_url" required value="${esc(state.publication?.post_url||'')}" placeholder="https://www.instagram.com/reel/…/"></label><button ${state.worker_live?'disabled':''}>실제 게시물 연결 확인</button></form>${state.post_check?`<p>${esc(state.post_check.reason||'')}</p>`:''}`);
      }
      if (state.stage==='awaiting_delivery') $('#result').insertAdjacentHTML('beforeend', `<button type="button" data-inspect-delivery ${state.worker_live?'disabled':''}>실제 DM 발송 내역 확인</button>${state.delivery_check?`<p>${esc(state.delivery_check.reason||'')}</p>`:''}`);
      if (state.worker_live || waits[waiting]) timer = setTimeout(refresh, 3000);
    } catch (error) { message(error.message); }
  }
  $('#work').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button');
    button.disabled = true;
    try { await connections(); if (!coupangReady) return; button.disabled = true; await request(encodeURIComponent(form.elements.task.value)+'/run', {}); message('저장된 계정과 고정 댓글 ‘나도’로 후속 작업을 시작했습니다.'); }
    catch (error) { message(error.message); }
    finally { await refresh(); }
  });
  $('#automation').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    try {
      const discovery = form.elements.discovery_account.value || form.elements.account.value;
      if (!accountRolesSupported && discovery.trim().replace(/^@/,'').toLowerCase() !== form.elements.account.value.trim().replace(/^@/,'').toLowerCase()) throw new Error('이 서버에는 상품 확인 계정 분리 기능의 적용이 필요합니다.');
      await request('automation', {account:form.elements.account.value, discovery_account:discovery, enabled:form.elements.enabled.checked}); await connections(); await loadInputs($('#work').elements.task.value); await refresh(); await verifyBinding(); message('우리 인스타 계정을 저장했습니다. 다음 작업과 다음 접속에도 자동으로 사용합니다.'); }
    catch (error) { message(error.message); }
    finally { button.disabled = false; }
  });
  $('#refresh').addEventListener('click', async () => {
    try { await connections(); await loadInputs($('#work').elements.task.value); await refresh(); }
    catch (error) { message(error.message); }
  });
  $('#verify-binding').addEventListener('click', async () => {
    try { await verifyBinding(); }
    catch (error) { $('#binding-check').textContent = error.message; }
  });
  $('#work').elements.task.addEventListener('change', () => {
    ++inputRequest;
    $('#result').textContent = ''; showInputs(); refresh();
  });
  $('#result').addEventListener('submit', async event => {
    if (!event.target.matches('[data-inspect-post], [data-inspect-littly]')) return;
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    const littly = event.target.matches('[data-inspect-littly]');
    const action = littly ? 'inspect-littly' : 'inspect-post';
    const data = littly ? {automation_url:event.target.elements.automation_url.value} : {post_url:event.target.elements.post_url.value};
    try { await request(encodeURIComponent($('#work').elements.task.value.trim())+'/'+action, data); message(littly?'중복 생성 없이 기존 자동화의 저장 내용을 확인합니다.':'실제 등록 설정과 우리 게시물의 연결을 확인합니다.'); await refresh(); }
    catch (error) { message(error.message); button.disabled = false; }
  });
  $('#result').addEventListener('click', async event => {
    const button = event.target.closest('[data-inspect-delivery], [data-publish]'); if (!button) return; button.disabled = true;
    const publish = button.hasAttribute('data-publish');
    try { await request(encodeURIComponent($('#work').elements.task.value.trim())+(publish?'/publish':'/inspect-delivery'), {}); message(publish?'준비한 게시 패키지로 인스타 게시를 시작했습니다. 결과가 불명확하면 다시 게시하지 않고 실제 주소를 확인합니다.':'실제 성공 발송 내역을 읽어 확인합니다.'); }
    catch (error) { message(error.message); }
    finally { await refresh(); }
  });
  const task = new URLSearchParams(location.search).get('task');
  connections().then(() => loadInputs(task)).then(refresh).catch(error => message(error.message));
})();

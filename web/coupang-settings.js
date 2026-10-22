(() => {
  'use strict';
  const form = document.querySelector('#coupang-credentials');
  const status = document.querySelector('#coupang-status');
  const button = form.querySelector('button[type="submit"]');
  async function request(data) {
    const response = await fetch('/api/monetization/connections', data === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'API 연결 정보를 확인하지 못했습니다.');
    return result;
  }
  async function load() {
    const {coupang} = await request();
    status.textContent = coupang.configured && coupang.eligible && coupang.account_ref
      ? '쿠팡파트너스 API 연결 정보가 저장되어 있습니다. 변경할 때만 새 키를 입력하세요.'
      : '쿠팡파트너스 API 연결이 필요합니다. 계정 참조와 API 키를 입력해 저장해 주세요.';
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    status.textContent = 'API 연결 정보를 저장하는 중…';
    try {
      await request({account_ref:form.elements.account_ref.value, access_key:form.elements.access_key.value,
        secret_key:form.elements.secret_key.value, eligible:form.elements.eligible.checked});
      form.reset();
      await load();
      status.textContent = 'API 연결 정보를 저장했습니다. 입력한 키는 화면에서 지웠습니다.';
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  load().catch(error => { status.textContent = 'API 연결 확인 실패: ' + error.message; });
})();

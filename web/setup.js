(async function () {
  'use strict';
  const form=document.getElementById('setup-form'),status=document.getElementById('setup-status');
  const save=document.getElementById('setup-save'),done=document.getElementById('setup-done');
  window.HotpostDisplay.theme(document.getElementById('theme-toggle'));
  let revision=0,canSave=false;
  function notice(text,error=false){status.textContent=text;status.classList.toggle('is-error',error);}
  async function request(options){
    const response=await fetch('/api/installation',{cache:'no-store',...options});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'연결 설정을 불러오지 못했어요.');return result;
  }
  try {
    const result=await request();revision=result.revision;canSave=result.can_save===true;
    for(const [name,value] of Object.entries(result.values))form.elements.namedItem(name).value=Array.isArray(value)?value.join(', '):value;
    save.disabled=!canSave;
    form.querySelectorAll('input').forEach(input=>input.disabled=!canSave);
    notice(!canSave?'이 화면은 미리보기예요. 설정 저장은 설치한 PC의 로컬 화면에서 진행해 주세요.':
      result.configured?'기존 연결 정보를 불러왔어요. 로그인 상태는 실행 전에 확인해요.':'내 계정과 스토어 정보를 입력하고 저장해 주세요.');
  } catch(error){notice(error.message,true);}
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!canSave||save.disabled)return;
    save.disabled=true;done.hidden=true;notice('연결 정보를 저장하고 있어요…');
    const read=name=>form.elements.namedItem(name).value.trim();
    const values={publication_accounts:read('publication_accounts').split(',').map(value=>value.trim()).filter(Boolean),
      discovery_account:read('discovery_account'),storefront_url:read('storefront_url'),collection:read('collection')};
    try {
      const result=await request({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,values})});
      revision=result.revision;done.hidden=false;notice('저장 완료! 실제 Chrome 로그인 계정과 스토어는 실행 직전에 확인해요.');
    } catch(error){notice(error.message,true);}finally{save.disabled=!canSave;}
  });
})();

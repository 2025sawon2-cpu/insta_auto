(async function () {
  'use strict';
  const form=document.getElementById('setup-form'),status=document.getElementById('setup-status');
  const save=document.getElementById('setup-save'),done=document.getElementById('setup-done');
  const saveStatus=document.getElementById('setup-save-status');
  const loginRows=document.getElementById('littly-login-rows');
  const accountInput=document.getElementById('publication-account'),add=document.getElementById('account-add');
  const accountStatus=document.getElementById('account-add-status');
  window.HotpostDisplay.theme(document.getElementById('theme-toggle'));
  let revision=0,canSave=false,saving=false;
  let accounts=[];
  const loginHints=Object.create(null);
  const canonical=value=>value.trim().replace(/^@/,'').toLowerCase();
  function notice(text,error=false){
    for(const target of [status,saveStatus]){
      target.textContent=text;target.classList.toggle('is-error',error);
    }
  }
  function accountNotice(text,error=false){
    accountStatus.textContent=text;accountStatus.classList.toggle('is-error',error);
  }
  function controls(){
    form.querySelectorAll('input,select,button').forEach(control=>control.disabled=!canSave||saving);
  }
  function changed(){
    done.hidden=true;notice('변경한 등록 내용을 확인하고 아래에서 연결 정보를 저장해 주세요.');
  }
  function rememberLogins(){
    loginRows.querySelectorAll('[data-account]').forEach(row=>{
      loginHints[row.dataset.account]={provider:row.querySelector('select').value,
        account_hint:row.querySelector('input').value.trim()};
    });
  }
  function renderAccounts(){
    rememberLogins();loginRows.replaceChildren();
    document.getElementById('account-count').textContent=accounts.length+'개';
    if(!accounts.length){
      const empty=document.createElement('p');empty.className='setup-account-empty';
      empty.textContent='아직 등록한 계정이 없어요. 위에서 게시용 인스타 계정을 추가해 주세요.';
      loginRows.append(empty);
    }
    for(const [index,account] of accounts.entries()){
      const hint=loginHints[account]||{provider:'chrome',account_hint:''};
      const row=document.createElement('fieldset');row.className='setup-login-row';row.dataset.account=account;
      const legend=document.createElement('legend');legend.textContent='@'+account;row.append(legend);
      const header=document.createElement('div');header.className='setup-account-actions';
      const detail=document.createElement('span');detail.textContent=index===0?'기본 게시 계정':'게시 계정';
      const remove=document.createElement('button');remove.type='button';remove.className='btn ghost setup-account-remove';
      remove.textContent='삭제';remove.setAttribute('aria-label','@'+account+' 등록 삭제');
      remove.addEventListener('click',()=>{
        if(!canSave||saving)return;
        rememberLogins();accounts=accounts.filter(value=>value!==account);renderAccounts();changed();
        accountNotice('@'+account+'을 목록에서 뺐어요. 연결 정보 저장 후 반영돼요.');accountInput.focus();
      });
      header.append(detail,remove);row.append(header);
      const fields=document.createElement('div');fields.className='setup-login-fields';
      const methodLabel=document.createElement('label');methodLabel.textContent='리틀리 로그인 방식';
      const select=document.createElement('select');select.setAttribute('aria-label','@'+account+' 리틀리 로그인 방식');
      for(const [value,text] of [['chrome','Chrome 자동완성'],['google','Google 간편로그인'],['kakao','카카오 간편로그인'],['email','이메일·비밀번호'],['','아직 지정하지 않음']]){
        const option=document.createElement('option');option.value=value;option.textContent=text;
        option.selected=value===hint.provider;select.append(option);
      }
      methodLabel.append(select);fields.append(methodLabel);
      const accountLabel=document.createElement('label');accountLabel.textContent='Chrome에 저장된 로그인 계정';
      const input=document.createElement('input');input.value=hint.account_hint;input.maxLength=160;
      input.placeholder='저장된 로그인 ID 또는 이메일';input.autocomplete='off';input.spellcheck=false;
      input.setAttribute('aria-label','@'+account+' Chrome 저장 계정 식별자');
      accountLabel.append(input);fields.append(accountLabel);row.append(fields);
      const help=document.createElement('small');help.textContent='저장 계정 지정은 로그인 확인과 달라요. 실제 연결된 인스타 계정은 업로드 전에 확인해요.';
      row.append(help);loginRows.append(row);
    }
    controls();
  }
  function addAccount(){
    if(!canSave||saving)return;
    const account=canonical(accountInput.value);
    if(!/^[a-z0-9_.]{1,30}$/.test(account)){
      accountNotice('인스타 아이디를 한 개 입력해 주세요. 영문·숫자·밑줄·마침표로 30자까지 사용할 수 있어요.',true);return;
    }
    if(accounts.includes(account)){accountNotice('이미 등록한 계정이에요: @'+account,true);return;}
    if(accounts.length>=10){accountNotice('게시 계정은 최대 10개까지 등록할 수 있어요.',true);return;}
    accounts.push(account);accountInput.value='';renderAccounts();changed();
    accountNotice('@'+account+'을 추가했어요. 연결 정보 저장 후 반영돼요.');accountInput.focus();
  }
  add.addEventListener('click',addAccount);
  accountInput.addEventListener('keydown',event=>{
    if(event.key==='Enter'){event.preventDefault();addAccount();}
  });
  form.addEventListener('input',()=>{if(canSave&&!saving)changed();});
  form.addEventListener('change',()=>{if(canSave&&!saving)changed();});
  async function request(options){
    const response=await fetch('/api/installation',{cache:'no-store',...options});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'연결 설정을 불러오지 못했어요.');return result;
  }
  controls();
  try {
    const result=await request();revision=result.revision;canSave=result.can_save===true;
    accounts=[...new Set(result.values.publication_accounts.map(canonical))];
    for(const name of ['discovery_account','storefront_url','collection'])form.elements.namedItem(name).value=result.values[name];
    Object.assign(loginHints,result.values.littly_logins||{});renderAccounts();
    notice(!canSave?'이 화면은 미리보기예요. 설정 저장은 설치한 PC의 로컬 화면에서 진행해 주세요.':
      result.configured?'등록한 계정과 연결 정보를 불러왔어요. 변경 후 아래에서 저장해 주세요.':'게시할 인스타 계정을 등록하고 스토어 정보를 저장해 주세요.');
  } catch(error){canSave=false;controls();notice(error.message,true);}
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!canSave||saving)return;
    if(accountInput.value.trim()){
      accountNotice('입력한 인스타 계정의 등록 버튼을 먼저 눌러 주세요.',true);accountInput.focus();return;
    }
    if(!accounts.length){
      accountNotice('게시용 인스타 계정을 한 개 이상 등록해 주세요.',true);accountInput.focus();return;
    }
    rememberLogins();
    const read=name=>form.elements.namedItem(name).value.trim();
    const routes=Object.fromEntries(accounts.filter(account=>loginHints[account]&&
      (loginHints[account].account_hint||!['','chrome'].includes(loginHints[account].provider))).map(account=>[account,loginHints[account]]));
    const values={publication_accounts:[...accounts],discovery_account:read('discovery_account'),
      storefront_url:read('storefront_url'),collection:read('collection'),littly_logins:routes};
    saving=true;controls();done.hidden=true;notice('연결 정보를 저장하고 있어요…');
    try {
      const result=await request({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,values})});
      revision=result.revision;done.hidden=false;accountNotice('');
      notice('저장 완료! 실제 Chrome 로그인 계정과 리틀리 연결은 업로드 전에 확인해요.');
    } catch(error){notice(error.message,true);}finally{saving=false;controls();}
  });
})();

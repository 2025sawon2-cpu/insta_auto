const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {parseHTML}=require(process.env.HOTPOST_TEST_DOM || '../remotion/node_modules/linkedom');
const code=fs.readFileSync(path.join(__dirname,'../web/setup.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../web/setup.html'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const values={publication_accounts:['first','second'],discovery_account:'reader',storefront_url:'https://influencers.coupang.com/s/test',collection:'Test'};
function harness(error,config={}){
  const {document,window}=parseHTML(html),puts=[];
  const form=document.getElementById('setup-form');
  Object.defineProperty(form,'elements',{value:{namedItem:name=>form.querySelector(`[name="${name}"]`)}});
  window.HTMLElement.prototype.focus=function(){};
  window.HotpostDisplay={theme:()=>{}};
  vm.runInNewContext(code,{document,window,fetch:async(url,options={})=>{
    if(config.loadError&&!options.method)throw new Error('설정을 불러오지 못했어요.');
    if(options.method==='PUT'){
      puts.push(JSON.parse(options.body));
      if(config.waitForSave)await config.waitForSave;
    }
    const failed=options.method==='PUT'&&error;
    return {ok:!failed,json:async()=>failed?{error}:{revision:puts.length,can_save:config.canSave!==false,configured:true,values:config.values||values}};
  }});
  return {document,window,form,puts};
}
function add(h,name,enter=false){
  const input=h.document.getElementById('publication-account');input.value=name;
  if(enter){const event=new h.window.Event('keydown',{cancelable:true});event.key='Enter';input.dispatchEvent(event);}
  else h.document.getElementById('account-add').click();
}
const rows=h=>[...h.document.querySelectorAll('.setup-login-row')];
const submit=h=>h.form.dispatchEvent(new h.window.Event('submit',{cancelable:true}));
const remove=(h,name)=>h.document.querySelector(`[data-account="${name}"] button`).click();

test('adding and removing accounts preserves existing login hints and excludes removed routes from saves',async()=>{
  const logins={first:{provider:'google',account_hint:'first@example.test'},second:{provider:'kakao',account_hint:'saved Kakao'}};
  const h=harness('잠시 후 다시 시도해 주세요.',{values:{...values,littly_logins:logins}});await tick();
  assert.equal(rows(h).length,2);
  assert.equal(rows(h)[0].querySelector('select').value,'google');
  rows(h)[1].querySelector('input').value='other saved Kakao';
  add(h,'@NEW.brand',true);
  assert.equal(rows(h).length,3);
  assert.equal(rows(h)[1].querySelector('input').value,'other saved Kakao');
  assert.equal(rows(h)[2].querySelector('select').value,'chrome');
  rows(h)[2].querySelector('input').value='saved@example.test';
  submit(h);await tick();
  assert.deepEqual(h.puts[0].values.publication_accounts,['first','second','new.brand']);
  assert.deepEqual(h.puts[0].values.littly_logins,{first:logins.first,second:{provider:'kakao',account_hint:'other saved Kakao'},'new.brand':{provider:'chrome',account_hint:'saved@example.test'}});
  assert.equal(h.document.getElementById('setup-save-status').textContent,'잠시 후 다시 시도해 주세요.');
  remove(h,'first');submit(h);await tick();
  assert.equal(h.puts[1].values.littly_logins.first,undefined);
  assert.equal(h.puts[1].values.littly_logins.second.account_hint,'other saved Kakao');
  assert.deepEqual(h.puts[1].values.publication_accounts,['second','new.brand']);
});

test('blank login hints do not block account registration and Chrome mapping is sent without credentials',async()=>{
  const h=harness(null);await tick();submit(h);await tick();
  assert.deepEqual(h.puts[0].values.littly_logins,{});
  rows(h)[0].querySelector('input').value='saved@example.test';
  submit(h);await tick();
  assert.deepEqual(h.puts[1].values.littly_logins,{first:{provider:'chrome',account_hint:'saved@example.test'}});
  assert.equal(h.document.querySelector('input[type="password"]'),null);
});

test('duplicates, comma lists, invalid names and more than ten accounts are rejected',async()=>{
  const h=harness(null);await tick();
  for(const name of ['@FIRST','a,b','invalid name','a'.repeat(31),'']){
    add(h,name);assert.equal(rows(h).length,2);assert.ok(h.document.getElementById('account-add-status').classList.contains('is-error'));
  }
  for(let i=0;i<8;i++)add(h,'brand'+i);
  add(h,'overflow');assert.equal(rows(h).length,10);
});

test('empty lists and pending unregistered input cannot be silently saved',async()=>{
  const h=harness(null);await tick();
  h.document.getElementById('publication-account').value='pending';submit(h);await tick();assert.equal(h.puts.length,0);
  h.document.getElementById('publication-account').value='';remove(h,'first');remove(h,'second');submit(h);await tick();
  assert.equal(h.puts.length,0);assert.ok(h.document.querySelector('.setup-account-empty'));
  add(h,'restored');submit(h);await tick();assert.deepEqual(h.puts[0].values.publication_accounts,['restored']);
});

test('preview and load failure keep every mutation control disabled',async()=>{
  for(const config of [{canSave:false},{loadError:true}]){
    const h=harness(null,config);await tick();
    assert.ok([...h.form.querySelectorAll('input,select,button')].every(e=>e.disabled));
    add(h,'new.brand');submit(h);await tick();assert.equal(h.puts.length,0);
  }
});

test('an in-flight save freezes account edits and ignores repeated submission',async()=>{
  let release;const waiting=new Promise(resolve=>release=resolve);
  const h=harness(null,{waitForSave:waiting});await tick();submit(h);await tick();
  assert.ok([...h.form.querySelectorAll('input,select,button')].every(e=>e.disabled));
  submit(h);await tick();assert.equal(h.puts.length,1);
  release();await tick();assert.equal(h.document.getElementById('account-add').disabled,false);
});

for(const error of [null,'상품 확인 대기·실행 기록이 있어요. 현재 연결 정보를 유지해 주세요.']){
  test(error?'save rejection is visible beside button and preserves edits':'save success clears after a subsequent edit',async()=>{
    const h=harness(error);await tick();remove(h,'second');add(h,'reader');submit(h);await tick();
    assert.deepEqual(h.puts[0].values.publication_accounts,['first','reader']);
    const bottom=h.document.getElementById('setup-save-status');
    assert.equal(bottom.textContent,h.document.getElementById('setup-status').textContent);
    assert.ok(bottom.textContent.includes(error||'저장 완료'));
    assert.equal(bottom.classList.contains('is-error'),Boolean(error));
    assert.equal(h.document.getElementById('setup-save').disabled,false);
    assert.equal(h.document.getElementById('setup-done').hidden,Boolean(error));
    add(h,'next.brand');assert.equal(h.document.getElementById('setup-done').hidden,true);
  });
}

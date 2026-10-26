const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require(process.env.HOTPOST_TEST_DOM || '../remotion/node_modules/linkedom');
const code=fs.readFileSync(require('node:path').join(__dirname,'../web/post-preparation.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const dm='본 포스팅은 쿠팡파트너스 활동의\n일환으로 제품 구매시 일정액의 수수료를\n지급 받습니다!\n👇👇👇👇👇👇👇👇';
function fixture(){return {accounts:['mr.salrim','__ariddaum__'],revision:0,coupang_link:{status:'idle',payload:{}},draft:{selected_accounts:[],thumbnail_options:{recommended:'기존 표지',hook:'후킹',curiosity:'궁금증',benefit:'이득'},selected_thumbnail:'recommended',caption:'우리 대본 ✨',pinned_comment:'댓글',product_link:'',dm_message:dm,dm_button_text:'변기 위 빈자리, 수납으로 바꾸기'},media:{final:'/final.mp4',reference:'/ref.mp4',cover:'/cover.jpg'}};}
function harness(fetch,navigator={}){const {document,window}=parseHTML('<html><body><div id="root"></div></body></html>');let timer;vm.runInNewContext(code,{window,document,navigator,fetch,AbortController,setTimeout:fn=>(timer=fn,1),clearTimeout:()=>{},console});return {root:document.querySelector('#root'),window,timer:()=>timer?.()};}
const response=(data,status=200)=>({ok:status<400,status,json:async()=>structuredClone(data)});
test('four editable choices, both accounts and draft inputs survive a save without replacing DOM',async()=>{
 const puts=[],d=fixture();const h=harness(async(url,options={})=>{if(options.method==='PUT'){puts.push(JSON.parse(options.body));return response({revision:puts.length});}return response(d);});
 const view=h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 assert.equal(h.root.querySelectorAll('[name=prep-thumbnail]').length,4);
 assert.equal(h.root.querySelector('[name=prep-link]').value,'');
 assert.equal(h.root.querySelectorAll('a[href*="studio"]').length,0);
 const caption=h.root.querySelector('[name=prep-caption]');caption.value='바꾼 내용';
 h.root.querySelectorAll('[name=prep-account]').forEach(el=>{el.checked=true;el.setAttribute('checked','');});
 caption.dispatchEvent(new h.window.Event('input',{bubbles:true}));h.timer();await tick();
 assert.deepEqual(puts[0].draft.selected_accounts,['mr.salrim','__ariddaum__']);
 assert.equal(puts[0].draft.caption,'바꾼 내용');assert.equal(h.root.querySelector('[name=prep-caption]'),caption);
 assert.equal(h.root.querySelector('[data-save-status]').textContent,'초안 저장됨');view.close();
});
test('closing during an in-flight save flushes the latest captured draft to its own post',async()=>{
 let release;const writes=[];const h=harness(async(url,options={})=>{if(options.method==='PUT'){writes.push({url,body:JSON.parse(options.body)});if(writes.length===1)return new Promise(resolve=>release=()=>resolve(response({revision:1})));return response({revision:2});}return response(fixture());});
 const view=h.window.PostPreparation.mount(h.root,{shortcode:'first'});await tick();
 const caption=h.root.querySelector('[name=prep-caption]');caption.value='first edit';caption.dispatchEvent(new h.window.Event('input',{bubbles:true}));h.timer();
 caption.value='latest edit';caption.dispatchEvent(new h.window.Event('input',{bubbles:true}));view.close();
 h.root.innerHTML='a different post';release();await tick();await tick();
 assert.equal(writes.length,2);assert.equal(writes[1].body.draft.caption,'latest edit');assert.equal(writes[1].body.revision,1);assert.equal(h.root.textContent,'a different post');
});
test('conflict keeps typed input and stops repeated automatic saves',async()=>{
 let writes=0;const h=harness(async(url,o={})=>o.method==='PUT'?(writes++,response({error:'다른 화면에서 변경됐어요'},409)):response(fixture()));
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 const el=h.root.querySelector('[name=prep-caption]');el.value='내 입력';el.dispatchEvent(new h.window.Event('input',{bubbles:true}));h.timer();await tick();
 assert.equal(el.value,'내 입력');assert.match(h.root.querySelector('[data-save-status]').textContent,/다른 화면/);
 el.value='계속 편집';el.dispatchEvent(new h.window.Event('input',{bubbles:true}));h.timer();await tick();assert.equal(writes,1);
});
test('late response after closing cannot replace the next screen and draft text is escaped',async()=>{
 let deliver;const h=harness(()=>new Promise(resolve=>deliver=resolve));const view=h.window.PostPreparation.mount(h.root,{shortcode:'post'});view.close();h.root.textContent='next screen';deliver(response(fixture()));await tick();assert.equal(h.root.textContent,'next screen');
 const malicious=fixture();malicious.draft.caption='</textarea><img src=x onerror=alert(1)>';
 const clean=harness(async()=>response(malicious));clean.window.PostPreparation.mount(clean.root,{shortcode:'post'});await tick();assert.equal(clean.root.querySelectorAll('img').length,0);assert.equal(clean.root.querySelector('[name=prep-caption]').value,malicious.draft.caption);
});

test('thumbnail button waits for saved words, shows progress, and refreshes only the finished media',async()=>{
 const initial=fixture();initial.thumbnail={ready:true,status:'idle',applied_text:'old title'};
 let releaseSave,postCount=0,getCount=0,posted;
 const h=harness(async(url,o={})=>{
  if(o.method==='PUT')return new Promise(resolve=>releaseSave=()=>resolve(response({revision:1})));
  if(o.method==='POST'){postCount++;posted=JSON.parse(o.body);return response({status:'running',message:'썸네일을 새로 만드는 중…'});}
  getCount++;if(getCount===1)return response(initial);
  const fresh=structuredClone(initial);fresh.thumbnail={ready:true,status:getCount===2?'running':'completed',message:'영상에 반영 중…',applied_text:'새 문구'};
  if(getCount>2)fresh.media={final:'/fresh.mp4?v=job',cover:'/fresh.png?v=job'};
  return response(fresh);
 });
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 const video=h.root.querySelector('video');video.pause=()=>{};video.load=()=>{};
 const copy=h.root.querySelector('[data-copy="recommended"]');copy.value='새 문구';copy.dispatchEvent(new h.window.Event('input',{bubbles:true}));
 const button=h.root.querySelector('[data-apply-thumbnail]');button.click();await tick();
 assert.equal(postCount,0);assert.equal(button.disabled,true);assert.match(button.textContent,/반영 중/);
 releaseSave();await tick();await tick();assert.equal(postCount,1);assert.equal(posted.revision,1);
 assert.equal(h.root.querySelector('[data-thumbnail-status]').classList.contains('is-running'),true);
 h.timer();await tick();assert.equal(h.root.querySelector('video'),video);assert.equal(video.getAttribute('src'),'/fresh.mp4?v=job');
 assert.equal(h.root.querySelector('.prep-download').getAttribute('href'),'/fresh.mp4?v=job&download=1');
 assert.equal(copy.value,'새 문구');assert.match(h.root.querySelector('[data-thumbnail-status]').textContent,/반영 완료/);
});

test('thumbnail start failure keeps existing media and offers another attempt',async()=>{
 const initial=fixture();initial.thumbnail={ready:true,status:'idle',applied_text:'old'};
 const h=harness(async(url,o={})=>o.method==='POST'?response({error:'저장한 문구를 확인해 주세요.'},409):response(initial));
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 h.root.querySelector('[data-apply-thumbnail]').click();await tick();await tick();
 assert.match(h.root.querySelector('[data-thumbnail-status]').textContent,/저장한 문구/);
 assert.equal(h.root.querySelector('video').getAttribute('src'),'/final.mp4');
 assert.equal(h.root.querySelector('[data-apply-thumbnail]').disabled,false);
});

test('publication fields copy current values while thumbnail choices have no copy buttons',async()=>{
 const copies=[],writes=[];const h=harness(async(url,o={})=>{writes.push(o.method||'GET');return response(fixture());},{clipboard:{writeText:async text=>copies.push(text)}});
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 const fields=[['prep-caption','인스타 게시물 내용'],['prep-comment','고정댓글'],['prep-dm','DM으로 보낼 메시지'],['prep-dm-button','DM 버튼 문구'],['prep-link','쿠팡 인플루언서 제품 링크']];
 for(const [name,label] of fields){
  const field=h.root.querySelector(`[name="${name}"]`);
  if(name!=='prep-dm')field.value='저장 전 '+label;
  h.root.querySelector(`[aria-label="${label} 복사"]`).click();await tick();
  assert.equal(copies.at(-1),field.value);assert.match(field.closest('section').querySelector('[data-copy-status]').textContent,/복사했어요/);
 }
 assert.equal(h.root.querySelector('[name=prep-dm]').value,dm);
 assert.equal(h.root.querySelector('[name=prep-dm]').hasAttribute('readonly'),true);
 assert.equal(h.root.querySelector('[name=prep-dm-button]').getAttribute('maxlength'),'20');
 assert.equal(h.root.querySelectorAll('[data-copy-text]').length,5);
 assert.equal(h.root.querySelectorAll('.prep-option [data-copy-text]').length,0);
 assert.equal(h.root.querySelectorAll('.prep-option textarea').length,4);
 assert.ok(h.root.querySelector('[data-apply-thumbnail]'));
 assert.deepEqual(writes,['GET']);
});

test('DM button edits are counted and saved with fixed message and existing caption',async()=>{
 let saved;const h=harness(async(url,o={})=>{if(o.method==='PUT'){saved=JSON.parse(o.body);return response({revision:1});}return response(fixture());});
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 const field=h.root.querySelector('[name=prep-dm-button]');field.value='욕실 수납의 빈자리 찾기';field.dispatchEvent(new h.window.Event('input',{bubbles:true}));
 assert.equal(h.root.querySelector('[data-dm-button-count]').textContent,Array.from(field.value).length+' / 20');
 h.timer();await tick();assert.equal(saved.draft.dm_button_text,field.value);assert.equal(saved.draft.dm_message,dm);assert.equal(saved.draft.caption,fixture().draft.caption);
});

test('missing clipboard and permission rejection select the field with honest fallback feedback',async()=>{
 for(const navigator of [{},{clipboard:{writeText:async()=>{throw Error('denied');}}}]){
  const h=harness(async()=>response(fixture()),navigator);h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
  const field=h.root.querySelector('[name=prep-dm]');let selected=0;field.focus=()=>{};field.select=()=>selected++;
  const button=h.root.querySelector('[aria-label="DM으로 보낼 메시지 복사"]');button.click();await tick();
  assert.equal(selected,1);assert.equal(button.disabled,false);assert.match(field.closest('section').querySelector('[data-copy-status]').textContent,/직접 복사/);
 }
});

const store='https://influencers.coupang.com/s/ourstore';
const oneLink='https://link.coupang.com/re/AFFSDP?lptag=AFTEST&pageKey=123&itemId=456&vendorItemId=789&portal=CREATOR';
function completedLink(){return {status:'completed',payload:{product_name:'난방텐트',storefront_url:store,product_url:'',register:false},result:{title:'브랜드 난방텐트',product_id:'123',item_id:'456',vendor_item_id:'789',one_link:oneLink,landing_verified:true},message:'원링크 확인 완료'};}
function queryLink(h){h.root.querySelector('[name=coupang-name]').value='난방텐트';h.root.querySelector('[name=coupang-store]').value=store;}

test('One-Link request is explicit, registration defaults off and verified result needs an apply click',async()=>{
 const initial=fixture();initial.draft.product_link='기존 제품 링크';let gets=0;const posts=[],puts=[];
 const h=harness(async(url,o={})=>{
  if(o.method==='POST'){posts.push(JSON.parse(o.body));return response({status:'running',payload:posts.at(-1),message:'확인 중'});}
  if(o.method==='PUT'){puts.push(JSON.parse(o.body));return response({revision:puts.length});}
  gets++;return response(gets===1?initial:{...initial,coupang_link:completedLink()});
 });
 h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();queryLink(h);
 assert.equal(posts.length,0);assert.equal(h.root.querySelector('[name=coupang-register]').hasAttribute('checked'),false);
 h.root.querySelector('[data-find-coupang]').click();await tick();await tick();
 assert.equal(posts.length,1);assert.equal(posts[0].register,false);
 assert.equal(h.root.querySelector('[name=prep-link]').value,'기존 제품 링크');
 assert.equal(h.root.querySelector('[data-use-coupang]').hidden,false);
 h.root.querySelector('[data-use-coupang]').click();h.timer();await tick();
 assert.equal(h.root.querySelector('[name=prep-link]').value,oneLink);
 assert.equal(puts.at(-1).draft.product_link,oneLink);assert.equal(puts.at(-1).draft.caption,initial.draft.caption);
});

test('One-Link result cannot be applied to changed query or change an edited link on its own',async()=>{
 const initial=fixture();initial.coupang_link=completedLink();initial.draft.product_link='내 링크';
 const h=harness(async()=>response(initial));h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 const field=h.root.querySelector('[name=coupang-name]');field.value='다른 상품';field.dispatchEvent(new h.window.Event('input',{bubbles:true}));
 assert.equal(h.root.querySelector('[data-use-coupang]').disabled,true);
 h.root.querySelector('[data-use-coupang]').click();assert.equal(h.root.querySelector('[name=prep-link]').value,'내 링크');
});

test('failed One-Link lookup preserves old link and late response cannot update the next post',async()=>{
 const initial=fixture();initial.draft.product_link='기존 링크';let release;
 const h=harness(async(url,o={})=>o.method==='POST'?new Promise(resolve=>release=resolve):response(initial));
 const view=h.window.PostPreparation.mount(h.root,{shortcode:'first'});await tick();queryLink(h);
 h.root.querySelector('[data-find-coupang]').click();await tick();
 release(response({error:'상품 불일치'},400));await tick();
 assert.equal(h.root.querySelector('[name=prep-link]').value,'기존 링크');assert.match(h.root.querySelector('[data-coupang-status]').textContent,/상품 불일치/);
 h.root.querySelector('[data-find-coupang]').click();await tick();view.close();h.root.textContent='next post';
 release(response({status:'running'}));await tick();assert.equal(h.root.textContent,'next post');
});

test('closing while draft saves prevents a later external One-Link submission',async()=>{
 let release,posts=0;const h=harness(async(url,o={})=>{
  if(o.method==='PUT')return new Promise(resolve=>release=()=>resolve(response({revision:1})));
  if(o.method==='POST'){posts++;return response({status:'running'});}
  return response(fixture());
 });
 const view=h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();queryLink(h);
 const field=h.root.querySelector('[name=prep-caption]');field.value='편집 중';field.dispatchEvent(new h.window.Event('input',{bubbles:true}));
 h.root.querySelector('[data-find-coupang]').click();await tick();view.close();release();await tick();await tick();assert.equal(posts,0);
});

test('old server without One-Link capability leaves manual product link available',async()=>{
 const initial=fixture();delete initial.coupang_link;
 const h=harness(async()=>response(initial));h.window.PostPreparation.mount(h.root,{shortcode:'post'});await tick();
 assert.equal(h.root.querySelector('[data-find-coupang]').disabled,true);
 assert.match(h.root.querySelector('[data-coupang-status]').textContent,/아직 연결되지/);
 assert.equal(h.root.querySelector('[name=prep-link]').hasAttribute('readonly'),false);
});

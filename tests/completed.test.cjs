const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const {parseHTML}=require(process.env.HOTPOST_TEST_DOM || '../remotion/node_modules/linkedom');
const html=fs.readFileSync(path.join(__dirname,'../web/completed.html'),'utf8');
const code=fs.readFileSync(path.join(__dirname,'../web/completed.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const fixtures=[
 {shortcode:'old',username:'history',title:'지난달 완성한 영상',completed_at:'2026-09-01T10:00:00+09:00',media:{cover:'/old.png',final:'/old.mp4'}},
 {shortcode:'new',username:'creator',title:'표지 첫 줄\n표지 둘째 줄',completed_at:'2026-10-31T00:30:00+09:00',media:{cover:'/new.png',final:'/new.mp4'}},
 {shortcode:'missing',username:'archive',title:'',completed_at:null,media:{cover:null,final:null}}
];
function harness(fetch){
 const {document,window}=parseHTML(html); const mounts=[],closed=[];
 window.PostPreparation={mount:(root,post)=>{mounts.push(post.shortcode);root.innerHTML='<p>기존 게시물 준비 화면</p>';return {close:()=>closed.push(post.shortcode)};}};
 vm.runInNewContext(code,{window,document,fetch,console,Date,localStorage:{getItem:()=>JSON.stringify('dark'),setItem:()=>{}},matchMedia:()=>({matches:false})});
 return {window,document,mounts,closed};
}
test('archive shows all dates, orders completions, searches and keeps unavailable completions visible',async()=>{
 const h=harness(async()=>({ok:true,json:async()=>({posts:fixtures})}));await tick();
 const cards=()=>Array.from(h.document.querySelectorAll('.archive-card'),el=>el.dataset.code);
 assert.deepEqual(cards(),['new','old','missing']);
 assert.equal(h.document.querySelector('#archive-count').textContent,'3');
 assert.match(h.document.querySelector('[data-code=missing]').textContent,/파일을 확인할 수 없어요/);
 assert.equal(h.document.querySelectorAll('.archive-month').length,3);
 const search=h.document.querySelector('#archive-query');search.value='HISTORY';search.dispatchEvent(new h.window.Event('input'));
 assert.deepEqual(cards(),['old']);
 search.value='없음';search.dispatchEvent(new h.window.Event('input'));
 assert.equal(h.document.querySelector('#archive-empty').hidden,false);
 search.value='';search.dispatchEvent(new h.window.Event('input'));
 const sort=h.document.querySelector('#archive-sort');sort.querySelector('[value=oldest]').selected=true;sort.dispatchEvent(new h.window.Event('change'));
 assert.deepEqual(cards(),['old','new','missing']);
});
test('archive opens the existing preparation view and closes it on Escape',async()=>{
 const methods=[];const h=harness(async(url,options)=>{methods.push(options.method||'GET');return {ok:true,json:async()=>({posts:fixtures})};});await tick();
 h.document.querySelector('[data-open=new]').click();
 assert.deepEqual(h.mounts,['new']);assert.equal(h.document.querySelector('#archive-modal').hidden,false);
 h.document.dispatchEvent(new h.window.Event('keydown')); // An unrelated key keeps the dialog open.
 assert.equal(h.document.querySelector('#archive-modal').hidden,false);
 const escape=new h.window.Event('keydown');escape.key='Escape';h.document.dispatchEvent(escape);
 assert.deepEqual(h.closed,['new']);assert.equal(h.document.querySelector('#archive-modal').hidden,true);
 assert.deepEqual(methods,['GET']);
});
test('load failure offers a retry and never presents an empty archive as a successful result',async()=>{
 let calls=0;const h=harness(async()=>{if(++calls===1)return {ok:false};return {ok:true,json:async()=>({posts:[]})};});await tick();
 assert.equal(h.document.querySelector('#archive-retry').hidden,false);
 assert.match(h.document.querySelector('#archive-result').textContent,/불러오지 못했어요/);
 h.document.querySelector('#archive-retry').click();await tick();
 assert.equal(calls,2);assert.equal(h.document.querySelector('#archive-retry').hidden,true);
 assert.match(h.document.querySelector('#archive-empty').textContent,/아직 완성/);
});

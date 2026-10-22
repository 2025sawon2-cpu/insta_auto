/* DOM integration only: no browser, server, live task, or network access. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
let parseHTML;
try { ({parseHTML}=require(process.env.HOTPOST_TEST_DOM||'linkedom')); } catch (_) {}
const web=path.join(__dirname,'../web');
const settle=()=>new Promise(resolve=>setImmediate(resolve));

function report(stamp,count=1){
  const now=Date.now()/1000;
  return {generated_at:stamp,generated_at_kst:String(stamp),source:'test',notes:[],
    settings:{recent_days:30},summary:{accounts:1},criteria:{version:1,values:{t1:1.8,t2:3,t3:5,maturity:true}},
    accounts:[{username:'creator',followers:1000}],
    posts:Array.from({length:count},(_,i)=>({shortcode:'post-'+i,username:'creator',kind:'reel',tier:1,
      caption:'확인할 제작 영상 '+i,hashtags:[],categories:['생활·기타'],flags:[],taken_at:now-3600,
      hot_detected_at:now-30,age_hours:1,views:2000,likes:100,comments:10,rank_score:2,multiplier:2,
      ratios:{views:2,likes:2,comments:2},baseline:{views:1000,likes:50,comments:5,peers:12},
      maturity:1,confidence:'high',url:'https://example.test/'+i}))};
}

async function dashboard(){
  const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
  const {document,window:domWindow}=parseHTML(html);
  const listeners=new Map(),storage=new Map(),requests=[];
  let currentReport=report(1),reportFailure=false,reloads=0;
  const task={id:'work-test',shortcode:'post-0',run_id:'current',status:'completed',automation:{protocol:2},
    scripts:[{id:'script-1',text:'선택한 제작 대본'}],script_id:'script-1',
    voices:[{id:'voice-1',script_id:'script-1',path_url:'/voice.wav'}],voice_id:'voice-1',
    sources:[],jobs:[],reference_url:'/reference.mp4',source_goal:{count:10,target:10,ready:true,platforms:{}},
    pipeline:[{id:'previous',created:1,status:'completed',video_url:'/previous.mp4',steps:[{key:'export',download_url:'/download?run=previous'}]},
      {id:'current',created:2,status:'completed',video_url:'/current.mp4',steps:[{key:'export',download_url:'/download?run=current'}]}]};
  const values={detection:'today',period:24,kind:'all',tier:1,sort:'rank',assessment:'all',account:''};
  const context={document,URL,URLSearchParams,Map,Set,Date,console,AbortController,AbortSignal,Event:domWindow.Event,
    HOTPOST_REPORT:currentReport,innerWidth:1280,
    location:{search:'?post=post-0',reload(){reloads++;}},
    matchMedia:()=>({matches:false}),
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
    addEventListener(name,callback){if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(callback);},
    removeEventListener(){},
    async fetch(url,options={}){
      assert.equal(options.method||'GET','GET','the regression harness must never send a mutation');
      requests.push(url);
      if(url==='/api/report'&&reportFailure)throw new Error('offline');
      const routes={
        '/api/display-settings':{values},'/api/report':currentReport,'/api/studio?view=list':{tasks:[task]},
        '/api/post-preparations/post-0':{revision:0,accounts:['mr.salrim','__ariddaum__'],draft:{selected_accounts:[],thumbnail_options:{recommended:'기본',hook:'후킹',curiosity:'궁금증',benefit:'이득'},selected_thumbnail:'recommended',caption:'우리 대본',pinned_comment:'댓글',product_link:''},media:{final:'/current.mp4',reference:'/reference.mp4'}},
        '/api/legacy-productions':{productions:[]},'/api/accounts':{accounts:[{username:'creator'}]},
        '/api/collection-status':{collection:{state:'success',newest_post_update:Date.now()/1000},schedule:{}}
      };
      assert.ok(url in routes,'unexpected request: '+url);
      return {ok:true,json:async()=>routes[url]};
    }};
  context.window=context;
  vm.createContext(context);
  for(const script of document.querySelectorAll('script[src]')){
    const name=script.getAttribute('src').split('?')[0];
    if(name==='data.js')continue;
    await vm.runInContext(fs.readFileSync(path.join(web,name),'utf8'),context,{filename:name});
  }
  await settle();
  return {document,requests,get reloads(){return reloads;},
    replaceReport(next){currentReport=next;},failReport(){reportFailure=true;},
    async focus(){await Promise.all((listeners.get('focus')||[]).map(callback=>callback()));await settle();}};
}

test('dashboard report refresh preserves open video and unsaved publication draft',{skip:!parseHTML},async()=>{
  const app=await dashboard(),d=app.document;
  assert.equal(String(d.querySelector('#result-count').textContent),'1');
  assert.equal(d.querySelector('#modal').hidden,false);
  const video=d.querySelector('video[src="/current.mp4"]');
  assert.ok(video);video.currentTime=11;
  const caption=d.querySelector('[name="prep-caption"]');caption.value='작성 중인 게시물';
  caption.dispatchEvent(new app.document.defaultView.Event('input',{bubbles:true}));
  app.replaceReport(report(2,3));
  await app.focus();
  assert.equal(String(d.querySelector('#result-count').textContent),'3');
  assert.equal(d.querySelectorAll('#cards .card').length,3);
  assert.equal(d.querySelector('#modal').hidden,false);
  assert.equal(d.querySelector('video[src="/current.mp4"]'),video);
  assert.equal(video.currentTime,11);
  assert.equal(d.querySelector('[name="prep-caption"]'),caption);
  assert.equal(caption.value,'작성 중인 게시물');
  assert.equal(app.reloads,0);
  assert.ok(app.requests.includes('/api/report'));
});

test('failed report refresh keeps verified cards, current video, and per-run download links',{skip:!parseHTML},async()=>{
  const app=await dashboard(),d=app.document,video=d.querySelector('video[src="/current.mp4"]');
  const downloads=()=>Array.from(d.querySelectorAll('.prep-download'),a=>a.getAttribute('href'));
  assert.deepEqual(downloads(),['/current.mp4?download=1']);
  app.failReport();await app.focus();
  assert.equal(String(d.querySelector('#result-count').textContent),'1');
  assert.equal(d.querySelector('video[src="/current.mp4"]'),video);
  assert.deepEqual(downloads(),['/current.mp4?download=1']);
  assert.equal(app.reloads,0);
});

// Only documented Ego APIs. Resumes a supplied existing space; never creates/claims/finishes one.
const fs=await import('node:fs/promises');
const crypto=await import('node:crypto');

async function write(path,value){await fs.writeFile(path,JSON.stringify(value,null,2),'utf8');}
export function queryArgument(request){return request.query??null;}
export function classifyVisibleAccess(data){
 const host=new URL(data.url).hostname;
 if(!(host==='tiktok.com'||host.endsWith('.tiktok.com')))return {status:'not_attempted',reason:'bound_page_host_mismatch'};
 if(data.rateEvent||data.rateErrorSurface)return {status:'rate_limited',reason:'current_rate_limit'};
 if(/verify to continue|drag the slider|로봇이 아닙니다|퍼즐을|보안 확인|完成验证|安全验证|captcha/i.test(data.body))return {status:'captcha_review_pending',reason:'screenshot_independent_review_required'};
 if(data.loginDialog||/log in to continue|로그인하여 계속|登录后继续/i.test(data.body))return {status:'login_required',reason:'current_visible_login_wall'};
 if(!data.body.trim())return {status:'browser_busy',reason:'empty_page_observation'};
 return {status:'ready',reason:'ego_current_page_observed'};
}
export function classifyControlError(code){
 return /USER_CONTROL|taskspace_user_control|inactive|unassigned/i.test(code)?'user_control':
  /task[ _]space.*not[ _]found|space.*missing|bound_page_missing/i.test(code)?'space_unavailable':'browser_busy';
}
export function inspectExactPlayback(expected){
    const id=location.pathname.split('/').at(-1),raw=document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
    if(id!==expected)throw Error('exact_video_url_mismatch');
    const unavailable=reason=>({status:'candidate_unavailable',reason,expected_id:expected,observed_id:id,source_url:location.href});
    if(!raw)return unavailable('exact_video_metadata_missing');
    const found=[];let budget=100000;
    function visit(x){if(!x||typeof x!=='object'||--budget<0)return;if(String(x.id)===id&&x.video)found.push(x);for(const v of Object.values(x))visit(v);}
    visit(JSON.parse(raw.textContent));const x=found[0],video=document.querySelector('video');
    if(!x||x.imagePost||!x.video.duration||!video||video.readyState<2)return unavailable('no_exact_playable_video');
    if(video.mediaKeys)throw Error('drm_not_supported');
    const urls=[];function collect(v){if(typeof v==='string'&&v.startsWith('https:'))urls.push(v);else if(v&&typeof v==='object')for(const x of Object.values(v))collect(x);}
    collect([x.video.playAddr,x.video.downloadAddr,x.video.PlayAddrStruct,x.video.bitrateInfo]);
    const exactResources=performance.getEntriesByType('resource').filter(e=>urls.includes(e.name)&&/video\/tos/.test(e.name));
    const blocked=exactResources.filter(e=>[403,429].includes(e.responseStatus)).at(-1);
    if(blocked)return {status:blocked.responseStatus===429?'rate_limited':'access_denied',
     reason:'observed_playback_http_'+blocked.responseStatus,rate_event:'playback-'+id+'-'+String(performance.timeOrigin+blocked.startTime)};
    const received=exactResources.filter(e=>e.responseStatus===200).at(-1);
    if(!received)return unavailable('no_observed_successful_exact_playback_resource');
    return {id,source_url:location.href,media_url:received.name,description:x.desc,width:x.video.width,height:x.video.height,duration:x.video.duration};
}
async function observe(page,request){
 const data=await page.evaluate(query=>{
  const visible=e=>!!e&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
  return {url:location.href,title:document.title,body:document.body?.innerText?.slice(0,30000)||'',
   loginDialog:[...document.querySelectorAll('[role="dialog"] input[type="password"],form input[type="password"]')].some(visible),
   rateEvent:[...performance.getEntriesByType('navigation'),...performance.getEntriesByType('resource')].filter(e=>{
     const u=new URL(e.name),t=performance.timeOrigin+e.startTime;
     const relevant=e.entryType==='navigation'||(u.hostname.endsWith('.tiktok.com')&&u.pathname.startsWith('/api/search/')&&(!query||u.searchParams.get('keyword')===query));
     return relevant&&e.responseStatus===429&&Date.now()-t<30000;
    }).map(e=>String(performance.timeOrigin+e.startTime)).at(-1),
   rateErrorSurface:/^(?:429(?:\s+Too Many Requests)?|Too Many Requests)$/i.test(document.title.trim())||[...document.querySelectorAll('[role="alert"],[data-e2e="error-page"]')].some(e=>visible(e)&&/too many requests|请求过于频繁|요청이 너무 많/i.test(e.innerText)),
   inputs:[...document.querySelectorAll('input,[contenteditable="true"]')].map((e,index)=>({index,
    placeholder:e.placeholder||e.getAttribute('aria-label')||e.getAttribute('data-placeholder')||'',
    role:e.getAttribute('role'),type:e.type||'editable',visible:visible(e)})),
   searchPanels:[...document.querySelectorAll('[role="searchbox"]')].map((e,index)=>({index,
    label:e.getAttribute('aria-label')||e.innerText?.trim(),editable:e.isContentEditable||e.tagName==='INPUT',visible:visible(e)}))};
 },queryArgument(request));
 const {status,reason}=classifyVisibleAccess(data);
 let screenshot;
 if(status!=='ready')screenshot=await page.screenshot({path:request.evidence_dir+'/access.png'});
 const rate_event=data.rateEvent||crypto.createHash('sha256').update(data.url+data.body).digest('hex');
 return {...data,status,reason,screenshot,rate_event};
}

export async function run(requestPath){
 const req=JSON.parse(await fs.readFile(requestPath,'utf8'));
 let out={task_id:req.task_id,spaceId:req.binding.spaceId,bridge_sha256:req.bridge_sha256,
  owner_context:req.owner_context,status:'browser_busy',reason:'ego_request_not_completed'};
 const done=async value=>{out={...out,...value};await write(req.result_path,out);};
 try{
  const bridge_sha256=crypto.createHash('sha256').update(await fs.readFile(new URL(import.meta.url))).digest('hex');
  out.bridge_sha256=bridge_sha256;
  if(bridge_sha256!==req.bridge_sha256)throw Error('bridge_changed_before_execution');
  const live=JSON.parse(await fs.readFile(req.binding_path,'utf8'));
  if(JSON.stringify(live)!==JSON.stringify(req.binding)||!live.authorizedTaskIds.includes(req.task_id))throw Error('binding_changed');
  const task=await taskSpace(live.spaceId);
  if(task.spaceId!==live.spaceId||task.ownership!=='agent')throw Error('taskspace_user_control_or_inactive');
  const tabs=await task.tabs();
  if(req.operation==='observe'){
   const routes={};
   for(const provider of req.providers){
    if(provider!=='tiktok'){routes[provider]={status:'not_attempted',reason:'ego_provider_not_implemented'};continue;}
    const label=live.pages[provider];
    if(!label||!tabs.some(t=>t.label===label)){routes[provider]={status:'not_attempted',reason:'bound_page_missing'};continue;}
    routes[provider]=await observe(task.page(label),req);
   }
   await done({status:'observed',routes});return;
  }
  if(req.provider!=='tiktok'){await done({status:'not_attempted',reason:'ego_provider_not_implemented'});return;}
  const label=live.pages[req.provider];
  if(!tabs.some(t=>t.label===label))throw Error('bound_page_missing');
  const page=task.page(label);
  let before=await observe(page,req);
  if(before.status!=='ready'){await done(before);return;}
  if(req.operation==='search'){
   if(!req.query?.trim()||req.query.trim().split(/\s+/).length>10)throw Error('query_word_contract');
   // Inspect current semantic page before choosing an existing search input.
   await fs.writeFile(req.evidence_dir+'/before-snapshot.txt',await page.snapshot(),'utf8');
   let fields=before.inputs.filter(i=>i.visible&&['text','search','editable'].includes(i.type)&&(/search|검색|搜索/i.test(i.placeholder)||['combobox','searchbox'].includes(i.role)||i.type==='search'));
   if(!fields.length){
    const panels=before.searchPanels.filter(p=>p.visible&&!p.editable&&/^(검색|Search|搜索)$/i.test(p.label));
    if(panels.length===1){
     await page.click('loc=css:[role="searchbox"] >> nth='+panels[0].index,{label:'기존 검색 입력 열기'});
     before=await observe(page,req);
     if(before.status!=='ready'){await done(before);return;}
     fields=before.inputs.filter(i=>i.visible&&['text','search','editable'].includes(i.type)&&(/search|검색|搜索/i.test(i.placeholder)||['combobox','searchbox'].includes(i.role)||i.type==='search'));
    }
   }
   if(fields.length!==1){await done({status:'browser_busy',reason:'search_input_ambiguous',observation:before});return;}
   const selector='loc=css:input,[contenteditable="true"] >> nth='+fields[0].index;
   await page.fill(selector,req.query);
   const actual=await page.evaluate(index=>{const e=document.querySelectorAll('input,[contenteditable="true"]')[index];return e?.isContentEditable?e.textContent:e?.value;},fields[0].index);
   if(actual!==req.query)throw Error('query_input_mismatch');
   const execution={input_value:actual,submit_intent:true,query_submitted:false,query_url_matched:false};
   await done({status:'started',execution,stage:'visible_search_input_enter'});
   await page.press(selector,'Enter');execution.query_submitted=true;execution.submitted_at=Date.now()/1000;
   await done({status:'started',execution,stage:'search_results'});
   try{await page.waitForFunction(query=>new URL(location.href).searchParams.get('q')===query&&
     (document.querySelector('[data-e2e="search_top-item"] a[href*="/video/"], [data-e2e="search_video-item"] a[href*="/video/"]')||/No results|검색 결과를 찾을 수|没有找到|verify to continue|完成验证/.test(document.body.innerText)),req.query,{timeout:25000});}catch{}
   const after=await observe(page,req);
   execution.result_url=after.url;
   const url=new URL(after.url);
   execution.query_url_matched=(url.hostname==='www.tiktok.com'||url.hostname==='tiktok.com')&&['/search','/search/video'].includes(url.pathname)&&url.searchParams.get('q')===req.query;
   if(after.status!=='ready'){await done({...after,execution});return;}
   if(!execution.query_url_matched){await done({...after,status:'browser_busy',reason:'query_url_mismatch',execution});return;}
   const cards=await page.evaluate(()=>[...document.querySelectorAll('[data-e2e="search_top-item"] a[href*="/video/"], [data-e2e="search_video-item"] a[href*="/video/"]')]
     .filter(a=>a.getClientRects().length).map(a=>({url:a.href,title:a.getAttribute('title')||a.innerText||a.closest('[data-e2e="search_top-item"],[data-e2e="search_video-item"]')?.innerText||''})));
   const candidates=[...new Map(cards.filter(c=>/^https:\/\/www\.tiktok\.com\/@[^/]+\/video\/\d+/.test(c.url)).map(c=>{const u=new URL(c.url);u.search='';u.hash='';return[u.href,{...c,url:u.href}];})).values()].slice(0,req.limit);
   const empty=/No results|검색 결과를 찾을 수|没有找到|暂无结果/i.test(after.body);
   await done({status:candidates.length?'results':empty?'no_results':'browser_busy',reason:candidates.length||empty?'visible_matching_search_result':'search_cards_unresolved',
    candidates,execution,result_method:'ego_visible_search_cards',observation:after});
   return;
  }
  if(req.operation==='download'){
   const u=new URL(req.url);if(!['www.tiktok.com','tiktok.com'].includes(u.hostname)||!/^\/@[^/]+\/video\/\d+$/.test(u.pathname))throw Error('not_exact_tiktok_video_url');
   await done({status:'started',navigation_started:true,attempted:false});
   await page.goto(req.url);
   let waitError;
   try{await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2&&document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__'),null,{timeout:25000});}
   catch(error){
    if(error?.executionStopped||error?.mayHaveLateEffects||classifyControlError(String(error?.code||'')+' '+String(error?.message||error))!=='browser_busy')throw error;
    waitError=error;
   }
   const after=await observe(page,req);
   if(after.status!=='ready'){await done({...after,navigation_started:true,attempted:false});return;}
   if(waitError)throw waitError; // Unknown SDK/wait failures never become candidate rejection.
   const meta=await page.evaluate(inspectExactPlayback,u.pathname.split('/').at(-1));
   if(meta.status){
    await done({...meta,navigation_started:true,navigation_attempted:true,attempted:false,stage:'candidate_playback_validation'});return;
   }
   // Explicit request pacing after the platform navigation/playback observation.
   await new Promise(resolve=>setTimeout(resolve,2000));
   await done({status:'started',navigation_started:true,attempted:true,stage:'observed_playback_fetch'});
   const response=await page.fetch(meta.media_url,{credentials:'include',saveAs:req.target,timeout:45000});
   if(!response.ok){await done({status:response.status===429?'rate_limited':response.status===403?'access_denied':'browser_busy',reason:'playback_fetch_http_'+response.status,
    rate_event:'fetch-'+req.url+'-'+Date.now(),retry_after_raw:response.headers?.['retry-after'],
    retry_after:Number(response.headers?.['retry-after'])||600,navigation_started:true,attempted:true});return;}
   const bytes=await fs.readFile(req.target);
   if(bytes.length<12||bytes.length>req.max_bytes||bytes.subarray(4,8).toString()!=='ftyp')throw Error('received_mp4_size_or_header_invalid');
   delete meta.media_url; // Signed playback URLs stay in browser scope, never in receipts/logs.
   await done({status:'received',navigation_started:true,attempted:true,bytes:bytes.length,
    sha256:crypto.createHash('sha256').update(bytes).digest('hex'),meta});return;
  }
  throw Error('unsupported_operation');
 }catch(error){
  // Do not retry, claim, create a space, or fall back to another browser.
  const code=String(error?.code||'')+' '+String(error?.message||error);
  const status=classifyControlError(code);
  await done({status,reason:code.replace(/https?:\/\/\S+/g,'[url]').slice(0,300),
   executionStopped:error?.executionStopped,mayHaveLateEffects:error?.mayHaveLateEffects});
 }
}

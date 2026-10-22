import assert from 'node:assert/strict';
import {run,inspectExactPlayback,classifyControlError} from '../hotpost/ego_source_backend.mjs';
const id='7111111111111111111',url='https://www.tiktok.com/@fixture/video/'+id,media='https://cdn.example/video/tos/fixture';
let raw,video,entries;globalThis.location={href:url,pathname:'/@fixture/video/'+id};globalThis.performance={getEntriesByType:()=>entries};
globalThis.document={querySelector:selector=>selector==='video'?video:raw};
function reset(){raw={textContent:JSON.stringify({item:{id,video:{duration:4,playAddr:media}}})};video={readyState:2};entries=[{responseStatus:200,name:media}];}
let checks=0;
reset();assert.equal(inspectExactPlayback(id).media_url,media);checks++;
reset();raw=null;assert.equal(inspectExactPlayback(id).reason,'exact_video_metadata_missing');checks++;
reset();video.readyState=0;assert.equal(inspectExactPlayback(id).reason,'no_exact_playable_video');checks++;
reset();entries=[];assert.equal(inspectExactPlayback(id).reason,'no_observed_successful_exact_playback_resource');checks++;
reset();entries=[{responseStatus:206,name:media}];assert.equal(inspectExactPlayback(id).status,'candidate_unavailable');checks++;
reset();entries=[{responseStatus:200,name:media+'-another-item'}];assert.equal(inspectExactPlayback(id).status,'candidate_unavailable');checks++;
reset();assert.throws(()=>inspectExactPlayback('other'),/exact_video_url_mismatch/);checks++;
reset();raw.textContent='{badJSON';assert.throws(()=>inspectExactPlayback(id),SyntaxError);checks++;
reset();video.mediaKeys={};assert.throws(()=>inspectExactPlayback(id),/drm_not_supported/);checks++;
assert.equal(classifyControlError('JavaScript error no_observed_successful_exact_playback_resource'),'browser_busy');checks++;
for(const status of [403,429]){reset();entries=[{responseStatus:status,name:media,startTime:1}];assert.equal(inspectExactPlayback(id).status,status===429?'rate_limited':'access_denied');checks++;}
// Exercise the public bridge operation at its documented SDK boundary, with no CLI/browser.
const fs=await import('node:fs/promises'),os=await import('node:os'),path=await import('node:path'),crypto=await import('node:crypto');
const folder=await fs.mkdtemp(path.join(os.tmpdir(),'ego-candidate-sdk-unit-'));
const bridge=await fs.readFile(new URL('../hotpost/ego_source_backend.mjs',import.meta.url));
const binding={spaceId:6,authorizedTaskIds:['work-test'],pages:{tiktok:'p1'}};
const bindingPath=path.join(folder,'binding.json');await fs.writeFile(bindingPath,JSON.stringify(binding));
try{
 for(const mode of ['candidate','sdk','user_control','late','403','429','login','captcha']){
  reset();entries=[];let observations=0,fetches=0;
  const page={goto:async()=>{},waitForFunction:async(fn,arg)=>{
   assert.equal(arg,null);
   if(['sdk','user_control','late'].includes(mode)){const error=new Error('SDK boundary failure');if(mode==='user_control')error.code='USER_CONTROL';if(mode==='late')error.mayHaveLateEffects=true;throw error;}
  },evaluate:async(fn,arg)=>{
   if(fn===inspectExactPlayback){if(['403','429'].includes(mode))entries=[{responseStatus:Number(mode),name:media,startTime:1}];return fn(arg);}
   observations++;return {url,title:'ordinary product page',body:observations>1&&mode==='login'?'Log in to continue':observations>1&&mode==='captcha'?'verify to continue':'product page',inputs:[],searchPanels:[]};
  },screenshot:async()=>({path:'unit-screenshot.png'}),fetch:async()=>{fetches++;throw Error('No network permitted in unit test');}};
  globalThis.taskSpace=async()=>({spaceId:6,ownership:'agent',tabs:async()=>[{label:'p1'}],page:()=>page});
  const req={operation:'download',provider:'tiktok',task_id:'work-test',owner_context:{task_id:'work-test',job_id:'job-test',run_id:'run-test'},binding,binding_path:bindingPath,url,target:path.join(folder,'incoming.mp4'),max_bytes:999999,evidence_dir:folder,result_path:path.join(folder,mode+'-result.json'),bridge_sha256:crypto.createHash('sha256').update(bridge).digest('hex')};
  const request=path.join(folder,mode+'-request.json');await fs.writeFile(request,JSON.stringify(req));await run(request);
  const receipt=JSON.parse(await fs.readFile(req.result_path,'utf8'));
  const expected={candidate:'candidate_unavailable',sdk:'browser_busy',user_control:'user_control',late:'browser_busy','403':'access_denied','429':'rate_limited',login:'login_required',captcha:'captcha_review_pending'}[mode];
  assert.equal(receipt.status,expected,mode);assert.equal(fetches,0);
  if(mode==='candidate'){assert.equal(receipt.attempted,false);assert.equal(receipt.navigation_attempted,true);assert.equal(receipt.observed_id,id);}
  if(mode==='late')assert.equal(receipt.mayHaveLateEffects,true);
  if(['login','captcha'].includes(mode))assert.ok(receipt.screenshot);
  checks++;
 }
}finally{assert.equal(path.dirname(path.resolve(folder)),path.resolve(os.tmpdir()));assert.ok(path.basename(folder).startsWith('ego-candidate-sdk-unit-'));await fs.rm(folder,{recursive:true,force:true});}
console.log(JSON.stringify({checks,networkCalls:0,browserCalls:0}));

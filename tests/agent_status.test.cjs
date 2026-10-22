const {test}=require('node:test');
const assert=require('node:assert/strict');
const {model,markup}=require('../web/agent-status.js');
test('shows actual running stage, no percent guess',()=>{
  const m=model({jobs:[{kind:'quality_review',status:'running'}],video_agent:{activity:{phase:'watching'}}});
  assert.equal(m.label,'완성 영상 검수 중');assert.equal(m.stage,4);assert.equal(m.live,true);assert.ok(!markup(m).includes('%'));
});
test('past tool execution never creates live motion',()=>{
  const m=model({video_agent:{status:'active',last_action:'test_patch',last_result:{status:'completed'}}});
  assert.equal(m.live,false);
});
test('model activity names thinking while production queue waits',()=>{
  const m=model({jobs:[{kind:'collect_sources',status:'queued'}],video_agent:{activity:{phase:'thinking',label:'다음 작업 판단 중',live:true}}});
  assert.equal(m.phase,'thinking');assert.equal(m.live,true);
});
test('disconnect and user pause always stop motion',()=>{
  const task={jobs:[{kind:'edit',status:'running'}],video_agent:{activity:{phase:'working',live:true}}};
  assert.equal(model(task,{online:false}).live,false);
  assert.equal(model({...task,automation:{paused_by_user:true}}).live,false);
});
test('guard hold cannot be disguised by queued or running job',()=>{
  const m=model({jobs:[{kind:'edit',status:'running'}],video_agent:{activity:{phase:'attention',label:'추가 확인이 필요해요',live:false}}});
  assert.equal(m.phase,'attention');assert.equal(m.live,false);
});
test('completed does not animate or invent historical QA receipt',()=>{
  const m=model({completed_video_ready:true});assert.equal(m.live,false);assert.equal(m.done[4],false);
  assert.equal(model({video_agent:{completion:{completion_verified:true}}}).done[4],true);
});
test('backend content stays escaped in status text and labels',()=>{
  const html=markup({...model(null),label:'<script>alert(1)</script>',detail:'" onmouseover="evil'});
  assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('&quot;'));
});
test('no task shows loading until initial authoritative response',()=>{
  assert.equal(model(null,{loaded:false}).phase,'loading');assert.equal(model(null).phase,'idle');
});
test('legacy results remain visible without claiming live AI or verified QA',()=>{
  const m=model(null,{legacy:{status:'done',variants:[{download_url:'/result.mp4'}]}});
  assert.equal(m.phase,'completed');assert.equal(m.live,false);assert.equal(m.ai,false);assert.equal(m.done[4],false);
  assert.equal(model(null,{legacy:{status:'error'}}).phase,'attention');
});

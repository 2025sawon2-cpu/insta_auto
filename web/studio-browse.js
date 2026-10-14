/* Match first hot-discovery dates; production revisions do not move a video. */
((root)=>{
 const date=n=>Number.isFinite(n)&&n>0?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n*1000)):'';
 const collectedAt=t=>t.collection_date_at||t.hot_detected_at||t.collected_at||(t.creation_mode==='self_shot'?t.created:0);
 const collected=t=>date(collectedAt(t));
 function bucket(t){
  const d=root.StudioBoard.describe(t);
  if(d.complete)return 'finished';
  if(t.automation?.paused_by_user||t.status==='paused')return 'working';
  if(d.primaryRunning||['queued','retry'].includes(d.state))return 'working';
  const blockers=(t.production_blockers||[]).filter(b=>b!=='core_footage_gap');
  return d.review||d.state==='error'||blockers.length||t.source_acquisition?.hold||t.source_search?.hold||t.creation_mode==='self_shot'&&!t.self_shot?.started?'attention':'working';
 }
 function mount(onChange){
  let screen='main',start=date(Date.now()/1000),end=start,scoped=[],followToday=true;
  const $=s=>document.querySelector(s),dialog=$('#studio-date-dialog');
  let collection=root.StudioCollectionContext||{};
  const latestDay=()=>collection.ready?date(collection.finished_at||collection.started_at):'';
  const inRange=t=>{const day=collected(t);return !start||!!day&&day>=start&&day<=end;};
  function update(tasks){
   const today=date(Date.now()/1000);if(followToday)start=end=today;
   scoped=tasks.filter(inRange);const attention=scoped.filter(t=>bucket(t)==='attention').length;
   $('#attention-count').textContent=attention;$('#attention-open').hidden=screen==='attention';$('#attention-back').hidden=screen!=='attention';
   $('#browse-title').textContent=screen==='attention'?'확인 필요한 영상':'내 영상';
   $('#browse-subtitle').textContent=screen==='attention'?'멈춘 이유를 확인하고 필요한 작업을 진행하세요.':'제작 중인 영상과 완성본을 한곳에서 확인하세요.';
   $('#date-range-label').textContent=!start?'전체 기간':followToday?'오늘 · '+start+' (한국 시간)':start===end?start:start+' — '+end;
   $('#date-today').setAttribute('aria-pressed',String(followToday));
   const latest=latestDay(),latestButton=$('#date-latest');
   latestButton.hidden=!latest;latestButton.textContent='최근 수집일 · '+latest.slice(5).replace('-','/');
   latestButton.setAttribute('aria-pressed',String(!followToday&&start===latest&&end===latest));
   const note=$('#collection-date-note');note.hidden=!collection.available;
   note.textContent=collection.ready?`마지막 수집일 ${latest} · 오늘은 ${today}입니다.`:'최근 수집이 진행 중이거나 결과를 갱신하고 있습니다.';
   const outside=tasks.filter(t=>!inRange(t)&&bucket(t)!=='finished'),older=outside.filter(t=>bucket(t)==='working').length,blocked=outside.length-older;
   const unknown=start?tasks.filter(t=>!collected(t)).length:0;
   $('#outside-dates').hidden=!outside.length&&!unknown;
   $('#outside-dates').innerHTML=outside.length||unknown?`<span>${outside.length?`선택한 기간 밖에 제작 중 ${older}개 · 확인 필요한 영상 ${blocked}개가 있습니다.`:''}${unknown?` 수집 날짜를 확인할 수 없는 영상 ${unknown}개는 전체 기간에서 볼 수 있습니다.`:''}</span><button type="button" id="show-outside">전체 기간 보기</button>`:'';
   $('#work-list').dataset.screen=screen;
   return scoped.filter(t=>screen==='attention'?bucket(t)==='attention':bucket(t)!=='attention');
  }
  function change(next){if(next===screen)return;const previous=screen;screen=next;onChange({kind:'screen',previous,next});}
  $('#attention-open').onclick=()=>change('attention');$('#attention-back').onclick=()=>change('main');
  $('#outside-dates').onclick=e=>{if(e.target.closest('#show-outside')){followToday=false;start=end='';onChange({kind:'date'});}};
  $('#date-today').onclick=()=>{followToday=true;start=end=date(Date.now()/1000);onChange({kind:'date'});};
  $('#date-latest').onclick=()=>{const day=latestDay();if(!day)return;followToday=false;start=end=day;onChange({kind:'date'});};
  $('#date-all').onclick=()=>{followToday=false;start=end='';dialog.close();onChange({kind:'date'});};
  $('#date-open').onclick=()=>{$('#date-start').value=start||date(Date.now()/1000);$('#date-end').value=end||$('#date-start').value;$('#date-error').textContent='';dialog.showModal();};
  $('#date-close').onclick=()=>dialog.close();
  dialog.onclick=e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}};
  $('#date-form').onsubmit=e=>{e.preventDefault();const a=$('#date-start').value,b=$('#date-end').value;if(!a||!b||a>b){$('#date-error').textContent='시작일과 종료일을 올바른 순서로 선택해 주세요.';return;}followToday=false;start=a;end=b;dialog.close();onChange({kind:'date'});};
  document.addEventListener('studio-collection-updated',e=>{collection=e.detail;onChange({kind:'collection'});});
  function emptyMessage(){
   const today=date(Date.now()/1000),latest=latestDay();
   if(screen==='main'&&scoped.length&&scoped.every(t=>bucket(t)==='attention'))return `선택한 날짜의 영상 ${scoped.length}개는 ‘확인 필요한 영상’에서 볼 수 있습니다.`;
   if(followToday&&!scoped.length&&collection.available){
    if(!collection.ready&&date(collection.started_at)===today)return `오늘(${today}) 수집 결과를 준비 중입니다. 완료 후 영상이 표시됩니다.`;
    if(latest&&latest<today)return `오늘(${today})은 아직 수집 결과가 없습니다. 최근 수집일(${latest})을 선택해 영상을 확인하세요.`;
    if(latest===today)return '오늘 수집한 영상이 아직 제작실에 추가되지 않았습니다. 수집 연결 내역에서 만들 영상을 선택하세요.';
   }
   return screen==='attention'?'선택한 수집 날짜에 확인이 필요한 영상이 없습니다.':'선택한 수집 날짜와 검색 조건에 맞는 영상이 없습니다.';
  }
  return {update,emptyMessage,get screen(){return screen;},get periodTasks(){return scoped;}};
 }
 const api={date,collectedAt,collected,bucket,mount};if(typeof module==='object'&&module.exports)module.exports=api;else root.StudioBrowse=api;
})(typeof window==='undefined'?globalThis:window);

/* Collection receipt: registration and execution status are separate facts. */
(()=>{
 const root=document.querySelector('#collection-intake');if(!root)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const work=id=>`studio.html?work=${encodeURIComponent(id)}`;
 let refreshing=false,busy=false,last='',receipt=null;
 const pages={rows:1,candidates:1},pageSize=6;
 function pagination(name,total){
  const count=Math.ceil(total/pageSize);pages[name]=Math.max(1,Math.min(pages[name],count||1));
  if(count<=1)return '';
  const page=pages[name],label=name==='rows'?'자동 선정 결과':'직접 고를 핫 영상';
  const arrow=direction=>`<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${direction==='left'?'m12 5-5 5 5 5':'m8 5 5 5-5 5'}"/></svg>`;
  return `<nav class="intake-pagination" aria-label="${label} 페이지"><div class="intake-page-meta"><span>전체 ${total}개</span><span>${(page-1)*pageSize+1}–${Math.min(page*pageSize,total)}번째</span></div><div class="intake-page-controls"><button type="button" aria-label="이전" data-intake-page="${name}" data-page="${page-1}" ${page===1?'disabled':''}>${arrow('left')}<span>이전</span></button><span class="intake-page-current" role="status" aria-live="polite"><strong>${page}</strong> / ${count} 페이지</span><button type="button" aria-label="다음" data-intake-page="${name}" data-page="${page+1}" ${page===count?'disabled':''}><span>다음</span>${arrow('right')}</button></div></nav>`;
 }
 function render(d){
   const rowPager=pagination('rows',d.rows.length),candidatePager=pagination('candidates',d.candidates.length);
   const opened=root.querySelector('[data-intake-candidates]')?.open;
   const detailOpen=root.querySelector('[data-intake-detail]')?.open;
   const problemsOpen=root.querySelector('[data-intake-problems]')?.open;
   const updated=d.updated_at?new Date(d.updated_at*1000).toLocaleString('ko-KR',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'}):'갱신 중';
   const rows=d.rows.slice((pages.rows-1)*pageSize,pages.rows*pageSize),candidates=d.candidates.slice((pages.candidates-1)*pageSize,pages.candidates*pageSize);
   root.innerHTML=`<header><div><h2>최근 수집</h2><p>${esc(updated)}</p></div><a href="index.html">게시물 ↗</a></header>
    <div class="intake-stats">${[['새로 발견한 게시물',d.new_posts],['새 핫 영상',d.new_hot_videos],['자동 신규 등록',d.created],['기존 작업 연결',d.existing]].map(([label,n])=>`<div><strong>${d.ready?n:'—'}</strong><span>${label}</span></div>`).join('')}</div>
    <details data-intake-detail ${detailOpen?'open':''}><summary>수집 연결 내역${d.blocked?` · 확인 필요 ${d.blocked}개`:''}</summary><p class="intake-policy">${!d.ready?'수집 결과를 갱신하고 있어요. 완료 후 신규 영상과 제작실 연결 결과가 표시됩니다.':!d.selection_ready?(d.enabled?'자동 선정 결과를 기다리고 있어요.':'자동 선정이 꺼져 있어요. 아래에서 만들 영상을 직접 고르세요.'):'한국시간 오늘 최초 감지된 핫 영상 중 상위 2개를 자동 선정합니다. 이전 감지일은 소모 처리하며, 기존 작업은 중복 추가하지 않습니다.'}</p>
    ${d.rows.length?`<details data-intake-problems ${problemsOpen?'open':''}><summary class="${d.blocked?'intake-warning':''}">자동 선정 ${d.rows.length}개 · ${d.blocked?`진행 불가 ${d.blocked}개 · 원인과 해결방법 보기`:'연결 결과 보기'}</summary><div class="intake-results">`:''}${rows.map(v=>`<article><div class="intake-row-heading"><b>${v.rank}위 · ${{new:'신규 등록',existing:'기존 작업',skipped:'선정 보류',pending:'등록 대기'}[v.registration]}</b><span class="intake-state ${esc(v.state)}">${esc(v.label)}</span></div><h3>${esc(v.title||v.shortcode)}</h3><p>${esc(v.reason)}</p><p class="intake-solution">${esc(v.solution)}</p>${v.task_id?`<a class="button secondary" href="${work(v.task_id)}">${v.state==='blocked'?'문제 확인하고 해결하기':'작업 열기'} →</a>`:''}</article>`).join('')}${d.rows.length?`</div>${rowPager}</details>`:''}
    ${d.candidates.length?`<details data-intake-candidates ${opened?'open':''}><summary>이번에 발견한 핫 영상 ${d.candidates.length}개 · 직접 골라 제작하기</summary><p>추가하면 소스 확보부터 제작을 시작합니다. 이미 추가한 영상은 기존 작업을 엽니다.</p><div class="intake-candidates">${candidates.map(v=>`<article><div><small>@${esc(v.username)}</small><h3>${esc(v.title)}</h3></div>${v.task_id?`<a class="button secondary" href="${work(v.task_id)}">기존 작업 열기</a>`:`<button class="primary" data-intake-add="${esc(v.shortcode)}">이 영상 제작 시작</button>`}</article>`).join('')}</div>${candidatePager}</details>`:''}</details><p data-intake-error role="status" hidden></p>`;
 }
 async function refresh(){
  if(refreshing||busy)return;refreshing=true;
  try{
   const r=await fetch('/api/studio/intake',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();
   root.hidden=!d.available;
   const context={available:!!d.available,ready:!!d.ready,started_at:d.started_at,finished_at:d.finished_at||d.updated_at};
   if(JSON.stringify(context)!==JSON.stringify(window.StudioCollectionContext)){
    window.StudioCollectionContext=context;document.dispatchEvent(new CustomEvent('studio-collection-updated',{detail:context}));
   }
   if(!d.available)return;
   const snapshot=JSON.stringify(d);if(snapshot===last)return;last=snapshot;
   receipt=d;render(d);
  }catch{root.hidden=false;let note=root.querySelector('[data-intake-error]');if(!note){root.innerHTML='<p data-intake-error role="status"></p>';note=root.firstElementChild;}note.hidden=false;note.textContent='수집 연결 상태를 불러오지 못했어요. 잠시 후 자동으로 다시 확인합니다.';last='';}
  finally{refreshing=false;}
 }
 root.addEventListener('click',async e=>{
  const pageButton=e.target.closest('[data-intake-page]');
  if(pageButton){
   if(busy||pageButton.disabled||!receipt)return;
   const name=pageButton.dataset.intakePage;if(!(name in pages))return;
   const direction=Number(pageButton.dataset.page)>pages[name]?1:-1;
   pages[name]=Number(pageButton.dataset.page);render(receipt);
   const buttons=[...root.querySelectorAll(`[data-intake-page="${name}"]`)];
   const focus=buttons.find(b=>Number(b.dataset.page)===pages[name]+direction&&!b.disabled)||buttons.find(b=>!b.disabled);
   focus?.focus({preventScroll:true});
   root.querySelector(name==='rows'?'[data-intake-problems]':'[data-intake-candidates]')?.scrollIntoView({block:'start'});
   return;
  }
  const button=e.target.closest('[data-intake-add]');if(!button||busy)return;
  busy=true;button.disabled=true;button.textContent='제작실에 추가 중…';
  try{
   const r=await fetch('/api/studio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({shortcodes:[button.dataset.intakeAdd],automatic:true,only_new:true})});const d=await r.json();
   if(!r.ok)throw Error(d.error||'추가하지 못했어요. 다시 시도하세요.');
   location.href=work(d.tasks[0].id);
  }catch(e){const note=root.querySelector('[data-intake-error]');note.hidden=false;note.textContent=e.message;button.disabled=false;button.textContent='이 영상 제작 시작';busy=false;}
 });
 refresh();setInterval(refresh,30000);
})();

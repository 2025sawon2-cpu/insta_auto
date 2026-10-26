/* Compact activity projection. A past tool result never means a live execution. */
(function(root){
  'use strict';
  const stages=['소스','대본','음성','편집','검수'];
  const jobs={prepare:[0,'원본 자료 준비 중'],collect_sources:[0,'소스 영상 찾는 중'],refresh_sources:[0,'소스 영상 보완 중'],
    rewrite:[1,'대본 작성 중'],proposal:[1,'대본 보완 중'],voice:[2,'내 목소리 생성 중'],
    edit:[3,'영상 편집 중'],quality_reedit:[3,'영상 보완 중'],export:[3,'완성 영상 저장 중'],register:[3,'편집 프로젝트 준비 중'],quality_review:[4,'완성 영상 검수 중']};
  function model(task,{loaded=true,online=true,legacy=null}={}){
    const base={phase:'idle',label:'아직 제작 전',detail:'소재를 선택해 제작을 시작하세요',live:false,ai:!!task?.video_agent,stage:-1,done:[]};
    if(!loaded)return {...base,phase:'loading',label:'제작 상태 확인 중',detail:'현재 작업과 연결하고 있어요'};
    if(!online)return {...base,phase:'offline',label:'연결 확인 중',detail:'마지막 결과 보관 · 연결되면 다시 갱신해요'};
    if(!task){
      if(!legacy)return base;
      if(legacy.status==='done'&&legacy.variants?.some(v=>v.download_url))return {...base,phase:'completed',label:'영상 제작 완료',detail:'이전 제작 결과를 다운로드할 수 있어요',done:[true,true,true,true,false],stage:4};
      if(['error','missing','done'].includes(legacy.status))return {...base,phase:'attention',label:'제작 결과 확인 필요',detail:'상세 보기에서 이전 제작 결과를 확인하세요'};
      return {...base,phase:'waiting',label:'제작 상태 확인 중',detail:'이전 제작 작업의 진행 상태를 확인하고 있어요'};
    }
    const owner=task.video_agent,activity=owner?.activity;
    base.done=[!!task.source_goal?.ready,!!task.approved_script_id,!!task.approved_voice_id,!!task.edit_id,false];
    if(task.completed_video_ready||owner?.completion?.completion_verified){
      const verified=!!owner?.completion?.completion_verified;
      return {...base,phase:'completed',label:'영상 제작 완료',detail:verified?'검수 완료 · 완성 영상을 바로 확인하세요':'완성 영상을 재생하고 다운로드하세요',stage:4,done:[true,true,true,true,verified]};
    }
    if(task.automation?.paused_by_user||task.automation?.active===false||activity?.phase==='paused')
      return {...base,phase:'paused',label:'제작 일시정지',detail:'작업 결과를 보관하고 있어요'};
    base.stage=Math.max(0,base.done.findIndex(v=>!v));
    if(activity&&['offline','attention'].includes(activity.phase))return {...base,...activity};
    const running=(task.jobs||[]).find(j=>j.status==='running'&&jobs[j.kind]);
    if(running){const [stage,label]=jobs[running.kind];return {...base,phase:'working',stage,label,live:true,detail:'현재 단계를 진행하고 있어요 · 자동 갱신'};}
    if(activity&&activity.phase!=='watching')return {...base,...activity};
    if(owner?.status==='attention')return {...base,phase:'waiting',label:'복구 검토 대기',detail:'이전 결과를 확인하고 이어갈 방법을 검토해요'};
    if(task.error||task.production_blockers?.length)return {...base,phase:'attention',label:'확인이 필요해요',detail:'제작실에서 원인과 필요한 준비를 확인하세요'};
    const queued=(task.jobs||[]).find(j=>j.status==='queued'&&jobs[j.kind]);
    if(queued)return {...base,phase:'waiting',stage:jobs[queued.kind][0],label:stages[jobs[queued.kind][0]]+' 작업 대기',detail:'실행 조건이 준비되면 이어서 진행해요'};
    return {...base,...(activity||{phase:'waiting',label:'다음 단계 준비',detail:'제작 결과를 확인하고 있어요'})};
  }
  function referenceModel(production={}){
    const base={...model(null),stage:-1};
    if(production.state==='completed')return production.completed_video_ready
      ? {...base,phase:'completed',label:'영상 제작 완료',detail:'검수 완료 · 완성 영상을 바로 확인하세요',stage:4,done:[true,true,true,true,true]}
      : {...base,phase:'attention',label:'완성본 확인 필요',detail:'현재 영상과 검수 근거를 다시 확인해 주세요',stage:4};
    if(production.state==='blocked')return {...base,phase:'attention',label:'제작 진행 보류',detail:'현재 작업과 자료를 보관하고 있어요 · 재개 조건 확인 필요'};
    if(production.state==='paused')return {...base,phase:'paused',label:'제작 일시정지',detail:'중단한 작업과 자료를 보관하고 있어요'};
    if(production.state==='in_progress')return {...base,phase:'waiting',label:'제작 작업 진행 중',detail:'등록된 작업 상태 · 실제 실행 여부는 별도 확인이 필요해요'};
    if(production.state==='not_started')return base;
    return {...base,phase:'waiting',label:'제작 이력 확인 필요',detail:'기존 작업과 완성본의 확인이 필요해요'};
  }
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function markup(value){
    const tag=value.live?'진행 중':({completed:'완료',waiting:'대기',attention:'확인 필요',paused:'일시정지',offline:'연결 확인',loading:'연결 중',watching:'확인 중'}[value.phase]||'준비');
    return `<div class="agent-strip" data-phase="${escape(value.phase)}" data-live="${value.live?'true':'false'}" role="group" aria-label="${escape((value.ai?'AI 담당 · ':'')+value.label+'. '+value.detail)}">
      <div class="agent-strip-top"><span class="agent-eyebrow">${value.ai?'AI STUDIO':'PRODUCTION'}</span><span class="agent-state"><i aria-hidden="true"></i>${tag}</span></div>
      <div class="agent-current"><span class="agent-orb" aria-hidden="true">${value.phase==='completed'?'<svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-8"/></svg>':'<i></i><i></i><i></i><i></i>'}</span><strong>${escape(value.label)}</strong></div>
      <p class="agent-detail">${escape(value.detail)}</p>
      <div class="agent-stages" aria-hidden="true">${stages.map((label,i)=>`<span data-done="${!!value.done[i]}" data-current="${i===value.stage&&value.phase!=='completed'}"><b></b><small>${label}</small></span>`).join('')}</div>
    </div>`;
  }
  const api={model,referenceModel,markup};if(typeof module==='object'&&module.exports)module.exports=api;else root.AgentStatus=api;
})(typeof window==='undefined'?globalThis:window);

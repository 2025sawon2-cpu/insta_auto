import React,{useState,useRef,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {Player} from '@remotion/player';
import {VideoComposition} from './composition.jsx';
import {ThumbnailEditor} from './thumbnail-editor.jsx';
import {FPS,WIDTH,HEIGHT,EMOJIS,clamp,frameCount,initialDocument,newElement,documentError,lanes} from './model.mjs';

const labels={text:'자막',arrow:'화살표',emoji:'이모지'};
const key=task=>'remotion-draft-'+task.id;
const readDraft=task=>{try{return JSON.parse(localStorage.getItem(key(task))||'null');}catch{return null;}};
const editOf=task=>(task.edits||[]).find(e=>e.id===task.edit_id);
function Editor({root,task,edit}){
  const draft=readDraft(task),changedBase=task.edit_id!==edit.id,stale=changedBase||draft&&draft.edit_id!==edit.id;
  const run=(task.pipeline||[]).find(r=>r.id===task.run_id);
  const editRun=(task.pipeline||[]).slice().reverse().find(r=>r.artifacts?.edit_id===edit.id&&r.status==='completed')||(task.pipeline||[]).slice().reverse().find(r=>r.artifacts?.edit_id===edit.id);
  const pending=task.pending_reproduction?.base_edit_id===edit.id?task.pending_reproduction.overlay_document:
    run?.inputs?.remotion_only&&run.inputs.base_edit_id===edit.id&&run.status!=='completed'?run.inputs.overlay_document:null;
  const saved=task.feedback?.base_edit_id===edit.id&&task.feedback?.overlay_document||pending;
  const baseline=saved||initialDocument(edit);
  const [document,setDocument]=useState(()=>!stale&&draft?draft.document:baseline);
  const docRef=useRef(document);docRef.current=document;
  const [selected,setSelected]=useState(document.elements[0]?.id||null);
  const [frame,setFrame]=useState(0),[notice,setNotice]=useState(''),[sending,setSending]=useState(false);
  const [original,setOriginal]=useState(false),[history,setHistory]=useState([]),[hasDraft,setHasDraft]=useState(!!draft&&!stale);
  const player=useRef(null),canvas=useRef(null),timeline=useRef(null);
  root._remotionPause=()=>player.current?.pause();
  const duration=Number(edit.duration||edit.plan.duration),element=document.elements.find(e=>e.id===selected);
  const activeJobs=task.pending_reproduction||(task.jobs||[]).some(j=>['queued','running'].includes(j.status)&&!['collect_sources','refresh_sources','proposal','suggest_edit'].includes(j.kind));
  const clean=!!edit.clean_preview_url,issue=documentError(document,duration);
  const blocked=stale||!clean||activeJobs||sending;
  const commit=(next,saveHistory=true)=>{
    if(blocked)return;
    if(saveHistory)setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);
    docRef.current=next;setDocument(next);setHasDraft(true);setOriginal(false);root._remotionDirty=true;
    const previous=readDraft(task);
    localStorage.setItem(key(task),JSON.stringify({edit_id:edit.id,feedback_revision:previous?.feedback_revision??task.feedback_revision??0,document:next}));
    root.dispatchEvent(new CustomEvent('production-draft',{bubbles:true}));
  };
  const patch=(id,values,saveHistory=true)=>commit({...docRef.current,elements:docRef.current.elements.map(e=>e.id===id?{...e,...values}:e)},saveHistory);
  const seek=seconds=>{player.current?.pause();player.current?.seekTo(clamp(Math.round(seconds*FPS),0,frameCount(duration)-1));};
  const select=id=>{setSelected(id);const e=docRef.current.elements.find(e=>e.id===id);if(e)seek(e.start);};
  useEffect(()=>{
    const p=player.current;if(!p)return;
    const update=e=>setFrame(e.detail.frame),play=()=>{root._remotionPlaying=true;},pause=()=>{root._remotionPlaying=false;};
    p.addEventListener('frameupdate',update);p.addEventListener('play',play);p.addEventListener('pause',pause);p.addEventListener('ended',pause);
    return()=>{p.removeEventListener('frameupdate',update);p.removeEventListener('play',play);p.removeEventListener('pause',pause);p.removeEventListener('ended',pause);root._remotionPlaying=false;};
  },[clean]);
  useEffect(()=>{root._remotionDirty=hasDraft||!!localStorage.getItem('thumbnail-draft-'+task.id);root.dispatchEvent(new CustomEvent('production-draft',{bubbles:true}));},[hasDraft]);
  const beginDrag=(event,item)=>{
    if(blocked||original)return;event.stopPropagation();event.preventDefault();player.current?.pause();setSelected(item.id);
    const target=event.currentTarget,scale=WIDTH/canvas.current.getBoundingClientRect().width;
    const startX=event.clientX,startY=event.clientY;target.setPointerCapture(event.pointerId);
    setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);
    target.onpointermove=e=>patch(item.id,{x:clamp(item.x+(e.clientX-startX)*scale,0,WIDTH),y:clamp(item.y+(e.clientY-startY)*scale,0,HEIGHT)},false);
    const end=()=>{target.onpointermove=null;target.onpointerup=null;target.onpointercancel=null;};target.onpointerup=end;target.onpointercancel=end;
  };
  const timeDrag=(event,item,edge)=>{
    if(blocked)return;event.preventDefault();event.stopPropagation();select(item.id);
    const target=event.currentTarget,width=timeline.current.getBoundingClientRect().width,start=event.clientX;
    setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);target.setPointerCapture(event.pointerId);
    target.onpointermove=e=>{const delta=(e.clientX-start)/width*duration;
      const value=clamp(Math.round((item[edge]+delta)*FPS)/FPS,edge==='start'?0:item.start+1/FPS,edge==='start'?item.end-1/FPS:duration);
      patch(item.id,{[edge]:value},false);};
    const end=()=>{target.onpointermove=null;target.onpointerup=null;target.onpointercancel=null;};target.onpointerup=end;target.onpointercancel=end;
  };
  const transformDrag=(event,item,field)=>{
    if(blocked||original)return;event.stopPropagation();event.preventDefault();player.current?.pause();
    const target=event.currentTarget,rect=canvas.current.getBoundingClientRect();
    const cx=rect.left+item.x/WIDTH*rect.width,cy=rect.top+item.y/HEIGHT*rect.height;
    const distance=Math.max(1,Math.hypot(event.clientX-cx,event.clientY-cy));
    const angle=Math.atan2(event.clientY-cy,event.clientX-cx);
    setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);target.setPointerCapture(event.pointerId);
    target.onpointermove=e=>{
      const value=field==='size'?clamp(Math.round(item.size*Math.hypot(e.clientX-cx,e.clientY-cy)/distance),24,500):
        ((Math.round(item.rotation+(Math.atan2(e.clientY-cy,e.clientX-cx)-angle)*180/Math.PI)+540)%360)-180;
      patch(item.id,{[field]:value},false);
    };
    const end=()=>{target.onpointermove=null;target.onpointerup=null;target.onpointercancel=null;};target.onpointerup=end;target.onpointercancel=end;
  };
  async function save(action){
    if(localStorage.getItem('thumbnail-draft-'+task.id)){setNotice('썸네일의 미저장 수정사항을 먼저 반영하거나 취소해 주세요.');return;}
    const other=JSON.parse(localStorage.getItem('production-feedback-'+task.id)||'{}');
    if(Object.keys(other).some(k=>/^(script$|speed$|pronunciation$|voice-profile$|source:|caption:|start:|end:|shot:|emphasis:)/.test(k))){setNotice('대본·목소리·소스의 미저장 변경사항을 먼저 반영하거나 취소해 주세요.');return;}
    if(issue){setNotice(issue);return;}setSending(true);setNotice('저장 중…');
    try{
      const body={edit_id:edit.id,feedback_revision:readDraft(task)?.feedback_revision??task.feedback_revision??0,document};
      const response=await fetch('/api/studio/'+task.id+'/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'저장하지 못했습니다.');
      // Do not clear a newer draft created in another window while this request ran.
      const now=readDraft(task);if(!now||JSON.stringify(now.document)===JSON.stringify(document)){localStorage.removeItem(key(task));setHasDraft(false);root._remotionDirty=false;}
      player.current?.pause();documentActiveBlur();root._renderedRevision=null;
      root._options?.onUpdate?.(result);window.ProductionFlow.mount(root,result,root._options);
      setNotice(action==='export-overlays'?'수정 영상 제작을 시작했습니다. 완성 영상 탭에서 확인하세요.':'편집 내용을 저장했습니다.');
    }catch(error){setNotice(error.message);}finally{setSending(false);}
  }
  function documentActiveBlur(){window.document.activeElement?.blur();}
  const resetDraft=()=>{localStorage.removeItem(key(task));setHasDraft(false);root._remotionDirty=false;
    if(changedBase){player.current?.pause();documentActiveBlur();root._renderedRevision=null;window.ProductionFlow.mount(root,task,root._options);return;}
    setDocument(baseline);docRef.current=baseline;setHistory([]);setNotice('이 기기의 미저장 편집을 취소했습니다.');};
  const number=(field,label,min,max,step=1)=><label>{label}<input aria-label={label} type="number" value={element[field]} min={min} max={max} step={step} disabled={blocked}
    onChange={e=>patch(element.id,{[field]:Number(e.target.value)})}/></label>;
  return <div className="re-editor">
    <header className="re-heading"><div><h3>영상 꾸미기</h3><p data-edit-target>편집 대상 · {editRun?'제작 버전 v'+editRun.number:'최신 편집본'}</p><p>자막·화살표·이모지를 넣고 영상 위에서 위치를 옮겨보세요.</p></div><button disabled={blocked||!history.length} onClick={()=>{const next=history.at(-1);setHistory(h=>h.slice(0,-1));commit(next,false);}}>실행 취소</button></header>
    {stale&&<div className="re-notice"><p>새 영상이 준비됐습니다. 이전 영상의 편집은 이 기기에 보관 중입니다.</p><button onClick={resetDraft}>이전 편집 입력 비우기</button><details><summary>보관한 편집 보기</summary><pre>{JSON.stringify(draft?.document||document,null,2)}</pre></details></div>}
    {!clean&&<div className="re-notice"><p>자막 없는 영상으로 편집 미리보기를 먼저 준비하세요.</p><button data-pf="prepare-caption-preview">편집 미리보기 준비</button></div>}
    <div className="re-workspace"><aside className="re-tools"><h4>추가하기</h4>
      {['text','arrow','emoji'].map((kind,i)=><button key={kind} disabled={blocked||document.elements.length>=120} onClick={()=>{const next=newElement(kind,frame/FPS,duration);commit({...document,elements:[...document.elements,next]});setSelected(next.id);}}><span>{['T','↗','😊'][i]}</span>{labels[kind]} 추가</button>)}
      <h4 className="re-layer-title">넣은 요소 <small>{document.elements.length}</small></h4><div className="re-layers">{document.elements.map((e,i)=><button key={e.id} aria-pressed={selected===e.id} onClick={()=>select(e.id)}><span>{labels[e.kind]} {i+1}</span><small>{e.start.toFixed(1)}–{e.end.toFixed(1)}초</small></button>)}{!document.elements.length&&<p>왼쪽 버튼으로 요소를 추가하세요.</p>}</div>
    </aside><section className="re-preview"><div className="re-preview-title"><span>미리보기</span><output>{(frame/FPS).toFixed(2)} / {duration.toFixed(2)}초</output></div>
      <div ref={canvas} className="re-canvas">{clean?<Player ref={player} component={VideoComposition} inputProps={{source:edit.clean_preview_url,document:original?{version:1,elements:[]}:document,selected:original?null:selected,onSelect:setSelected,onDrag:beginDrag,onTransform:transformDrag}}
        durationInFrames={frameCount(duration)} compositionWidth={WIDTH} compositionHeight={HEIGHT} fps={FPS} controls autoPlay={false} clickToPlay={false} moveToBeginningWhenEnded={false}
        style={{width:'100%',aspectRatio:'9/16'}}/>:<div className="re-preview-empty">미리보기를 준비하면 여기에 표시됩니다.</div>}</div>
      <label className="re-original"><input type="checkbox" checked={original} onChange={e=>setOriginal(e.target.checked)}/>꾸미기 전 영상 보기</label>
      <p className="re-help">요소를 끌어 위치를 옮기세요. 모서리는 크기, ↻ 손잡이는 회전을 조절합니다.</p>
    </section><aside className="re-properties"><h4>{element?labels[element.kind]+' 설정':'요소 설정'}</h4>
      {element?<>
        {element.kind==='text'&&<><label>화면 자막<textarea aria-label="화면 자막" maxLength={200} value={element.text} disabled={blocked} onChange={e=>patch(element.id,{text:e.target.value})}/></label><p className="re-help">읽는 대사는 ‘내 대본’에서 수정하세요.</p><label className="re-check"><input type="checkbox" checked={element.background} disabled={blocked} onChange={e=>patch(element.id,{background:e.target.checked})}/>자막 배경 넣기</label></>}
        {element.kind==='emoji'&&<div className="re-emojis" role="group" aria-label="이모지 선택">{EMOJIS.map(emoji=><button key={emoji} disabled={blocked} aria-label={emoji+' 이모지'} aria-pressed={element.text===emoji} onClick={()=>patch(element.id,{text:emoji})}>{emoji}</button>)}</div>}
        {element.kind==='arrow'&&<label>모양<select aria-label="화살표 모양" value={element.shape} disabled={blocked} onChange={e=>patch(element.id,{shape:e.target.value})}><option value="straight">직선 화살표 ↗</option><option value="curved">곡선 화살표 ⤴</option></select></label>}
        {element.kind!=='emoji'&&<label>색상<input aria-label="요소 색상" type="color" value={element.color} disabled={blocked} onChange={e=>patch(element.id,{color:e.target.value})}/></label>}
        <label>크기 <output>{element.size}</output><input aria-label="요소 크기" type="range" min="24" max="500" value={element.size} disabled={blocked} onChange={e=>patch(element.id,{size:Number(e.target.value)})}/></label>
        <label>회전 <output>{element.rotation}°</output><input aria-label="요소 회전" type="range" min="-180" max="180" value={element.rotation} disabled={blocked} onChange={e=>patch(element.id,{rotation:Number(e.target.value)})}/></label>
        <div className="re-pair">{number('x','가로 위치',0,WIDTH)}{number('y','세로 위치',0,HEIGHT)}</div>
        <h4>표시 시간</h4><div className="re-pair">{number('start','시작(초)',0,duration,.01)}{number('end','끝(초)',0,duration,.01)}</div>
        <button className="re-delete" disabled={blocked} onClick={()=>{commit({...document,elements:document.elements.filter(e=>e.id!==element.id)});setSelected(null);}}>요소 삭제</button>
      </>:<p>영상 위나 왼쪽 목록에서 요소를 선택하세요.</p>}
    </aside></div>
    <section className="re-timeline" aria-label="영상과 꾸미기 타임라인"><div className="re-time-heading"><strong>표시 시간 조절</strong><span>막대를 누르면 해당 요소를 선택합니다.</span></div>
      <label className="re-seek">재생 위치<input aria-label="재생 위치" type="range" min="0" max={frameCount(duration)-1} value={frame} onChange={e=>seek(Number(e.target.value)/FPS)}/></label>
      <div className="re-track-row"><span>시간</span><div className="re-ruler">{[0,.25,.5,.75,1].map(r=><span key={r}>{(r*duration).toFixed(1)}초</span>)}</div></div>
      <div className="re-track-row"><span>영상</span><div className="re-video-track" ref={timeline}>{(edit.plan.beats||[]).map((b,i)=>{const shot=edit.plan.shots?.find(s=>s.id===b.selected_shot_id);return <button key={b.id} style={{width:(b.end-b.start)/duration*100+'%'}} onClick={()=>seek(b.start)} aria-label={(i+1)+'번 장면으로 이동'}>{shot?.thumbnail_url?<img src={shot.thumbnail_url} alt=""/>:i+1}</button>;})}<i style={{left:frame/FPS/duration*100+'%'}}/></div></div>
      {['text','arrow','emoji'].map(kind=>{const track=lanes(document.elements.filter(e=>e.kind===kind));return <div key={kind} className="re-track-row"><span>{labels[kind]}</span><div className="re-track" style={{height:track.count*36+8}}>{track.placed.map(({item:e,lane})=><div className={'re-clip '+(kind==='arrow'?'re-yellow ':'')+(selected===e.id?'re-clip-selected':'')} key={e.id} style={{left:e.start/duration*100+'%',width:(e.end-e.start)/duration*100+'%',top:4+lane*36}}>
        <button className="re-time-handle" aria-label={labels[kind]+' 시작 시간 끌기'} disabled={blocked} onPointerDown={event=>timeDrag(event,e,'start')}/><button className="re-clip-label" onClick={()=>select(e.id)} title={e.text||labels[kind]}>{e.text||labels[kind]}</button><button className="re-time-handle" aria-label={labels[kind]+' 끝 시간 끌기'} disabled={blocked} onPointerDown={event=>timeDrag(event,e,'end')}/>
      </div>)}<i style={{left:frame/FPS/duration*100+'%'}}/></div></div>;})}
    </section><div className="re-feedback" role="status">{issue||notice||(activeJobs?'수정 영상을 만드는 중입니다. 완료되면 완성 영상 탭에서 확인하세요.':hasDraft?'수정한 내용은 이 기기에 임시 보관 중입니다.':'화면 글자와 꾸미기만 바뀝니다. 기존 영상과 음성은 보존됩니다.')}</div>
    <footer className="re-footer"><button disabled={sending||!hasDraft} onClick={resetDraft}>이번 수정 취소</button><details><summary>추가 도구</summary><button disabled={blocked||!!issue} onClick={()=>save('save-overlays')}>편집 내용만 저장</button></details><button className="re-primary" disabled={blocked||!!issue} onClick={()=>save('export-overlays')}>{sending?'요청 중…':activeJobs?'수정 영상 제작 중':'수정 내용으로 영상 만들기'}</button></footer>
  </div>;
}
const controllers=new WeakMap();
function EditingSpace({root,task,edit}){
  const modeKey='studio-edit-mode-'+task.id;
  const [mode,setMode]=useState(()=>localStorage.getItem(modeKey)==='thumbnail'?'thumbnail':'video');
  return <><nav className="re-mode-tabs" aria-label="편집 공간"><button type="button" aria-pressed={mode==='video'} onClick={()=>{root._remotionPause?.();setMode('video');localStorage.setItem(modeKey,'video');}}>영상 꾸미기</button>
    <button type="button" aria-pressed={mode==='thumbnail'} onClick={()=>{root._remotionPause?.();setMode('thumbnail');localStorage.setItem(modeKey,'thumbnail');}}>썸네일 · 첫 프레임</button></nav>
    {mode==='thumbnail'?<ThumbnailEditor root={root} task={task} edit={edit}/>:<Editor root={root} task={task} edit={edit}/>}</>;
}
window.RemotionEditor={
  pause(root){root._remotionPause?.();root._remotionPlaying=false;},
  markup:edit=>`<section data-pf-section="edit" class="re-host" data-remotion-edit="${edit.id}"></section>`,
  unmount(root){const host=root.querySelector('[data-remotion-edit]');if(host){controllers.get(host)?.unmount();controllers.delete(host);}root._remotionDirty=false;root._remotionPlaying=false;},
  bind(root,task){const host=root.querySelector('[data-remotion-edit]');if(!host)return;const edit=(task.edits||[]).find(e=>e.id===host.dataset.remotionEdit);if(!edit)return;
    let controller=controllers.get(host);if(!controller){controller=createRoot(host);controllers.set(host,controller);}
    controller.render(<EditingSpace key={edit.id} root={root} task={task} edit={edit}/>);
  }
};

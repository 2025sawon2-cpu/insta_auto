import React,{useState,useRef,useEffect} from 'react';
import {Player} from '@remotion/player';
import {ThumbnailComposition} from './thumbnail-composition.jsx';
import {initialThumbnail,thumbnailError} from './thumbnail-model.mjs';
import {FPS,WIDTH,HEIGHT,clamp,frameCount,newElement} from './model.mjs';
const key=t=>'thumbnail-draft-'+t.id;
const read=t=>{try{return JSON.parse(localStorage.getItem(key(t))||'null');}catch{return null;}};
export function ThumbnailEditor({root,task,edit}){
  const draft=read(task),stale=task.edit_id!==edit.id||!!draft&&draft.edit_id!==edit.id;
  const run=(task.pipeline||[]).find(r=>r.id===task.run_id);
  const saved=task.feedback?.base_edit_id===edit.id&&task.feedback.thumbnail_document||
    task.pending_reproduction?.base_edit_id===edit.id&&task.pending_reproduction.thumbnail_document||
    run?.status!=='completed'&&run?.inputs?.base_edit_id===edit.id&&run.inputs.thumbnail_document;
  const baseline=saved||initialThumbnail(edit);
  const [document,setDocument]=useState(()=>draft&&!stale?draft.document:baseline);
  const docRef=useRef(document);docRef.current=document;
  const [selected,setSelected]=useState(document.elements[0]?.id||null),[hasDraft,setHasDraft]=useState(!!draft&&!stale);
  const [notice,setNotice]=useState(()=>root._thumbnailNotice||''),[sending,setSending]=useState(false),[history,setHistory]=useState([]);
  useEffect(()=>{delete root._thumbnailNotice;},[]);
  const canvas=useRef(null),player=useRef(null);
  root._remotionPause=()=>player.current?.pause();
  useEffect(()=>{root._remotionDirty=hasDraft||!!localStorage.getItem('remotion-draft-'+task.id);root.dispatchEvent(new CustomEvent('production-draft',{bubbles:true}));},[hasDraft]);
  const duration=Number(edit.duration||edit.plan.duration),source=edit.clean_preview_url||edit.export_url;
  const active=task.pending_reproduction||(task.jobs||[]).some(j=>['running','queued'].includes(j.status)&&!['collect_sources','refresh_sources','proposal','suggest_edit'].includes(j.kind));
  const blocked=stale||!edit.export_url||!source||sending||!!active;
  const issue=thumbnailError(document,duration),element=document.elements.find(e=>e.id===selected);
  const apiReady=task.thumbnail_editor_supported===true;
  const commit=(next,record=true)=>{if(blocked)return;if(record)setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);
    setDocument(next);docRef.current=next;setHasDraft(true);root._remotionDirty=true;
    localStorage.setItem(key(task),JSON.stringify({edit_id:edit.id,feedback_revision:read(task)?.feedback_revision??task.feedback_revision??0,document:next}));
    root.dispatchEvent(new CustomEvent('production-draft',{bubbles:true}));};
  const patch=(id,fields,record=true)=>commit({...docRef.current,elements:docRef.current.elements.map(e=>e.id===id?{...e,...fields}:e)},record);
  const drag=(event,item)=>{if(blocked)return;event.preventDefault();setSelected(item.id);
    const target=event.currentTarget,scale=WIDTH/canvas.current.getBoundingClientRect().width,x=event.clientX,y=event.clientY;
    setHistory(h=>[...h.slice(-39),structuredClone(docRef.current)]);target.setPointerCapture(event.pointerId);
    target.onpointermove=e=>patch(item.id,{x:clamp(item.x+(e.clientX-x)*scale,0,WIDTH),y:clamp(item.y+(e.clientY-y)*scale,0,HEIGHT)},false);
    const end=()=>{target.onpointermove=null;target.onpointerup=null;target.onpointercancel=null;};target.onpointerup=end;target.onpointercancel=end;};
  const cancel=()=>{localStorage.removeItem(key(task));setHasDraft(false);root._remotionDirty=false;setDocument(baseline);setHistory([]);
    if(stale){window.document.activeElement?.blur();root._renderedRevision=null;window.ProductionFlow.mount(root,task,root._options);}
    else setNotice('이 기기의 썸네일 수정 내용을 취소했습니다.');};
  async function save(action){
    if(!apiReady){setNotice('썸네일 저장 API를 사용하려면 제작실 웹 서버 업데이트가 필요합니다.');return;}
    const other=JSON.parse(localStorage.getItem('production-feedback-'+task.id)||'{}');
    if(localStorage.getItem('remotion-draft-'+task.id)||Object.keys(other).some(k=>/^(script$|speed$|pronunciation$|voice-profile$|source:|caption:|start:|end:|shot:|emphasis:)/.test(k))){setNotice('영상 꾸미기·대본·목소리의 미저장 수정사항을 먼저 반영하거나 취소해 주세요.');return;}
    if(issue){setNotice(issue);return;}setSending(true);setNotice('썸네일 저장 중…');
    try{
      const response=await fetch('/api/studio/'+task.id+'/'+action,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({edit_id:edit.id,feedback_revision:read(task)?.feedback_revision??task.feedback_revision??0,document})});
      const result=await response.json();if(!response.ok)throw Error(result.error||'썸네일을 저장하지 못했습니다.');
      const now=read(task);if(!now||JSON.stringify(now.document)===JSON.stringify(document)){localStorage.removeItem(key(task));setHasDraft(false);root._remotionDirty=false;}
      root._thumbnailNotice=action==='export-thumbnail'?'첫 프레임을 바꾼 새 버전을 제작합니다. 완성 영상 탭에서 확인하세요.':'썸네일 내용을 저장했습니다. 영상에 반영하려면 아래 버튼을 누르세요.';
      window.document.activeElement?.blur();root._renderedRevision=null;root._options?.onUpdate?.(result);window.ProductionFlow.mount(root,result,root._options);
      setNotice(action==='export-thumbnail'?'첫 프레임을 바꾼 새 버전을 제작합니다. 완성 영상 탭에서 확인하세요.':'썸네일 내용을 저장했습니다. 영상에 반영하려면 아래 버튼을 누르세요.');
    }catch(error){setNotice(error.message);}finally{setSending(false);}
  }
  const number=(field,label,min,max)=><label>{label}<input aria-label={label} type="number" min={min} max={max} value={element[field]} disabled={blocked} onChange={e=>patch(element.id,{[field]:Number(e.target.value)})}/></label>;
  return <section className="re-thumbnail" aria-label="첫 프레임 썸네일 편집">
    <header className="re-heading"><div><h3>첫 프레임 썸네일</h3><p>영상 맨 앞 한 장만 바꿉니다. 본문 장면·자막·음성은 그대로 유지됩니다.</p></div><span className="re-frame-badge">1 frame · 0.033초</span></header>
    {stale&&<div className="re-notice"><p>새 편집본이 준비됐습니다. 이전 썸네일 초안은 이 기기에 보관 중입니다.</p><button onClick={cancel}>이전 초안 비우고 새 영상 보기</button></div>}
    {!edit.export_url&&<div className="re-notice">완성 영상이 준비되면 썸네일을 편집할 수 있습니다.</div>}
    {!apiReady&&<div className="re-notice">미리보기와 임시 편집을 사용할 수 있습니다. 저장·영상 반영은 제작실 웹 서버 업데이트 후 사용할 수 있습니다.</div>}
    <div className="re-thumbnail-workspace"><section className="re-preview"><div className="re-preview-title"><strong>썸네일 미리보기</strong><span>9:16</span></div>
      <div ref={canvas} className="re-canvas">{source?<Player ref={player} component={ThumbnailComposition}
        inputProps={{source,background:edit.thumbnail_background_url,document,selected,onDrag:drag}}
        durationInFrames={1} compositionWidth={WIDTH} compositionHeight={HEIGHT} fps={FPS} controls={false} clickToPlay={false} autoPlay={false} style={{width:'100%',aspectRatio:'9/16'}}/>:
        <div className="re-preview-empty">완성 영상을 준비하면 여기에 표시됩니다.</div>}</div>
      <p className="re-help">문구를 직접 끌어 위치를 조절할 수 있습니다.</p>
    </section><aside className="re-thumbnail-controls">
      <section><h4>배경 장면</h4><p className="re-help">장면을 고르면 그 한 장이 첫 프레임에 들어갑니다.</p>
        {edit.thumbnail_background_url&&<button type="button" aria-pressed={document.frame===-1} disabled={blocked} onClick={()=>commit({...document,frame:-1})}>현재 썸네일 배경 사용</button>}
        <label>영상에서 장면 선택 <output>{document.frame===-1?'현재 배경':(document.frame/FPS).toFixed(2)+'초'}</output>
          <input aria-label="썸네일 배경 장면" type="range" min="0" max={frameCount(duration)-1} value={Math.max(0,document.frame)} disabled={blocked} onChange={e=>commit({...document,frame:Number(e.target.value)})}/></label>
      </section><section><div className="re-thumbnail-copy-heading"><h4>썸네일 문구</h4><button disabled={blocked||document.elements.length>=20} onClick={()=>{
        const next={...newElement('text',0,1/FPS),text:'썸네일 문구',size:110,y:520+document.elements.length*160,rotation:-8};
        next.y=clamp(next.y,0,HEIGHT);commit({...document,elements:[...document.elements,next]});setSelected(next.id);
      }}>＋ 문구 추가</button></div>
      <div className="re-thumbnail-lines">{document.elements.map((e,i)=><button key={e.id} aria-pressed={selected===e.id} onClick={()=>setSelected(e.id)}>{i+1}. {e.text||'문구'}</button>)}</div>
      {!element&&<p className="re-help">문구를 추가하거나 목록에서 선택하세요.</p>}
      {element&&<div className="re-properties"><label>선택한 문구<textarea aria-label="썸네일 문구" maxLength={200} value={element.text} disabled={blocked} onChange={e=>patch(element.id,{text:e.target.value})}/></label>
        <div className="re-pair"><label>글자 색상<input aria-label="썸네일 글자 색상" type="color" value={element.color} disabled={blocked} onChange={e=>patch(element.id,{color:e.target.value})}/></label>
          {number('size','썸네일 글자 크기',24,500)}</div>
        <div className="re-pair">{number('x','썸네일 가로 위치',0,WIDTH)}{number('y','썸네일 세로 위치',0,HEIGHT)}</div>
        <label>기울기 <output>{element.rotation}°</output><input aria-label="썸네일 기울기" type="range" min="-180" max="180" value={element.rotation} disabled={blocked} onChange={e=>patch(element.id,{rotation:Number(e.target.value)})}/></label>
        <label className="re-check"><input type="checkbox" checked={element.background} disabled={blocked} onChange={e=>patch(element.id,{background:e.target.checked})}/>문구 뒤에 배경 넣기</label>
        <button className="re-delete" disabled={blocked} onClick={()=>{commit({...document,elements:document.elements.filter(e=>e.id!==element.id)});setSelected(null);}}>선택한 문구 삭제</button>
      </div>}</section></aside></div>
    <div className="re-feedback" role="status">{issue||notice||(active?'썸네일을 반영한 새 버전을 만드는 중입니다.':hasDraft?'미저장 썸네일은 이 기기에 임시 보관 중입니다.':'문구는 도현 폰트로 표시됩니다. 썸네일은 영상 재생 시간에 추가되지 않습니다.')}</div>
    <footer className="re-footer"><button disabled={blocked||!history.length} onClick={()=>{const next=history.at(-1);setHistory(h=>h.slice(0,-1));commit(next,false);}}>실행 취소</button>
      <button disabled={sending||!hasDraft&&!stale} onClick={cancel}>이번 수정 취소</button>
      <button disabled={blocked||!!issue||!apiReady} onClick={()=>save('save-thumbnail')}>썸네일 내용 저장</button>
      <button className="re-primary" disabled={blocked||!!issue||!apiReady} onClick={()=>save('export-thumbnail')}>{active?'새 버전 제작 중':'썸네일 반영한 영상 만들기'}</button></footer>
  </section>;
}

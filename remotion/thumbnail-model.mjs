import {FPS,clamp,frameCount,documentError} from './model.mjs';
export function initialThumbnail(edit){
  if(edit.plan.thumbnail_document)return structuredClone(edit.plan.thumbnail_document);
  const spec=edit.plan.cover_spec||{},duration=Number(edit.duration||edit.plan.duration);
  return {version:1,frame:edit.thumbnail_background_url?-1:clamp(Math.round((spec.source?.timeline_time||0)*FPS),0,frameCount(duration)-1),
    elements:(spec.lines||[]).slice(0,2).filter(t=>t.trim()).map((text,i)=>({id:'cover-line-'+i,kind:'text',text,
      start:0,end:1/FPS,x:spec.layout?.[i]?.center?.[0]??540,y:spec.layout?.[i]?.center?.[1]??(520+i*160),
      size:clamp(spec.layout?.[i]?.font_px||spec.style?.font_sizes?.[i]||110,24,500),rotation:spec.style?.rotation??-8,
      color:spec.style?.colors?.[i]||['#ffffff','#ffdf40'][i],background:false,shape:'straight'}))};
}
export function thumbnailError(doc,duration){
  if(!Number.isInteger(doc.frame)||doc.frame < -1||doc.frame>=frameCount(duration))return '영상 안의 배경 장면을 선택하세요.';
  if(doc.elements.length>20)return '썸네일에는 요소를 최대 20개까지 넣을 수 있습니다.';
  if(doc.elements.some(e=>e.start!==0||e.end!==1/FPS))return '썸네일은 첫 한 프레임에만 표시됩니다.';
  return documentError(doc,1/FPS);
}

export const FPS=30, WIDTH=1080, HEIGHT=1920;
export const EMOJIS=['😊','😍','👍','👇','👉','🔥','✨','❤️','✅','🎉'];
export const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
export const frameCount=duration=>Math.max(1,Math.ceil(duration*FPS));
export const visible=(item,frame)=>frame>=Math.round(item.start*FPS)&&frame<Math.round(item.end*FPS);
export function initialDocument(edit){
  if(edit.plan.overlay_document)return structuredClone(edit.plan.overlay_document);
  const style=edit.plan.caption_style||{};
  return {version:1,elements:(edit.plan.cues||[]).map((cue,i)=>({
    id:'caption-'+i,kind:'text',text:cue.text,start:cue.start,end:cue.end,
    x:style.position?.[0]??540,y:style.position?.[1]??1180,size:Math.min(500,style.font_size||56),rotation:0,color:'#ffffff',background:false,shape:'straight'
  }))};
}
export function newElement(kind,at,duration){
  const start=clamp(Math.round(at*FPS)/FPS,0,Math.max(0,duration-1/FPS));
  return {id:'element-'+crypto.randomUUID(),kind,text:kind==='text'?'자막을 입력하세요':kind==='emoji'?'😊':'',
    start,end:Math.min(duration,start+3),x:540,y:kind==='text'?1440:800,
    size:kind==='text'?64:kind==='emoji'?140:220,rotation:0,color:kind==='arrow'?'#ffdf00':'#ffffff',
    background:false,shape:'curved'};
}
export function documentError(document,duration){
  if(document.elements.length>120)return '요소는 최대 120개까지 넣을 수 있습니다.';
  for(const e of document.elements){
    for(const [field,min,max] of [['x',0,WIDTH],['y',0,HEIGHT],['size',24,500],['rotation',-180,180]])if(!Number.isFinite(e[field])||e[field]<min||e[field]>max)return '위치·크기·회전 값을 표시된 범위 안에서 지정하세요.';
    if(!Number.isFinite(e.start)||!Number.isFinite(e.end)||e.start<0||e.end>duration+.001||Math.round(e.end*FPS)<=Math.round(e.start*FPS))return '표시 시작과 끝을 영상 범위 안에서 지정하세요.';
    if(e.kind==='text'&&(!e.text.trim()||e.text.length>200))return '자막은 1~200자로 입력하세요.';
    if(e.kind==='emoji'&&!EMOJIS.includes(e.text))return '목록에서 이모지를 선택하세요.';
  }
  return '';
}
export function lanes(elements){
  const ends=[],placed=[];
  for(const item of elements.slice().sort((a,b)=>a.start-b.start)){
    let lane=ends.findIndex(end=>end<=item.start);if(lane<0)lane=ends.length;
    ends[lane]=item.end;placed.push({item,lane});
  }
  return {placed,count:Math.max(1,ends.length)};
}

import React from 'react';
import {AbsoluteFill,OffthreadVideo,useCurrentFrame} from 'remotion';
import {visible,WIDTH,HEIGHT} from './model.mjs';

export function Element({item,fontFamily,thumbnail=false}){
  if(item.kind==='arrow')return <svg width={item.size} height={item.size} viewBox="0 0 200 200" aria-hidden="true" style={{overflow:'visible'}}>
    <path d={item.shape==='curved'?'M25 165 Q30 25 165 55':'M25 165 L165 35'} fill="none" stroke={item.color} strokeWidth="15" strokeLinecap="round"/>
    <path d={item.shape==='curved'?'M130 22 L168 55 L135 91':'M122 35 L165 35 L165 78'} fill="none" stroke={item.color} strokeWidth="15" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>;
  return <div style={{fontFamily:fontFamily||'"Malgun Gothic","Apple SD Gothic Neo","Segoe UI Emoji",sans-serif',fontSize:item.size,fontWeight:700,fontStyle:thumbnail?'italic':'normal',
    color:item.color,textAlign:'center',lineHeight:1.25,whiteSpace:'pre-wrap',overflowWrap:'anywhere',
    maxWidth:thumbnail?1000:900,padding:item.background?'16px 26px':'0',borderRadius:16,background:item.background?'rgba(0,0,0,.72)':'transparent',
    textShadow:item.kind==='text'?(thumbnail?'5px 5px 16px #000,-4px -4px 0 #000,4px -4px 0 #000,-4px 4px 0 #000':'2px 2px 3px #000,-2px -2px 3px #000,2px -2px 3px #000,-2px 2px 3px #000'):'none'}}>{item.text}</div>;
}
export function VideoComposition({source,document,selected,onSelect,onDrag,onTransform}){
  const frame=useCurrentFrame();
  return <AbsoluteFill style={{background:'#111'}}>
    <OffthreadVideo src={source} style={{width:WIDTH,height:HEIGHT,objectFit:'cover'}}/>
    {document.elements.filter(e=>visible(e,frame)).map(item=><div key={item.id} data-overlay-id={item.id}
      onPointerDown={onDrag?event=>onDrag(event,item):undefined}
      onClick={onSelect?event=>{event.stopPropagation();onSelect(item.id);}:undefined}
      style={{position:'absolute',left:item.x,top:item.y,transform:`translate(-50%,-50%) rotate(${item.rotation}deg)`,
        outline:selected===item.id?'4px solid #3879ff':'none',outlineOffset:12,cursor:onDrag?'move':'default',touchAction:'none',userSelect:'none'}}>
      <Element item={item}/>
      {selected===item.id&&onTransform&&<>
        <button type="button" data-overlay-resize aria-label="선택 요소 크기 끌기" onPointerDown={event=>onTransform(event,item,'size')}
          style={{position:'absolute',right:-30,bottom:-30,width:40,height:40,borderRadius:'50%',background:'white',border:'4px solid #3879ff',cursor:'nwse-resize',touchAction:'none'}}/>
        <button type="button" data-overlay-rotate aria-label="선택 요소 회전 끌기" onPointerDown={event=>onTransform(event,item,'rotation')}
          style={{position:'absolute',left:'50%',top:-80,transform:'translateX(-50%)',width:50,height:50,fontSize:36,color:'#2454be',borderRadius:'50%',background:'white',border:'4px solid #3879ff',cursor:'grab',touchAction:'none'}}>↻</button>
      </>}
    </div>)}
  </AbsoluteFill>;
}

import React,{useEffect,useState} from 'react';
import {AbsoluteFill,Img,Freeze,OffthreadVideo,delayRender,continueRender,cancelRender} from 'remotion';
import {Element} from './composition.jsx';
import {WIDTH,HEIGHT} from './model.mjs';
export function ThumbnailComposition({source,background,document,fontUrl='/assets/fonts/DoHyeon-Regular.ttf',selected,onDrag}){
  const [handle]=useState(()=>delayRender('썸네일 폰트 준비'));
  useEffect(()=>{let done=false;
    const font=new FontFace('StudioThumbnail',`url(${fontUrl})`);
    font.load().then(f=>{window.document.fonts.add(f);if(!done)continueRender(handle);}).catch(error=>{if(!done)cancelRender(error);});
    return()=>{done=true;continueRender(handle);};
  },[fontUrl,handle]);
  return <AbsoluteFill style={{background:'#111'}}>
    {background&&document.frame===-1?<Img src={background} style={{width:WIDTH,height:HEIGHT,objectFit:'cover'}}/>:
      <Freeze frame={Math.max(0,document.frame)}><OffthreadVideo src={source} muted style={{width:WIDTH,height:HEIGHT,objectFit:'cover'}}/></Freeze>}
    {document.elements.map(item=><div key={item.id} data-thumbnail-element={item.id} onPointerDown={onDrag?e=>onDrag(e,item):undefined}
      style={{position:'absolute',width:'max-content',maxWidth:1000,left:item.x,top:item.y,transform:`translate(-50%,-50%) rotate(${item.rotation}deg)`,
        outline:selected===item.id?'4px solid #3879ff':'none',outlineOffset:10,cursor:onDrag?'move':'default',touchAction:'none',userSelect:'none'}}>
      <Element item={item} fontFamily='StudioThumbnail' thumbnail/>
    </div>)}
  </AbsoluteFill>;
}

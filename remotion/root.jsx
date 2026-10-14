import React from 'react';
import {Composition,registerRoot} from 'remotion';
import {VideoComposition} from './composition.jsx';
import {ThumbnailComposition} from './thumbnail-composition.jsx';
import {FPS,WIDTH,HEIGHT,frameCount} from './model.mjs';
function Root(){return <><Composition id="InstaOverlay" component={VideoComposition} fps={FPS} width={WIDTH} height={HEIGHT}
  durationInFrames={30} defaultProps={{source:'',document:{version:1,elements:[]},duration:1}}
  calculateMetadata={({props})=>({durationInFrames:frameCount(props.duration)})}/>
  <Composition id="InstaThumbnail" component={ThumbnailComposition} fps={FPS} width={WIDTH} height={HEIGHT} durationInFrames={1}
    defaultProps={{source:'',background:'',document:{version:1,frame:-1,elements:[]}}}/></>;}
registerRoot(Root);

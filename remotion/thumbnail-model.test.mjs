import {test} from 'node:test';
import assert from 'node:assert/strict';
import {initialThumbnail,thumbnailError} from './thumbnail-model.mjs';
test('thumbnail imports existing copy and layout without changing the video captions',()=>{
  const edit={duration:3,thumbnail_background_url:'/background.png',plan:{cues:[{text:'본문'}],cover_spec:{lines:['첫 줄','둘째 줄'],layout:[{center:[520,400],font_px:136}]}}};
  const original=structuredClone(edit),doc=initialThumbnail(edit);
  assert.equal(doc.frame,-1);assert.equal(doc.elements[0].text,'첫 줄');assert.equal(doc.elements[0].x,520);
  assert.equal(doc.elements[0].end,1/30);assert.equal(thumbnailError(doc,3),'');assert.deepEqual(edit,original);
});
test('saved empty thumbnail stays empty and out of bounds frames cannot be exported',()=>{
  assert.equal(initialThumbnail({plan:{thumbnail_document:{version:1,frame:0,elements:[]}}}).elements.length,0);
  assert.ok(thumbnailError({version:1,frame:90,elements:[]},3));
});

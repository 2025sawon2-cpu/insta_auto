import {test} from 'node:test';
import assert from 'node:assert/strict';
import {visible,initialDocument,documentError,lanes} from './model.mjs';
test('preview uses nearest-frame inclusive start and exclusive end',()=>{
  const item={start:.05,end:.15};
  assert.equal(visible(item,1),false);assert.equal(visible(item,2),true);
  assert.equal(visible(item,4),true);assert.equal(visible(item,5),false);
});
test('empty overlay document survives reopening instead of restoring captions',()=>{
  assert.deepEqual(initialDocument({plan:{overlay_document:{version:1,elements:[]},cues:[{text:'old'}]}}).elements,[]);
});
test('timeline packs non-overlapping captions and separates overlapping layers',()=>{
  assert.equal(lanes([{start:0,end:1},{start:1,end:2},{start:2,end:3}]).count,1);
  assert.equal(lanes([{start:0,end:2},{start:1,end:3}]).count,2);
});
test('subframe empty intervals are invalid',()=>{
  assert.ok(documentError({elements:[{kind:'arrow',start:0,end:.001}]},1));
});

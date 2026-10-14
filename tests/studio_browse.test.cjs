const {test}=require('node:test');
const assert=require('node:assert/strict');
const browse=require('../web/studio-browse.js');
const detection=require('../web/hot-detection.js');
const {listPage}=require('../web/studio-board.js');

test('studio and hot dashboard share the discovery day when first collection was earlier',()=>{
 const now=Date.parse('2026-10-12T07:00:00+09:00')/1000;
 const item={collected_at:now-86400,hot_detected_at:now,collection_date_at:now,tier:1};
 assert.equal(browse.collected(item),detection.dateKey(item.hot_detected_at));
 assert.equal(browse.collected(item),'2026-10-12');
 assert.equal(detection.isToday(item,now),true);
 assert.equal(browse.collected({collected_at:now-86400}),'2026-10-11');
 assert.equal(browse.collected({creation_mode:'self_shot',created:now}),'2026-10-12');
 assert.equal(browse.collected({created:now}),'');
});

test('Korean midnight is independent of UTC and invalid dates remain unknown',()=>{
 for(const iso of ['2026-10-11T14:59:59Z','2026-10-11T15:00:00Z']){
  const ts=Date.parse(iso)/1000;assert.equal(browse.date(ts),detection.dateKey(ts));
 }
 assert.equal(browse.date(Date.parse('2026-10-11T15:00:00Z')/1000),'2026-10-12');
 assert.equal(browse.date(NaN),'');assert.equal(browse.date(undefined),'');
});

test('recent collection ordering follows the same date as the filter, not creation time',()=>{
 const items=[{id:'earlier',status:'completed',created:200,collected_at:90,collection_date_at:100},
              {id:'later-hot',status:'completed',created:100,collected_at:10,collection_date_at:150}];
 assert.deepEqual(listPage(items,{filter:'all',collectedOrder:true}).items.map(t=>t.id),['later-hot','earlier']);
});

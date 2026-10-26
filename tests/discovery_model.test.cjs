const {test}=require('node:test');
const assert=require('node:assert/strict');
const detection=require('../web/hot-detection.js');
const model=require('../web/discovery/model.js').create(detection);
const now=Date.parse('2026-10-06T00:30:00+09:00')/1000;
const state={detection:'today',period:24,kind:'all',account:'',q:'',tier:1,assessment:'all',topic:null,sort:'rank'};
const post=(id,changes={})=>({shortcode:id,username:'creator',caption:'텐트를 펼치는 방법',hashtags:['캠핑'],
  categories:['캠핑·여행'],kind:'reel',tier:2,rank_score:4,hot_detected_at:now-60,taken_at:now-86400,
  assessment:{status:'confirmed'},...changes});

test('daily 72-hour snapshots rank only qualified posts across dates and preserve completed ranks',()=>{
  const daily=(id,rank,changes={})=>post(id,{ranking_mode:'views_per_follower_72h',eligible:true,
    rank,rank_score:10-rank,hot_detected_at:null,assessment:{status:'qualified'},...changes});
  const posts=[daily('new',2),daily('completed',1,{taken_at:now-71*3600,production:{state:'completed'}}),
    daily('below',undefined,{eligible:false,tier:0})];
  const base=model.baseFiltered(posts,state,now);
  assert.equal(base.length,2);
  assert.deepEqual(model.filtered(base,state,now).map(p=>p.shortcode),['completed','new']);
  assert.deepEqual(model.filtered(base,{...state,account:'creator',assessment:'confirmed'},now)
    .map(p=>p.rank),[1,2]);
});

test('discovery filters use Korean detection date, and rolling periods can include yesterday',()=>{
  const posts=[post('today'),post('yesterday',{hot_detected_at:now-3600}),post('ordinary',{tier:0})];
  assert.deepEqual(model.baseFiltered(posts,state,now).map(p=>p.shortcode),['today']);
  assert.deepEqual(model.baseFiltered(posts,{...state,detection:'all'},now).map(p=>p.shortcode),['today','yesterday']);
  assert.equal(model.baseFiltered(posts,{...state,q:'#캠핑',kind:'video'},now).length,1);
  assert.equal(model.baseFiltered(posts,{...state,account:'someone-else'},now).length,0);
});

test('today outranks higher-scoring history without mutating the report order',()=>{
  const posts=[post('yesterday',{hot_detected_at:now-3600,rank_score:100}),post('today')];
  assert.deepEqual(model.filtered(posts,state,now).map(p=>p.shortcode),['today','yesterday']);
  assert.equal(posts[0].shortcode,'yesterday');
});

test('daily totals stay independent from card filters and exclude undetected posts',()=>{
  const posts=[post('one'),post('two',{kind:'image',username:'other',assessment:{status:'provisional'}}),
    post('old',{hot_detected_at:now-3600}),post('unknown',{hot_detected_at:null})];
  assert.equal(model.baseFiltered(posts,{...state,q:'not present'},now).length,0);
  assert.deepEqual(model.dailyStats(posts,now),{day:'2026-10-06',total:2,confirmed:1,provisional:1,accounts:2,videoPercent:50});
});

test('topics count distinct accounts and keep the miscellaneous category last',()=>{
  const posts=[post('one'),post('two'),post('three',{categories:['생활·기타'],tier:3})];
  assert.deepEqual(model.topics(posts,state),[
    {label:'캠핑·여행',posts:2,score:4,accounts:1},{label:'생활·기타',posts:1,score:3,accounts:1}]);
});

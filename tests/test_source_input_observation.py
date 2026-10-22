"""Input diagnostics preserve real actions, and expose restoration/remounts."""
import json
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from hotpost import source_input_observation as obs
from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings


def facts(**kw):
    return dict(same_node=True,original_connected=True,connected=True,visible=True,
        focused=True,read_only=False,disabled=False,value='old',value_truncated=False,
        matches_query=False,selection_start=0,selection_end=0,selection_direction='none',**kw)


class Field:
    def __init__(self,actions,mode):self.actions=actions;self.mode=mode;self.value='old';self.snap=0;self.disposed=False
    def is_visible(self):return True
    def wait_for(self,**kw):pass
    def input_value(self):return self.value
    def element_handle(self,**kw):
        if self.mode=='diagnostic_error':raise RuntimeError('not exposed')
        return SimpleNamespace(dispose=lambda:setattr(self,'disposed',True))
    def evaluate(self,script,args,**kw):
        self.snap+=1
        row=facts();row.update(value=self.value,matches_query=self.value=='new query')
        if self.snap==3:row.update(selection_start=0,selection_end=3)
        if self.mode=='remount' and self.snap>=4:row.update(same_node=False,original_connected=False)
        if self.mode=='malformed':row['html']='secret'
        return row
    def press(self,key):self.actions.append(('press',key))
    def press_sequentially(self,text,**kw):
        self.actions.append(('type',text,kw['delay']))
        if self.mode=='typing_error':raise RuntimeError('actual typing failed')
        self.value=text
    def fill(self,*a):pytest.fail('Observation must not introduce fill')


def run(tmp_path,monkeypatch,mode):
    actions=[];field=Field(actions,mode)
    def wait(ms):
        actions.append(('wait',ms))
        if mode=='restore':field.value='old'
    page=SimpleNamespace(url='https://www.tiktok.com/search?q=old',
        locator=lambda _:SimpleNamespace(first=field,count=lambda:1),wait_for_timeout=wait,
        wait_for_url=lambda *a,**kw:actions.append(('url_match',)))
    searcher=BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(searcher,'_pace',lambda *a,**kw:actions.append(('pace',)))
    monkeypatch.setattr('hotpost.browser_search.record_unresolved',lambda *a:actions.append(('unresolved',)))
    audit={}
    return searcher,page,field,actions,audit


@pytest.mark.parametrize('mode',['normal','diagnostic_error','malformed','remount'])
def test_diagnostic_results_never_change_input_actions_or_success(tmp_path,monkeypatch,mode):
    searcher,page,field,actions,audit=run(tmp_path,monkeypatch,mode)
    assert searcher._submit_search(page,'tiktok','new query',audit) is True
    assert actions==[('pace',),('press','ControlOrMeta+A'),('type','new query',90),
                     ('wait',750),('press','Enter'),('url_match',)]
    rows=audit['input_observations']['snapshots']
    assert [r['phase'] for r in rows]==list(obs.PHASES)
    if mode in ('diagnostic_error','malformed'):
        assert all(r['status']=='unavailable' for r in rows)
        assert 'secret' not in json.dumps(rows) and 'not exposed' not in json.dumps(rows)
    elif mode=='remount':assert rows[3]['same_node'] is False and rows[3]['original_connected'] is False
    if mode!='diagnostic_error':assert field.disposed


def test_restoration_is_observed_but_existing_mismatch_still_prevents_enter(tmp_path,monkeypatch):
    searcher,page,field,actions,audit=run(tmp_path,monkeypatch,'restore')
    assert searcher._submit_search(page,'tiktok','new query',audit) is False
    assert actions==[('pace',),('press','ControlOrMeta+A'),('type','new query',90),('wait',750),('unresolved',)]
    rows=audit['input_observations']['snapshots']
    assert rows[3]['matches_query'] is True and rows[4]['matches_query'] is False
    assert rows[2]['selection_end']==3
    assert audit['execution']['query_submitted'] is False


def test_real_typing_error_is_not_swallowed_and_handle_is_disposed(tmp_path,monkeypatch):
    searcher,page,field,actions,audit=run(tmp_path,monkeypatch,'typing_error')
    with pytest.raises(RuntimeError,match='actual typing failed'):
        searcher._submit_search(page,'tiktok','new query',audit)
    assert field.disposed and ('press','Enter') not in actions
    assert len(audit['input_observations']['snapshots'])==3


@pytest.mark.parametrize('patch',[{'value':'x'*201},{'value':'\ud800'},{'selection_start':True},
    {'selection_end':-1},{'selection_direction':'secret'},{'read_only':1},{'unknown':0}])
def test_host_discards_unbounded_or_unknown_output(patch):
    row=facts();row.update(patch)
    with pytest.raises(ValueError):obs._validated(row)


def test_fixed_js_limits_iteration_handles_unicode_and_tracks_original_node():
    node=shutil.which('node')
    if not node:pytest.skip('Node required for isolated fixed-JS execution')
    script='const observe='+obs._JS+''';
      const make=value=>({value,isConnected:true,readOnly:false,disabled:false,
        selectionStart:0,selectionEnd:0,selectionDirection:'none',getBoundingClientRect:()=>({width:1,height:1})});
      const el=make('😀'.repeat(200)+'Z');global.document={activeElement:el};
      const normal=observe(el,{original:el,query:el.value});
      const replacement=make('new');const changed=observe(replacement,{original:el,query:'new'});
      const surrogate=observe(make('A'+String.fromCharCode(0xD800)),{original:el,query:'no'});
      let steps=0;const bounded=make({[Symbol.iterator]:function*(){while(true){if(++steps>201)throw Error('unbounded');yield 'x'}}});
      const long=observe(bounded,{original:el,query:'no'});
      process.stdout.write(JSON.stringify({normal,changed,surrogate,long,steps}));'''
    result=subprocess.run([node,'-e',script],capture_output=True,text=True,encoding='utf8',timeout=10,check=True)
    rows=json.loads(result.stdout)
    assert len(rows['normal']['value'])==200 and rows['normal']['value_truncated'] is True
    assert rows['normal']['matches_query'] is True and rows['normal']['same_node'] is True
    assert rows['changed']['same_node'] is False and rows['changed']['focused'] is False
    assert rows['surrogate']['value']=='A\ufffd' and rows['steps']==201
    for key in ('normal','changed','surrogate','long'):obs._validated(rows[key])


def test_snapshot_count_budget_and_disposal_failure_do_not_escape():
    field=SimpleNamespace(element_handle=lambda **kw:SimpleNamespace(dispose=lambda:(_ for _ in ()).throw(RuntimeError())),
        evaluate=lambda *a,**kw:facts())
    audit={};observer=obs.InputObservation(field,'new query',audit)
    for _ in range(10):observer.capture('before_pacing')
    observer.close()
    assert len(audit['input_observations']['snapshots'])==5
    assert len(json.dumps(audit,ensure_ascii=False).encode('utf8'))<8192


def test_observer_is_protected_from_domain_repair():
    from hotpost.video_agent_repairs import _PROTECTED
    assert 'source_input_observation.py' in _PROTECTED

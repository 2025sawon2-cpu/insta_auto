"""Actual renderer/voice verification in per-video isolated review stores."""
import argparse,copy,json,time,sqlite3
from pathlib import Path
from dataclasses import replace
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost import daily_quality

ROOT=Path('data/feedback-remake-20261012-v1').resolve()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('code');parser.add_argument('--version',default='final');a=parser.parse_args();code=a.code
    final=ROOT/code/a.version;base=json.loads((ROOT/code/'baseline.json').read_text('utf-8'))
    result=json.loads((final/'render-result.json').read_text('utf-8'));plan=json.loads((final/'timeline.json').read_text('utf-8'))
    assert plan['script_text'].endswith('댓글에 ‘나도’ 남겨주세요.')
    assert not plan['footage_diversity']['frozen_beats'] and plan['footage_diversity']['replayed_seconds']<=.001
    assert plan['cover_spec']['source']['reviewed'] and plan['cover_spec']['source']['faces_present'] is False
    # Each short-lived client owns its review writer until completion, rather
    # than starting the next client's queued job in a disappearing daemon.
    studio=Studio(replace(load_settings(),data_dir=ROOT/'review-store'/code/a.version,studio_auto_top_enabled=False),workers=False)
    task,_=studio.store.create(code,'재제작 실제 완성본 검토',prepare=False)
    edit={**result,'id':'remake-20261012-'+code,'export_path':result['preview_path'],
          'script_id':plan['voice']['script_id'],'voice_id':plan['voice']['id'],'status':'completed'}
    def setup(s,db):
        s.update(reference_video=base['state']['reference_video'],original_text=base['state']['original_text'],
          reviewed_original_text=base['state'].get('reviewed_original_text') or base['state']['original_text'],
          benchmark_analysis=base['state'].get('benchmark_analysis',{}),
          selected_candidate=json.loads(((final if (final/'script.json').exists() else ROOT/code/'final')/'script.json').read_text('utf-8')),edits=[edit],edit_id=edit['id'],
          daily_quality={'policy':daily_quality.POLICY,'status':'pending','max_repairs':3,'repair_round':0,'reviews':[]},
          automation={'active':False,'protocol':2})
    state=studio.store.change(task['id'],setup)
    daily_quality.REVIEW_INSTRUCTION+=(
      ' This user revision additionally requires NO human face in the first-frame cover, including reflected or photographed faces. '
      'A blurred face does not qualify: select another actual scene. The cover IMAGE AND COPY together must leave a concrete '
      'product curiosity unresolved, rather than reveal the whole answer. Reject logo-only fallback scenes that do not show '
      'the product or its use; physical logos on a visible garment are allowed. '
      'Every voice was generated in one complete pass with the same verified server configuration and seed. '
      'Do not infer subjective vocal naturalness from frames or fixed parameters. '
      'The requested brief CTA is exactly 댓글에 ‘나도’ 남겨주세요. No end announcement should precede it.'
    )
    report=studio._quality_review(state,{'id':'actual-remake-review-'+code,'kind':'quality_review','payload':{'edit_id':edit['id']}})
    _atomic_json(final/'daily-review.json',report)
    # Audit actual synthesis runs, rather than just submitted parameters.
    voice_folder=final if (final/'voice-submission.json').exists() else ROOT/code/'final'
    request=json.loads((voice_folder/'voice-submission.json').read_text('utf-8'))['request_id']
    db=sqlite3.connect('file:../VoiceBench/data/voicebench.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row
    rows=db.execute('SELECT q.id request_id,q.seed,q.quality_mode,q.generation_json,p.reference_sha256,r.manifest_json,r.metrics_json FROM studio_requests q JOIN projects p ON p.id=q.project_id JOIN studio_segments s ON s.request_id=q.id JOIN runs r ON r.job_id=s.job_id WHERE q.id=?',(request,)).fetchall();db.close()
    audit=[]
    for row in rows:
        v=dict(row);m=json.loads(v.pop('manifest_json'));metrics=json.loads(v.pop('metrics_json'))
        v.update(engine=m.get('engine'),synthesis=metrics.get('synthesis'),quality=metrics.get('quality'));audit.append(v)
    original=json.loads((ROOT/'voice-settings-audit.json').read_text('utf-8'))
    preferred=next(v for v in original if v['request_id']==168)
    for v in audit:
        assert v['seed']==preferred['seed'] and v['reference_sha256']==preferred['reference_sha256']
        assert v['engine']==preferred['engine'] and v['generation_json']==preferred['generation_json']
    assert len(audit)==1,'A retry or alternate synthesis requires separate tonal review'
    _atomic_json(final/'effective-voice-audit.json',{'matches_preferred_configuration':True,'single_actual_synthesis':True,'runs':audit,'auditory_naturalness_reviewed':False})
    print(json.dumps({'code':code,'passed':report['passed'],'issues':report['issues'],'audio':report['audio_timing_audit']['passed'],'metrics':report['metrics'],'same_voice_configuration':True},ensure_ascii=False),flush=True)

if __name__=='__main__':main()

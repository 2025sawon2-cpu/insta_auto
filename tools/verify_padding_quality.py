"""Run the production final-video reviewer on read-only cloned task state."""
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hotpost.config import load_settings
from hotpost.daily_quality import DailyQualityMixin
from improve_padding_quality import OUT,OLD,read,save


class Reviewer(DailyQualityMixin):
    def __init__(self):self.settings=load_settings()
    def folder(self,task_id):
        folder=OUT/'qa/production-review';folder.mkdir(parents=True,exist_ok=True);return folder


if __name__=='__main__':
    state=read(OUT/'original-state.json')
    parent=next(e for e in state['edits'] if Path(e['plan_path']).resolve()==(OLD/'timeline.json').resolve())
    for label,folder in [('old',OLD),('improved',OUT/'improved-video')]:
        clone=copy.deepcopy(state);edit=copy.deepcopy(parent);edit.update(id='padding-'+label,
            plan_path=str(folder/'timeline.json'),preview_path=str(folder/'preview.mp4'),
            portable_draft_path=str(folder/'capcut'/('Studio-'+folder.name)))
        if label=='old':edit['portable_draft_path']=parent['portable_draft_path']
        edit.pop('export_path',None);edit.pop('parent_id',None)
        clone['edits']=[edit];clone['edit_id']=edit['id'];clone['daily_quality']['reviews']=[]
        clone['daily_quality']['feedback']=[]
        result=Reviewer()._quality_review(clone,dict(id='qa-'+label,payload=dict(edit_id=edit['id'])))
        save(OUT/'qa'/f'production-{label}.json',result)
        print(label,'passed',result['passed'],'issues',result['issues'],flush=True)

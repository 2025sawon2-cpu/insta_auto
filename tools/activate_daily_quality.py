"""Enable the authorized next-day daily quality routine, preserving settings."""
import json,shutil,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json

def main():
    path=Path('config.json');root=Path('data/daily-quality-activation-20261011');root.mkdir(exist_ok=True)
    backup=root/'config-before.json'
    if not backup.exists():shutil.copy2(path,backup)
    data=json.loads(path.read_text('utf-8'))
    data.update(studio_auto_top_enabled=True,studio_auto_start_date_kst='2026-10-12',
        studio_daily_quality_enabled=True,studio_daily_quality_max_repairs=3)
    _atomic_json(path,data);settings=load_settings()
    flags={k:getattr(settings,k) for k in ('studio_auto_top_enabled','studio_auto_start_date_kst',
        'studio_daily_quality_enabled','studio_daily_quality_max_repairs','photo_production_enabled')}
    assert flags['studio_auto_top_enabled'] and flags['studio_daily_quality_enabled']
    assert flags['studio_auto_start_date_kst']=='2026-10-12' and not flags['photo_production_enabled']
    _atomic_json(root/'activation.json',{'checked_at':time.time(),'flags':flags,'backup':str(backup),
        'existing_task_states_not_resumed':True,'schedule':'2026-10-12 07:00 Asia/Seoul'})
    print(json.dumps(flags,ensure_ascii=False))
if __name__=='__main__':main()

"""Run only the three videos explicitly requested on 2026-10-10."""
import json
import os
import threading
import time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_store import StudioStore

CODES = ('DeRIBMYzn0x', 'DeRFXHpEwck', 'DeJ7hD6zsnR')
OWNER = 'selected-three-20261010'


class SelectedStore(StudioStore):
    task_ids = ()

    def claim(self, lane=None, **kwargs):
        for task_id in self.task_ids:
            job = super().claim(lane, task_id=task_id)
            if job:
                return job
        return None


class ReviewStudio(Studio):
    def _register(self, state, job):
        edit = next(e for e in state['edits'] if e['id'] == job['payload']['edit_id'])
        portable = Path(edit.get('portable_draft_path') or '__missing__')
        if not (portable / 'draft_content.json').is_file():
            raise RuntimeError('편집 가능한 프로젝트 파일이 없습니다.')
        return {'registration_deferred': True,
                'registration_note': '품질 검토용 MP4 · 편집 프로젝트 보존 · CapCut 자동 실행 없음'}


def main():
    settings = load_settings()
    bins = list(Path(os.environ.get('LOCALAPPDATA', '')).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    if bins:
        os.environ['PATH'] = str(bins[0]) + os.pathsep + os.environ['PATH']
    studio = ReviewStudio(settings, workers=False)
    lease = (studio.store.root / 'worker.lock').open('a+b')
    import msvcrt
    lease.seek(0)
    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    studio._lease = lease
    studio.store = SelectedStore(studio.store.root)
    tasks = [studio.create(code, automation={
        'protocol': 2, 'active': True, 'paused_by_user': False,
        'selection_mode': 'user_batch', 'finish_selected_batch': True,
        'priority': 100, 'selected_at': time.time(), 'owner': OWNER,
    }) for code in CODES]
    studio.store.task_ids = tuple(t['id'] for t in tasks)
    receipt = settings.data_dir / (OWNER + '.json')
    threads = [threading.Thread(target=studio._worker, args=(lane,), daemon=True,
                                name=OWNER + '-' + lane)
               for lane in ('media', 'scripts', 'sources')]
    for thread in threads:
        thread.start()
    try:
        while not studio.stop.is_set():
            states = [studio.store.get(task_id) for task_id in studio.store.task_ids]
            snapshot = {'owner': OWNER, 'codes': CODES, 'updated': time.time(),
                        'pid': os.getpid(), 'tasks': [{k: s.get(k) for k in
                        ('id','shortcode','status','message','error','source_goal','edit_id')}
                        for s in states]}
            temp = receipt.with_suffix('.tmp')
            temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(receipt)
            print(json.dumps(snapshot['tasks'], ensure_ascii=False), flush=True)
            if all(s['status'] == 'completed' for s in states):
                studio.stop.set()
                break
            if (settings.data_dir / (OWNER + '-stop')).is_file():
                studio.stop.set()
                break
            studio.stop.wait(15)
    finally:
        studio.stop.set()
        for thread in threads:
            thread.join(timeout=30)
        lease.close()


if __name__ == '__main__':
    main()

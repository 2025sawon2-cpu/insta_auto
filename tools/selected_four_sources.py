"""Run the requested batch with fresh source code, preserving the live server."""
import json
import os
import threading
import time
from pathlib import Path

from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_store import StudioStore

TASKS = ('work-59fb19cdc16c44cc', 'work-068226965a434ad7',
         'work-e6e9f219d29e4cf2', 'work-2edceeb819694427')
OWNER = 'selected-four-20261009'


class BatchStore(StudioStore):
    def reserve(self, db, job_id, *, initial=False):
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row['status'] != 'queued':
            return
        cp = json.loads(row['checkpoint'])
        if cp.get('batch_reservation') != OWNER:
            # Initial photo jobs were explicitly deferred by the preparation
            # helper to avoid an older worker that cannot read photo posts.
            old = cp.get('not_before', 0)
            if initial and row['task_id'] in TASKS[2:] and old > time.time()+3600:
                old = 0
            cp.update(batch_reservation=OWNER, batch_original_not_before=old)
        cp['not_before'] = time.time()+3600
        db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(cp), job_id))

    def enqueue(self, db, task_id, kind, payload, key):
        job_id = super().enqueue(db, task_id, kind, payload, key)
        if task_id in TASKS and kind in {'collect_sources', 'refresh_sources'}:
            self.reserve(db, job_id)
        return job_id

    def claim(self, lane=None, **kwargs):
        with self.connect() as db:
            busy = db.execute("SELECT 1 FROM jobs WHERE status='running' AND kind IN ('collect_sources','refresh_sources') LIMIT 1").fetchone()
        if busy:
            return None
        for task_id in TASKS:
            job = super().claim(lane, task_id=task_id, reservation=OWNER)
            if job:
                return job
        return None

    def defer(self, job, message, seconds, **kwargs):
        if job['checkpoint'].get('batch_reservation') == OWNER:
            job['checkpoint']['batch_original_not_before'] = time.time()+seconds
        super().defer(job,message,seconds,**kwargs)
        with self.transaction() as db:
            self.reserve(db,job['id'])


def maintain(studio):
    while not studio.stop.is_set():
        if all(studio.store.get(t)['status']=='completed' for t in TASKS):
            print('All four completed; releasing background queue.',flush=True)
            studio.stop.set(); return
        if (studio.store.root/'selected-four-stop').is_file():
            studio.stop.set(); return
        with studio.store.transaction() as db:
            for row in db.execute("SELECT id,task_id,checkpoint FROM jobs WHERE status='queued'").fetchall():
                if row['task_id'] in TASKS:
                    if db.execute('SELECT kind FROM jobs WHERE id=?', (row['id'],)).fetchone()[0] in {'collect_sources','refresh_sources'}:
                        studio.store.reserve(db, row['id'], initial=True)
                    continue
                cp = json.loads(row['checkpoint'])
                cp.setdefault('batch_deferred', {'owner': OWNER, 'not_before': cp.get('not_before', 0)})
                cp['not_before'] = time.time()+120
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(cp),row['id']))
        studio.stop.wait(15)


def restore(studio):
    with studio.store.transaction() as db:
        for row in db.execute('SELECT state FROM tasks').fetchall():
            state = json.loads(row[0])
            hold = state.get('batch_deferred_automation')
            if hold and hold['owner'] == OWNER:
                state['automation']['active'] = hold['active']
                state.pop('batch_deferred_automation')
                studio.store.save(db, state)
        for row in db.execute('SELECT id,checkpoint FROM jobs').fetchall():
            cp = json.loads(row['checkpoint'])
            held = cp.get('batch_deferred')
            if held and held['owner'] == OWNER:
                cp['not_before'] = held['not_before']; cp.pop('batch_deferred')
            if cp.get('batch_reservation') == OWNER:
                cp['not_before'] = cp.pop('batch_original_not_before', 0)
                cp.pop('batch_reservation')
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(cp),row['id']))


def main():
    settings = load_settings()
    os.environ['PATH'] = os.environ['PATH'] + os.pathsep + os.environ.get('LOCALAPPDATA','')+'/Microsoft/WinGet/Links'
    ffmpeg = list(Path(os.environ.get('LOCALAPPDATA','')) .glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    if ffmpeg: os.environ['PATH'] = str(ffmpeg[0])+os.pathsep+os.environ['PATH']
    studio = Studio(settings, workers=False)
    lease = (studio.store.root/'selected-four.lock').open('a+b')
    import msvcrt
    lease.seek(0); msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    studio.store = BatchStore(studio.store.root)
    with studio.store.transaction() as db:
        for row in db.execute('SELECT state FROM tasks').fetchall():
            state = json.loads(row[0])
            if state['id'] in TASKS:
                if state['status'] != 'completed':
                    studio.release_source_hold(state)
                    state['automation'].update(active=True,finish_selected_batch=True,priority=100)
                    studio.store.save(db,state)
            elif state.get('automation',{}).get('active'):
                state.setdefault('batch_deferred_automation', {'owner': OWNER, 'active': True})
                state['automation']['active'] = False
                studio.store.save(db,state)
    maintainer = threading.Thread(target=maintain,args=(studio,),daemon=True)
    maintainer.start()
    try:
        print('Requested four reserved; current source job is allowed to finish.',flush=True)
        studio._worker('sources')
    finally:
        studio.stop.set();maintainer.join(timeout=20);restore(studio);lease.close()


if __name__ == '__main__':
    main()

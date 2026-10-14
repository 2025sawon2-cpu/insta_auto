"""Durable shared capacity gate; content repair counters are independent."""
import random
import math
from contextlib import contextmanager
import sqlite3
import time
import uuid
from pathlib import Path


class ModelServiceUnavailable(RuntimeError):
    def __init__(self, message='모델 처리 용량 부족', retry_at=None, attempted=True):
        super().__init__(message)
        self.retry_at = retry_at or time.time() + 60
        self.attempted = attempted


class ModelResponseInvalid(ValueError):
    pass


@contextmanager
def database(directory):
    root = Path(directory).resolve()
    # Every writing call is below the shared data/writing directory.
    while root.name != 'writing' and root.parent != root:
        root = root.parent
    if root.name != 'writing':
        root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'model-service.sqlite3', timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS capacity(id INTEGER PRIMARY KEY, failures INTEGER, retry_at REAL, probe_until REAL)')
    db.execute('INSERT OR IGNORE INTO capacity(id,failures,retry_at,probe_until) VALUES(1,0,0,0)')
    columns={r[1] for r in db.execute('PRAGMA table_info(capacity)')}
    if 'generation' not in columns:db.execute('ALTER TABLE capacity ADD COLUMN generation INTEGER DEFAULT 0')
    if 'probe_owner' not in columns:db.execute("ALTER TABLE capacity ADD COLUMN probe_owner TEXT DEFAULT ''")
    db.execute('CREATE TABLE IF NOT EXISTS calls(token TEXT PRIMARY KEY, directory TEXT, generation INTEGER, probe INTEGER, created REAL)')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def before_call(directory, *, ticket=False):
    with database(directory) as db:
        db.execute('BEGIN IMMEDIATE')
        failures, retry_at, probe_until, generation = db.execute('SELECT failures,retry_at,probe_until,generation FROM capacity WHERE id=1').fetchone()
        now = time.time()
        if now < max(retry_at, probe_until):
            raise ModelServiceUnavailable('모델 처리 용량 부족 · 공통 복구 대기', max(retry_at, probe_until), False)
        token=uuid.uuid4().hex
        if failures:
            # One recovery probe; lease expiration only recovers a dead owner.
            db.execute('UPDATE capacity SET probe_until=?,probe_owner=? WHERE id=1', (now + 1200,token))
        db.execute('INSERT INTO calls VALUES(?,?,?,?,?)',(token,str(Path(directory).resolve()),generation,bool(failures),now))
        permit={'token':token,'generation':generation,'probe':bool(failures)}
        return permit if ticket else bool(failures)


def _permit(db,directory,permit):
    if permit is not None:return permit
    row=db.execute('SELECT token,generation,probe FROM calls WHERE directory=? ORDER BY rowid DESC LIMIT 1',
                   (str(Path(directory).resolve()),)).fetchone()
    return {'token':row[0],'generation':row[1],'probe':bool(row[2])} if row else {}


def keep_probe(directory,permit=None):
    """Renew ownership of a live probe; this is not content progress or a time budget."""
    with database(directory) as db:
        permit=_permit(db,directory,permit)
        db.execute('UPDATE capacity SET probe_until=? WHERE id=1 AND failures>0 AND probe_owner=? AND generation=?',
                   (time.time()+1200,permit.get('token'),permit.get('generation')))


def release_probe(directory,permit):
    """A known-ended probe releases its ownership, preserving the capacity barrier."""
    with database(directory) as db:
        db.execute("UPDATE capacity SET probe_until=0,probe_owner='' WHERE id=1 AND probe_owner=? AND generation=?",
                   (permit.get('token'),permit.get('generation')))


def capacity_failure(directory, *, retry_at=None):
    with database(directory) as db:
        db.execute('BEGIN IMMEDIATE')
        failures,previous = db.execute('SELECT failures,retry_at FROM capacity WHERE id=1').fetchone()
        failures+=1
        provider=retry_at if type(retry_at) in (int,float) and math.isfinite(retry_at) and retry_at>=0 else 0
        retry_at = max(previous or 0,provider,
                      time.time() + min(600, 30 * 2 ** min(failures, 5)) * random.uniform(.8, 1.2))
        db.execute("UPDATE capacity SET failures=?,retry_at=?,probe_until=0,probe_owner='',generation=generation+1 WHERE id=1", (failures, retry_at))
    return retry_at


def response_received(directory,permit=None):
    with database(directory) as db:
        permit=_permit(db,directory,permit)
        # An older in-flight success is not the designated recovery probe.
        db.execute("UPDATE capacity SET failures=0,retry_at=0,probe_until=0,probe_owner='' WHERE id=1 AND generation=? AND probe_owner=?",
                   (permit.get('generation'),permit.get('token')))

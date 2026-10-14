"""소스·대본 작업을 하나의 SQLite 큐에서 실행한다."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import uuid
from typing import Callable

from .config import Settings
from .storage import Storage

Worker = Callable[[str, Callable[[str, int], None]], dict]


class JobQueue:
    def __init__(self, settings: Settings, *, workers=True, autostart=True):
        self.settings = settings
        self.pending: queue.Queue[str] = queue.Queue()
        self.workers: dict[str, Worker] = {}
        self.submitted: set[str] = set()
        self.lock = threading.Lock()
        self._threads = []
        self._closed = False
        self._lease = None
        if not workers:
            return  # Read/submit port; the leased consumer polls the durable queue.
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._lease = (settings.data_dir / 'legacy-queue.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            raise RuntimeError('기존 소스·전사 작업 큐가 실행 중입니다.') from exc
        if autostart:
            try:self.start_workers()
            except Exception:
                # Some workers may already have started. Drain them before
                # releasing ownership; preserve the original startup error.
                try:self.close()
                except Exception:pass
                raise

    def start_workers(self) -> None:
        """Activate only after all handlers replace temporary legacy routes."""
        with self.lock:
            if self._closed:
                raise RuntimeError('작업 큐가 종료되었습니다.')
            if not self._lease or self._threads:
                return
            store = Storage(self.settings.db_path)
            try:store.interrupt_running_jobs()
            finally:store.close()
            for _ in range(max(1, self.settings.job_concurrency)):
                thread = threading.Thread(target=self._run, daemon=True)
                thread.start()
                self._threads.append(thread)

    def close(self) -> None:
        """Keep ownership until every running worker has saved its result."""
        if self._closed:
            return
        self._closed = True
        for _ in self._threads:
            self.pending.put(None)
        for thread in self._threads:
            thread.join()
        if self._lease:
            self._lease.close()

    def register(self, kind: str, worker: Worker) -> None:
        self.workers[kind] = worker

    def resume_queued(self) -> None:
        store = Storage(self.settings.db_path)
        try:
            items = store.queued_jobs()
        finally:
            store.close()
        for item in items:
            if item['kind'] in self.workers:
                self._enqueue(item["id"])

    def _enqueue(self, job_id: str) -> None:
        with self.lock:
            if self._closed:
                raise RuntimeError('작업 큐가 종료되었습니다.')
            if not self._lease:
                return
            if job_id in self.submitted:
                return
            self.submitted.add(job_id)
        self.pending.put(job_id)

    def start(self, kind: str, shortcode: str) -> dict:
        if kind not in self.workers:
            raise ValueError("작업 종류가 등록되지 않았습니다")
        job_id = hashlib.sha1(f"{kind}-{shortcode}-{time.time_ns()}".encode()).hexdigest()[:12]
        store = Storage(self.settings.db_path)
        try:
            job, created = store.create_job(job_id, kind, shortcode)
        finally:
            store.close()
        if created:
            self._enqueue(job["id"])
        return job

    def get(self, job_id: str) -> dict | None:
        store = Storage(self.settings.db_path)
        try:
            return store.job_for(job_id)
        finally:
            store.close()

    def _run(self) -> None:
        while True:
            try:
                job_id = self.pending.get(timeout=1)
            except queue.Empty:
                if not self._closed:
                    self.resume_queued()
                continue
            if job_id is None:
                self.pending.task_done()
                return
            store = Storage(self.settings.db_path)
            try:
                token = uuid.uuid4().hex
                job = store.claim_job(job_id, token)
                if not job:
                    continue
                worker = self.workers.get(job["kind"])
                if worker is None:
                    store.update_running_job(job_id, token, status="interrupted", message="작업 실행기 없음",
                                     finished_at=int(time.time()))
                    continue
                def progress(message: str, percent: int) -> None:
                    store.update_running_job(job_id, token, message=message, progress=max(0, min(100, int(percent))))
                try:
                    result = worker(job["shortcode"], progress)
                    path = result.get("zip_path") or result.get("json_path") or ""
                    accepted = store.update_running_job(job_id, token, status="done", progress=100,
                                     message=(f"소스 영상 {result.get('downloaded', 0)}개 준비 완료"
                                              if job["kind"] == "source" else
                                              "제작실 작업 접수 완료 · 영상 제작 진행은 제작실에서 확인" if result.get('studio') else
                                              "쇼츠 두 버전 제작 완료" if job["kind"] == "production" else "대본 추출 완료"),
                                     result_json=json.dumps(result, ensure_ascii=False),
                                     result_path=path, finished_at=int(time.time()))
                    if accepted and job["kind"] == "source" and any("429" in note for note in
                                                           result.get("browser_notes", [])):
                        store.notify("source_429", f"source-429-{job_id}",
                                     f"소스 탐색 {job['shortcode']} 중 플랫폼 429 제한이 발생했습니다")
                except Exception as exc:  # 개별 실패가 큐를 중단하지 않는다.
                    accepted = store.update_running_job(job_id, token, status="error", error=str(exc)[:600],
                                     message="작업 실패", finished_at=int(time.time()))
                    if accepted and "429" in str(exc):
                        store.notify("source_429", f"source-429-{job_id}",
                                     f"소스 탐색 {job['shortcode']} 중 플랫폼 429 제한이 발생했습니다")
            finally:
                store.close()
                with self.lock:
                    self.submitted.discard(job_id)
                self.pending.task_done()

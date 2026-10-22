"""Public Studio facade: resource ownership and composition of production services.

Implementation map: docs/studio_runtime_architecture.md. Keep this import stable
for the HTTP server, workflow integrations, tests, and operator scripts.
"""
from __future__ import annotations

import os
import re
import threading

from .studio_store import StudioStore
from .studio_workflow import WorkflowMixin
from .studio_sources import SourceAcquisitionMixin
from .studio_self_shot import SelfShotMixin
from .studio_runtime.commands import CommandsMixin
from .studio_runtime.media import MediaMixin
from .studio_runtime.lifecycle import LifecycleMixin
from .studio_runtime.generation import GenerationMixin
from .studio_runtime.editing import EditingMixin
from .daily_quality import DailyQualityMixin
from .studio_runtime.common import digest, selected

__all__ = ["Studio", "digest", "selected"]


class Studio(SelfShotMixin, CommandsMixin, MediaMixin, LifecycleMixin, GenerationMixin, DailyQualityMixin,
             EditingMixin, SourceAcquisitionMixin, WorkflowMixin):
    def __init__(self, settings, *, workers=True):
        self.settings = settings
        self.store = StudioStore(settings.data_dir / "studio")
        self.stop = threading.Event()
        self.render_lock = threading.Lock()
        self._lease = None
        self._threads = []
        self._close_lock = threading.Lock()
        self.supervisor = None
        self.video_agents = None
        if workers:
            self._lease = (self.store.root / "worker.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    self._lease.seek(0)
                    msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._lease.close(); self._lease = None
            if self._lease:
                try:
                    from .studio_supervision import StudioSupervisor
                    self.supervisor = StudioSupervisor(self)
                    self.store.supervisor = self.supervisor
                    self._start_owned_thread(self.supervisor.run, (), 'studio-supervision')
                    if not self.supervisor.ready.wait(10) or not self.supervisor.healthy():
                        raise RuntimeError('제작 감시 시작 실패 · 작업을 실행하지 않습니다.')
                    from .video_agents import VideoAgentManager
                    from .video_agent_runtime import configure
                    self.video_agents=VideoAgentManager(self)
                    configure(self,self.video_agents)
                    self.store.video_agents=self.video_agents
                    self._start_owned_thread(self.video_agents.run,(), 'studio-video-agents')
                    if not self.video_agents.ready.wait(10) or not self.video_agents.healthy():
                        raise RuntimeError('영상 담당 에이전트 시작 실패 · 작업을 실행하지 않습니다.')
                    self.store.recover()
                # Codex writing uses the CLI, while local media/model work
                # remains serial. A task has at most one production job at
                # once, enforced transactionally by StudioStore.claim. Saved
                # proposals remain non-mutating and can overlap media work.
                    self._start_owned_thread(self._worker,('media',),'studio-production')
                    self._start_owned_thread(self._worker,('scripts',),'studio-scripts')
                    self._start_owned_thread(self._worker,('sources',),'studio-sources')
                    if settings.studio_auto_top_enabled:
                        self._start_owned_thread(self._watch_top,(),'studio-top-two')
                except BaseException:
                    self.close()
                    raise

    def _start_owned_thread(self, target, args, name):
        thread=threading.Thread(target=target,args=args,name=name,daemon=True)
        try:
            thread.start()
        except BaseException:
            if thread.ident is not None:
                self._threads.append(thread)
            raise
        self._threads.append(thread)

    def close(self):
        """Drain claimed work before releasing the exclusive worker lease."""
        self.stop.set()
        if self.video_agents:self.video_agents.stop.set()
        if threading.current_thread() in self._threads:
            raise RuntimeError('Studio.close는 소유 worker 밖에서 호출해야 합니다. 실행 소유권은 유지합니다.')
        with self._close_lock:
            for thread in self._threads:
                if thread.name == 'studio-supervision':
                    continue
                if thread.ident is not None:
                    thread.join()
            if self.supervisor:
                self.supervisor.stop.set()
            for thread in self._threads:
                if thread.name == 'studio-supervision' and thread.ident is not None:
                    thread.join()
            if self._lease is not None:
                self._lease.close()
                self._lease=None

    def create(self, code, automation=None, *, with_created=False, allow_photo=False):
        from .storage import Storage
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code):
            raise ValueError("올바르지 않은 게시물 ID")
        db = Storage(self.settings.db_path)
        try:
            row = db.conn.execute("SELECT * FROM posts WHERE shortcode=?", (code,)).fetchone()
            if row and row["kind"] in {"image", "carousel"} and not self.settings.photo_production_enabled:
                raise ValueError("사진·캐러셀 게시물의 영상 제작은 비활성화되어 있습니다.")
            if not row or row["kind"] not in ({"reel", "video", "image", "carousel"} if allow_photo else {"reel", "video"}):
                raise ValueError("수집된 동영상 게시물을 선택하세요.")
            from .studio_titles import caption_title
            title = caption_title(row['caption']) or code
        finally:
            db.close()
        initial = {"collected_at": row["first_seen"]}
        if self.settings.studio_daily_quality_enabled:
            from .daily_quality import POLICY
            initial['daily_quality']={'policy':POLICY,'max_repairs':max(0,self.settings.studio_daily_quality_max_repairs),
                'repair_round':0,'status':'pending','reviews':[]}
            from .quality_progress import ensure
            ensure(initial)
        if row["kind"] in {"image", "carousel"}:
            initial["creation_mode"] = "photo_post"
        state, created = self.store.create(code, title, automation, initial=initial)
        task = self.public(state)
        return (task, created) if with_created else task

    def folder(self, task_id):
        if not re.fullmatch(r"work-[a-f0-9]{16}", task_id):
            raise ValueError("올바르지 않은 제작 ID")
        path = self.store.root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

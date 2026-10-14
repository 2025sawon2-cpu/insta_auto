"""Stable adapter name for the internal Codex writer and archived script jobs."""
import json
import time
from pathlib import Path
from .writing.contract import snapshot
from .writing.jobs import Jobs


class StudioAdapter:
    def __init__(self,settings,session=None):
        self.settings=settings
        self._jobs=None

    @property
    def jobs(self):
        if self._jobs is None:self._jobs=Jobs(self.settings.data_dir/'writing')
        return self._jobs

    def writing_contract(self):return snapshot()

    def review(self,text,reference,evidence_mode='benchmark'):
        from .writing.checks import review
        return review(text,reference,evidence_mode)

    def submit(self,production_id,video,reference,payload):
        from .source_quality import sha256_file
        if not reference.strip():raise ValueError('원본 발화가 없습니다.')
        body={**payload,'reference_script':reference,'reference_video_sha256':sha256_file(Path(video)),
              'writing_contract':self.writing_contract(),'writing_provider':'codex_internal','flow':'single-draft-v1'}
        job=self.jobs.create('script',body,production_id)
        if job['state']=='failed' and (job.get('result') or {}).get('error_reason')=='model_capacity':
            from .model_service import ModelServiceUnavailable
            failure=job['result']
            if time.time()<failure.get('retry_at',0):
                raise ModelServiceUnavailable(str(job.get('error')),failure['retry_at'],False)
            self.jobs.update(job['id'],state='queued',error='',result=None)
            job=self.jobs.get(job['id'])
        self.jobs.start();return job

    def get(self,job_id, *, include_payload=True):
        if not isinstance(job_id,str) or not job_id.isalnum():raise ValueError('잘못된 대본 작업 ID')
        if not job_id.startswith('codex'):
            path=self.jobs.root/'legacy'/f'{job_id}.json'
            if not path.is_file():raise ValueError('과거 대본 기록이 내재화되지 않았습니다. 기존 결과를 확인하세요.')
            return json.loads(path.read_text('utf-8'))
        job=self.jobs.get(job_id,include_payload=include_payload)
        if job['state'] in ('queued','running'):self.jobs.start()
        return job

    def retry(self,production_id,job_id):
        old=self.get(job_id)
        if old['state'] not in ('failed','cancelled','interrupted'):raise ValueError('실패·취소·중단 작업만 재시도할 수 있습니다.')
        if self.jobs.active_children(job_id):raise ValueError('이전 Codex 실행이 아직 진행 중입니다.')
        body={**old['payload'],'writing_contract':snapshot(old['payload'].get('generation_mode')),'writing_provider':'codex_internal','flow':'single-draft-v1'}
        job=self.jobs.create('script' if old['kind']=='script' else old['kind'],body,production_id+'-retry-'+job_id)
        self.jobs.start();return job

    def editorial(self,instruction,evidence,media=None):
        payload={'instruction':instruction,'evidence':evidence,'media':media or []}
        if evidence.get('purpose') in ('script_selection','script_revision','script_review'):
            payload['writing_contract']=self.writing_contract()
        if len(payload['media'])>128 or len(json.dumps(payload).encode())>12*1024*1024:
            raise ValueError('분석 자료가 너무 큽니다.')
        job=self.jobs.create('editorial',payload)
        # A later request may retry a transient failure once; never loop or
        # replace an in-flight job. The retry identity is itself durable.
        if job['state'] in ('failed','cancelled','interrupted') and not self.jobs.active_children(job['id']):
            failure=job.get('result') or {}
            if failure.get('error_reason')=='model_capacity':
                from .model_service import ModelServiceUnavailable
                if time.time()<failure.get('retry_at',0):
                    raise ModelServiceUnavailable(str(job.get('error')),failure['retry_at'],False)
                self.jobs.update(job['id'],state='queued',error='',result=None)
                job=self.jobs.get(job['id'])
            else:
                job=self.jobs.create('editorial',payload,'retry-'+job['id'])
        self.jobs.start()
        return self._wait(job)['result']['value']

    def save_manual(self,text,reference,product,source_evidence,evidence_mode='benchmark'):
        job=self.jobs.create('manual',{'text':text,'reference_script':reference,'product':product,
            'source_evidence':source_evidence,'evidence_mode':evidence_mode,'writing_contract':self.writing_contract()})
        self.jobs.start();return self._wait(job)

    def _wait(self,job):
        from .operation_progress import ProgressWatch
        from .model_service import ModelServiceUnavailable
        watch=ProgressWatch(self.settings.studio_timeout,'집필 작업 응답')
        seen=set()
        # Existing injected/subclass readers use get(job_id). Detect supported
        # arguments before calling; exceptions inside a reader remain visible.
        import inspect
        parameters=inspect.signature(self.get).parameters
        light=('include_payload' in parameters or any(p.kind==inspect.Parameter.VAR_KEYWORD for p in parameters.values()))
        while True:
            job=self.get(job['id'],**({'include_payload':False} if light else {}))
            identity=(job['state'],job.get('progress'))
            if identity not in seen:
                seen.add(identity);watch.observe('job_states',len(seen))
            if job['state']=='queued':watch.reset()
            if job['state']=='completed':return job
            if job['state'] in ('failed','cancelled','interrupted'):
                failure=job.get('result') or {}
                if failure.get('error_reason')=='model_capacity':
                    raise ModelServiceUnavailable(str(job.get('error')),failure.get('retry_at'),failure.get('attempted',True))
                raise RuntimeError('Codex 실행 실패: '+str(job.get('error') or job.get('message'))[:500])
            if job['id'].startswith('codex'):
                self.jobs.observe_progress(job['id'],watch)
            watch.check()
            time.sleep(.5)
        raise RuntimeError('집필 대기 시간이 초과됐습니다. 재요청하면 같은 저장 작업을 확인합니다.')

"""Stage exact code repairs, run pinned tests, independently review, then apply.

The test harness restricts Python-audited filesystem/network/process operations;
it is not an OS security sandbox against hostile native extension code. Nothing
in this module restarts a service or changes production data/quality approvals.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import time
import threading
import uuid
from contextlib import contextmanager, nullcontext


class RepairRejected(ValueError):
    pass


class AppliedSourceChanged(RepairRejected):
    """Authenticated historical repair whose source has since been superseded."""


_RECORD_LOCKS={}
_RECORD_LOCKS_GUARD=threading.Lock()


_SCOPES = {'main': ('hotpost', 'tests'), 'renderer': ('auto_capcut/core', 'tests')}
_METADATA = {'pyproject.toml', 'pytest.ini', 'setup.cfg', 'requirements.txt'}
_PROTECTED = {
    'config.py', 'studio_store.py', 'studio_supervision.py', 'supervision_evidence.py',
    'video_agent_repairs.py', 'retry_policy.py', 'retry_budget.py', 'studio_pause.py',
    'source_policy.py', 'quality_progress.py', 'daily_quality.py', 'captcha_review.py',
    'search_access.py', 'source_query_identity.py', 'source_quality.py',
    'studio_masks.py', 'studio_source_diversity.py', 'studio_core_priority.py',
    'video_agents.py', 'video_agent_actions.py', 'video_agent_context.py',
    'agent_runtime_restart.py', 'runtime_restart.py', 'cli.py', 'server.py', 'studio.py',
    'video_agent_runtime.py', 'jobs.py', 'codex_writer.py',
    'video_agent_memory.py', 'video_agent_recovery.py',
    'video_agent_planning_claim.py',
    'video_agent_preparation_evidence.py',
    'video_agent_page_evidence.py',
    'video_agent_source_wait.py',
    'video_agent_payload.py',
    'source_input_observation.py',
    'source_topic_queries.py',
    'source_loader.py', '__init__.py', '__main__.py',
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _planning_child_incident(record):
    incident=record.get('incident') or {}
    job=incident.get('job') if isinstance(incident,dict) else None
    if not isinstance(job,dict) or job.get('kind')!='collect_sources':return False
    payload=job.get('payload')
    if isinstance(payload,str):
        try:payload=json.loads(payload)
        except ValueError:return False
    parent=payload.get('planning_recovery_from') if isinstance(payload,dict) else None
    return isinstance(parent,str) and bool(parent)


SOURCE_REPLACEMENT_CONTRACT='eol-equivalent-unique-v1'


def _replace_exact_source(content,old,new):
    """EOL-equivalent context is exact code; retain untouched source bytes."""
    if not isinstance(old,str) or not old or not isinstance(new,str):
        raise RepairRejected('Each replacement must match exactly once.')
    count=content.count(old)
    if count==1:return content.replace(old,new,1)
    if count>1:raise RepairRejected('Each replacement must match exactly once.')
    pattern=r'\r?\n'.join(re.escape(part) for part in old.replace('\r\n','\n').split('\n'))
    matches=list(re.finditer(pattern,content))
    if len(matches)!=1:raise RepairRejected('Each replacement must match exactly once.')
    match=matches[0]
    eol='\r\n' if '\r\n' in match.group() else '\n'
    replacement=new.replace('\r\n','\n').replace('\n',eol)
    return content[:match.start()]+replacement+content[match.end():]


def purge_bytecode(path):
    """Remove only interpreter caches belonging to this exact Python source."""
    if path.suffix == '.py':
        for optimization in ('','1','2'):
            cache=Path(importlib.util.cache_from_source(str(path),optimization=optimization))
            cache.unlink(missing_ok=True)


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _source_replace(path,data,expected):
    """Preserve the actual displaced file; never overwrite a competing save."""
    displaced=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.preserved')
    journal=displaced.with_suffix('.repair-journal.json')
    moved=False
    try:
        if expected is not None:
            _atomic(journal,_json({'target':path.name,'preserved':displaced.name,'sha256':expected}).encode('utf8'))
            os.rename(path,displaced)
            moved=True
            if _sha(displaced.read_bytes())!=expected:
                raise RepairRejected('Concurrent source edit preserved at '+str(displaced))
        elif path.exists():
            raise RepairRejected('New source appeared before replacement; preserve it.')
        if data is not None:
            temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.candidate')
            _atomic(temporary,data)
            try:
                # Atomic no-clobber installation on Windows and POSIX.
                os.link(temporary,path)
            finally:
                temporary.unlink(missing_ok=True)
    except BaseException:
        if moved:
            try:os.link(displaced,path)
            except FileExistsError:pass
        if path.exists():journal.unlink(missing_ok=True)
        raise
    # Keep displaced bytes: another editor may still hold an open file handle.
    journal.unlink(missing_ok=True)


def _safe_relative(path):
    if not isinstance(path, str) or '\\' in path or ':' in path or '\x00' in path:
        raise RepairRejected('Expected a repository-relative POSIX path.')
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or not parsed.parts or any(p in {'.', '..'} or p.startswith('.') for p in parsed.parts):
        raise RepairRejected('Path traversal or hidden paths are forbidden.')
    return parsed.as_posix()


def _guard_nodes(content):
    tree = ast.parse(content)
    nodes = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.match(
                r'(?:_*)(?:validate|verify|check|assert|approve|editing_ready|quality_gate)', node.name):
            nodes['function:' + node.name] = ast.dump(node, include_attributes=False)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and re.search(r'threshold|policy|minimum|maximum|quality_limit', target.id, re.I):
                    nodes['setting:' + target.id] = ast.dump(node, include_attributes=False)
    return nodes


_HARNESS = r'''
import os, pathlib, sys
import pytest
root = pathlib.Path(sys.argv[1]).resolve()
allowed_reads = [root, pathlib.Path(sys.prefix).resolve(), pathlib.Path(sys.base_prefix).resolve()]
def inside(path, roots):
    if isinstance(path, int): return True
    if os.fsdecode(path).lower() == os.devnull.lower(): return True
    try:
        resolved = pathlib.Path(os.fsdecode(path)).resolve()
        if resolved == pathlib.Path(os.devnull).resolve(): return True
        return any(resolved == base or resolved.is_relative_to(base) for base in roots)
    except (ValueError, TypeError): return False
def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if not inside(path, [root] if writing else allowed_reads):
            raise PermissionError('repair test file access outside isolated roots')
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'):
        if not inside(args[0], [root]): raise PermissionError('repair test write outside stage')
    elif event in ('os.rename', 'os.link', 'os.symlink'):
        if not all(inside(p, [root]) for p in args[:2]): raise PermissionError('repair test link outside stage')
    elif event in ('os.listdir', 'os.scandir'):
        if not inside(args[0] or '.', allowed_reads): raise PermissionError('repair test listing outside stage')
    elif event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'ctypes.dlopen'):
        raise PermissionError('repair tests cannot launch processes or use network/native loaders')
sys.addaudithook(audit)
sys.dont_write_bytecode = True
result = pytest.main(sys.argv[2:])
# A test/module calling sys.exit(0) or os._exit(0) must not masquerade as a
# successfully completed pytest session. Only normal pytest completion uses 73.
raise SystemExit(73 if result == 0 else int(result))
'''


def _harness(record):
    # Keep already-signed legacy harnesses byte-identical across deployments.
    if not record.get('incident_fixture'):return _HARNESS
    check = """
    evidence = root / '.repair-evidence'
    def protected(path):
        if isinstance(path, int):return False
        try:
            resolved = pathlib.Path(os.fsdecode(path)).resolve()
            return resolved == evidence or resolved.is_relative_to(evidence)
        except (ValueError, TypeError):return False
    def absolute_write(path):
        # open's audit event does not expose dir_fd. Relative mutations must
        # therefore be rejected instead of incorrectly resolving against cwd.
        if isinstance(path,int):return
        if os.fsdecode(path).lower()==os.devnull.lower():return
        if pathlib.Path(os.fsdecode(path)).resolve()==pathlib.Path(os.devnull).resolve():return
        if not pathlib.Path(os.fsdecode(path)).is_absolute():
            raise PermissionError('isolated fixture tests require absolute mutation paths')
    if event == 'open':
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            absolute_write(path)
            if protected(path):raise PermissionError('captured incident fixture is read-only')
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'):
        absolute_write(args[0])
        if protected(args[0]):raise PermissionError('captured incident fixture is read-only')
    elif event in ('os.rename', 'os.link', 'os.symlink'):
        for path in args[:2]:absolute_write(path)
        if any(protected(path) for path in args[:2]):raise PermissionError('captured incident fixture is read-only')
"""
    harness=_HARNESS.replace('def audit(event, args):\n', 'def audit(event, args):\n'+check, 1)
    if record['incident_fixture'].get('sandbox_version',1)>=2:
        # Compare extended-length and ordinary paths in one canonical namespace;
        # actual I/O retains the extended path supplied by pytest's basetemp.
        canonical="""
def canonical(path):
    value = str(pathlib.Path(path).resolve())
    if os.name == 'nt' and value.startswith(chr(92)*2 + '?' + chr(92)):
        value = (chr(92)*2 + value[8:]) if value[4:8].upper() == 'UNC'+chr(92) else value[4:]
    return pathlib.Path(value)
"""
        harness=harness.replace('def inside(path, roots):',canonical+'\ndef inside(path, roots):',1)
        harness=harness.replace('resolved = pathlib.Path(os.fsdecode(path)).resolve()', 'resolved = canonical(os.fsdecode(path))')
        harness=harness.replace("evidence = root / '.repair-evidence'", "evidence = canonical(root / '.repair-evidence')")
        harness=harness.replace('resolved == base or resolved.is_relative_to(base)', 'resolved == canonical(base) or resolved.is_relative_to(canonical(base))')
    if record['incident_fixture'].get('sandbox_version',1)>=3:
        # deepcopy emits builtins.id for every value. Unrelated audit events
        # must not resolve filesystem paths; keep all guarded event branches.
        fast_path="""    if not (event in ('open', 'os.remove', 'os.rmdir', 'os.mkdir',
            'os.chmod', 'os.utime', 'os.rename', 'os.link', 'os.symlink',
            'os.listdir', 'os.scandir', 'subprocess.Popen', 'os.system',
            'os.posix_spawn', 'ctypes.dlopen') or event.startswith('socket.')):
        return
"""
        harness=harness.replace('def audit(event, args):\n','def audit(event, args):\n'+fast_path,1)
    return harness


def _test_temp_path(path):
    path=str(Path(path).resolve())
    if os.name=='nt' and not path.startswith('\\\\?\\'):
        return '\\\\?\\UNC\\'+path[2:] if path.startswith('\\\\') else '\\\\?\\'+path
    return path


class VideoRepairPipeline:
    def __init__(self, main_root, renderer_root, receipt_root, *, interpreters,
                 regression_tests, independent_reviewer=None, require_incident=False):
        self.roots = {'main': Path(main_root).resolve(), 'renderer': Path(renderer_root).resolve()}
        self.receipts = Path(receipt_root).resolve()
        with _RECORD_LOCKS_GUARD:
            self._record_lock=_RECORD_LOCKS.setdefault(os.path.normcase(str(self.receipts)),threading.RLock())
        self.interpreters = {k: Path(v).resolve() for k, v in interpreters.items()}
        self.regressions = regression_tests
        self.reviewer = independent_reviewer
        self.require_incident = require_incident
        self.receipts.mkdir(parents=True, exist_ok=True)
        key = self.receipts / '.review-signing-key'
        try:
            with key.open('xb') as stream:
                stream.write(secrets.token_bytes(32))
        except FileExistsError:
            pass
        self._key = key.read_bytes()
        if len(self._key) != 32:
            raise RepairRejected('Review signing key is invalid.')

    def _path(self, repo, path, *, edit=False):
        if repo not in self.roots:
            raise RepairRejected('Unknown repository.')
        path = _safe_relative(path)
        allowed = any(path.startswith(scope + '/') for scope in _SCOPES[repo])
        if (not allowed or not path.endswith('.py')
                or re.search(r'credential|secret|cookie|password', PurePosixPath(path).name, re.I)):
            raise RepairRejected('Only allowlisted Python source and tests are accessible.')
        target = self.roots[repo] / path
        if not target.resolve().is_relative_to(self.roots[repo]):
            raise RepairRejected('Symlink leaves repository.')
        if any(part.is_symlink() for part in [target, *target.parents] if part != self.roots[repo].parent):
            raise RepairRejected('Symlinked source is not repairable.')
        if edit and not path.startswith('tests/') and (target.name in _PROTECTED or 'policy' in target.stem or 'guard' in target.stem):
            raise RepairRejected(f'{repo}/{path}: policy, ownership and quality guards require a separate reviewed change.')
        return target, path

    def inspect_code(self, repo, path):
        target, path = self._path(repo, path)
        data = target.read_bytes()
        if len(data) > 512 * 1024:
            raise RepairRejected('Source is too large for a bounded repair.')
        return {'repo': repo, 'path': path, 'base_sha256': _sha(data), 'content': data.decode('utf-8')}

    def inspect_staged_file(self,repair_id,task_id,repo,path,*,offset=0,limit=24000):
        record=self._read(repair_id)
        if record['binding']['task_id']!=task_id:raise RepairRejected('Repair belongs to another video.')
        row=next((r for r in record['files'] if r['repo']==repo and r['path']==path),None)
        if row is None:raise RepairRejected('Choose a file listed in this exact repair diagnostics.')
        self._assert_stage(record)
        if type(offset) is not int or offset<0 or type(limit) is not int or limit<1:
            raise RepairRejected('Staged file offsets and limits must be nonnegative/positive integers.')
        content=row['content'];limit=min(48000,limit)
        return {'status':'completed','repair_id':repair_id,'repo':repo,'path':path,'source':'staged_repair',
            'base_sha256':row['base_sha256'],'sha256':row['sha256'],'content':content[offset:offset+limit],
            'offset':offset,'total_characters':len(content),'next_offset':offset+limit if len(content)>offset+limit else None}

    def inspect_incident(self,repair_id,task_id,path,*,offset=0,limit=24000):
        """Read a bounded JSON subtree from this owner's immutable incident."""
        record=self._read(repair_id)
        if record['binding']['task_id']!=task_id:raise RepairRejected('Repair belongs to another video.')
        fixture=record.get('incident_fixture')
        if not fixture:raise RepairRejected('This legacy repair has no full incident fixture; restage current inputs.')
        if not isinstance(path,list) or len(path)>16 or any(type(k) not in (str,int) for k in path):
            raise RepairRejected('incident_path must be a JSON key/index list, e.g. ["task","sources",0].')
        if type(offset) is not int or offset<0 or type(limit) is not int or limit<1:
            raise RepairRejected('Incident offsets and limits must be nonnegative/positive integers.')
        self._assert_stage(record)
        target=self._folder(repair_id)/'stage'/fixture['relative_path']
        raw=target.read_bytes()
        if _sha(raw)!=fixture['sha256']:raise RepairRejected('Captured incident fixture changed after staging.')
        value=json.loads(raw)
        if 'preparation_frame_evidence' in value:
            from .video_agent_preparation_evidence import frame_summary
            value['preparation_frame_evidence']=frame_summary(value['preparation_frame_evidence'])
        try:
            for key in path:
                if isinstance(value,dict) and type(key) is str:value=value[key]
                elif isinstance(value,list) and type(key) is int and key>=0:value=value[key]
                else:raise KeyError(key)
        except (KeyError,IndexError) as exc:raise RepairRejected('Incident key/index does not exist; inspect its parent subtree.') from exc
        text=json.dumps(value,ensure_ascii=False,indent=2);limit=min(24000,limit)
        return {'status':'completed','repair_id':repair_id,'incident_path':path,'historical_evidence':True,
            'binding':dict(record['binding']),'sha256':fixture['sha256'],'content':text[offset:offset+limit],
            'fixture_media_bytes_omitted':True,
            'offset':offset,'total_characters':len(text),'next_offset':offset+limit if len(text)>offset+limit else None}

    def repair_material(self,repair_id,task_id):
        """Read-only identity of staged contents, independent of restaging IDs."""
        record=self._read(repair_id)
        if record['binding']['task_id']!=task_id:raise RepairRejected('Repair belongs to another video.')
        files=[]
        for row in record['files']:
            file={k:row[k] for k in ('repo','path','base_sha256','sha256')}
            # This is a context hint, never authority to apply a draft. The
            # eventual read still verifies the staged content and its hash.
            hunk=re.search(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@',row.get('diff',''),re.M)
            if hunk:
                line=max(0,int(hunk.group(1))-1)
                file['change_offset']=sum(len(part) for part in row['content'].splitlines(keepends=True)[:line])
            files.append(file)
        material=sorted((r['repo'],r['path'],r['sha256']) for r in files)
        return {'repair_id':repair_id,'status':record['status'],'binding':dict(record['binding']),'files':files,
                'content_fingerprint':_sha(_json(material).encode('utf8'))}

    def diagnostics(self,repair_id,task_id):
        from .video_agent_context import compact_incident
        record=self._read(repair_id)
        if record['binding']['task_id']!=task_id:raise RepairRejected('Repair belongs to another video.')
        tests=[]
        for test in record.get('tests',[]):
            path=Path(test['log_path']).resolve()
            if path.parent!=self._folder(repair_id).resolve():raise RepairRejected('Test log outside exact repair folder.')
            raw=path.read_bytes()
            if _sha(raw)!=test['log_sha256']:raise RepairRejected('Test log changed after verification.')
            tests.append({**test,'log_excerpt':raw.decode('utf8',errors='replace')[-12000:]})
        changes=[]
        for name,expected in record.get('snapshot_hashes',{}).items():
            repo,relative=name.split('/',1)
            if repo not in self.roots:raise RepairRejected('Unknown dependency repository.')
            live=(self.roots[repo]/relative).resolve()
            if not live.is_relative_to(self.roots[repo]):raise RepairRejected('Dependency path leaves repository.')
            actual=_sha(live.read_bytes()) if live.is_file() else None
            if actual!=expected:changes.append({'path':name,'tested_sha256':expected,'current_sha256':actual})
        return {'repair_id':repair_id,'status':record['status'],'binding':record['binding'],
            'incident':compact_incident(record.get('incident'),evidence_excerpt=True),
            'incident_fixture':record.get('incident_fixture'),
            'test_environment_recovery':('Restage with prior_repair_id to retain exact files with the current isolated harness: extended Windows paths and no filesystem resolution for memory-only audit events. Then test and independently review again.'
                if record.get('incident_fixture') and record['incident_fixture'].get('sandbox_version',1)<3 else None),
            'review_rejection':record.get('review_rejection'),'tests':tests,
            'dependency_changes':{'count':len(changes),'files':changes[:40]},
            'dependency_recovery':('propose_patch with prior_repair_id='+repair_id+' and a reason; test and independently review the new snapshot' if changes else None),
            'test_success_exit_code':73,'files':[{'repo':r['repo'],'path':r['path']} for r in record['files']]}

    @contextmanager
    def authorized(self,repair_id,task_id,epoch,store):
        binding=self._read(repair_id)['binding']
        if binding.get('task_id')!=task_id or binding.get('agent_epoch')!=epoch:
            raise RepairRejected('Repair task or owner epoch differs from the caller.')
        with store.transaction() as db:
            owner=db.execute('SELECT epoch FROM video_agents WHERE task_id=?',(task_id,)).fetchone()
            state=store.get(task_id,db);auto=state.get('automation') or {}
            if not owner or owner['epoch']!=epoch or not auto.get('active') or auto.get('paused_by_user'):
                raise RepairRejected('Current repair owner changed or paused.')
            from .video_agent_context import semantic_fingerprint, job_method_fingerprint
            job=db.execute('SELECT kind,payload,checkpoint FROM jobs WHERE id=? AND task_id=?',(binding.get('job_id'),task_id)).fetchone()
            if (not job or not binding.get('job_fingerprint')
                    or semantic_fingerprint(state)!=binding.get('input_fingerprint')
                    or job_method_fingerprint(job)!=binding['job_fingerprint']):
                raise RepairRejected('Historical repair is not bound to current task/job inputs. Bound job='+str(binding.get('job_id'))+
                    '. Inspect current recovery job and propose its repair; prior_repair_id may restage only the same job and owner. Do not review an old successful test as the current incident.')
            yield

    def authorize(self,repair_id,task_id,epoch,store):
        with self.authorized(repair_id,task_id,epoch,store):pass

    def _require_incident(self,record):
        if self.require_incident and record.get('status')!='applied' and ('incident' not in record or record.get('incident_evidence_version',0)<2):
            raise RepairRejected('Current persisted failure must be reviewed. Restage with prior_repair_id='+record['repair_id']+', then test and independently review the existing incident.')

    def _folder(self, repair_id):
        if not isinstance(repair_id, str) or not re.fullmatch(r'repair-[a-f0-9]{32}', repair_id):
            raise RepairRejected('Invalid repair ID.')
        return self.receipts / repair_id

    def _read(self, repair_id):
        return json.loads((self._folder(repair_id) / 'repair.json').read_text('utf-8'))

    def _save(self, record):
        _atomic(self._folder(record['repair_id'])/'repair.json', _json(record).encode('utf-8'))

    def _review_context(self,record,requested):
        """Read-only staged dependencies needed to assess the actual failure."""
        candidates=[];incident=record.get('incident') or {}
        trace=((incident.get('job') or {}).get('checkpoint') or {}).get('failure_trace') or {}
        for frame in trace.get('frames') or []:
            if not isinstance(frame,dict):continue
            for repo,root in self.roots.items():
                try:relative=Path(frame['path']).resolve().relative_to(root).as_posix()
                except (KeyError,TypeError,ValueError,OSError):continue
                candidates.append((repo,relative))
        for item in (requested if isinstance(requested,list) else [])[:6]:
            if isinstance(item,dict):candidates.append((item.get('repo'),item.get('path')))
        for row in record['files']:
            if row['path'].startswith('tests/'):continue
            for node in ast.walk(ast.parse(row['content'])):
                if not isinstance(node,ast.ImportFrom) or not node.level or not node.module:continue
                if not any(re.search('validate|verify|binding',a.name) for a in node.names):continue
                parts=PurePosixPath(row['path']).parent.parts
                if node.level>len(parts):continue
                parent=parts[:len(parts)-node.level+1]
                candidates.append((row['repo'],'/'.join((*parent,*node.module.split('.')))+'.py'))
        stage=self._folder(record['repair_id'])/'stage';result=[];seen=set();budget=120000
        changed={(r['repo'],r['path']) for r in record['files']}
        for repo,path in candidates:
            if not isinstance(repo,str) or not isinstance(path,str) or (repo,path) in seen|changed:continue
            seen.add((repo,path))
            try:_,relative=self._path(repo,path)
            except (ValueError,OSError):continue
            expected=record['snapshot_hashes'].get(repo+'/'+relative)
            if not expected:continue
            raw=(stage/repo/relative).read_bytes()
            if _sha(raw)!=expected:raise RepairRejected('Review dependency differs from tested staged source.')
            content=raw.decode('utf8');limit=min(48000,budget)
            if limit<=0 or len(result)>=6:break
            result.append({'repo':repo,'path':relative,'sha256':expected,'content':content[:limit],'truncated':len(content)>limit})
            budget-=min(len(content),limit)
        return result

    @staticmethod
    def _copyable(path):
        return (path.suffix in {'.py', '.md', '.txt', '.json', '.toml', '.ini', '.cfg'}
                and not any(p.startswith('.') or p in {'__pycache__', 'data', 'works', 'sessions'} for p in path.parts)
                and path.name not in {'config.json', 'credentials.json', 'cookies.json'}
                and not re.search(r'credential|secret|cookie|token|password', path.name, re.I))

    def _recovery_context(self,record):
        """Bind unchanged host retry code and actually pinned tests to review."""
        paths=['hotpost/video_agent_actions.py','hotpost/video_agent_runtime.py','hotpost/video_agent_repairs.py']
        planning=_planning_child_incident(record)
        if planning:paths.insert(0,'hotpost/video_agent_planning_claim.py')
        paths.extend(row['path'] for row in record['pinned_tests'] if row['repo']=='main')
        stage=self._folder(record['repair_id'])/'stage/main';result=[];seen=set();budget=200000 if planning else 160000
        for relative in paths:
            if relative in seen:continue
            seen.add(relative)
            expected=record['snapshot_hashes'].get('main/'+relative)
            if not expected:
                result.append({'repo':'main','path':relative,'omitted_reason':'Not in this staged snapshot; no contract evidence supplied.'})
                continue
            raw=(stage/relative).read_bytes()
            if _sha(raw)!=expected:raise RepairRejected('Recovery context differs from staged source.')
            content=raw.decode('utf8')
            if len(content)>budget:
                result.append({'repo':'main','path':relative,'sha256':expected,
                    'omitted_reason':'Review context budget; do not infer this contract was supplied.'})
                continue
            result.append({'repo':'main','path':relative,'sha256':expected,'content':content,
                'pinned_test':any(r['repo']=='main' and r['path']==relative for r in record['pinned_tests'])})
            budget-=len(content)
        return result

    def propose_patch(self, proposal):
        if (not all(isinstance(proposal.get(k), str) and proposal[k] for k in
                    ('task_id', 'job_id', 'input_fingerprint', 'planner_call_id'))
                or type(proposal.get('agent_epoch')) is not int):
            raise RepairRejected('Trusted task, job, input, planner and agent epoch bindings are required.')
        retained={}
        if proposal.get('prior_repair_id'):
            prior=self._read(proposal['prior_repair_id'])
            if any(prior['binding'].get(k)!=proposal[k] for k in ('task_id','job_id','agent_epoch')):
                raise RepairRejected('Restaging requires the same current task, job and owner.')
            # A fresh proposal binds the host-observed current input. It never
            # inherits old test/review approvals, even when reusing exact code.
            self._assert_stage(prior)
            retained={(row['repo'],row['path']):row for row in prior['files']}
            merged={key:{k:row[k] for k in ('repo','path','base_sha256','content')} for key,row in retained.items()}
            supplied=set()
            for row in proposal.get('files') or []:
                _,relative=self._path(row['repo'],row['path'],edit=True)
                key=(row['repo'],relative)
                if key in supplied:raise RepairRejected('Duplicate patch file.')
                supplied.add(key)
                if key in retained and row.get('base_sha256')!=retained[key]['base_sha256']:
                    raise RepairRejected('Revision must retain the original live base SHA.')
                merged[key]={**row,'path':relative}
            proposal={**proposal,'files':list(merged.values())}
        rows = proposal.get('files') or []
        # Exact replacements avoid regenerating large files and preserve unrelated code.
        rows = [dict(row) for row in rows]
        for row in rows:
            replacements=row.pop('replacements',None)
            if replacements is None:continue
            if 'content' in row or not isinstance(replacements,list) or not 1<=len(replacements)<=20:
                raise RepairRejected('Use content OR a bounded list of exact replacements.')
            target,_=self._path(row['repo'],row['path'],edit=True)
            original=target.read_bytes() if target.is_file() else None
            if (_sha(original) if original is not None else None)!=row.get('base_sha256'):raise RepairRejected('Replacement base SHA changed.')
            prior_row=retained.get((row['repo'],row['path']))
            if prior_row is None and original is None:raise RepairRejected('Replacement requires an existing live or retained staged file.')
            content=prior_row['content'] if prior_row else original.decode('utf8')
            for edit in replacements:
                old,new=edit.get('old'),edit.get('new')
                content=_replace_exact_source(content,old,new)
            row['content']=content
        if not 1 <= len(rows) <= 8 or not proposal.get('reason'):
            raise RepairRejected('A bounded repair needs a reason and one to eight exact files.')
        files, identities, new_tests, source_repos = [], set(), [], set()
        for row in rows:
            target, relative = self._path(row['repo'], row['path'], edit=True)
            identity = (row['repo'], relative)
            if identity in identities:
                raise RepairRejected('Duplicate patch file.')
            identities.add(identity)
            content = row.get('content')
            if not isinstance(content, str) or len(content.encode('utf-8')) > 512 * 1024:
                raise RepairRejected('Full UTF-8 replacement content is required.')
            old = target.read_bytes() if target.is_file() else None
            base = _sha(old) if old is not None else None
            if row.get('base_sha256') != base:
                raise RepairRejected('The inspected source changed before staging.')
            try:tree=ast.parse(content,filename=relative)
            except SyntaxError as exc:
                raise RepairRejected(f'{row["repo"]}/{relative}:{exc.lineno}: {exc.msg}; source={str(exc.text or "").strip()[:300]}') from exc
            if relative.startswith('tests/'):
                if old is not None or not re.fullmatch(r'tests/(?:[\w-]+/)*test_[\w]+\.py', relative):
                    raise RepairRejected('Existing regressions cannot be weakened; add a new test file.')
                if not any(isinstance(n, ast.Assert) for n in ast.walk(tree)):
                    raise RepairRejected('New regression must contain an assertion.')
                new_tests.append({'repo': row['repo'], 'path': relative})
            else:
                source_repos.add(row['repo'])
            if old is not None and _guard_nodes(old.decode('utf-8')) != _guard_nodes(content):
                raise RepairRejected('Existing validation functions or quality settings cannot change.')
            ast.parse(content)
            files.append({'repo': row['repo'], 'path': relative, 'base_sha256': base,
                'sha256': _sha(content.encode('utf-8')), 'content': content,
                'diff': ''.join(difflib.unified_diff((old or b'').decode('utf-8').splitlines(True),
                    content.splitlines(True), fromfile=relative, tofile=relative))})
        if not source_repos or not source_repos <= {t['repo'] for t in new_tests}:
            raise RepairRejected('Every changed source repository needs a new regression test.')
        pinned = []
        for repo in sorted(source_repos):
            paths = list(self.regressions.get(repo) or [])
            if not paths:
                raise RepairRejected('Trusted existing regression paths must be pinned for each repository.')
            if repo=='main' and _planning_child_incident(proposal):
                paths.append('tests/test_video_agent_planning_claim.py')
            for path in dict.fromkeys(paths):
                target, path = self._path(repo, path)
                if not path.startswith('tests/') or not target.is_file():
                    raise RepairRejected('Pinned regression is not an existing test.')
                pinned.append({'repo': repo, 'path': path, 'sha256': _sha(target.read_bytes())})
        repair_id = 'repair-' + uuid.uuid4().hex
        folder = self._folder(repair_id)
        snapshot = folder/'stage'
        snapshot_hashes = {}
        for repo, root in self.roots.items():
            package = 'hotpost' if repo == 'main' else 'auto_capcut'
            for directory in (package, 'tests'):
                for source in (root/directory).rglob('*'):
                    relative = source.relative_to(root)
                    if source.is_file() and not source.is_symlink() and self._copyable(relative):
                        if not source.resolve().is_relative_to(root):
                            raise RepairRejected('Snapshot symlink leaves repository.')
                        data = source.read_bytes()
                        destination = snapshot/repo/relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
                        snapshot_hashes[repo+'/'+relative.as_posix()] = _sha(data)
            for name in _METADATA:
                source = root/name
                if source.is_file() and not source.is_symlink():
                    data = source.read_bytes()
                    (snapshot/repo).mkdir(parents=True, exist_ok=True)
                    (snapshot/repo/name).write_bytes(data)
                    snapshot_hashes[repo+'/'+name] = _sha(data)
        for row in files:
            original = snapshot/row['repo']/row['path']
            actual = _sha(original.read_bytes()) if original.is_file() else None
            if actual != row['base_sha256']:
                raise RepairRejected('Working tree changed while taking the repair snapshot.')
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_text(row['content'], encoding='utf-8', newline='')
        record = {'repair_id': repair_id, 'status': 'staged', 'created_at': time.time(),
                  'reason': str(proposal['reason']), 'planner_call_id': proposal.get('planner_call_id'),
                  'binding': {k: proposal.get(k) for k in ('task_id', 'job_id', 'input_fingerprint', 'agent_epoch', *(['job_fingerprint'] if proposal.get('job_fingerprint') else []))},
                  'files': files, 'pinned_tests': pinned, 'new_tests': new_tests,
                  'snapshot_hashes': snapshot_hashes}
        if proposal.get('prior_repair_id'):record['prior_repair_id']=proposal['prior_repair_id']
        if proposal.get('incident') is not None:
            from .video_agent_context import compact_incident
            record.update(incident=compact_incident(proposal['incident']),incident_evidence_version=2)
            record['review_context']=self._review_context(record,proposal.get('review_context'))
            record['recovery_context']=self._recovery_context(record)
        fixture=proposal.get('incident_fixture')
        if fixture is not None:
            if (not isinstance(fixture,dict) or (fixture.get('task') or {}).get('id')!=proposal['task_id']
                    or (fixture.get('job') or {}).get('id')!=proposal['job_id']):
                raise RepairRejected('Incident fixture must match the exact task and job.')
            raw=_json(fixture).encode('utf8')
            if len(raw)>16*1024*1024:raise RepairRejected('Incident fixture exceeds isolated evidence limit.')
            path=snapshot/'.repair-evidence'/'incident.json'
            _atomic(path,raw)
            record['incident_fixture']={'relative_path':'.repair-evidence/incident.json',
                'sha256':_sha(raw),'bytes':len(raw),'environment':'HOTPOST_REPAIR_INCIDENT',
                'keys':['task','job','artifacts'],'sandbox_version':3}
        self._save(record)
        return repair_id

    def _assert_stage(self, record):
        stage = self._folder(record['repair_id'])/'stage'
        fixture=record.get('incident_fixture')
        if fixture:
            path=stage/'.repair-evidence'/'incident.json'
            if (fixture.get('relative_path')!='.repair-evidence/incident.json' or path.is_symlink()
                    or not path.resolve().is_relative_to(stage.resolve()) or not path.is_file()
                    or _sha(path.read_bytes())!=fixture.get('sha256')):
                raise RepairRejected('Captured incident fixture changed after staging.')
        expected = dict(record['snapshot_hashes'])
        expected.update({r['repo']+'/'+r['path']: r['sha256'] for r in record['files']})
        for relative, sha in expected.items():
            path = stage/relative
            if not path.is_file() or _sha(path.read_bytes()) != sha:
                raise RepairRejected('Staged inputs changed after the exact repair was recorded.')
        for repo in self.roots:
            for directory in ('hotpost' if repo == 'main' else 'auto_capcut', 'tests'):
                for path in (stage/repo/directory).rglob('*.py'):
                    if path.relative_to(stage).as_posix() not in expected:
                        raise RepairRejected('Unexpected executable source appeared in the isolated stage.')
        return stage

    def test_patch(self, repair_id, *, timeout_seconds=120, guard=nullcontext):
        with guard():pass
        record = self._read(repair_id)
        if record['status'] == 'applied' or record.get('applied_at'):
            raise RepairRejected('Applied repairs cannot be retested in place.')
        stage = self._assert_stage(record)
        harness = self._folder(repair_id)/'test_harness.py'
        _atomic(harness, _harness(record).encode('utf-8'))
        results = []
        for repo in sorted({r['repo'] for r in record['files']}):
            python = self.interpreters.get(repo)
            if python is None or not python.is_file():
                raise RepairRejected('Configured existing repository interpreter is unavailable.')
            tests = sorted({r['path'] for r in record['pinned_tests']+record['new_tests'] if r['repo'] == repo})
            temp = stage/repo/'test-tmp'
            temp.mkdir(exist_ok=True)
            env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'COMSPEC') if k in os.environ}
            env.update(PYTHONPATH=os.pathsep.join(str(stage/r) for r in self.roots),
                PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                PYTHONIOENCODING='utf-8', TEMP=str(temp), TMP=str(temp), HOME=str(temp), USERPROFILE=str(temp))
            if record.get('incident_fixture'):
                env['HOTPOST_REPAIR_INCIDENT']=str(stage/'.repair-evidence'/'incident.json')
            extended=bool(record.get('incident_fixture',{}).get('sandbox_version',0)>=2)
            if extended:env.update(TEMP=_test_temp_path(temp),TMP=_test_temp_path(temp))
            timeout=max(1,min(600,timeout_seconds))
            command = [str(python), '-u', str(harness), str(stage), '-vv', '-p', 'no:cacheprovider',
                       '-o', 'faulthandler_timeout='+str(max(.5,timeout*.7)),
                       '--confcutdir', str(stage/repo), '--rootdir', str(stage/repo),
                       '--basetemp', _test_temp_path(temp/'pytest') if extended else str(temp/'pytest'), *tests]
            started = time.time()
            try:
                run = subprocess.run(command, cwd=stage/repo, env=env, capture_output=True,
                    text=True, encoding='utf-8', errors='replace', timeout=timeout,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                output, code = run.stdout+'\n'+run.stderr, run.returncode
            except subprocess.TimeoutExpired as exc:
                chunks=[value.decode('utf8',errors='replace') if isinstance(value,bytes) else str(value or '')
                    for value in (exc.stdout,exc.stderr)]
                output, code = 'Pinned regression timeout; no live retry or apply.\n'+'\n'.join(chunks), None
            log = self._folder(repair_id)/(repo+'-tests-'+uuid.uuid4().hex[:12]+'.log')
            _atomic(log, output.encode('utf-8'))
            results.append({'repo': repo, 'tests': tests, 'returncode': code, 'passed': code == 73,
                'started_at': started, 'finished_at': time.time(), 'log_sha256': _sha(log.read_bytes()),
                'log_path': str(log), 'command': command})
        self._assert_stage(record)
        with self._record_lock, guard():
            current=self._read(repair_id)
            if current['status']=='applied' or current.get('applied_at'):
                raise RepairRejected('Applied repair history changed while testing; preserve its receipt.')
            record.pop('review', None)
            record.update(status='tests_passed' if all(r['passed'] for r in results) else 'tests_failed', tests=results,review_evidence_version=2)
            self._save(record)
        return {'repair_id': repair_id, 'status': record['status'], 'tests': results}

    def review_request(self, repair_id):
        record = self._read(repair_id)
        self._require_incident(record)
        self._assert_stage(record)
        if (record['status'] not in {'tests_passed', 'reviewed', 'applied'} or not record.get('tests')
                or not all(t['passed'] for t in record['tests'])):
            raise RepairRejected('Independent review requires passing pinned tests.')
        for test in record['tests']:
            if _sha(Path(test['log_path']).read_bytes()) != test['log_sha256']:
                raise RepairRejected('Test log changed after verification.')
        material = {k: record[k] for k in ('repair_id', 'binding', 'files', 'pinned_tests', 'new_tests', 'snapshot_hashes', 'tests')}
        if 'incident' in record:material['incident']=record['incident']
        if 'incident_evidence_version' in record:material['incident_evidence_version']=record['incident_evidence_version']
        if 'review_context' in record:material['review_context']=record['review_context']
        if 'recovery_context' in record:material['recovery_context']=record['recovery_context']
        if 'incident_fixture' in record:material['incident_fixture']=record['incident_fixture']
        if record.get('review_evidence_version',1)>=2:
            harness=self._folder(repair_id)/'test_harness.py'
            if harness.read_text('utf8')!=_harness(record):raise RepairRejected('Test harness changed after execution.')
            material['test_execution']={'success_exit_code':73,'harness_sha256':_sha(harness.read_bytes()),
                'harness_source':_harness(record),'logs':self.diagnostics(repair_id,record['binding']['task_id'])['tests']}
        return {**material, 'binding_sha256': _sha(_json(material).encode('utf-8')),
                'instruction': 'Independently review exact diff and regression evidence. Reject weakened quality/identity/access/ownership guards, threshold changes to pass, unsafe side effects, or tests that merely mirror implementation. When incident is present it is host-captured preserved task/job evidence, not planner claims. Require regression coverage of this existing failure state and a demonstrated route for the original job to recover; prevention only for future new jobs is insufficient. A faithful minimal reproducer is acceptable for a local defect if all defect-relevant fields and execution branches correspond to the actual incident and omitted history cannot affect that route. Do not require wholesale historical state copying merely because it exists. Ownership-bound migrations still require exact task/job/run/input binding and negative tests. Distinguish a meaningful regression from incomplete incident coverage; any rejection must identify the specific untested relevant condition or branch, not a generic full-state demand. Changes to checkpoint behavior must verify persisted outcomes. Isolated tests may supply fresh valid external model/browser responses and temporary media with consistently rebound hashes in a deep fixture copy. This is test data, never production approval. Preserve the causal defect and task/job/run identity, keep internal validators real, demonstrate the old failure and repaired production entry advancing to its next normal stage, and retain negative guards. Do not require real network searches, final rendering or live QA before code can be applied: live production and completion are separately verified afterward. Recovery evidence may be composed: recovery_context supplies unchanged staged host retry code and actually pinned test bodies, with their hashes and execution logs. Distinguish mocked validators in unit tests from actual signature/load enforcement in host code. Explicitly omitted context is not evidence; require any relevant missing contract. A tested production sub-entry such as cached_visual_queries is not helper-only merely because it omits the full collection lifecycle. Require only the missing relevant connection from this preserved job/checkpoint to that sub-entry; do not reimplement unrelated browser/download/render lifecycle per local repair. failed jobs use the owner explicit retry_repaired action; resume_loaded_repairs automatically continues only eligible parked jobs. Do not infer access readiness from old observations. Rejection must specify the remaining causal field/branch not covered by the composed evidence. Reject helper-only or rejection-only tests when this relevant recovery connection is unproven. Do not authorize rewriting invalid production receipts into approvals. Return approved, preserves_quality_guards, regression_meaningful, recovers_current_incident, binding_sha256, reviewer_call_id, reason.'}

    def review_patch(self, repair_id, *, guard=nullcontext):
        with guard():pass
        record=self._read(repair_id)
        if record['status']=='applied' or record.get('applied_at'):
            raise RepairRejected('Applied repair history cannot be reviewed again in place. Inspect its receipt; propose a new repair for a new incident.')
        if not callable(self.reviewer):
            raise RepairRejected('An independent model reviewer must be supplied by the coordinator.')
        request = self.review_request(repair_id)
        review = self.reviewer(request)
        with self._record_lock, guard():
            record = self._read(repair_id)
            if record['status']=='applied' or record.get('applied_at'):
                raise RepairRejected('Applied repair history changed while reviewing; preserve its receipt.')
            if (not isinstance(review, dict) or review.get('binding_sha256') != request['binding_sha256']
                    or not isinstance(review.get('reviewer_call_id'), str) or not review['reviewer_call_id']
                    or review['reviewer_call_id'] == record.get('planner_call_id')
                    or ('incident' in record and review.get('recovers_current_incident') is not True)
                    or not all(review.get(k) is True for k in ('approved', 'preserves_quality_guards', 'regression_meaningful'))):
                record.update(status='review_rejected', review_rejection=review)
                self._save(record)
                raise RepairRejected('Independent reviewer did not approve this exact repair.')
            signed = {'binding_sha256': request['binding_sha256'], 'review': review}
            signed['signature'] = hmac.new(self._key, _json(signed).encode(), hashlib.sha256).hexdigest()
            record.update(status='reviewed', review=signed)
            self._save(record)
        return {**signed, 'review_id': request['binding_sha256']}

    def apply_patch(self, repair_id, *, store, review_id=None):
        # Same-process pipeline instances share this lock; production final
        # receipt guards and apply also serialize through the Studio transaction.
        with self._record_lock:
            return self._apply_patch(repair_id,store=store,review_id=review_id)

    def _apply_patch(self, repair_id, *, store, review_id=None):
        record = self._read(repair_id)
        if record['status'] == 'applied':
            receipt = self.applied_receipt(repair_id)
            if review_id is not None and review_id != receipt['review_id']:
                raise RepairRejected('Review identity differs from the applied repair.')
            return receipt
        request = self.review_request(repair_id)
        signed = dict(record.get('review') or {})
        signature = signed.pop('signature', '')
        expected = hmac.new(self._key, _json(signed).encode(), hashlib.sha256).hexdigest()
        if (record['status'] != 'reviewed' or not hmac.compare_digest(signature, expected)
                or (review_id is not None and review_id != request['binding_sha256'])
                or signed.get('binding_sha256') != request['binding_sha256']):
            raise RepairRejected('Missing or changed signed independent review.')
        folder = self._folder(repair_id)
        backups, replaced = [], []
        with store.connect() as db:
            queues = [('main', 'status')]
            for alias, path, column in [('writer_queue', store.root.parent/'writing'/'jobs.sqlite3', 'state'),
                                         ('collection_queue', store.root.parent/'hotpost.db', 'status')]:
                if path.is_file():
                    db.execute('ATTACH DATABASE ? AS '+alias, (str(path),))
                    queues.append((alias, column))
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='video_agents'").fetchone():
                raise RepairRejected('Responsible-agent enrollment is missing.')
            binding = record['binding']
            if not binding.get('job_fingerprint'):
                raise RepairRejected('Legacy repair lacks exact job inputs; restage with prior_repair_id='+repair_id+', then test and independently review again.')
            owner = db.execute('SELECT epoch FROM video_agents WHERE task_id=?', (binding['task_id'],)).fetchone()
            task = db.execute('SELECT state FROM tasks WHERE id=?', (binding['task_id'],)).fetchone()
            auto = json.loads(task['state']).get('automation', {}) if task else {}
            if (not owner or owner['epoch'] != binding['agent_epoch']
                    or not auto.get('active') or auto.get('paused_by_user')):
                raise RepairRejected('Agent ownership changed or the task is inactive/user-paused.')
            job = db.execute('SELECT * FROM jobs WHERE id=?', (binding['job_id'],)).fetchone()
            if (not job or job['task_id'] != binding['task_id']
                    or json.loads(job['checkpoint']).get('video_agent_input_fingerprint') != binding['input_fingerprint']):
                raise RepairRejected('Original job input binding changed or is missing.')
            from .video_agent_actions import _gate, ActionHeld, context_recovery_job
            current_state=json.loads(task['state'])
            quality_context=context_recovery_job(current_state,job)
            if (json.loads(job['checkpoint']).get('failure_classification') or {}).get('category')=='access_blocked':
                raise RepairRejected('Access-blocked job requires verified session recovery before code repair.')
            try:_gate(current_state,'apply_context_repair' if quality_context else 'retry_repaired',job)
            except ActionHeld as exc:raise RepairRejected('Current repair authority is held: '+str(exc)) from exc
            if ((current_state.get('source_acquisition') or {}).get('receipt_wait')
                    and not json.loads(job['checkpoint']).get('internal_evidence_wait')):
                raise RepairRejected('Unsettled external receipt cannot authorize code application.')
            if binding.get('job_fingerprint'):
                from .video_agent_context import job_method_fingerprint, semantic_fingerprint
                if (job_method_fingerprint(job)!=binding['job_fingerprint']
                        or semantic_fingerprint(json.loads(task['state']))!=binding['input_fingerprint']):
                    raise RepairRejected('Reviewed task/job inputs changed; restage, test and review again.')
            if job['status'] not in {'failed','paused'} and not quality_context:
                raise RepairRejected('Exact repair target must be parked before apply.')
            coordinator=getattr(store,'video_agents',None)
            quiesced=bool(coordinator and coordinator.maintenance.is_set())
            for alias, column in queues:
                present = db.execute(f"SELECT 1 FROM {alias}.sqlite_master WHERE name='jobs'").fetchone()
                states="('running')" if alias=='main' and quiesced else "('queued','running')"
                if present and db.execute(f"SELECT 1 FROM {alias}.jobs WHERE {column} IN {states} LIMIT 1").fetchone():
                    raise RepairRejected('All production, collection and model queues must be idle before apply.')
            for relative, sha in record['snapshot_hashes'].items():
                repo, path = relative.split('/', 1)
                live = self.roots[repo]/path
                if not live.is_file() or _sha(live.read_bytes()) != sha:
                    raise RepairRejected('Working tree dependency changed since isolated tests; use propose_patch with prior_repair_id='+repair_id+' to restage exact files, then test and independently review again.')
            for row in record['files']:
                target, _ = self._path(row['repo'], row['path'], edit=True)
                old = target.read_bytes() if target.is_file() else None
                if (_sha(old) if old is not None else None) != row['base_sha256']:
                    raise RepairRejected('Live source changed; preserve user edits and prepare a new repair.')
                backup = folder/'backups'/row['repo']/row['path']
                if old is not None:
                    _atomic(backup, old)
                backups.append((target, backup if old is not None else None, row))
            record.update(status='applying', apply_started_at=time.time())
            self._save(record)
            barrier=store.root/'agent-maintenance.json'
            _atomic(barrier,_json({'repair_id':repair_id,'phase':'applying'}).encode('utf8'))
            try:
                for target, backup, row in backups:
                    current = target.read_bytes() if target.is_file() else None
                    if (_sha(current) if current is not None else None) != row['base_sha256']:
                        raise RepairRejected('Concurrent edit detected before replacement; preserve it.')
                    _source_replace(target,row['content'].encode('utf-8'),row['base_sha256'])
                    replaced.append((target, backup, row))
                    purge_bytecode(target)
                record.update(status='applied', applied_at=time.time(), restart_required=True)
                self._save(record)
            except BaseException:
                rollback = []
                for target, backup, row in reversed(replaced):
                    if not target.is_file() or _sha(target.read_bytes()) != row['sha256']:
                        rollback.append({'path': str(target), 'restored': False, 'reason': 'concurrent_user_change_preserved'})
                        continue
                    _source_replace(target,backup.read_bytes() if backup else None,row['sha256'])
                    purge_bytecode(target)
                    rollback.append({'path': str(target), 'restored': True})
                record.update(status='apply_failed', rollback=rollback)
                self._save(record)
                raise
        return self.applied_receipt(repair_id)

    def applied_receipt(self, repair_id):
        """Authenticate a completed apply after a coordinator/process crash.

        This read-only receipt can reconstruct a missing restart request. An
        interrupted partial apply is never promoted to applied by this method.
        """
        record = self._read(repair_id)
        if record['status'] != 'applied' or not record.get('restart_required'):
            raise RepairRejected('Repair has no completed apply receipt.')
        request = self.review_request(repair_id)
        signed = dict(record.get('review') or {})
        signature = signed.pop('signature', '')
        if (signed.get('binding_sha256') != request['binding_sha256'] or not hmac.compare_digest(signature,
                hmac.new(self._key, _json(signed).encode(), hashlib.sha256).hexdigest())):
            raise RepairRejected('Applied repair independent review cannot be authenticated.')
        for row in record['files']:
            path, _ = self._path(row['repo'], row['path'], edit=True)
            if not path.is_file() or _sha(path.read_bytes()) != row['sha256']:
                raise AppliedSourceChanged('Applied source no longer matches the reviewed repair.')
        return {'repair_id': repair_id, 'status': 'applied', 'restart_required': True,
                'applied_at': record['applied_at'], 'review_id': request['binding_sha256'],
                'binding': dict(record['binding']),
                'files': [{k: r[k] for k in ('repo', 'path', 'sha256')} for r in record['files']]}

    def ready_to_apply(self, repair_id):
        """Read-only proof for parking the exact queued job before idle apply."""
        try:
            record = self._read(repair_id)
            if record['status'] != 'reviewed':
                return False
            request = self.review_request(repair_id)
            signed = dict(record.get('review') or {})
            signature = signed.pop('signature', '')
            if (signed.get('binding_sha256') != request['binding_sha256'] or not hmac.compare_digest(signature,
                    hmac.new(self._key, _json(signed).encode(), hashlib.sha256).hexdigest())):
                return False
            for relative, sha in record['snapshot_hashes'].items():
                repo, relative = relative.split('/', 1)
                live = self.roots[repo]/relative
                if not live.is_file() or _sha(live.read_bytes()) != sha:
                    return False
            for row in record['files']:
                live, _ = self._path(row['repo'], row['path'], edit=True)
                if (_sha(live.read_bytes()) if live.is_file() else None) != row['base_sha256']:
                    return False
            return {'repair_id': repair_id, 'binding': dict(record['binding']),
                    'files': [{k: r[k] for k in ('repo','path','sha256')} for r in record['files']],
                    'review_binding_sha256': request['binding_sha256']}
        except (KeyError, TypeError, ValueError, OSError):
            return False


def recover_partial_apply(pipeline,store,record):
    """Recover a process interruption using exact original/tested bytes only."""
    barrier=store.root/'agent-maintenance.json'
    if json.loads(barrier.read_text('utf8'))['repair_id']!=record['repair_id']:
        raise RepairRejected('Maintenance barrier belongs to another repair.')
    from .source_loader import restore_missing_sources
    for root in pipeline.roots.values():
        for relative in ('hotpost','auto_capcut','tests'):
            if (root/relative).is_dir():restore_missing_sources(root/relative)
    folder=pipeline._folder(record['repair_id']);restored=[]
    for row in record['files']:
        target,_=pipeline._path(row['repo'],row['path'],edit=True)
        actual=_sha(target.read_bytes()) if target.is_file() else None
        if actual==row['base_sha256']:
            purge_bytecode(target)
            continue
        if actual!=row['sha256']:
            raise RepairRejected('Concurrent user source changed during interrupted apply; preserve it.')
        if row['base_sha256'] is None:_source_replace(target,None,row['sha256'])
        else:
            backup=folder/'backups'/row['repo']/row['path']
            data=backup.read_bytes()
            if _sha(data)!=row['base_sha256']:raise RepairRejected('Interrupted apply backup SHA changed.')
            _source_replace(target,data,row['sha256'])
        purge_bytecode(target)
        restored.append(row['path'])
    record.update(status='apply_failed',interruption_recovered=True,restored_paths=restored,restored_at=time.time())
    pipeline._save(record)
    _atomic(barrier,_json({'repair_id':record['repair_id'],'phase':'restored_restart_required'}).encode('utf8'))


def verified_repair(studio, state, action, old_job):
    """A paused method may resume only after this repair is loaded in this process.

    The coordinator supplies the pipeline and an in-memory loaded-code receipt;
    planner action data is never accepted as evidence of a process restart.
    """
    pipeline = getattr(studio, 'video_repair_pipeline', None)
    loaded = (getattr(studio,'loaded_code_receipts',{}) or {}).get(action.get('repair_id')) or getattr(studio, 'loaded_code_receipt', None)
    if not isinstance(pipeline, VideoRepairPipeline) or not isinstance(loaded, dict):
        return False
    try:
        record = pipeline._read(action.get('repair_id'))
        binding = record.get('binding') or {}
        if not binding.get('job_fingerprint'):return False
        expected_input = (old_job.get('checkpoint') or {}).get('video_agent_input_fingerprint')
        if binding.get('job_fingerprint'):
            from .video_agent_context import job_method_fingerprint, semantic_fingerprint
            if (job_method_fingerprint(old_job)!=binding['job_fingerprint']
                    or semantic_fingerprint(state)!=binding['input_fingerprint']):return False
        if (record['status'] != 'applied' or not expected_input
                or any(binding.get(k) != v for k, v in {'task_id': state['id'], 'job_id': old_job['id'], 'input_fingerprint': expected_input}.items())
                or (action.get('_agent_epoch') is not None and binding.get('agent_epoch') != action['_agent_epoch'])
                or old_job.get('task_id') != state['id']
                or loaded.get('repair_id') != record['repair_id'] or loaded.get('process_id') != os.getpid()
                or not isinstance(loaded.get('loaded_at'), (int, float))
                or loaded['loaded_at'] < record['applied_at']):
            return False
        request = pipeline.review_request(record['repair_id'])
        signed = dict(record.get('review') or {})
        signature = signed.pop('signature', '')
        if (signed.get('binding_sha256') != request['binding_sha256'] or not hmac.compare_digest(signature,
                hmac.new(pipeline._key, _json(signed).encode(), hashlib.sha256).hexdigest())):
            return False
        expected = sorted(({k: r[k] for k in ('repo', 'path', 'sha256')} for r in record['files']), key=_json)
        if sorted(loaded.get('files') or [], key=_json) != expected:
            return False
        if not all((pipeline.roots[r['repo']]/r['path']).is_file()
                and _sha((pipeline.roots[r['repo']]/r['path']).read_bytes()) == r['sha256'] for r in record['files']):
            return False
        return {'repair_id': record['repair_id'], 'binding': dict(binding), 'files': expected,
                'review_binding_sha256': request['binding_sha256']}
    except (KeyError, TypeError, ValueError, OSError):
        return False

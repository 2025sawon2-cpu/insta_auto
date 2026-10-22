"""A private, serialized CLI conversation for one video owner epoch/run."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from ..editing_adapter import _atomic_json
from ..production import file_lock


@contextmanager
def conversation(state):
    binding=state.get('owner_conversation')
    if state.get('purpose')!='video_agent' or not binding or state.get('_format_repair_depth'):
        yield None
        return
    if (not isinstance(binding,dict) or set(binding)!={'task_id','run_id','epoch'}
            or not isinstance(binding['task_id'],str) or not re.fullmatch(r'work-[a-f0-9]{16}',binding['task_id'])
            or type(binding['epoch']) is not int or binding['epoch']<1
            or binding['run_id'] is not None and (not isinstance(binding['run_id'],str)
                or not re.fullmatch(r'run-[a-f0-9]{16}',binding['run_id']))):
        raise ValueError('Invalid responsible video conversation binding.')
    key=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
    root=Path(state['directory']).resolve().parent/'owner-sessions'/key
    with file_lock(root/'session.lock'):
        path=root/'session.json'
        raw=path.read_bytes() if path.is_file() else None
        reset_reason=None
        try:
            record=json.loads(raw) if raw is not None else {'binding':dict(binding),'thread_id':None}
            if not isinstance(record,dict) or record.get('binding')!=binding:raise ValueError('Wrong binding')
            thread=record.get('thread_id')
            if thread is not None and (not isinstance(thread,str) or str(uuid.UUID(thread))!=thread):raise ValueError('Invalid identity')
        except (ValueError,TypeError):
            # Never follow a corrupt or foreign registry identity. Preserve it
            # and restart only this host-bound owner from durable job evidence.
            archive=path.with_name('invalid-'+uuid.uuid4().hex+'.json');archive.write_bytes(raw)
            reset_reason='invalid_local_conversation_registry'
            thread=None
            _atomic_json(path,{'binding':dict(binding),'thread_id':None,'reset_reason':reset_reason,
                              'preserved_registry':archive.name,'updated_at':time.time()})
        cwd=root/'context';cwd.mkdir(exist_ok=True)
        yield {'path':path,'cwd':cwd,'binding':dict(binding),'thread_id':thread,'reset_reason':reset_reason}


def accept(context,events,call_id):
    ids=[row.get('thread_id') for row in events if row.get('type')=='thread.started']
    if len(ids)!=1 or not isinstance(ids[0],str) or str(uuid.UUID(ids[0]))!=ids[0]:
        raise ValueError('CLI did not attest an exact conversation identity.')
    if context['thread_id'] is not None and ids[0]!=context['thread_id']:
        raise ValueError('CLI resumed a different conversation.')
    _atomic_json(context['path'],{'binding':context['binding'],'thread_id':ids[0],
        'last_success_call':call_id,'updated_at':time.time()})
    return ids[0]


def missing_rollout(context,events,stderr,call_id):
    """Recover only the CLI's exact local missing-history error, not auth/capacity."""
    thread=context.get('thread_id')
    if not thread or events or not re.fullmatch(
            r'Error: thread/resume: thread/resume failed: no rollout found for thread id '
            +re.escape(thread)+r' \(code -32600\)\s*',stderr):return False
    path=context['path']
    record=json.loads(path.read_text('utf8'))
    if record.get('binding')!=context['binding'] or record.get('thread_id')!=thread:
        raise ValueError('Conversation changed during missing-history recovery.')
    _atomic_json(path.with_name('missing-'+call_id+'.json'),record)
    _atomic_json(path,{'binding':context['binding'],'thread_id':None,
        'reset_reason':'verified_missing_cli_rollout','previous_thread_id':thread,'updated_at':time.time()})
    context['thread_id']=None
    return True


def value_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def recovered_missing_receipt(receipt,receipts,saved,expected_binding):
    """A failed local resume may precede an exactly bound successful result."""
    if (receipt.get('status')!='failed' or receipt.get('error_type')!='MissingOwnerConversation'
            or receipt.get('missing_rollout_verified') is not True or receipt.get('exit_code')!=1
            or 'value' not in saved):return False
    replacement=receipts.get(receipt.get('replacement_call_id'))
    if not isinstance(replacement,dict) or replacement is receipt or replacement.get('status')!='completed' or replacement.get('exit_code')!=0:return False
    original=receipt.get('owner_conversation') or {};current=replacement.get('owner_conversation') or {}
    if (not isinstance(original,dict) or not isinstance(current,dict) or not expected_binding
            or original.get('binding')!=expected_binding or original.get('binding')!=current.get('binding')
            or current.get('resumed') is not False or not current.get('thread_id')
            or original.get('thread_id')==current.get('thread_id')):return False
    digest=value_digest(saved['value'])
    if receipt.get('decoded_value_sha256')!=digest or replacement.get('decoded_value_sha256')!=digest:return False
    inference=saved.get('inference') if isinstance(saved.get('inference'),dict) else {}
    calls=inference.get('calls',[])
    if not isinstance(calls,list):return False
    return receipt in calls and replacement in calls


def command(binary,directory,schema,output,thread_id):
    args=[binary,'exec','--ignore-user-config','--skip-git-repo-check',
        '--sandbox','read-only','--disable','shell_tool','-c','web_search="disabled"',
        '-c','approval_policy="never"','-c','project_doc_max_bytes=0',
        '-C',str(directory),'--color','never']
    if thread_id is not None:args+=['resume']
    args+=['--json','--output-schema',str(schema),'--output-last-message',str(output)]
    if thread_id is not None:args.append(thread_id)
    return args+['-']

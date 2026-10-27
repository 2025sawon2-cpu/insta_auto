"""Stage entry/exit receipts so each production step starts from its own rules.

``begin`` lists the stage's rules and questions and records their bytes; ``end``
takes the producer's answers plus the stage outputs, checks the outputs came
from the official path, and refuses when the rules changed after ``begin``.
Answers are the producer's own judgment; code checks presence and binding only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from .final_qa import digest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs' / 'stage_contracts.json'
# Productions started before this keep their original path; later ones need gate receipts.
REQUIRED_SINCE = datetime(2026, 10, 28, tzinfo=timezone.utc)


def load_contract(path=None):
    contract = json.loads(Path(path or CONTRACT).read_text('utf-8'))
    for name, stage in contract['stages'].items():
        allowed = set(contract['common_rules']) | set(stage['rules'])
        for check in stage['checks']:
            if check['rule'] not in allowed:
                raise ValueError(f'{name} check {check["id"]} cites a rule outside the stage')
        for need in stage['requires']:
            if need not in contract['stages']:
                raise ValueError(f'{name} requires unknown stage {need}')
    return contract


def required_rules(contract=None, stages=None):
    contract = contract or load_contract()
    names = stages or list(contract['stages'])
    rules = list(contract['common_rules'])
    for name in names:
        rules += [rule for rule in contract['stages'][name]['rules'] if rule not in rules]
    return [ROOT / rule for rule in rules]


def _file(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'Not a file: {path}')
    return {'path': str(path), 'sha256': digest(path)}


def _unchanged(item, label):
    try:
        current = digest(item['path'])
    except OSError as error:
        raise ValueError(f'{label} is missing: {item["path"]}') from error
    if current != item['sha256']:
        raise ValueError(f'{label} changed after it was recorded: {item["path"]}')


def _json(path):
    return json.loads(Path(path).read_text('utf-8'))


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    temporary.replace(path)


def _paths(gates, stage):
    return gates / f'{stage}.begin.json', gates / f'{stage}.end.json'


def _identity(video_id, task_id, run_id):
    for label, value in (('video_id', video_id), ('task_id', task_id), ('run_id', run_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{label} is required')
    return {'video_id': video_id, 'task_id': task_id, 'run_id': run_id}


def verify_end(gates, stage, identity=None):
    """Return a finished stage's receipt if its outputs are still the recorded bytes."""
    path = _paths(Path(gates), stage)[1]
    if not path.is_file():
        raise ValueError(f'{stage} stage has not ended; run its begin/end first')
    receipt = _json(path)
    if identity and {k: receipt.get(k) for k in identity} != identity:
        raise ValueError(f'{stage} stage belongs to another video/task/run')
    for name, items in receipt['outputs'].items():
        for item in items:
            _unchanged(item, f'{stage} output {name}')
    return receipt


def begin(gates, stage, *, video_id, task_id, run_id, restart=False, contract_path=None):
    gates = Path(gates)
    contract = load_contract(contract_path)
    if stage not in contract['stages']:
        raise ValueError(f'Unknown stage: {stage}')
    identity = _identity(video_id, task_id, run_id)
    spec = contract['stages'][stage]
    begin_path, end_path = _paths(gates, stage)
    if end_path.exists():
        if not restart:
            raise ValueError(f'{stage} stage already ended; pass --restart to redo it')
        history = gates / 'history'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        for path in (begin_path, end_path):
            if path.exists():
                history.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(history / f'{stamp}-{path.name}'))
    for need in spec['requires']:
        verify_end(gates, need, identity)
    receipt = {'schema_version': 1, 'stage': stage, **identity,
               'began_at': datetime.now(timezone.utc).isoformat(),
               'contract': {'version': contract['version'], **_file(contract_path or CONTRACT)},
               'rules': [_file(ROOT / rule) for rule in contract['common_rules'] + spec['rules']],
               'checks': spec['checks']}
    _write(begin_path, receipt)
    return receipt


def _output_files(spec, value):
    values = value if isinstance(value, list) else [value]
    if spec['kind'] != 'files' and len(values) != 1:
        raise ValueError(f'{spec["kind"]} output takes one file')
    if not values:
        raise ValueError('files output needs at least one file')
    return [_file(path) for path in values]


def _check_writing(data, spec):
    if data.get('type') != 'scripts' or len(data.get('scripts') or []) != spec['variants']:
        raise ValueError(f'Writing result must hold {spec["variants"]} variants from the official pipeline')
    _check_calls(data.get('generation_inference') or {}, spec['model'], 'Writing result')


def _check_calls(inference, model, label):
    calls = inference.get('calls')
    if not calls or inference.get('fallback') is True:
        raise ValueError(f'{label} has no official model calls')
    for call in calls:
        if call.get('requested_model') != model or call.get('fallback') is not False:
            raise ValueError(f'{label} must use {model} without fallback')


def _check_outputs(spec_map, outputs, gates, identity):
    recorded = {}
    for name, spec in spec_map.items():
        if outputs.get(name) in (None, []):
            if spec.get('optional'):
                continue
            raise ValueError(f'Output {name} is required')
        recorded[name] = _output_files(spec, outputs[name])
    unknown = set(outputs) - set(spec_map)
    if unknown:
        raise ValueError(f'Unknown outputs: {sorted(unknown)}')
    data = {name: _json(items[0]['path']) for name, items in recorded.items()
            if spec_map[name]['kind'] not in ('file', 'files')}

    for name, spec in spec_map.items():
        kind = spec['kind']
        if name not in recorded:
            continue
        if kind == 'writing_result':
            _check_writing(data[name], spec)
        elif kind == 'script_selection':
            _check_calls({'calls': data[name].get('calls')}, spec['model'], 'Script selection')
        elif kind == 'voice_result':
            result = data[name]
            if (result.get('status') != 'succeeded' or result.get('style_verified') is not True
                    or result.get('requested_style_id') != spec['style'] or result.get('voice_profile_id')):
                raise ValueError(f'Voice must be the personal clone with verified style {spec["style"]}')
            recorded[name].append(_file(result['output_path']))
        elif kind == 'edit_plan':
            _check_plan(data[name], spec, gates, identity)
        elif kind == 'delivery_receipt':
            receipt = data[name]
            for media in ('video', 'cover'):
                if _file(receipt[media])['sha256'] != receipt[f'{media}_sha256']:
                    raise ValueError(f'Delivery {media} differs from its finalize receipt')
                recorded[name].append(_file(receipt[media]))
            if not (receipt.get('full_decode') and receipt.get('faststart')):
                raise ValueError('Delivery must pass finalize decode and faststart checks')

    if 'selected_script' in recorded:
        text = Path(recorded['selected_script'][0]['path']).read_text('utf-8').strip()
        variants = [s.get('text', '').strip() for s in data['writing_result']['scripts']]
        selection = data.get('selection')
        if text not in variants and not (selection and selection.get('text', '').strip() == text
                                         and selection.get('before', '').strip() in variants):
            raise ValueError('Selected script is not one of the variants or an official refinement of one')
    return recorded


def _check_plan(plan, spec, gates, identity):
    script = Path(verify_end(gates, 'script', identity)['outputs']['selected_script'][0]['path'])
    if plan.get('script_text', '').strip() != script.read_text('utf-8').strip():
        raise ValueError('Edit plan script differs from the selected script')
    review = (plan.get('caption_semantic_contract') or {}).get('review') or {}
    if review.get('script_sha256') != hashlib.sha256(plan['script_text'].encode('utf-8')).hexdigest():
        raise ValueError('Edit plan needs the caption meaning review for this script')
    if (plan.get('narration_policy') or {}).get('profile') != spec['narration_profile']:
        raise ValueError(f'Edit plan must use the {spec["narration_profile"]} pause policy')
    audio = verify_end(gates, 'voice', identity)['outputs']['voice_result'][-1]['sha256']
    if (plan.get('voice_source') or {}).get('sha256') != audio:
        raise ValueError('Edit plan voice is not the voice stage output')


def end(gates, stage, *, answers, outputs, contract_path=None):
    gates = Path(gates)
    begin_path, end_path = _paths(gates, stage)
    if not begin_path.is_file():
        raise ValueError(f'{stage} stage has not begun; run begin first and read its rules')
    started = _json(begin_path)
    identity = {k: started[k] for k in ('video_id', 'task_id', 'run_id')}
    _unchanged(started['contract'], 'Stage contract')
    for rule in started['rules']:
        try:
            _unchanged(rule, 'Rule')
        except ValueError as error:
            raise ValueError(f'{error}; run begin again and read the changed rule') from error
    contract = load_contract(contract_path)
    spec = contract['stages'][stage]
    for need in spec['requires']:
        verify_end(gates, need, identity)
    for check in started['checks']:
        row = answers.get(check['id'])
        if (not isinstance(row, dict) or not isinstance(row.get('answer'), str) or not row['answer'].strip()
                or not isinstance(row.get('evidence'), list) or not row['evidence']
                or not all(isinstance(e, str) and e.strip() for e in row['evidence'])):
            raise ValueError(f'Check {check["id"]} needs an answer and evidence: {check["question"]}')
    receipt = {**{k: started[k] for k in ('schema_version', 'stage', 'video_id', 'task_id', 'run_id', 'began_at')},
               'ended_at': datetime.now(timezone.utc).isoformat(),
               'begin_sha256': digest(begin_path),
               'answers': {check['id']: answers[check['id']] for check in started['checks']},
               'outputs': _check_outputs(spec['outputs'], outputs, gates, identity)}
    _write(end_path, receipt)
    return receipt


def require_complete(gates, identity, contract_path=None):
    """Completion needs every stage ended with unchanged outputs."""
    for stage in load_contract(contract_path)['stages']:
        verify_end(gates, stage, identity)


def status(gates, contract_path=None):
    gates = Path(gates)
    rows = {}
    for stage in load_contract(contract_path)['stages']:
        begin_path, end_path = _paths(gates, stage)
        rows[stage] = 'ended' if end_path.exists() else 'begun' if begin_path.exists() else 'not_started'
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description='Production stage entry/exit receipts')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('begin', 'end', 'status'):
        command = sub.add_parser(name)
        command.add_argument('--gates', type=Path, required=True,
                             help='task folder stage-gates directory')
        if name != 'status':
            command.add_argument('--stage', required=True)
    first = sub.choices['begin']
    for key in ('--video-id', '--task-id', '--run-id'):
        first.add_argument(key, required=True)
    first.add_argument('--restart', action='store_true')
    last = sub.choices['end']
    last.add_argument('--answers', type=Path, required=True,
                      help='JSON {check_id: {"answer": ..., "evidence": [...]}}')
    last.add_argument('--output', action='append', default=[], metavar='NAME=PATH',
                      help='repeat; repeat the same NAME for multi-file outputs')
    args = parser.parse_args(argv)
    if args.command == 'begin':
        result = begin(args.gates, args.stage, video_id=args.video_id, task_id=args.task_id,
                       run_id=args.run_id, restart=args.restart)
        result = {'stage': result['stage'], 'read_now': [r['path'] for r in result['rules']],
                  'answer_at_end': result['checks']}
    elif args.command == 'end':
        outputs = {}
        for item in args.output:
            name, _, path = item.partition('=')
            if not path:
                raise SystemExit(f'--output needs NAME=PATH: {item}')
            outputs.setdefault(name, []).append(path)
        outputs = {k: v if len(v) > 1 or k == 'sources' else v[0] for k, v in outputs.items()}
        result = end(args.gates, args.stage, answers=_json(args.answers), outputs=outputs)
        result = {'stage': result['stage'], 'ended_at': result['ended_at']}
    else:
        result = status(args.gates)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

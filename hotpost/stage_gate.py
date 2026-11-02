"""Stage entry/exit receipts so each production step starts from its own rules.

``begin`` lists the stage's rules and questions and records their bytes; ``end``
takes the producer's answers plus the stage outputs, checks the outputs came
from the official path, and refuses when the rules changed after ``begin``.
Answers are the producer's own judgment; code checks presence and binding only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

from .final_qa import digest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs' / 'stage_contracts.json'
# Productions started before this keep their original path; later ones need gate receipts.
REQUIRED_SINCE = datetime(2026, 10, 28, tzinfo=timezone(timedelta(hours=9)))


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


def verify_end(gates, stage, identity=None, _verified=None):
    """Return a finished stage's receipt if its outputs are still the recorded bytes."""
    _verified = {} if _verified is None else _verified
    if stage in _verified:
        return _verified[stage]
    path = _paths(Path(gates), stage)[1]
    if not path.is_file():
        raise ValueError(f'{stage} stage has not ended; run its begin/end first')
    receipt = _json(path)
    if identity and {k: receipt.get(k) for k in identity} != identity:
        raise ValueError(f'{stage} stage belongs to another video/task/run')
    for need, expected in receipt.get('dependencies', {}).items():
        actual = verify_end(gates, need, identity, _verified)['outputs']
        if actual != expected:
            raise ValueError(f'{stage} stage has stale {need} inputs; review and restart {stage}')
    for name, items in receipt['outputs'].items():
        for item in items:
            _unchanged(item, f'{stage} output {name}')
    _verified[stage] = receipt
    return receipt


def _dependencies(gates, needs, identity):
    verified = {}
    return {need: verify_end(gates, need, identity, verified)['outputs'] for need in needs}


def begin(gates, stage, *, video_id, task_id, run_id, restart=False, contract_path=None):
    gates = Path(gates)
    contract = load_contract(contract_path)
    if stage not in contract['stages']:
        raise ValueError(f'Unknown stage: {stage}')
    identity = _identity(video_id, task_id, run_id)
    spec = contract['stages'][stage]
    begin_path, end_path = _paths(gates, stage)
    dependencies = _dependencies(gates, spec['requires'], identity)
    if end_path.exists():
        if not restart:
            raise ValueError(f'{stage} stage already ended; pass --restart to redo it')
        history = gates / 'history'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        for path in (begin_path, end_path):
            if path.exists():
                history.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(history / f'{stamp}-{path.name}'))
    receipt = {'schema_version': 2, 'stage': stage, **identity,
               'dependencies': dependencies,
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
    _check_calls(data.get('generation_inference') or {}, 'Writing result')


def _check_calls(inference, label):
    calls = inference.get('calls')
    if not calls or inference.get('fallback') is True:
        raise ValueError(f'{label} has no official model calls')
    for call in calls:
        if call.get('provider') != 'codex' or call.get('status') != 'completed' or call.get('fallback') is not False:
            raise ValueError(f'{label} must have completed official Codex calls without fallback')


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
            _check_calls({'calls': data[name].get('calls')}, 'Script selection')
        elif kind == 'voice_result':
            result = data[name]
            from .ai_studio_adapter import MODEL, VOICE, STYLE
            if (result.get('status') != 'succeeded' or result.get('style_verified') is not True
                    or result.get('provider') != 'google-ai-studio-browser'
                    or result.get('model') != MODEL or result.get('voice_name') != VOICE
                    or result.get('style') != STYLE):
                raise ValueError('Voice must be Google AI Studio Arlo with verified style')
            selected = verify_end(gates, 'script', identity)['outputs']['selected_script'][0]['path']
            script = Path(selected).read_text('utf-8').strip()
            if result.get('text_sha256') != hashlib.sha256(script.encode('utf-8')).hexdigest():
                raise ValueError('Voice request text differs from the selected script')
            if (result.get('seed_supported') is not False or result.get('seed') is not None
                    or result.get('quality_mode') != 'google-ai-studio'
                    or result.get('segment_count') != 1):
                raise ValueError('Google TTS must use one whole-script segment without a fake Seed claim')
            actual = _file(result['output_path'])
            if actual['sha256'] != result.get('audio_sha256'):
                raise ValueError('Voice WAV differs from its Google browser receipt')
            recorded[name].append(actual)
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
    # Reuse the renderer's existing parent grouping/body-only enforcement.
    # Omitting its opt-in flag otherwise silently disables that protection.
    diversity = plan.get('source_diversity_policy') or {}
    minimum = diversity.get('minimum_parent_sources', 5)
    if (diversity.get('version') != 'minimum-five-sources-v1'
            or type(minimum) is not int or minimum < 5):
        raise ValueError('Edit plan must enable the renderer source diversity protection')
    source_outputs = verify_end(gates, 'source', identity)['outputs']['sources']
    reviewed = {Path(item['path']).resolve(): item['sha256'] for item in source_outputs}
    sources = plan.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('Edit plan needs the actual sources reviewed at the source stage')
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('path'), str) or not source['path'].strip():
            raise ValueError('Edit plan source stage input needs a file path')
        actual = _file(source['path'])
        if (source.get('sha256') != actual['sha256']
                or reviewed.get(Path(actual['path'])) != actual['sha256']):
            raise ValueError('Edit plan source differs from the source stage output; review the changed file first')
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
    hook = verify_end(gates, 'script', identity).get('answers', {}).get('script_hook', {}).get('review')
    if hook:
        lines = (plan.get('cover_spec') or {}).get('lines')
        if lines is None:
            cover = plan.get('cover_text', '')
            lines = cover.splitlines() if isinstance(cover, str) else cover
        if lines != hook.get('thumbnail_lines'):
            raise ValueError('Edit plan thumbnail differs from its audience hook review')


def montage_usage(plan):
    """Bind native rendered selections and describe normal-speed body exposure.

    This reads the plan's render receipt, not decoded pixels. The edit gate
    separately binds its source files; editorial truth still needs actual QA.
    """
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Montage timing must be finite')
        return value

    def same(left, right):
        return abs(number(left) - number(right)) <= 8 * max(math.ulp(left), math.ulp(right))

    def selected(items, key, label):
        if not isinstance(items, list):
            raise ValueError(f'Montage selected {label} records are missing')
        matches = [item for item in items if isinstance(item, dict) and item.get('id') == key]
        if not key or len(matches) != 1:
            raise ValueError(f'Montage selected {label} is missing or ambiguous')
        return matches[0]

    fps = number(plan.get('fps', 30))
    length = number(plan.get('duration'))
    if fps <= 0 or length <= 0:
        raise ValueError('Montage output clock is invalid')
    selections = plan.get('visual_cuts') or plan.get('beats')
    clips = plan.get('rendered_clips')
    if not isinstance(clips, list) or not clips:
        raise ValueError('Montage review needs the actual rendered clips')
    if not isinstance(selections, list) or len(selections) != len(clips):
        raise ValueError('Montage rendered clips differ from the current picture selections')
    sources, shots = plan.get('sources', []), plan.get('shots', [])
    selected_windows = plan.get('footage_selection_policy') in {
        'diverse-sequential-v1', 'diverse-sequential-v2-semantic-first', 'product-story-global-v3'}
    parents, cursor, raw_duration = {}, 0, 0
    for index, (selection, clip) in enumerate(zip(selections, clips)):
        if not isinstance(selection, dict) or not isinstance(clip, dict):
            raise ValueError('Montage selection and rendered clip must be records')
        shot = selected(shots, selection.get('selected_shot_id'), 'shot')
        source = selected(sources, shot.get('source_id'), 'source')
        paths = [item.get('path') for item in (source, shot)]
        if (any(not isinstance(path, str) or not path.strip() for path in paths)
                or Path(paths[0]).resolve() != Path(paths[1]).resolve()
                or not source.get('sha256') or shot.get('sha256') != source['sha256']):
            raise ValueError('Montage selected shot differs from its reviewed plan source')
        if (not selection.get('id') or clip.get('beat_id') != selection['id']
                or clip.get('selected_shot_id') != shot['id']
                or clip.get('source_sha256') != source['sha256']):
            raise ValueError('Rendered clip differs from the current selected shot/source')
        parent_beat = None
        if plan.get('visual_cuts'):
            parent_id = selection.get('parent_beat_id')
            parent_beat = selected(plan.get('beats', []), parent_id, 'parent beat')
            if clip.get('parent_beat_id') != parent_id:
                raise ValueError('Rendered clip differs from its current parent beat')
        start, end = number(selection.get('start')), number(selection.get('end'))
        first = round(start * fps)
        last = math.ceil(length * fps) if index == len(clips) - 1 else round(end * fps)
        if (start < 0 or end <= start or first != cursor or last <= first
                or (index == len(clips) - 1 and math.ceil(end * fps) != last)):
            raise ValueError('Montage current selections do not cover the output frame clock')
        if parent_beat:
            parent_first = round(number(parent_beat.get('start')) * fps)
            parent_last = (math.ceil(length * fps) if parent_beat is plan['beats'][-1]
                           else round(number(parent_beat.get('end')) * fps))
            if first < parent_first or last > parent_last:
                raise ValueError('Montage visual cut differs from its current parent beat timing')
        duration = number(clip.get('duration'))
        if not same(clip.get('start'), first / fps) or not same(duration, (last - first) / fps):
            raise ValueError('Rendered clip timing differs from the current output frame clock')
        window = clip.get('selected_source_window')
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError('Rendered clip needs its actual source window')
        window = [number(value) for value in window]
        expected = ([selection.get('source_start'), selection.get('source_end')] if selected_windows
                    else [shot.get('start'), shot.get('end')])
        if any(not same(actual, expected) for actual, expected in zip(window, expected)):
            raise ValueError('Rendered clip source window differs from the current selected window')
        if window[0] < 0 or window[1] <= window[0] or duration <= 0:
            raise ValueError('Rendered clip timing is invalid')
        if ((window[0] < number(shot.get('start')) and not same(window[0], shot['start']))
                or (window[1] > number(shot.get('end')) and not same(window[1], shot['end']))
                or window[1] - window[0] < duration - 1e-9):
            raise ValueError('Montage selected window cannot supply normal-speed rendered frames')
        cursor = last
        raw_duration += duration
        skip = min(duration, 1 / fps) if index == 0 and plan.get('cover_mode') == 'replace_first_frame' else 0
        if duration <= skip:
            continue  # A source replaced entirely by the cover has no body exposure.
        parent = source.get('original_sha256') or source.get('parent_sha256') or source['sha256']
        offset = (source.get('original_interval') or {}).get('start', source.get('parent_start', 0))
        if number(offset) < 0:
            raise ValueError('Original source offset is invalid')
        item = parents.setdefault(parent, {'duration': 0, 'uses': 0, 'intervals': []})
        item['duration'] += duration - skip
        item['uses'] += 1
        # -frames:v limits the output even when the reviewed/selected window
        # is longer. Only the actually exposed part contributes unique time.
        item['intervals'].append((offset + window[0] + skip, offset + window[0] + duration))
    rows = []
    for parent, item in parents.items():
        merged = []
        for start, end in sorted(item['intervals']):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        unique = sum(end - start for start, end in merged)
        rows.append({'parent_sha256': parent, 'duration': round(item['duration'], 6),
                     'uses': item['uses'], 'unique_seconds': round(unique, 6),
                     'replay_seconds': round(max(0, item['duration'] - unique), 6)})
    return {'timeline_seconds': round(raw_duration, 6),
            'body_seconds': round(sum(item['duration'] for item in parents.values()), 6),
            'parents': sorted(rows, key=lambda row: (-row['duration'], row['parent_sha256']))}


def _editorial_review(check, row, outputs):
    kind = check.get('review_kind')
    if not kind:
        return
    review = row.get('review')
    if not isinstance(review, dict) or review.get('decision') != 'proceed':
        raise ValueError(f'{kind} needs a current editorial review before proceeding')
    if kind in {'audience_hook_v1', 'audience_hook_v2'}:
        script = outputs['selected_script'][0]
        from .writing.script_style import explicit_expression_issues
        if explicit_expression_issues(Path(script['path']).read_text('utf-8')):
            raise ValueError('Selected script contains 사용자 금지 표현: 괜히 반가워요')
        from .writing.hook_policy import first_sentence
        opening = first_sentence(Path(script['path']).read_text('utf-8').strip())
        if review.get('script_sha256') != script['sha256'] or review.get('opening_quote') != opening:
            raise ValueError('Audience hook review differs from the current script/opening')
        required = ('target_audience', 'viewer_interest', 'why_keep_watching', 'weakness_considered',
                    'thumbnail_interest', 'thumbnail_promise', 'thumbnail_weakness_considered')
        lines = review.get('thumbnail_lines')
        if not isinstance(lines, list) or len(lines) != 2 or not all(isinstance(x, str) and x.strip() for x in lines):
            raise ValueError('Audience hook review needs the actual two thumbnail lines')
        if kind == 'audience_hook_v2':
            empathy = review.get('empathy_review')
            context = review.get('thumbnail_context_review')
            if (not isinstance(empathy, dict) or empathy.get('natural') is not True
                    or not isinstance(empathy.get('quote'), str) or not empathy['quote'].strip()
                    or empathy['quote'] not in Path(script['path']).read_text('utf-8')
                    or not isinstance(empathy.get('reason'), str) or not empathy['reason'].strip()):
                raise ValueError('Audience review needs current natural empathy; revise forced or awkward wording')
            if (not isinstance(context, dict) or context.get('pre_view_relevant') is not True
                    or any(not isinstance(context.get(k), str) or not context[k].strip()
                           for k in ('core_appeal', 'expected_topic', 'reason'))):
                raise ValueError('Audience review needs thumbnail relevance before viewing; revise story-dependent copy')
    elif kind == 'montage_v1':
        recorded = outputs['plan'][0]
        if review.get('plan_sha256') != recorded['sha256']:
            raise ValueError('Montage review differs from the current plan')
        if review.get('usage') != montage_usage(_json(recorded['path'])):
            raise ValueError('Montage review usage differs from the actual rendered source windows')
        required = ('sequence_assessment', 'repetition_assessment', 'script_visual_relation', 'weakness_considered')
    else:
        raise ValueError(f'Unknown editorial review kind: {kind}')
    if any(not isinstance(review.get(key), str) or not review[key].strip() for key in required):
        raise ValueError(f'{kind} needs specific audience/sequence/weakness observations')


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
    dependencies = _dependencies(gates, spec['requires'], identity)
    if started.get('dependencies') != dependencies:
        raise ValueError(f'{stage} predecessor inputs changed; run begin again and review the changed inputs')
    for check in started['checks']:
        row = answers.get(check['id'])
        if (not isinstance(row, dict) or not isinstance(row.get('answer'), str) or not row['answer'].strip()
                or not isinstance(row.get('evidence'), list) or not row['evidence']
                or not all(isinstance(e, str) and e.strip() for e in row['evidence'])):
            raise ValueError(f'Check {check["id"]} needs an answer and evidence: {check["question"]}')
    recorded = _check_outputs(spec['outputs'], outputs, gates, identity)
    for check in started['checks']:
        _editorial_review(check, answers[check['id']], recorded)
    receipt = {**{k: started[k] for k in ('schema_version', 'stage', 'video_id', 'task_id', 'run_id', 'began_at')},
               'ended_at': datetime.now(timezone.utc).isoformat(),
               'begin_sha256': digest(begin_path),
               'dependencies': dependencies,
               'answers': {check['id']: answers[check['id']] for check in started['checks']},
               'outputs': recorded}
    _write(end_path, receipt)
    return receipt


def require_complete(gates, identity, contract_path=None):
    """Completion needs every stage ended with unchanged outputs."""
    verified = {}
    for stage in load_contract(contract_path)['stages']:
        verify_end(gates, stage, identity, verified)


def status(gates, contract_path=None):
    gates = Path(gates)
    rows = {}
    for stage in load_contract(contract_path)['stages']:
        begin_path, end_path = _paths(gates, stage)
        if end_path.exists():
            try:
                verify_end(gates, stage)
                rows[stage] = 'ended'
            except (ValueError, OSError):
                rows[stage] = 'stale'
        else:
            rows[stage] = 'begun' if begin_path.exists() else 'not_started'
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

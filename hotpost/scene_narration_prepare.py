"""Prepare fresh narration context without rendering or replacing a failed edit."""
import copy
import hashlib
import json
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_quality import sha256_file, editing_ready

POLICY = 'fresh-narration-analysis-remap-v1'


class NarrationContextHold(ValueError):
    def __init__(self, issues):
        self.issues = copy.deepcopy(issues)
        super().__init__('새 승인 대본의 실제 장면 문맥·피드백 연결이 불명확하여 보류: '
                         + ' / '.join(str(i.get('reason', '')) for i in issues))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def commit_identity(target):
    from .scene_requirement_context import build_scene_requirement_context
    from .scene_requirements import required_scenes
    return _hash({'script_id':target.get('script_id'), 'approved_script_id':target.get('approved_script_id'),
            'voice_id':target.get('voice_id'), 'edit_id':target.get('edit_id'),
            'feedback':target.get('daily_quality', {}).get('feedback'),
            'repair_round':target.get('daily_quality', {}).get('repair_round'),
            'max_repairs':target.get('daily_quality', {}).get('max_repairs'),
            'context_signature':build_scene_requirement_context(target,required_scenes(target))['signature'],
            'active':target.get('automation', {}).get('active')})


def _save(studio, state, changes, expected_identity=None, *, job=None):
    expected = expected_identity or commit_identity(state)
    def apply(target, db):
        if commit_identity(target) != expected:
            raise NarrationContextHold([{'kind':'scene_gap','reason':'문맥 검토 중 선택 대본·음성·편집·피드백·중지 설정이 변경됨'}])
        for key, value in changes.items():
            if key == 'daily_quality':
                target.setdefault(key, {}).update({k:copy.deepcopy(value[k]) for k in
                    ('narration_preparations', 'feedback_remap_history', 'feedback', 'scene_requirements') if k in value})
            else:
                target[key] = copy.deepcopy(value)
    if job is not None:
        from .studio_store import change_claimed
        change_claimed(studio.store, {**job, 'task_id':state['id']}, apply)
    else:
        studio.store.change(state['id'], apply)
    # The store may operate on a separate snapshot; update this worker's view.
    if commit_identity(state) == expected:
        apply(state, None)


def prepare_narration_context(studio, state, job, generate=None):
    """Only bridge a changed approved script; unchanged or unverified inputs stay held."""
    from .scene_requirements import required_scenes
    from .scene_requirement_context import build_scene_requirement_context, _spoken_text, _expected_spoken_text
    requirements = required_scenes(state)
    if not requirements:
        return False
    context = build_scene_requirement_context(state, requirements)
    if context['verified']:
        return False
    script = next((s for s in state.get('scripts', []) if s.get('id') == state.get('script_id')), {})
    old = next((e for e in state.get('edits', []) if e.get('id') == state.get('edit_id')), {})
    if not old or old.get('script_id') == script.get('id'):
        return False
    input_identity = commit_identity(state)
    text = script.get('text')
    voice = next((v for v in state.get('voices', []) if v.get('id') == state.get('voice_id')), {})
    if (not isinstance(text, str) or not text.strip() or state.get('approved_script_id') != script.get('id')
            or voice.get('script_id') != script.get('id') or not Path(voice.get('path', '')).is_file()
            or sha256_file(Path(voice['path'])) != voice.get('sha256')
            or voice.get('script_sha256') not in (None, hashlib.sha256(text.encode()).hexdigest())
            or (voice.get('spoken_text') is not None and _spoken_text(voice['spoken_text'])
                != _spoken_text(_expected_spoken_text(state, text)))):
        raise NarrationContextHold([{'kind': 'scene_gap', 'reason': '새 대본·음성의 실제 파일 연결이 확인되지 않아 장면 문맥 준비 보류'}])
    old_path = Path(old.get('plan_path', ''))
    if not old_path.is_file():
        raise NarrationContextHold(requirements)
    old_plan = json.loads(old_path.read_text('utf-8'))
    if old.get('plan_sha256') and old['plan_sha256'] != sha256_file(old_path):
        raise NarrationContextHold(requirements)
    records = [s for s in state.get('sources', []) if editing_ready(s)
               and Path(s.get('path', '')).is_file() and sha256_file(Path(s['path'])) == s.get('sha256')]
    if not records:
        raise NarrationContextHold(requirements)
    source_key = _hash([{'id': s.get('id'), 'sha256': s.get('sha256'),
                        'reviewed_intervals': s.get('reviewed_intervals')} for s in records])
    key = _hash({'policy': POLICY, 'script': script, 'voice_sha256': voice['sha256'],
                 'old_plan_sha256': sha256_file(old_path), 'requirements': requirements, 'sources': source_key})
    quality = state.get('daily_quality', {})
    saved = quality.get('narration_preparations', {}).get(key)
    if saved:
        path = Path(saved['path'])
        if not path.is_file() or sha256_file(path) != saved['sha256']:
            raise NarrationContextHold([{'kind': 'scene_gap', 'reason': '저장한 대본 문맥 준비 결과 파일이 변경됨'}])
        receipt = json.loads(path.read_text('utf-8'))
        if receipt.get('status') != 'ready':
            raise NarrationContextHold(requirements)
    else:
        # _process checkpoints analysis by actual payload; no render is invoked.
        job.setdefault('checkpoint', {})
        folder = studio.folder(state['id']) / 'nctx' / key[:20]
        folder.mkdir(parents=True, exist_ok=True)
        plan_path = folder / 'analysis-plan.json'
        analysis_receipt_path = folder / 'analysis-receipt.json'
        if analysis_receipt_path.is_file():
            analysis_receipt = json.loads(analysis_receipt_path.read_text('utf-8'))
            if (analysis_receipt.get('input_key') != key or not plan_path.is_file()
                    or sha256_file(plan_path) != analysis_receipt.get('plan_sha256')):
                raise NarrationContextHold(requirements)
            plan = json.loads(plan_path.read_text('utf-8'))
        else:
            sources = studio._source_records([s['path'] for s in records], state.get('manifest_path', ''), records)
            result = studio._process(state, job, 'analyze', {'sources': sources, 'voice': voice, 'script': script})
            plan = result.get('plan') or {}
            _atomic_json(plan_path, plan)
            _atomic_json(analysis_receipt_path, {'policy': POLICY, 'input_key': key, 'plan_sha256': sha256_file(plan_path)})
        valid_plan = (plan.get('script_text') == text and bool(plan.get('beats'))
            and all(isinstance(b.get('text'), str) and b['text'].strip() for b in plan.get('beats', []))
            and _spoken_text(' '.join(b['text'] for b in plan['beats'])) == _spoken_text(text)
            and len({b.get('id') for b in plan['beats']}) == len(plan['beats']))
        receipt = {'policy': POLICY, 'input_key': key, 'status': 'held', 'plan_path': str(plan_path),
                   'plan_sha256': sha256_file(plan_path), 'old_edit_id': old['id'],
                   'original_feedback': copy.deepcopy(quality.get('feedback', []))}
        mappings = {}
        specific = [(i, r) for i, r in enumerate(requirements) if r.get('beat_id')]
        old_beats = {b.get('id'): b for b in old_plan.get('beats', [])}
        if valid_plan and all(r['beat_id'] in old_beats for _, r in specific):
            if specific:
                if generate is None:
                    from .script_rewriter import _generate
                    generate = _generate
                value = generate(studio.settings,
                    'Remap old visual quality defects to the actual beats of the new approved narration. '
                    'Return {mappings:[{index,beat_ids:[string],narration_quote:string,reason:string}]}. '
                    'Every specific defect must explicitly retain its object/action/whole-part meaning in '
                    'the new narration. Use only supplied new actual beat IDs, and narration_quote must equal '
                    'their connected exact text. Do not drop a defect, approve footage, rewrite narration, '
                    'or copy an old beat ID by position. If correspondence is ambiguous omit its mapping; '
                    'the job will hold, never render.',
                    {'old_script_text': old_plan.get('script_text'), 'old_requirements': [
                        {'index': i, 'requirement': r, 'old_beat': old_beats[r['beat_id']]} for i, r in specific],
                     'approved_new_script': text, 'new_actual_beats': plan['beats'],
                     'original_product_text': state.get('reviewed_original_text') or state.get('original_text')})
                new_beats = {b['id']: b for b in plan['beats']}
                positions = {b['id']:i for i,b in enumerate(plan['beats'])}
                for row in (value.get('mappings', []) if isinstance(value, dict) and isinstance(value.get('mappings'), list) else []):
                    if not isinstance(row, dict):continue
                    index = row.get('index'); ids = row.get('beat_ids')
                    if (type(index) is int and index in {i for i, _ in specific} and isinstance(ids, list)
                            and ids and all(isinstance(i, str) and i in new_beats for i in ids) and len(set(ids)) == len(ids)
                            and [positions[i] for i in ids] == list(range(positions[ids[0]], positions[ids[0]] + len(ids)))
                            and isinstance(row.get('reason'), str) and row['reason'].strip()
                            and row.get('narration_quote') == ' '.join(new_beats[i]['text'] for i in ids)):
                        if index in mappings:
                            mappings[index] = None
                        else:
                            mappings[index] = row
            if all(mappings.get(i) for i, _ in specific):
                updated = []
                visual_index = 0
                from .quality_issue_scope import is_cover_scene_gap
                for feedback in quality.get('feedback', []):
                    if (feedback.get('kind') not in {'scene_gap', 'repetition', 'watermark'}
                            or is_cover_scene_gap(feedback)):
                        updated.append(copy.deepcopy(feedback));continue
                    mapping = mappings.get(visual_index)
                    for beat_id in (mapping['beat_ids'] if mapping else [feedback.get('beat_id')]):
                        updated.append({**copy.deepcopy(feedback), 'beat_id': beat_id,
                            'narration_remap': {'policy': POLICY, 'input_key': key, 'from_edit_id': old['id'],
                                'from_beat_id': feedback.get('beat_id'), 'reason': mapping['reason'] if mapping else 'Global visual requirement preserved'}})
                    visual_index += 1
                receipt.update(status='ready', feedback=updated)
        receipt_path = folder / 'preparation-receipt.json'
        _atomic_json(receipt_path, receipt)
        quality = copy.deepcopy(state.get('daily_quality', {}))
        quality.setdefault('narration_preparations', {})[key] = {'path': str(receipt_path), 'sha256': sha256_file(receipt_path), 'status': receipt['status']}
        _save(studio, state, {'daily_quality': quality}, input_identity, job=job)
        if receipt['status'] != 'ready':
            raise NarrationContextHold(requirements)
    # The original failed edit and its current selection remain unchanged.
    prepared = {'policy': POLICY, 'id': 'analysis-' + key[:20], 'script_id': script['id'],
        'script_sha256': hashlib.sha256(text.encode()).hexdigest(), 'voice_id': voice['id'],
        'voice_sha256': voice['sha256'], 'plan_path': receipt['plan_path'],
        'plan_sha256': receipt['plan_sha256'], 'old_edit_id': old['id'], 'source_input_key': source_key}
    prepared['old_plan_sha256'] = sha256_file(old_path)
    quality = copy.deepcopy(state['daily_quality'])
    quality.setdefault('feedback_remap_history', []).append({'policy': POLICY, 'input_key': key,
        'old_edit_id': old['id'], 'feedback': receipt['original_feedback']})
    quality['feedback'] = receipt['feedback']
    _save(studio, state, {'scene_narration_plan': prepared, 'daily_quality': quality}, input_identity, job=job)
    if not build_scene_requirement_context(state, required_scenes(state))['verified']:
        raise NarrationContextHold(required_scenes(state))
    return True

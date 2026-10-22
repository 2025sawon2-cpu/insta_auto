"""Model-only owner context projection; durable evidence is never rewritten.

The cap counts UTF-8 JSON escaping of the complete instruction/prompt/schema,
with room for the writer's fixed envelope. Omitted bodies are references, never
partial tool results whose next_offset could falsely skip unread evidence.
"""
import copy
import hashlib
import json
import re


MAX_INPUT_BYTES = 768 * 1024
ENVELOPE_RESERVE = 16 * 1024
_PRIORITY = (
    'id', 'task_id', 'job_id', 'run_id', 'epoch', 'kind', 'status', 'error',
    'type', 'category', 'reason', 'message', 'failure_trace', 'frames',
    'binding', 'input_fingerprint', 'job_fingerprint', 'agent_epoch',
    'repair_id', 'incident_fixture', 'repo', 'path', 'log_path', 'log_sha256',
    'sha256', 'base_sha256', 'offset', 'total_characters', 'failure_summary',
    'passed', 'returncode', 'review_rejection', 'tests', 'checkpoint', 'payload',
)
_CAPS = {'checkpoint': 28 * 1024, 'failure_trace': 12 * 1024,
         'parser_repair_context': 12 * 1024, 'source_access_preflight': 12 * 1024,
         'incident': 12 * 1024, 'response': 1024, 'tests': 18 * 1024,
         'diagnostics': 32 * 1024, 'failure_summary': 8 * 1024}
_FIELDS = {'jobs': 128 * 1024, 'previous_steps': 128 * 1024,
           'working_evidence': 96 * 1024, 'repair_packet': 128 * 1024,
           'memory_index': 48 * 1024, 'artifacts': 24 * 1024}
_READ_KEYS = ('kind', 'repo', 'path', 'repair_id', 'decision_id', 'incident_path', 'query')


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _size(value):
    return len(_json(value).encode('utf8'))


def input_bytes(instruction, prompt, schema):
    """Conservative escaped request size, not a character/token estimate."""
    return _size({'instruction': instruction, 'prompt': prompt, 'schema': schema}) + ENVELOPE_RESERVE


def _reference(value, location, read_again=None):
    raw = _json(value).encode('utf8')
    result = {'projection_only': True, 'omitted': True,
              'original_utf8_bytes': len(raw), 'json_sha256': hashlib.sha256(raw).hexdigest(),
              'evidence_path': list(location), 'type': type(value).__name__}
    if isinstance(value, (dict, list, str)):
        result['count'] = len(value)
    if read_again:
        result['read_again'] = copy.deepcopy(read_again)
    return result


def _reader(value, inherited):
    action = value.get('action')
    result = value.get('result')
    if isinstance(action, dict) and isinstance(result, dict):
        reader = {k: copy.deepcopy(action[k]) for k in _READ_KEYS if k in action}
        if reader.get('kind') in {'inspect_code', 'inspect_artifact', 'inspect_repair', 'recall'}:
            reader['offset'] = result.get('offset', action.get('offset', 0))
            reader['limit'] = (min(24000, len(result['content']) or 12000)
                               if isinstance(result.get('content'), str)
                               else action.get('limit', 20 if reader['kind'] == 'recall' else 12000))
            return reader
    if value.get('repo') and value.get('path'):
        reader = {k: value[k] for k in ('repo', 'path')}
        reader.update(kind='inspect_repair' if value.get('source') == 'staged_repair' else 'inspect_code',
                      offset=value.get('offset', 0), limit=24000)
        if reader['kind'] == 'inspect_repair':
            reader['repair_id'] = value.get('repair_id')
        return reader
    if value.get('repair_id') and value.get('incident_fixture') and 'tests' not in value:
        return {'kind': 'inspect_repair', 'repair_id': value['repair_id'], 'incident_path': [], 'offset': 0, 'limit': 12000}
    if value.get('repair_id') and isinstance(value.get('tests'), list):
        return {'kind': 'inspect_repair', 'repair_id': value['repair_id']}
    if isinstance(value.get('id'), str) and value['id'].startswith('job-'):
        return {'kind': 'recall', 'query': value['id'], 'offset': 0, 'limit': 20}
    return inherited


def _failure_summary(text, max_bytes=6 * 1024):
    """Literal exception/source context; no fabricated verdict or partial body."""
    source = text.splitlines()
    result, seen, used = [], set(), 2
    # Exception first, then its nearby source expression/path, then failing IDs.
    errors = [i for i, line in enumerate(source) if re.search(
        r'^E\s|AssertionError|External call count|before\s*[=:]|after\s*[=:]', line)]
    groups = [[i, *range(max(0, i - 3), i), *range(i + 1, min(len(source), i + 3))]
              for i in errors]
    groups += [[i] for i, line in enumerate(source) if re.search(r'^FAILED |^ERROR ', line)]
    for group in groups:
        for i in group:
            line = source[i]
            if not line.strip() or line in seen or len(line.encode('utf8')) > 800:
                continue
            size = _size(line) + 2
            if used + size > max_bytes or len(result) >= 24:
                continue
            result.append(line); seen.add(line); used += size
    return result


def _fit(value, budget, location=(), reader=None):
    if _size(value) <= budget:
        return copy.deepcopy(value)
    ref = _reference(value, location, reader)
    if not isinstance(value, (dict, list)) or budget < 1024:
        return ref
    if isinstance(value, list):
        # Retain whole recent entries; the summary explicitly marks the rest.
        items = []
        recent_first = location and (location[0] in {'previous_steps', 'memory_index', 'working_evidence'}
                                    or location[-1] in {'queries', 'rounds', 'interrupted_attempts', 'source_attempts', 'tests'})
        order = reversed(range(len(value))) if recent_first else range(len(value))
        for index in order:
            remaining = budget - _size({'_projection': ref, 'items': items}) - 128
            if remaining < 1024:
                break
            item = _fit(value[index], min(24 * 1024, remaining), (*location, index), reader)
            if _size({'_projection': ref, 'items': [item, *items]}) > budget:
                break
            if recent_first:
                items.insert(0, item)
            else:
                items.append(item)
        return {'_projection': ref, 'items': items}
    reader = _reader(value, reader)
    result = {'_projection': ref}
    # Reserve causal failure evidence before command/environment fields spend
    # the diagnostic budget. The original SHA-bound log remains unchanged.
    if isinstance(value.get('log_excerpt'), str):
        summary = _failure_summary(value['log_excerpt'], min(6 * 1024, budget // 2))
        if summary:
            result['failure_summary'] = summary
            result['diagnostics_read_again'] = copy.deepcopy(reader)
    keys = [k for k in _PRIORITY if k in value] + [k for k in value if k not in _PRIORITY]
    for key in keys:
        if key == 'next_offset' and 'content' in value:
            continue
        remaining = budget - _size(result) - len(str(key).encode('utf8')) - 64
        if remaining < 512:
            continue
        child = value[key]
        projected = _fit(child, min(_CAPS.get(key, 8 * 1024), remaining), (*location, key), reader)
        candidate = {**result, key: projected}
        if _size(candidate) <= budget:
            result = candidate
    if isinstance(value.get('content'), str):
        if isinstance(result.get('content'), str):
            if 'next_offset' in value:
                result['next_offset'] = value['next_offset']
        else:
            result.pop('content', None)
            result['content_omitted'] = _reference(value['content'], (*location, 'content'), reader)
            # No next_offset: this body was NOT delivered to this model turn.
    return result if _size(result) <= budget else ref


def _previous(steps, budget):
    """Never excerpt the last explicit text read while keeping its next_offset."""
    latest = next((i for i in reversed(range(len(steps))) if
                   isinstance(steps[i], dict) and isinstance(steps[i].get('result'), dict)
                   and isinstance(steps[i]['result'].get('content'), str)), None)
    if latest is None:
        return _fit(steps, budget, ('previous_steps',))
    preserved = copy.deepcopy(steps[latest])
    # Other diagnostic structures may be summarized, but not its requested body.
    content = preserved['result'].pop('content')
    small = _fit(preserved, 12 * 1024, ('previous_steps', latest))
    if not isinstance(small.get('result'), dict) or small['result'].get('omitted'):
        small['result'] = copy.deepcopy(preserved['result'])
    small['result']['content'] = content
    if 'next_offset' in steps[latest]['result']:
        small['result']['next_offset'] = steps[latest]['result']['next_offset']
    others = [_fit(row, max(1024, budget // max(1, len(steps))), ('previous_steps', index))
              for index, row in enumerate(steps) if index != latest]
    return {'_projection': _reference(steps, ('previous_steps',)),
            'latest_complete_read': small, 'other_steps': others}


def owner_prompt(instruction, evidence, image_labels, schema):
    """Return bounded model JSON only; the passed payload and store stay intact."""
    prompt = _json({'evidence': evidence, 'image_labels': image_labels})
    if input_bytes(instruction, prompt, schema) <= MAX_INPUT_BYTES:
        return prompt
    # Only memory/history views are projected. Host action authorization still
    # uses the original state, bindings, complete jobs and durable observations.
    for scale in (1, .5, .25):
        projected = {}
        for key, value in evidence.items():
            budget = int(_FIELDS.get(key, 24 * 1024) * scale)
            projected[key] = (_previous(value, budget) if key == 'previous_steps' and isinstance(value, list)
                              else _fit(value, budget, (key,)))
        projected['model_input_projection'] = {
            'projection_only': True, 'original_evidence_sha256': hashlib.sha256(_json(evidence).encode('utf8')).hexdigest(),
            'original_evidence_utf8_bytes': _size(evidence), 'max_escaped_input_bytes': MAX_INPUT_BYTES,
            'retrieval': 'Original payload, jobs and observations are preserved. recall(decision_id,offset,limit) retrieves historical responses; recall(query,offset,limit) searches all decisions, including entries outside this projection. Use read_again on omitted code bodies. inspect_repair(repair_id,incident_path,offset,limit) retrieves the exact immutable incident. Omitted evidence is NOT a pass, approval or delivery of its next_offset.'}
        prompt = _json({'evidence': projected, 'image_labels': image_labels})
        if input_bytes(instruction, prompt, schema) <= MAX_INPUT_BYTES:
            return prompt
    raise ValueError('Owner model input core exceeds UTF-8 budget; no model request sent. Original evidence remains preserved.')

"""Optional, independently grounded editorial intent; never candidate approval."""
import copy

POLICY = 'reference-scene-intent-v1'
FIELDS = ('visible_content', 'information_or_emotion', 'persuasive_role', 'alternative_visuals')

PROPOSAL_PROMPT = (
    'Also describe reference_scenes:[{id,frame_ids,visible_content,information_or_emotion,'
    'persuasive_role,alternative_visuals}] as FREE TEXT based on this reference. Identify the visible '
    'shot content, what it communicates, its plausible persuasive purpose and other related footage '
    'that could serve that purpose. Purposes/emotions are editorial interpretations, not verified '
    'viewer responses or product facts. Do not impose a fixed taxonomy, scene count, reaction shot, '
    'or one scene per narration sentence. The supplied mixed frame order has unknown timestamps: '
    'do not invent chronology, duration, or before/after actions. Use independent visible states. '
    'Add scene_ids to each query only when its observed product detail helps discover that scene. '
    'Keep the query itself a grounded short product noun phrase; never append emotions, shot '
    'instructions or invented features. A core-only query may have no scene_ids. '
)
REVIEW_PROMPT = (
    'Also return scene_checks:[{scene_id,visible_content_supported:boolean,'
    'role_plausible:boolean,alternatives_relevant:boolean,reason}] and for each query check '
    'scene_ids_supported:boolean. Independently inspect the cited pixels: reject invented actions, '
    'chronology or product facts; plausible persuasive roles are interpretations only. Alternatives '
    'must remain relevant to this product and message. Missing/unsupported scene intent does NOT '
    'reject an otherwise valid product query. Reactions are optional, never universally preferred. '
)


def approved_scenes(proposal, review, evidence):
    """Missing advisory data degrades to the established product-only search."""
    checks = review.get('scene_checks') or []
    if not isinstance(checks, list):
        return []
    checked = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get('scene_id'), str):
            continue
        key = check['scene_id']
        checked[key] = None if key in checked else check
    rows = proposal.get('reference_scenes') or []
    if not isinstance(rows, list):
        return []
    from collections import Counter
    counts = Counter(r['id'] for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str))
    ids = {f['id'] for f in evidence['frames']}
    result, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or row['id'] in seen or counts[row['id']] != 1):
            continue
        seen.add(row['id'])
        check = checked.get(row['id']) or {}
        frames = row.get('frame_ids')
        if (not isinstance(frames, list) or not frames or any(not isinstance(f, str) for f in frames)
                or not set(frames) <= ids
                or not all(isinstance(row.get(k), str) and row[k].strip() for k in FIELDS)
                or not all(check.get(k) is True for k in
                    ('visible_content_supported', 'role_plausible', 'alternatives_relevant'))):
            continue
        result.append({'id':row['id'], 'frame_ids':list(dict.fromkeys(frames)),
                       **{k:row[k].strip() for k in FIELDS}, 'basis':'reviewed_editorial_interpretation'})
    return result


def scene_links(query, check, scenes):
    linked = query.get('scene_ids')
    if check.get('scene_ids_supported') is not True or not isinstance(linked, list):
        return []
    known = {s['id'] for s in scenes}
    return list(dict.fromkeys(s for s in linked if isinstance(s, str) and s in known))


def diverse_query_order(rows):
    """Prefer unseen reference purposes within each language without dropping queries."""
    ordered = []
    for language in dict.fromkeys(r.get('language') for r in rows):
        pending = [r for r in rows if r.get('language') == language]
        covered = set()
        while pending:
            index = max(range(len(pending)), key=lambda i:len(set(pending[i].get('scene_ids', []))-covered))
            row = pending.pop(index)
            ordered.append(row)
            covered.update(row.get('scene_ids', []))
    return ordered


def plan_context(plan, reference_sha256):
    """Revalidate the receipt and exact reference before transferring advisory roles."""
    if not plan.get('visual_query_evidence') or plan.get('query_reference_sha256') != reference_sha256:
        return None
    from .source_visual_queries import plan_queries
    plan_queries(plan)
    receipt = plan['visual_query_evidence']
    scenes = approved_scenes(receipt['proposal'], receipt['review'], receipt['evidence'])
    if not scenes:
        return None
    return {'policy':POLICY, 'reference_sha256':reference_sha256,
            'input_sha256':receipt['input_sha256'], 'scenes':copy.deepcopy(scenes),
            'usage':'editorial_preference_only_not_identity_or_coverage_approval'}

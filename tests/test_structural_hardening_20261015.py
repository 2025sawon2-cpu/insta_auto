"""Regression tests for 2026-10-15 structural hardening (Items A, B, C, D)."""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from hotpost.config import Settings
from hotpost.quality_progress import resume_assessment
from hotpost.source_planning import enrich_plan, QUERY_PLAN_POLICY
from hotpost.source_queries import (
    grounded_tiktok_noun_phrase,
    platform_queries,
    product_query_plan,
    tiktok_product_queries,
)
from hotpost.studio_automation import _resolve_rewrite_manifest, identify_subject
from hotpost.writing.jobs import Jobs


def test_item_a_jobs_sqlite_payload_offloading_media_compaction_and_rehydration(tmp_path):
    jobs = Jobs(tmp_path)
    img_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9'
    b64_img = base64.b64encode(img_bytes).decode('ascii')
    original_payload = {
        'instruction': 'Inspect frame',
        'evidence': {'purpose': 'overlay_review'},
        'media': [
            {'text': 'FRAME 1'},
            {'inlineData': {'mimeType': 'image/jpeg', 'data': b64_img}},
        ],
    }
    created = jobs.create('editorial', original_payload)
    jid = created['id']

    # 1. SQLite payload column must be NULL, and idx_jobs_state_created + WAL must be active
    with jobs.db() as db:
        row = db.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()
        assert row['payload'] is None
        journal = db.execute('PRAGMA journal_mode').fetchone()[0]
        assert journal.lower() == 'wal'
        indexes = [r[1] for r in db.execute("PRAGMA index_list('jobs')").fetchall()]
        assert 'idx_jobs_state_created' in indexes

    # 2. payload.json exists on disk before worker runs
    payload_file = tmp_path / jid / 'payload.json'
    assert payload_file.is_file()

    # 3. Simulate image extraction during execute() and compact media
    image_path = tmp_path / jid / 'image-1.jpg'
    image_path.write_bytes(img_bytes)
    assert jobs._compact_payload_media(jid, original_payload) is True

    # Caller's in-memory dict must not be mutated
    assert original_payload['media'][1]['inlineData']['data'] == b64_img

    # On-disk payload.json must replace base64 data with _external_file reference
    disk_json = json.loads(payload_file.read_text('utf-8'))
    assert disk_json['media'][1]['inlineData'] == {
        '_external_file': 'image-1.jpg',
        'mimeType': 'image/jpeg',
    }

    # 4. get(jid, include_payload=False) omits 'payload'; include_payload=True re-hydrates inlineData.data
    without_payload = jobs.get(jid, include_payload=False)
    assert 'payload' not in without_payload
    with_payload = jobs.get(jid, include_payload=True)
    assert with_payload['payload'] == original_payload


def test_item_b_uncatalogued_literal_primary_subject_survives_tiktok_and_multilingual_action_heads(tmp_path):
    caption = '집에서 쓰는 전동 네일케어 추천합니다. 버튼으로 속도 조절이 쉬워요.'
    base_plan = product_query_plan(caption, [], [], {'speech': ''}, [])
    assert base_plan['products'] == []  # Not in static PRODUCTS catalog

    llm_response = {
        'subject_kind': 'product',
        'primary_subject': {
            'name': '전동 네일케어',
            'source': 'caption',
            'quote': '집에서 쓰는 전동 네일케어 추천합니다',
        },
        'queries': [
            {
                'query': 'speed control button',
                'language': 'en',
                'intent': 'action',
                'source': 'caption',
                'quote': '버튼으로 속도 조절이 쉬워요',
            },
            {
                'query': '速度调节按钮',
                'language': 'zh',
                'intent': 'action',
                'source': 'caption',
                'quote': '버튼으로 속도 조절이 쉬워요',
            },
        ],
        'tiktok_queries': [
            {
                'query': 'electric nail care',
                'language': 'en',
                'source': 'caption',
                'quote': '집에서 쓰는 전동 네일케어 추천합니다',
            },
            {
                'query': '电动美甲器',
                'language': 'zh',
                'source': 'caption',
                'quote': '집에서 쓰는 전동 네일케어 추천합니다',
            },
        ],
    }

    enriched = enrich_plan(
        Settings(data_dir=tmp_path),
        base_plan,
        caption,
        {'speech': ''},
        lambda *_: llm_response,
    )
    # D1: Literal Korean primary_subject is dynamically approved for TikTok and survives platform_queries
    tk_queries = tiktok_product_queries(enriched)
    assert '전동 네일케어' in tk_queries
    assert '전동 네일케어' in platform_queries(tk_queries, 'tiktok', 5)
    # Ungrounded English translation still blocked on TikTok
    assert grounded_tiktok_noun_phrase('vacuum cleaner', caption) == ''

    # D2: English and Chinese bare action queries get the multilingual subject head prepended
    q_texts = [d['query'] for d in enriched['query_details']]
    assert 'electric nail care speed control button' in q_texts
    assert '电动美甲器 速度调节按钮' in q_texts


def test_item_c_early_subject_identification_from_screen_text_and_cached_query_plan(tmp_path):
    # 1. Screen text alone identifies a catalog product in identify_subject
    manifest_screen = {'caption': '댓글에 링크 남겨주세요', 'screen_text': [{'text': '휴대용 손난로 추천'}]}
    assert identify_subject(manifest_screen, '겨울에 정말 따뜻해요', '미확인') == '손난로'

    # 2. _resolve_rewrite_manifest links cached query plan before source_search_manifest_path exists
    caption = '책상 위 필수템 각도조절 북스탠드'
    speech = '공부할 때 목이 안 아파요'
    screen_text = ''
    value = {
        'policy': QUERY_PLAN_POLICY,
        'caption': caption,
        'speech': speech,
        'screen_text': screen_text,
        'reference_sha256': None,
    }
    import hashlib
    identity = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    plan_dir = tmp_path / 'source-query-plans'
    plan_dir.mkdir(parents=True, exist_ok=True)
    cached_plan = {
        'primary_subject': {'name': '각도조절 북스탠드', 'source': 'caption', 'quote': caption},
        'query_evidence': {'caption': caption, 'speech': speech, 'screen_text': screen_text},
    }
    (plan_dir / f'{identity}.json').write_text(
        json.dumps({'input_sha256': identity, 'policy': QUERY_PLAN_POLICY, 'plan': cached_plan}, ensure_ascii=False),
        encoding='utf-8',
    )
    studio = SimpleNamespace(settings=Settings(data_dir=tmp_path))
    state = {'shortcode': 'Abc123xyz', 'original_text': speech, 'title': '댓글에 남겨주세요'}
    resolved = _resolve_rewrite_manifest(studio, state, {'caption': caption})
    assert identify_subject(resolved, speech, '댓글에 남겨주세요') == '각도조절 북스탠드'


def test_product_action_cannot_use_unrelated_catalog_noun_or_poisoned_subject(tmp_path):
    caption = '헬로키티 핑크 손난로는 버튼을 누르면 조명도 켜져요'
    response = {'subject_kind': 'product',
        'primary_subject': {'name': '손난로', 'source': 'caption', 'quote': caption},
        'queries': [
            {'query': 'mirror', 'language': 'en', 'intent': 'subject',
             'source': 'caption', 'quote': 'not in caption'},
            *[{'query': query, 'language': 'en', 'intent': 'action',
               'source': 'caption', 'quote': caption}
              for query in ('button activated light', 'mirror button activated light',
                            'silver mirror button activated light')]],
        'tiktok_queries': []}
    result = enrich_plan(Settings(data_dir=tmp_path),
        product_query_plan(caption, [], [], {'speech': ''}, []), caption,
        {'speech': ''}, lambda *_: response)
    actions = [row['query'] for row in result['query_details'] if row.get('intent') == 'action']
    assert actions
    assert all('hand warmer' in query for query in actions)
    assert 'mirror button activated light' not in actions


def test_item_d_resume_assessment_recovers_unreviewed_edit_and_refresh_sources_technical_failure(tmp_path):
    # Case 1: Edit 2 exists (edit_id='edit-2'), reviewed_edit_id='edit-1', quality_review failed technically
    state_qr = {
        'id': 'work-test1',
        'run_id': 'run-1',
        'edit_id': 'edit-2',
        'sources': [],
        'daily_quality': {
            'enabled': True,
            'status': 'needs_attention',
            'pending': 'failed',
            'failed_job_kind': 'quality_review',
            'failed_job_id': 'job-qr-1',
            'reviewed_edit_id': 'edit-1',
            'error': 'RuntimeError: transient frame read error',
            'feedback': [{'kind': 'scene_gap', 'beat_id': 'beat-2', 'reason': 'old issue'}],
        },
    }
    assert resume_assessment(state_qr) is True
    assert state_qr['daily_quality'].get('pending') is None
    assert state_qr['daily_quality']['status'] == 'pending'
    assert state_qr['daily_quality']['resume_retry_count'] == 1
    assert 'failed_job_kind' not in state_qr['daily_quality']

    # Case 2: refresh_sources failed technically after edit_id='edit-1' was reviewed
    state_rs = {
        'id': 'work-test2',
        'run_id': 'run-1',
        'edit_id': 'edit-1',
        'sources': [],
        'daily_quality': {
            'enabled': True,
            'status': 'needs_attention',
            'pending': 'failed',
            'failed_job_kind': 'refresh_sources',
            'failed_job_id': 'job-rs-1',
            'reviewed_edit_id': 'edit-1',
            'error': 'RuntimeError: browser timeout',
            'feedback': [{'kind': 'scene_gap', 'beat_id': 'beat-2', 'reason': 'need scene'}],
        },
    }
    assert resume_assessment(state_rs) is True
    assert state_rs['daily_quality']['pending'] == 'recollect'
    assert state_rs['daily_quality']['status'] == 'repair'
    assert state_rs['daily_quality']['local_review_resume_count'] == 1

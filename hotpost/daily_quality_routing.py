"""Quality workflow scheduling; evidence validators remain in protected modules."""
import json


def advance_daily_quality(self,state,db,script,voice,edit):
    from .daily_quality import enabled
    quality=state.get('daily_quality',{})
    if not enabled(state):return False
    from .quality_progress import ensure, permit, hold, queue_method
    ensure(state)
    if state.get('automation',{}).get('paused_by_user'):return True
    pending=quality.get('pending');cycle=quality.get('repair_round',0)
    from .quality_progress import valid_cover_evidence
    from .quality_issue_scope import is_cover_scene_gap
    cover_gap=any(i.get('kind')=='cover' or is_cover_scene_gap(i)
                  for i in quality.get('feedback',[]))
    cover_ready=not cover_gap or valid_cover_evidence(state,quality.get('cover_repair_evidence') or {})
    if pending in {'scene_wait','reedit'} and state.get('edit_id') and not cover_ready:
        acquisition=state.get('source_acquisition') or {}
        if (acquisition.get('hold') or acquisition.get('waiting') or acquisition.get('receipt_wait')
                or state.get('editorial_content_hold') or quality.get('narration_context_hold')):
            return True
        # Obtain independently reviewed pixels before requesting any render permit.
        pending='recollect'
    key=f"quality:{state['run_id']}:{cycle}"
    payload={'script_id':state['script_id'],'voice_id':state.get('voice_id'),'edit_id':state.get('edit_id')}
    if pending=='rewrite':
        method=queue_method(state,db,'rewrite')
        if not method:return True
        quality['repair_context'] = {'reason':'quality_feedback_rewrite',
            'parent_edit_id':state.get('edit_id'), 'feedback':quality.get('feedback', [])}
        state['rewrite_instructions']='완성본 검토에서 확인한 사실·의미 연결·전체 음성 일관성 문제를 보완하고 공통 규칙으로 대본 3안을 다시 생성. 소스 부족 때문에 대본을 바꾸지 말 것: '+json.dumps(quality['feedback'],ensure_ascii=False)
        state['automation']['needs_top_pick']=True
        # Force fresh contract-bound proposals instead of merely ranking the old candidates.
        payload={'quality_rewrite':True,'generation_key':key,'quality_method':method}
        stage='rewrite';quality['pending']='rewriting'
    elif pending in {'rewriting','recollecting','reediting','exhausted','failed','scene_wait'}:return True
    elif pending=='recollect':
        from .scene_requirements import coverage_current, required_scenes
        if required_scenes(state) and coverage_current(state) and cover_ready:
            quality['pending']='reedit'
            return self.advance_daily_quality(state,db,script,voice,edit)
        feedback_items=(quality.get('feedback')
            or ((quality.get('preparation_failures') or [{}])[-1].get('failure_reason') or []))
        brief=' '.join(i['search_query'] for i in feedback_items if isinstance(i,dict) and i.get('search_query'))
        brief=brief or state.get('product') or state['title']
        stage='refresh_sources';payload={'request':brief,'daily_quality_repair':True}
        key+=':collection:'+str(quality.get('collection_attempt',0))
        if quality.get('local_review_resume_count'):
            key+=':resume:'+str(quality['local_review_resume_count'])
        if db is not None:
            previous=db.execute('SELECT id,status FROM jobs WHERE key=?',
                (key+':'+stage+':'+str(state.get('edit_id')),)).fetchone()
            if previous and previous['status'] in {'done','failed','superseded','cancelled'}:
                quality['collection_queue_hold']={'job_id':previous['id'],
                    'job_status':previous['status'], 'request':brief,
                    'reason':'완료한 수집 범위의 재등록 대신 현재 로컬 근거·미소비 범위 평가 필요'}
                hold(state,'완료한 품질 수집 큐 보존 · 실제 새 구간·미소비 검색 근거 대기')
                return True
        quality['pending']='recollecting'
    elif pending=='reedit':
        from .scene_requirements import repair_render_signature,REPAIR_SIGNATURE_POLICY
        signature=repair_render_signature(state)
        quality['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
        coverage=quality.get('scene_requirements',{})
        from .scene_requirements import coverage_current
        from .mask_application_evidence import approved_material
        mask_only=bool(approved_material(state))
        if any(i['kind'] in {'scene_gap','repetition','watermark'} for i in quality.get('feedback',[])) and (
                not coverage_current(state)) and not mask_only:
            quality['pending']='recollect'
            return self.advance_daily_quality(state,db,script,voice,edit)
        method=queue_method(state,db,'reedit')
        if not method:return True
        from .source_quality import editing_ready
        stage='quality_reedit';payload.update(source_ids=[s['id'] for s in state['sources'] if editing_ready(s)])
        # New approved scenes are new edit inputs even when the old draft and
        # repair cycle are unchanged. Do not reuse an already finished/paused
        # queue item after local source recovery.
        key+=':method:'+method['key'][:24]
        payload['repair_input_signature']=signature
        payload['repair_signature_policy']=REPAIR_SIGNATURE_POLICY
        payload['quality_method']=method
        if mask_only:payload['mask_application_only']=True
        quality['pending']='reediting'
    elif edit and voice and script and voice['script_id']==script['id'] and edit['script_id']==script['id'] and edit['voice_id']==voice['id']:
        if quality.get('reviewed_edit_id')==edit['id'] and quality.get('status')=='passed':return False
        stage='quality_review'
        if int(quality.get('resume_retry_count',0) or 0)>0:
            key+=':retry:'+str(int(quality['resume_retry_count']))
    else:return False
    queue_key=key+':'+stage+':'+str(state.get('edit_id'))
    if stage=='quality_reedit' and db is not None:
        previous=db.execute('SELECT id,status FROM jobs WHERE key=?',(queue_key,)).fetchone()
        if previous and previous['status'] in {'done','failed','superseded','cancelled'}:
            quality.update(pending='scene_wait',status='needs_attention',repair_queue_hold={
                'job_id':previous['id'],'job_status':previous['status'],
                'repair_input_signature':signature,'repair_signature_policy':REPAIR_SIGNATURE_POLICY})
            state.update(status='source_wait',message='같은 편집 자료·계약의 완료 또는 실패 작업 재실행 보류')
            return True
    identity=self.store.enqueue(db,state['id'],stage,payload,queue_key)
    if stage in {'quality_reedit','rewrite'}:
        permit(state,'rewrite' if stage=='rewrite' else 'reedit',reserve=True,job_id=identity)
    state['automation']['stage']=stage
    state.update(status='quality_review' if stage=='quality_review' else 'editing' if stage=='quality_reedit' else 'source_wait' if stage=='refresh_sources' else 'rewriting',
        message={'quality_review':'완성 영상 실제 프레임·썸네일·반복감 검토','refresh_sources':'품질 보완용 장면 추가 수집',
                 'quality_reedit':'검토 피드백과 추가 소스로 새 편집본 제작','rewrite':'사실 문제 보완 · 대본 3안 다시 생성'}[stage],progress=0,error='')
    return True

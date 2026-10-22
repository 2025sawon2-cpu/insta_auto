"""Read-only, user-facing activity; never infer execution from a past action."""
TOOL_LABELS={
    'inspect_artifact':'제작 자료 확인 중','inspect_code':'멈춘 원인 확인 중',
    'recall':'이전 진단 기록 확인 중','recover_preparation':'자료 준비 경로 복구 중',
    'inspect_repair':'복구 검증 결과 확인 중',
    'advance':'다음 단계 준비 중','collect_sources':'소스 영상 찾는 중',
    'repair_scenes':'장면 보완 중','quality_review':'완성 영상 검수 중',
    'retry':'작업 다시 연결 중','retry_repaired':'복구한 작업 재개 중',
    'propose_patch':'복구 방법 준비 중','test_patch':'복구 방법 검증 중',
    'review_patch':'복구 방법 재검토 중','park_for_repair':'복구 준비 중',
    'apply_patch':'검증한 복구 적용 중'}

def project(owner, *, model_state=None, executing=None, healthy=True):
    def result(phase,label,detail,live=False):
        return {'phase':phase,'label':label,'detail':detail,'live':live}
    if not healthy:return result('offline','연결 확인 중','마지막으로 확인한 제작 상태를 보관하고 있어요')
    if owner.get('status')=='completed':return result('completed','영상 제작 완료','검수를 마쳤어요 · 완성 영상을 확인하세요')
    if owner.get('status') in {'dormant','user_command'}:return result('paused','진행을 잠시 멈췄어요','현재 자료와 작업 결과는 보관돼 있어요')
    if owner.get('no_progress_hold'):
        return result('held','원인 해결 후 이어 제작 대기','문제와 다음 해결 행동을 기록했어요 · 현재 영상은 아직 미완료예요')
    if owner.get('status')=='waiting_turn':
        return result('waiting','앞 영상 완료 대기','앞 영상의 최종 검수가 끝나면 제작을 시작해요')
    if owner.get('runtime_error') or owner.get('blocked_observation'):
        return result('waiting','실행 오류 자동 복구 중','오류를 기록하고 복구 경로를 다시 연결하고 있어요')
    if executing:return result('working',TOOL_LABELS.get(executing,'제작 작업 진행 중'),'담당 AI가 이 영상의 다음 단계를 진행하고 있어요',True)
    if model_state=='running':return result('thinking','다음 작업 판단 중','제작 결과를 읽고 이어갈 방법을 검토하고 있어요',True)
    if model_state=='queued':return result('waiting','AI 응답 순서 대기','연결을 유지하며 실행 순서를 기다리고 있어요')
    if owner.get('status')=='recovering':return result('waiting','자동 복구 진행 준비','실패 원인을 기록하고 다른 해결 방법을 검토하고 있어요')
    if owner.get('status')=='attention':return result('waiting','복구 검토 대기','이전 시도의 결과를 보존하고 다음 판단을 기다려요')
    if owner.get('status')=='waiting':return result('waiting','서비스 연결 대기','서비스가 준비되면 이어서 진행해요')
    return result('watching','제작 흐름 확인 중','담당 AI가 작업 결과를 확인하고 있어요')

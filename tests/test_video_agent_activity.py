from hotpost.video_agent_activity import project

def test_past_action_is_not_live():
    assert not project({'status':'active','last_action':'test_patch'})['live']

def test_model_wait_and_actual_execution_are_different():
    owner={'status':'active'}
    assert project(owner,model_state='queued')['phase']=='waiting'
    assert project(owner,model_state='running')['live']
    assert project(owner,executing='test_patch')['label']=='복구 방법 검증 중'

def test_blocked_or_disconnected_never_pretends_execution():
    assert not project({'status':'attention','blocked_observation':'same'},model_state='running')['live']
    assert not project({'status':'active'},executing='test_patch',healthy=False)['live']

def test_paused_and_complete_are_static():
    for status in ('completed','dormant','user_command'):
        assert not project({'status':status},executing='advance')['live']

"""Prepare and stage evidence-bound clause scenes inside normal approved ranges."""
import argparse,copy,hashlib,json,re,subprocess,time
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_quality import editing_ready,sha256_file
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve()

def rock_specs():
    a='source-13b01d3459ca499e';b='source-5e8cf52c4ab443a5';c='source-174918249db74c3c'
    stretch='focused-DeWFM7RyO0t-inverted-stretch';dry='focused-DeWFM7RyO0t-drying-slow-062'
    return [
        (stretch,0,'context','뒤집힌 프레임을 짧게 보여주는 도입; 뒤에서 다른 미사용 시간으로 기능을 설명함'),
        (b,4.3,'context','같은 곡면 의자에 쿠션을 놓는 장면'),
        (a,0,'direct','프레임을 세워 놓은 테이블 형태가 보이는 실제 구간'),
        (b,5.04,'context','작업 공간에 놓인 의자로 앉는 과정의 연속 구간'),
        (b,5.9133333333,'context','의자에 앉는 모습; 새 대본의 동료 사연은 연출임'),
        (b,6.9533333333,'context','같은 의자에 기대어 앉는 연속 구간'),
        (a,8.6,'direct','곡면 의자의 쿠션을 펼쳐 놓는 모습; 편안함 효과를 따로 입증하지 않음'),
        (a,10.733333,'direct','쿠션 의자에 앉아 쉬는 실제 사용 장면'),
        (a,.96,'direct','세워진 곡면 프레임의 테이블 상태가 이어지는 구간'),
        (a,1.74,'direct','테이블 설명 전체에 상판과 세운 프레임이 유지되는 좁은 구간'),
        (stretch,.45,'context','뒤집힌 곡면 프레임의 스트레칭 자세; 특정 신체 효과는 주장하지 않음'),
        (dry,0,'direct','뒤집힌 프레임 살대에 천을 걸어 둔 건조대 활용'),
        (dry,1.06,'direct','건조대 설명이 끝날 때까지 천을 걸어 둔 같은 기능 상태를 유지'),
        (a,11.413333,'context','의자에 기대어 쉬는 연속 구간으로 공간 활용을 연결'),
        (a,12.273333,'direct','같은 휴식 구간의 다음 시간; 앞부분으로 되감지 않음'),
        (dry,1.8,'direct','건조대 시연의 남은 미사용 원본 시간; 앞 구간 재사용 없음'),
        (c,18.3,'context','앞서 쓰지 않은 식물과 유리문 주변의 다른 휴식 공간'),
        (c,19.4133333333,'context','다른 공간의 의자 사용 모습을 연속해서 보여줌'),
        (c,20.3566666666,'context','같은 새로운 사용 공간에서 이어지는 댓글 요청'),
        (b,2.7,'context','앞서 쓰지 않은 프레임을 기울이는 변환 모습으로 제품을 마무리; 발화에는 변환 방향 주장이 없음'),
    ]

def cat_specs():
    wide='focused-DeWWtERKroR-room-wide';body='focused-DeWWtERKroR-body-play'
    down='focused-DeWWtERKroR-neck-climbing';white='source-3d15f8a0e7bd4f69'
    blue='source-5fab359c02a34f2d';home='source-12e10797fa184d94'
    return [
        (wide,1.5,'context','흰 공룡 캣타워와 거실을 연속해 보여주는 도입; 실제 사연의 증거가 아님'),
        (wide,2.7,'context','동일 거실 전경의 다음 미사용 시간으로 비교 상황을 연결'),
        (wide,3.7133333333,'context','거실 속 캣타워의 전체 형태를 이어서 보여줌'),
        (body,0,'direct','다른 생활 공간의 공룡 캣타워 몸통 위 고양이 모습'),
        (body,1.26,'context','제품 위에 놓인 고양이의 가까운 구도를 연속해 보여줌'),
        (body,2.0933333333,'context','제품 형태와 고양이가 공간의 포인트가 되는 모습'),
        (down,4.4,'context','파란 공룡 목에서 내려오는 실제 동작으로 위아래 사용을 연결'),
        (white,37.1,'direct','흰 공룡의 목에 앞발을 붙이고 위로 오르는 고양이'),
        (white,18.55,'context','몸통의 섬유 표면과 둥근 구멍 부위를 가까이 보여줌'),
        (white,19.79,'context','몸통에 앞발을 대는 고양이와 실제 기능 부위; 적극적인 긁기 동작으로 단정하지 않음'),
        (blue,36.266667,'context','다른 색상 두 캣타워가 놓인 거실 전체 모습으로 공간 배치를 마무리'),
        (blue,37.406667,'context','고양이가 다른 공룡 사이를 이용하는 연속 구간'),
        (home,32.033333,'context','앞서 쓰지 않은 목과 장난감 주변을 이용하는 다른 단계'),
        (home,32.5466663333,'context','고양이가 목 주변으로 앞발을 뻗는 다음 미사용 시간으로 댓글 요청을 마무리'),
    ]

def mat_specs():
    gray='local-recovery-14-7e5cf4ef';edge='focused-DeWWWOeDhGk-edge-insert'
    water='source-75640d1dd13f4a5b';wipe='focused-DeWWWOeDhGk-actual-wiping'
    cushion='focused-mat-cushion'
    return [
        (gray,13.4666665,'context','실제 바닥 매트와 하부장 앞 가장자리로 제품 궁금증을 시작'),
        (gray,13.8466665,'context','매트 가장자리를 이어서 보여주는 다음 미사용 구간'),
        (gray,0,'context','일반 매트의 끝과 하부장 사이에 열린 경계를 가리키는 실제 장면으로 주방 상황을 연결'),
        (gray,.7133333333,'context','하부장 밑 열린 경계를 가리킴; 깨가 실제로 굴러가는 영상은 아님'),
        (gray,1.9333333333,'context','같은 열린 경계의 다음 구간으로 청소 번거로움을 연결'),
        (gray,3.0133333333,'context','일반 매트 끝이 가리지 못하는 경계를 연속해서 보여줌'),
        (edge,0,'direct','손으로 L자 끝의 꺾인 형태를 보여주는 실제 장면'),
        (edge,1.7,'context','손으로 끝을 하부장 앞 경계에 맞춰 누르는 실제 설치 구간; 내부 라이너가 아님'),
        (edge,2.58,'context','L자 끝을 맞춰 놓은 설치 상태; 카메라가 빈 바닥으로 이동하기 전에 끝냄'),
        (water,25,'context','실제로 매트 표면에 묻은 액체; 액체를 특정 소스 종류로 단정하지 않음'),
        (wipe,0,'direct','액체가 묻은 매트를 천으로 닦는 실제 동작'),
        (cushion,3.8533333333,'context','바닥 매트 위에서 서 있는 생활 상황; 독립적인 편안함 성능 시험이 아님'),
        (cushion,0,'context','매트 표면과 들어 올린 두꺼운 모서리로 구조를 보여줌; 정확한 두께나 의학적 효과를 주장하지 않음'),
        (cushion,4.9666666666,'context','서 있는 사용 상황의 다음 미사용 시간; 발 편안함은 원문 제품 정보'),
        (gray,26.933333,'context','청소 도구와 실제 바닥 매트의 새로운 사용 구간으로 마무리'),
        (gray,27.3866663333,'context','설치된 매트와 청소 장면을 이어서 보여주는 댓글 요청'),
    ]

def print_specs():
    gray='source-d329cf540eb44599';other='source-e7f081748e7f4f3d'
    large='focused-DeVKnW6z_Rl-large-print-context';liquid='focused-DeVKnW6z_Rl-front-liquid-application'
    return [
        (gray,0,'context','옷의 프린팅 부위를 가까이 보여주는 도입; 실제 계절이나 개인 사연의 증거가 아님'),
        (gray,.96,'context','같은 옷의 다음 미사용 시간으로 옷을 아끼는 상황을 연결'),
        (gray,1.7666666667,'context','옷과 프린팅 처리 장면을 이어 보여줌; 가격을 입증하는 화면이 아님'),
        (other,0,'context','회색 옷 앞면에 크게 박힌 글자와 그림을 보여줌'),
        (other,.9266666667,'context','큰 프린팅을 연속해 보여주며 생활 상황의 갈등을 연결'),
        (other,1.6266666667,'context','같은 큰 프린팅의 다음 시간; 아직 프린팅이 보이는 상태'),
        (gray,6.533333,'context','프린팅 처리 부위의 다른 미사용 시간; 세탁소 사연은 연출'),
        (gray,7.1266663333,'context','손으로 처리하는 옷 부위가 이어짐; 실제 직원의 추천 증거가 아님'),
        (liquid,0,'context','프린팅 부위에 액체를 적용하는 모습으로 제거제 소개를 연결'),
        (liquid,1.0466666667,'direct','검은 옷의 프린팅 부위에 액체를 적용하는 연속 구간'),
        (other,27.5333335,'direct','다른 옷의 프린팅 부위를 손으로 처리하는 실제 장면'),
        (other,28.5733335,'direct','프린팅 처리 동작을 다음 미사용 시간으로 이어서 보여줌'),
        (large,1,'context','큰 프린팅을 제거한 검은 옷의 표면으로 결과 단계 시작'),
        (large,1.62,'context','프린팅이 사라진 옷의 다음 시간; 완벽한 무손상 효과를 따로 주장하지 않음'),
        (other,55.066667,'context','다른 회색 옷의 마지막 처리 단계; 큰 글자 조각을 제거한 상태'),
        (other,56.0733336667,'context','동일 결과 단계의 다음 미사용 시간으로 댓글 요청 시작'),
        (other,56.4000003334,'context','같은 미사용 결과 구간으로 댓글 요청 끝; 원본 시간 반복 없음'),
    ]

def taco_specs():
    manual='focused-DeWPBQyzpfR-manual-flat-pan-slow-065'
    rotating='source-ea72bf7997ef45e7';home='source-e1a92b3e45564c27'
    demo='source-f6f0fe76824a45cf';ingredients='focused-DeWPBQyzpfR-ingredients-stable-caption'
    serving='focused-DeWPBQyzpfR-serve-one-ball'
    return [
        (manual,0,'context','도입의 손이 바쁜 상황을 사각 수동 팬으로 비교; 소개할 원형 자동 기기의 증거로 쓰지 않음'),
        (manual,1.5566666667,'context','같은 수동 조리 구간의 다음 시간으로 불편 상황을 연결'),
        (rotating,0,'direct','중앙 회전 구조가 있는 원형 자동 기기와 익는 알을 보여줌'),
        (rotating,1.2733333333,'direct','손으로 돌리지 않고 원형 기기에서 알이 움직이는 연속 구간'),
        (rotating,2.5533333333,'direct','원형 틀에서 알이 익는 연속 구간; 아직 접시에 담은 장면은 넣지 않음'),
        (ingredients,0,'direct','원형 자동 기기에 반죽 재료를 넣는 실제 장면'),
        (ingredients,.6033333333,'context','투입 뒤 스위치 조작으로 이어지는 같은 구간'),
        (home,8.2416665,'direct','원형 자동 기기에서 익은 알이 움직이는 새로운 조리 구간'),
        (home,9.2216665,'direct','익은 알에서 접시에 담는 단계로 이어지는 다음 시간'),
        (serving,0,'context','완성 알을 집어 접시로 옮기는 실제 장면'),
        (demo,10.966667,'context','완성된 알과 소스 마무리 단계; 앉아 기다리는 사연은 연출'),
        (demo,12.186667,'context','완성 알을 보여주는 다음 시간; 생반죽 상태로 되돌아가지 않음'),
        (demo,12.766667,'context','완성 알이 있는 원형 기기의 다음 미사용 구간'),
        (demo,13.386667,'context','같은 완성 단계로 마지막 문장을 이어줌'),
        (home,10.52,'context','다른 원본의 완성 알과 접시 단계로 댓글 요청 시작'),
        (home,11.0933333333,'context','같은 완성 단계의 미사용 시간으로 마무리; 재료 투입 장면 재사용 없음'),
    ]

def prepare(studio,state):
    code=state['shortcode'];get_specs={'DeWFM7RyO0t':rock_specs,'DeWWtERKroR':cat_specs,'DeWWWOeDhGk':mat_specs,'DeVKnW6z_Rl':print_specs,'DeWPBQyzpfR':taco_specs}[code]
    edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
    plan=json.loads(Path(edit['plan_path']).read_text('utf-8'));specs=get_specs()
    assert len(specs)==len(plan['beats'])
    sources={s['id']:s for s in state['sources']};rules=[]
    folder=ROOT/code/('manual-binding-'+edit['id']);folder.mkdir(exist_ok=True)
    sheets=[]
    for group in range((len(specs)+3)//4):
        sheet=Image.new('RGB',(810,2016),'#222');draw=ImageDraw.Draw(sheet)
        for row in range(4):
            index=group*4+row
            if index>=len(specs):break
            beat=plan['beats'][index];sid,start,relation,reason=specs[index];source=sources[sid]
            assert editing_ready(source) and sha256_file(Path(source['path']))==source['sha256']
            end=start+beat['end']-beat['start']
            assert any(w['source_start']<=start<end<=w['source_end']+.001 for w in source['reviewed_intervals']), (beat['id'],start,end)
            frames=[]
            for col,fraction in enumerate((.05,.5,.95)):
                ts=start+(end-start)*fraction;target=folder/f'{index+1:02}-{col}.jpg'
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(ts),'-i',source['path'],'-frames:v','1',
                    '-vf','scale=270:480:force_original_aspect_ratio=increase,crop=270:480',str(target)],check=True,capture_output=True,timeout=30)
                with Image.open(target) as im:sheet.paste(im,(col*270,row*504+24))
                draw.text((col*270+3,row*504+3),f'{beat["id"]} {ts:.3f}s',fill='white')
                frames.append(str(target))
            rules.append({'reviewed':False,'pattern':'^'+re.escape(beat['text'])+'$','source_sha256':source['sha256'],
                'source_id':sid,'start':start,'end':end,'relation':relation,'reason':reason,'evidence_frames':frames,
                'evidence_sha256s':[sha256_file(Path(f)) for f in frames],'beat_id':beat['id']})
        target=folder/f'contact-{group+1}.jpg';sheet.save(target,quality=94);sheets.append(str(target))
    value={'code':code,'parent_edit_id':edit['id'],'script_id':state['script_id'],'voice_id':state['voice_id'],
        'script_text':plan['script_text'],'rules':rules,'sheets':sheets,'actual_visual_review_pending':True}
    _atomic_json(folder/'binding.json',value)
    print(json.dumps({'binding':str(folder/'binding.json'),'sheets':sheets},ensure_ascii=False),flush=True)

def stage(studio,state,path):
    receipt=json.loads(path.read_text('utf-8'))
    assert receipt['code']==state['shortcode'] and receipt.get('actual_visual_review_pending') is False
    rules=receipt['rules'];assert all(r['reviewed'] is True for r in rules)
    digest=sha256_file(path)
    def update(s,db):
        if s.get('automation',{}).get('paused_by_user') or s.get('daily_quality',{}).get('pending') in {'failed','exhausted'}:
            raise ValueError('사용자 중지·과거 품질 중단 유지: 정상 제작실의 새 근거 평가와 명시 재개가 먼저 필요합니다.')
        assert s['script_id']==receipt['script_id'] and s['voice_id']==receipt['voice_id'] and s['edit_id']==receipt['parent_edit_id']
        assert not db.execute("select 1 from jobs where task_id=? and status='running'",(s['id'],)).fetchone(), 'Wait for the existing live job'
        sources={v['id']:v for v in s['sources']}
        for rule in rules:
            source=sources[rule['source_id']];assert source['sha256']==rule['source_sha256'] and editing_ready(source)
            assert all(sha256_file(Path(f))==h for f,h in zip(rule['evidence_frames'],rule['evidence_sha256s']))
        for row in db.execute("select id,checkpoint from jobs where task_id=? and status='queued'",(s['id'],)).fetchall():
            cp=json.loads(row['checkpoint']);cp.update(superseded_by_manual_binding=digest)
            db.execute("update jobs set status='paused',checkpoint=? where id=?",(json.dumps(cp),row['id']))
        if s.get('reviewed_scene_rules'):s.setdefault('reviewed_scene_rule_history',[]).append(copy.deepcopy(s['reviewed_scene_rules']))
        s['reviewed_scene_rules']=rules;s['automation']['active']=True
        q=s['daily_quality'];q.update(status='repair',pending='reediting')
        payload={'script_id':s['script_id'],'voice_id':s['voice_id'],'edit_id':s['edit_id'],
            'source_ids':[v['id'] for v in s['sources'] if editing_ready(v)]}
        job=studio.store.enqueue(db,s['id'],'quality_reedit',payload,'manual-binding:'+digest)
        s.update(status='editing',message='직접 확인한 대사별 구간으로 새 편집본 제작',error='')
        studio.store.event(db,s['id'],'actual_source_scene_binding',{'receipt':str(path),'sha256':digest,'job':job,'script_and_voice_unchanged':True})
    studio.store.change(state['id'],update)
    print('Reviewed binding queued; final render QA remains required',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--code',required=True);p.add_argument('--stage',type=Path);a=p.parse_args()
    studio=Studio(load_settings(),workers=False);state=next(t for t in studio.store.list() if t['shortcode']==a.code)
    if a.stage:stage(studio,state,a.stage)
    else:prepare(studio,state)

if __name__=='__main__':main()

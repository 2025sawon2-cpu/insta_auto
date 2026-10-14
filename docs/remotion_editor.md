# 제작실 Remotion 편집

제작실의 ‘편집’ 탭에서 자막·직선/곡선 화살표·이모지를 추가한다.
영상 위에서 위치를 끌고, 모서리 손잡이로 크기와 ↻ 손잡이로 회전을 조절한다.
오른쪽 입력과 슬라이더로도 같은 값을 바꿀 수 있다. 타임라인 양 끝 손잡이 또는
시작·끝 시간 입력으로 표시 구간을 바꾼다. 화면 글자만 바뀌며 읽는 대사는 내 대본에서 바꾼다.

‘수정 내용으로 영상 만들기’는 편집을 저장하고 새 MP4 버전을 만든다. 완성 영상 탭에서
새 버전을 재생하고 다운로드한다. 기존 완성 영상·대본·음성을 덮어쓰지 않는다.
‘추가 도구 → 편집 내용만 저장’은 제작 없이 저장한다. ‘이번 수정 취소’는 이 기기의
미저장 입력만 취소한다. 서버에 저장된 수정사항은 기존 제작실의 수정 취소를 사용한다.

## 실행 준비

이 PC에는 설치와 번들 생성을 완료했다. 다른 PC에서는 Node와 pnpm을 준비한 뒤:

```powershell
cd remotion
pnpm install --frozen-lockfile
node build.mjs
```

정적 대시보드는 계속 일반 HTML/CSS/JS로 제공된다. 편집 영역만 독립 React/Remotion
번들을 사용한다. 생성된 `web/remotion-editor.js`와 `remotion/node_modules`는 Git에서 제외한다.
서버에 Node가 없거나 설치/번들이 누락되면 기존 자막 편집기를 유지한다. `HOTPOST_REMOTION_NODE`로
Node 실행 파일을 지정할 수 있다. Windows에서는 Codex 번들 Node도 자동 탐색한다.
FFmpeg/ffprobe는 기존 제작 파이프라인과 동일하게 PATH에 있어야 한다.

## 저장·렌더링 경계

- `remotion/composition.jsx`: Player와 MP4 렌더러가 공유하는 영상·꾸미기 컴포지션.
- `remotion/model.mjs`: 30fps 시간 경계, 초기 자막, 타임라인 겹침 처리.
- `remotion/editor.jsx`: 편집 UI와 기기 임시 입력. API 키/외부 서비스 없이 동작한다.
- `hotpost/remotion_editor.py`: 입력 검증, 별도 Node 프로세스, MP4 규격·길이·음성 확인.
- `POST /api/studio/{id}/save-overlays`, `export-overlays`: 현재 편집 ID와 피드백 리비전을 확인한다.
- `overlay_document` 버전 1: 자막/화살표/이모지 최대 120개. 표시 시간(초), 위치(1080×1920 좌표),
  크기, 회전, 색상, 자막 배경, 화살표 모양을 저장한다. 임의 URL·HTML·파일 경로를 받지 않는다.
- 기존 깨끗한 미리보기의 영상·음성을 사용한다. 자막이 구워진 MP4 위에 다시 자막을 덧씌우지 않는다.
- 내보내기 실패나 서버 재시작 후 기존 완성본은 보존되고, 같은 작업의 렌더링 영수증과 잠금을 재사용한다.
- 새 대본/음성/소스 수정과 기존 영상 꾸미기를 함께 적용하지 않는다. 서버의 충돌 검증으로 입력을 보존한다.
- 현재 자동 제작 프로토콜 2 작업에 연결한다. 이전 수동 제작 프로토콜의 화면은 보존한다.

## 확인

```powershell
node --test remotion/model.test.mjs
.venv/Scripts/python.exe -m pytest -q tests/test_remotion_editor.py tests/test_studio_workflow.py
```

`tests/remotion_preview_server.py`는 `data/remotion-qa`의 별도 DB와 3초 합성 영상을 사용해
localhost:8792에서 실제 UI/API/Remotion 출력을 검증한다. 운영 제작실 큐에 가상 작업을 넣지 않는다.
테스트 서버를 종료하면 이 검증용 URL도 종료된다.

2026-10-09 검증: 브라우저 요소 추가·위치 드래그·표시 시간·새로고침 입력 복원과 실제
1080×1920/30fps/오디오 MP4 새 버전 생성·완성 탭 연결을 확인했다. 실제 수집 영상으로 하는
사용자 검토는 오전 7시 수집 후 진행한다. Remotion 공식 참고:
[Player](https://www.remotion.dev/docs/player), [renderMedia](https://www.remotion.dev/docs/renderer/render-media).

운영 반영 시 실행 중인 대시보드 서버를 재시작해야 Python 변경이 로드된다.
2026-10-12 썸네일 용량 수정은 사용자가 승인한 재시작 범위에서 운영 서버에 적용했다.
수동 시작은 프로젝트의 `start-dashboard.ps1`을 사용한다.
## 첫 프레임 썸네일

편집 탭의 `썸네일 · 첫 프레임`은 영상 꾸미기와 별도 문서·임시 초안을 사용한다.
`thumbnail_document`는 version, frame, elements만 받는다. frame=-1은 현재 배경,
0 이상은 기존 편집 영상에서 선택한 배경 프레임이다. 모든 문구는 0부터 1/30초까지
한 프레임에만 표시한다. 기존 cover_spec의 문구·위치·색상을 초기값으로 가져온다.
도현 폰트와 OFL은 web/assets/fonts에 보존하며 미리보기와 이미지 렌더에 같은 파일을 쓴다.

`save-thumbnail`은 제작하지 않고 저장만 한다. `export-thumbnail`은 기존 완성본을 남기고
thumbnail_only revision을 만든다. 대본·TTS·소스를 다시 수집하거나 선택하지 않는다.
Remotion renderStill로 PNG를 만든 뒤 썸네일 한 프레임만 H.264로 압축한다. 본문과
음성은 기존 압축 패킷을 복사한다. `hotpost/thumbnail_mp4.py`가 기존 첫 프레임을
디코더 참조로 보존하고 표시 타이밍에서 숨겨 본문의 P/B 프레임을 그대로 유지한다.
반복 수정도 최초 완성본을 기준으로 결합해 용량이 누적되지 않는다. 본문 프레임·타이밍,
음성 해시, 30fps·1080×1920, 프레임 수·길이와 용량 증가 상한을 검증한다.
원본 완성본과 이전 썸네일 버전은 보존한다.
신규 thumbnail_editor_supported capability가 없는 실행 중 서버에서는 미리보기·임시
편집만 제공하고 저장·반영 버튼은 잠근다. API 변경은 서버 업데이트 후 사용할 수 있다.

# Editing adapter

현재 실행 경계는 [WORKFLOW](WORKFLOW.md), 편집 품질은
[제품 매력 기준](editorial_montage_policy.md), 글꼴·표지는
[RULES](../hotpost/writing/RULES.md)를 따른다. 아래 production UI/Studio 연결과
2026-10-07 나눔고딕 스타일은 보존된 구현 설명이다. 신규 제작에서 제작실을
켜거나 현재 본문 십대·표지 도현을 이전 글꼴로 바꾸라는 지시가 아니다.
프로세스·버전 JSON 경계와 아래 음성/자막 시간축 원칙은 계속 적용한다.

화면 자막으로 대본을 자르기 전에는 [의미 단위 분할 원본](CAPTION_SEGMENTATION.md)을
읽는다. 제품·명사구와 시간 표현 등을 보호구로 검토하고, 원고·정책·실제 글꼴 배치·
분할별 이유를 결속한 검토를 Auto CapCut JSON 경계에 전달한다. 자동 제안의 폭 검사나
유한 분할 점수만으로 의미 검토를 완료하지 않는다. 신규 분석·수동 수정·재분할·렌더·
자막 내보내기에서 누락·금지 경계·변경된 검토는 거절하며 기존 파일은 보존한다.

`insta_auto` and `auto_capcut` remain separate processes even when their Git
repositories are later combined. `hotpost.editing_adapter.AutoCapcutAdapter`
writes a versioned request under `data/editing_jobs/<job_id>/` and invokes the
dedicated `auto_capcut` virtual environment without a shell.

The v1 request contains local source-video paths and optional semantic labels,
an optional spoken-text script, an optional voice asset, an audio profile,
optional narration tempo, and a draft name. Results are one of
`completed`, `blocked`, or `failed`. Missing voice returns the stable
`blocked / voice_required` state because the current editor uses narration
duration and word timestamps as its timeline clock.

`script_from_transcript` copies only `speech` segments into `words.txt`.
`screen_text` remains OCR evidence and is never silently converted into spoken
subtitles. All assets passed by the adapter must live under `data/`.
The legacy adapter rejects `source_quality=unknown` and detected text overlays by
default. The current production masking rule is scoped to original source-script
captions and source watermarks; it does not require blanket masking of product
labels or other incidental text. If a legacy rejection treats those as the same
kind of overlay, record the implementation mismatch and correct that path
separately rather than claiming the current output passed. A Windows compatibility
spike may opt into unclassified footage explicitly, but that override is not a
claim that the footage is clean or licensed.

`hotpost.ai_studio_adapter.AiStudioAdapter` prepares the existing job's whole-script request for Google AI Studio Arlo. The production agent uses the existing Chrome 사원2 session and `tools/ai_studio_browser.mjs` to submit once and save the matching rendered WAV/receipt. The same adapter validates/imports it. There is no local TTS service, API-key lookup or GPU lifecycle dependency. The browser-pending result is the agent's next action, not a user approval gate. See [the TTS source](TTS_TRUNCATION_RECOVERY.md) for commands and failure handling.

Integrated builds use the `clean_tts` audio profile and 1.0x tempo.
The latest sound-effects policy is recorded in auto_capcut's
`docs/shortform_house_style.md`, section 4: use only CapCut effects with recorded
popularity evidence and available real audio assets, at the opening, meaningful
product benefits, and emotional exclamations. Visual caption emphasis alone
does not enable audio effects. Do not treat legacy favorites as proof of
popularity or substitute synthesized tones. The current runtime still defaults
to narration only; `core/studio_sfx.py` now supports explicitly reviewed CapCut
assets with the same processed audio clips in the MP4 and editable draft.
Automatic catalog discovery and semantic selection for new scripts remain
to be implemented. Until those prerequisites are available, keep
narration, record why SFX was not applied, and continue production without an
approval hold. Old exports and caption-only revisions retain their recorded audio.
CapCut/TikTok commercial-use labels do not establish Instagram permission.
The tent Popular-SFX revision is saved as a review-only version with that
scope limitation; no external posting is performed.
The user's subsequent choice fixes the opening effect at 0 seconds to CapCut's
`팔로우 알림 “땡”` (`6998438183729891329`), once per video. New auto_capcut analyses
attach the verified bundled clip at 0 seconds automatically; existing saved timelines
and completed files are preserved. This explicit choice
overrides popularity-based opening selection; body effects retain their
reviewed timing and gain. `studio_sfx.opening_policy()` records the contract.
Preserve prior revisions; do not replace a missing bell with a different sound.
The legacy helper retains its 1.12x default. This avoids applying microphone denoise,
podcast color, vocal beautification, and +20dB gain to a clean generated WAV.

`hotpost.production.ProductionManager` persists the entire handoff, revision,
and resume state. The legacy `build_with_ai_studio` helper requires an explicit
approved script and no longer falls back to original speech. The browser TTS bridge and auto_capcut keep their separate execution boundaries.

Configuration can be overridden with `HOTPOST_AUTO_CAPCUT_ROOT`,
`HOTPOST_AUTO_CAPCUT_PYTHON`, and `HOTPOST_AUTO_CAPCUT_TIMEOUT`.
## 2026-10-07 자막·쉼 제작 합의

신규 제작실 편집의 자막은 auto_capcut `studio_typography.default_style()`에서
나눔고딕 ExtraBold(800) / 설정 크기 108 / 대본 문구 그대로를 적용하고 타임라인에 버전으로
보존한다. 문장이 길면 글자 축소나 요약 대신 실제 글꼴 폭을 기준으로 구절을 나눈다.
과거 완성본·스타일 없는 과거 타임라인은 이전 렌더링 계약을 유지한다.
과거 Pretendard 타임라인은 그대로 보존한다. 사용자는 4종 비교에서
나눔고딕 ExtraBold를 선택했다. 크기는 이전 90에서 20% 추가 확대한 108이며
자막 중심을 화면 상단에서 2/5 높이로 고정한다.
1080×1920에서 위치는 (540,768)이며 MP4와 CapCut 초안에 동일하게 적용한다.
설정값과 실제 글자 높이는 구분한다.

2026-10-10 새 타임라인의 `footage_selection_policy=diverse-sequential-v1`은 같은
검토 장면이 연속 자막에 쓰이면 미사용 시간 구간을 이어 재생한다. 렌더러도 beat의
선택 구간을 읽어 shot 시작점으로 되감지 않는다. 기존 필드 없는 타임라인은 이전
동작을 유지한다. 선택은 주제·장면 역할에 맞게 검토된 후보 안에서 수행하며 부족한 길이와
반복량을 기록한다. 실제 다양성 감사는 파생 클립 개수가 아니라 원본 SHA-256과
원본 시간 오프셋으로 합산한다. 수동 소스 재제작에서도 기존 음성 해시·대본·자막
시계를 보존하고 새 수정본만 추가한다. 영상 컷의 역할 이름이나 길이로 자막 문구와
표시 시각을 다시 만들지 않는다. 음성 또는 대본을 실제로 바꾼 경우에만 해당 버전의
단어 시각에 맞춰 자막을 갱신하고, 컷을 바꾼 뒤에도 최종 MP4에서 발화·자막의
문구와 순서를 여러 시점에서 직접 확인한다. 오디오·비디오 시작 시각의 일치만으로
문장별 싱크가 맞는다고 판정하지 않는다.

자막 `cues`와 시각 장면은 독립적으로 설계한다. 초기 analyze가 만든 cue별 `beats`를 그대로 고정하면 자막 조각마다 컷과 원본 시작점이 반복될 수 있다. 이 경우 기존 plan JSON에서 원고·voice·cues·자막 스타일·cue별 강조는 보존하고, 여러 `cue_ids`를 포함하는 장면/주제 단위 beat와 그 안의 native `visual_cuts`를 구성한다. 기존 `select-shots`/`freeze-selection`→`render` 경로를 사용하며 새 편집기를 만들지 않는다. beat 재설계 뒤 실제 caption binding과 최종 화면을 검증한다. 모든 영상을 한 beat로 만들거나 모든 자막마다 새 장면을 넣는 고정 규칙은 아니다.

2026-10-29 신규 독립 편집 기본은 사용자가 확정한 `short_pauses_breath_v1`이다. 문장 뒤 긴 쉼도 줄이고 기존 스펙트럼 들숨 제거를 적용한다. 원음은 불변이며 샘플 단위 cut-map으로 원래 ASR 단어 시각을 변환한다. 상세 기준은 [TTS 원본](TTS_TRUNCATION_RECOVERY.md)을 따른다. 기존 계획·완료본의 음성·시각은 자동 변경하지 않는다.

신규 화면 자막은 쉼표·마침표를 생략하고 물음표·느낌표를 유지한다.
선택 대본과 Google AI Studio TTS 입력의 문장부호는 그대로 보존한다.
같은 표시 규칙을 웹 MP4와 CapCut 텍스트에 적용하며 자막 시간은 바꾸지 않는다.

2026-10-12 실제 타코야키 출력의 장면 전환에서 블러가 한 프레임 누락되는 사례를 확인했다.
30fps 시점을 소수점 여섯 자리로 반올림해 `enable(t)`에 쓰면 실제 299/30 프레임이
9.966667보다 작아 블러가 빠졌다. 웹 렌더러는 블러 구간을 정수 프레임 번호로 적용하고,
개별 클립의 PTS를 0부터 정규화한다. 이전 캐시·완성본을 덮어쓰지 않고 별도 캐시 버전을
사용한다. 실제 FFmpeg 픽셀 비교와 새 완성본의 전환 전후 밀집 프레임을 함께 검증한다.

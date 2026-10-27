# 기존 Windows 완료본의 수동 복사 도구

현재 공통 저장 경로는 [PC별 저장 절차](LOCAL_VIDEO_STORAGE.md)를 따른다. 아래 도구는 이전 Windows 설치에서 설정한 날짜·파일명 계약을 유지하는 수동 호환 경로다. 신규 제작·독립 전달의 QA 또는 완료 판정을 대신하지 않는다.

저장 경로는 해당 PC의 Git 제외 로컬 설정에서 읽는다. 개인 드라이브 경로를 원격 저장소에 기록하지 않는다.
한국 시간 완료/수정일의 `YYYY-MM-DD` 폴더에 `YYYY-MM-DD_주제명.mp4`와
`YYYY-MM-DD_주제명_썸네일.png`를 복사한다. 기존 JPG/WebP 썸네일 확장자는 유지한다.
동명 및 수정본에는 `_02`부터 번호를 붙인다. 원본이나 기존 저장 파일은 덮어쓰지 않는다.

독립 `tools/sync_completed_exports.py`는 완료 상태와 검증된 export를 읽고,
같은 edit의 `post-preparations/{code}/active.json`이 있으면 그 버전의 영상/표지를 함께 선택한다.
적용 전 문구 초안이나 미완성 미리보기는 내보내지 않는다. 최초 설정 이전의 과거 완료본은 소급하지 않는다.
현재 제작실 실행기/DB/웹 서버를 수정하거나 실행하지 않는다.

영상 완료/썸네일 수정 작업에서 아래 명령으로 복사하고 실제 저장 결과를 확인한다.
2026-10-23 Windows 작업 `HotpostCompletedExport`의 1분 간격 자동 등록은 자동 승인 검토에서
차단됐으며 구체적 사유는 제공되지 않았다. 현재 예약 작업은 등록되지 않았고 상시 자동 복사는 비활성이다.
설정은 Git 제외 `data/local-services/completed-export.json`이다.
`completed-export-status.json`에 최근 확인/오류, `completed-export-journal.json`에 파일별
경로와 SHA256 및 중단 복구 예약을 기록한다. 복사 후 해시 및 원본/현재 버전 일치를 검증한다.
부분 파일을 검증한 뒤 완성 파일명으로 공개하며 실패 시 다음 확인 때 재시도한다.
Windows 로그인과 지정 드라이브 연결이 필요하며 연결되지 않으면 다른 위치로 대체 저장하지 않는다.

수동 확인(동시 실행은 파일 잠금으로 제외):

```powershell
.\.venv\Scripts\python.exe tools\sync_completed_exports.py --config data\local-services\completed-export.json
Get-Content data\local-services\completed-export-status.json
```

대상 검증: `.\.venv\Scripts\python.exe -m pytest -q tests/test_completed_exports.py`

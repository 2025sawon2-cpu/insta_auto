# WireGuard를 통한 Android 릴스 게시 경로

현재 PC → 기존 WireGuard VPN → 휴대폰 ADB → Instagram/Edits의 보이는 화면 순서다. 다른 PC나 기존 제작실 실행기를 거치지 않는다. 구현은 로컬 CLI이며 공개 Cloudflare 웹서버에 폰 제어/페어링/임의 셸 API를 추가하지 않았다. 단순 서버 시작이나 문서 읽기로 폰 작업이 재개되지 않는다.

## 현재 확인한 것과 남은 것

- Windows PC의 기존 WireGuard 경로 활성은 확인했다. PC/폰의 실제 IP와 포트는 각 PC의 Git 제외 로컬 설정과 기록에서 관리한다.
- `requirements-mobile.txt`의 uiautomator2 3.7.0/adbutils 2.12.0 설치, 포함된 Windows adb 실행 확인. 전역 PATH/방화벽/VPN 설정 변경 없음.
- 초기 기존 완성본 시험은 H.264 High/4.1, yuv420p, AAC였으며 16.633초/499프레임과 화면 크기를 유지했다. 이후 사용자 확정 규칙에 맞춰 현재 모바일 전달 경로도 공통 `encode_delivery`의 **H.264 Main@4.0/yuv420p/AAC-LC/+faststart**로 통합했다. 원래 최종본은 수정하지 않는다.
- 폰 IP와 VPN 경로 응답은 로컬에서 확인했으나 ADB 연결 포트와 최초 페어링이 아직 필요하다. 실제 폰 연결·앱 설치 상태·계정·앱 화면·영상 전송·릴스 게시 검증은 하지 않았다. `doctor`는 필수 연결 정보가 없으면 `needs_phone_details`로 표시한다.
- Edits의 영상 수신/Instagram 넘기기, 앱 버전별 본문/계정/표지 선택 화면은 실제 폰의 XML과 캡처로 확인해야 한다. 예상 화면이 맞지 않으면 멈추고 화면을 반환하며, 추측 좌표 매크로로 진행하지 않는다. 모의 테스트 통과를 실폰 업로드 성공으로 간주하지 않는다.

## 폰에서 필요한 정보

1. 휴대폰 WireGuard 내부 IP.
2. 개발자 옵션 → 무선 디버깅 화면의 **연결 포트**. 페어링 포트와 다를 수 있다.
3. 처음 연결할 때 페어링 포트와 폰에 표시되는 일회용 코드/승인. 코드는 PC의 프롬프트로 입력하고 저장하지 않는다.

WireGuard는 네트워크 경로이며 ADB를 켜거나 권한을 부여하지 않는다. Android 무선 디버깅의 Wi-Fi 요구·서비스 바인딩은 폰/OS에 따라 확인해야 한다. 모바일 데이터에 VPN만 켰다고 ADB 수신이 보장되는 것은 아니다. 이 구현은 `adb tcpip 5555`, 공개 포트 개방, 루팅, 잠금 해제, 인증 우회를 자동 수행하지 않는다. 휴대폰 버전/식별자는 연결 후 읽으므로 사전에 따로 적을 필요는 없다.

## 로컬 사용법

저장소 루트에서 실행한다. 설정은 Git에서 제외된 `data/.mobile-device.json`, 작업/캡처/영수증은 `data/mobile-reels/`에 남는다. 참고 설정은 `docs/mobile-device.example.json`이다.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-mobile.txt
.venv/Scripts/python.exe -X utf8 -m hotpost.mobile_reels_cli doctor
.venv/Scripts/python.exe -X utf8 -m hotpost.mobile_reels_cli configure --phone-ip PHONE_VPN_IP --adb-port CONNECT_PORT
.venv/Scripts/python.exe -X utf8 -m hotpost.mobile_reels_cli pair --pairing-port PAIR_PORT
.venv/Scripts/python.exe -X utf8 -m hotpost.mobile_reels_cli connect
```

페어링은 필요할 때 한 번만 한다. 설정/진단은 연결 또는 업로드가 아니다. 실제 제어는 매번 해당 IP로 가는 WireGuard 인터페이스, 지정 TCP 포트, ADB 인증과 휴대폰 식별자를 다시 확인한다. 폰의 무선 디버깅 연결 포트가 바뀌면 configure 후 connect로 갱신한다. VPN 대역이 다르면 configure의 `--vpn-network`를 실제 사설 대역으로 지정한다. VPN 설정/개인키는 읽거나 변경하지 않는다.

## 한 편 업로드 순서

1. 게시물 준비에서 본문/표지/계정을 정하고 `prepare SHORTCODE --account mr.salrim` 또는 `__ariddaum__`로 한 계정의 패키지를 만든다. 이것은 게시가 아니다. 현재 active 영상/표지/원음 규칙/선택 문구/초안 버전·본문/댓글/링크를 결속하며 파일을 복사해 고정한다. 영상에 광고 표시와 감탄사 없는 낭독 대본이 있어야 한다. Android 호환 영상은 별도로 변환하고 원래 편집본은 보존한다.
2. `transfer JOB`는 폰의 `/sdcard/Movies/Hotpost/JOB/`에 영상/표지를 보내고 실제 SHA256을 확인한다. MediaStore에 등록된 해당 영상의 content URI 하나만 사용한다. 갤러리 등록이 늦으면 다시 확인하며 임의의 최신 영상을 선택하지 않는다.
3. `app instagram`으로 앱을 열고 폰의 **본인 프로필**에서 업로드 계정을 확인한다. `inspect JOB`가 현재 화면의 요소/번호/해시 및 로컬 PNG/XML을 저장한다. `navigate JOB --node INDEX --screen-sha HASH`는 그 화면에서 관찰된 다음/릴스/프로필/표지 등의 요소만 누른다. 계정 전환도 실제 화면에서 수행한다.
4. `open JOB --via instagram`은 계정 프로필을 확인하고 전송 영상 URI로 Instagram 작성기를 연다. `--via edits`는 Edits로 영상을 보내 실제 앱의 편집/내보내기/Instagram 넘기기 화면을 진행하는 경로다. 이 앱이 SEND 인텐트를 지원하지 않거나 화면 구조가 다르면 캡처를 보고 연결 후 보정한다. 이미 연 작업을 자동으로 재시작하지 않는다.
5. `advance JOB`는 현재 관찰된 릴스/다음/Edits 넘기기 단계 하나만 진행하거나 본문을 입력한다. 불명확하면 현재 화면을 반환한다. `fill-caption JOB`는 Unicode setText로 한글·줄바꿈·이모지를 그대로 입력하고 실제 입력값을 대조한다.
6. 표지 편집 화면에서 폰에 전송한 cover.png를 실제 선택한다. 파일 선택기의 구현/레이아웃은 실폰 확인 후 맞춘다. 최종 작성 화면의 표지를 준비된 cover.png와 **시각 비교한 후** `review-cover JOB --screen-sha HASH --cover-sha COVER_SHA`로 기록한다. 이것은 이미지 자동 인식 성공 주장이 아니라 작업자의 검토 영수증이다.
7. `ready JOB`는 현재 계정 헤더·정확한 본문·릴스 작성 화면·공유 버튼·표지 검토를 확인하고 공유 직전 캡처와 패키지 SHA를 기록한다. 여기까지 실제 게시하지 않는다.
8. 사용자가 해당 계정/영상의 실제 게시를 지시한 뒤 `publish JOB --approved-package-sha PACKAGE_SHA`로 공유를 한 번 실행한다. 현재 문서 구현 요청만으로 실제 게시를 실행하지 않는다.
9. 공유 완료 메시지를 확인하면 submitted로 기록한다. 전송 이후 연결이 끊기거나 성공 안내가 불명확하면 unknown으로 영속 보류한다. `reconcile JOB`는 읽기 확인만 하고 다시 공유하지 않는다. 앱/프로필에서 실제 게시를 확인한 운영자는 현재 화면과 우리 릴스 URL로 `confirm-result JOB --post-url URL --screen-sha HASH`를 명시 기록할 수 있다. 원본 레퍼런스 URL은 허용하지 않는다. 이 역시 공개된 인코딩 영상의 픽셀 동일성을 인증하지 않는다.

하나의 폰 작성기는 한 영상이 소유한다. CLI 사이에도 소유권이 DB에 남으므로 다른 영상이 작성 화면을 덮어쓰지 않는다. `cancel JOB`는 공유 전 작업만 해제할 수 있고 자료를 삭제하지 않는다. 공유를 시도한 작업은 재시작/시간 경과/취소로 재게시 잠금이 풀리지 않는다. 같은 입력의 prepare는 기존 작업을 반환한다.

고정댓글/제품 링크는 패키지에 보존하되 댓글 작성·고정·DM·쿠팡 연동은 이번 릴스 게시 경로에서 자동 실행하지 않는다. Instagram 비공개 API, 로그인 정보 복제, 자동 CAPTCHA/비밀번호 입력을 사용하지 않는다.

## 코드와 검증

- `mobile_device.py`: 장치 설정, WireGuard 경로/포트 확인, 명시 ADB 대상, 일회용 페어링, 파일 해시 전송, 화면/요소/Unicode 입력.
- `mobile_reels.py`: 최신 게시물 패키지 동결·호환 변환, 폰 소유권, 작성 화면 검증, 단 한 번의 공유와 불명 결과 보존.
- `mobile_reels_cli.py`: PC에서만 사용하는 명령 진입점. 다른 제작/수집/예약 실행기를 시작하지 않는다.
- `tests/test_mobile_reels.py`: 전송·화면·계정/본문 검증·공유 후 실패·재시작 중복 방지·패키지 변경·실제 대상 명령 인자 격리 fixture.
- PC 확인 근거: `data/mobile-reels-implementation-20261023/`.

실제 화면은 기기 연결 후 위 절차로 캡처하고 조정해야 한다. 여기서 실행한 검사는 기기 없는 코드/모의 검증과 PC 호환 변환 시험이다.

공식 참고: [Android ADB 연결·페어링](https://developer.android.com/tools/adb), [uiautomator2 화면 요소와 Unicode set_text](https://github.com/openatx/uiautomator2), [WireGuard 경로 구성](https://www.wireguard.com/quickstart/), [Instagram Edits의 공식 앱 정보](https://play.google.com/store/apps/details?id=com.instagram.basel).

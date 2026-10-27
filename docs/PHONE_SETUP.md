# 휴대폰 연결 가이드 (WireGuard + 무선 디버깅)

이 저장소를 새로 받은 사람이 **자기 PC와 안드로이드 폰을 처음 연결**하는 방법이다. 연결이 끝나면 PC가 WireGuard VPN을 통해 폰의 Instagram/Edits 앱 화면을 사람처럼 조작할 수 있다. 게시 절차와 안전 규칙은 [폰 제어·게시](MOBILE_REELS_WIREGUARD.md)를 따른다.

```
PC (이 저장소) ──WireGuard VPN──▶ 안드로이드 폰 (무선 디버깅 = ADB) ──▶ Instagram / Edits 앱
```

- Instagram API는 쓰지 않는다. 폰의 실제 앱 화면을 한 단계씩 확인하며 진행한다.
- 이 가이드의 스크립트는 **연결만** 한다. 폰에서 앱을 열거나 업로드·게시하지 않는다.
- 2026-10-26에 Galaxy SM-S948N(Android 17)으로 WireGuard 경유 페어링·연결·Instagram 화면 캡처까지 확인했다.

## 여러 폰 등록·선택

기존 폰의 이름은 `primary`이며 기존 설정·페어링을 그대로 유지한다. 새 폰은 `phone2`, `phone3`처럼 서로 다른 이름으로 등록한다. 이름을 생략하면 기존 폰을 사용한다. 폰별로 WireGuard IP와 기기 식별자를 구분하며, 같은 폰을 이름만 바꿔 중복 등록하지 않는다.

- 기존 폰 설정: Git 제외 `data/.mobile-device.json`.
- 추가 폰 설정: Git 제외 `data/mobile-devices/<기기 이름>.json`.
- 등록 목록: `python -m hotpost.mobile_reels_cli devices`. 목록은 저장된 정보이며 실시간 연결 검사는 아니다.
- 추가 폰 최초 등록: 에이전트가 `phone-pair.cmd phone2` 또는 `phone-pair.cmd phone3`를 실행하도록 준비한다. 폰에서만 가능한 최초 설정·페어링 승인과 일회용 코드 입력은 사용자가 한다. 기존 폰에 새 폰 정보를 덮어쓰지 않는다.
- 새 Wi-Fi·포트 변경: 해당 이름에 `--device phone2 configure --adb-port N` → `--device phone2 connect`를 사용한다. 사용자용 스크립트도 `phone-reconnect.cmd phone2`처럼 이름을 받을 수 있다. 다른 폰의 포트·식별자는 바꾸지 않는다.
- 업로드 준비: `--device phone2 prepare SHORTCODE --account mr.salrim`처럼 폰과 게시 계정을 지정한다. 이후 `transfer JOB`, `inspect JOB` 등은 작업에 결속된 폰을 자동 선택한다. 다른 `--device`를 지정하면 실행 전에 거절한다.

각 폰의 최초 연결은 별도로 확인해야 한다. 세 기기 설정·작업 격리 검사는 실폰 세 대의 연결·게시 성공을 뜻하지 않는다. 계정별 중복 게시 방지는 [게시 워크플로우](MOBILE_REELS_WIREGUARD.md)를 따른다.

## VPN이 아직 없는 경우

WireGuard 앱 설치와 같은 VPN 연결 구성은 별개다. 기존 터널이 있으면 에이전트가 먼저 PC의 WireGuard 어댑터·폰 등록 정보·폰까지의 경로를 조회하고 유지한다. 새 설치에서 터널이 없으면 다음 준비를 먼저 한다.

VPN이 실제로 없다면 PC·폰의 [WireGuard 공식 앱](https://www.wireguard.com/install/)과 기기별 연결 구성이 필요하다. 기존 VPN 관리자에게 이 PC와 각 폰의 연결을 별도로 준비받고, 비공개 로컬 경로의 구성 파일/QR을 해당 기기에 적용한다. 에이전트는 실제 경로·ADB 포트 도달 여부를 확인한 뒤 아래 페어링을 진행한다. 개인키/QR은 채팅·로그·Git에 넣지 않는다. VPN 서버 구축은 업로드 절차로 자동 시작하지 않는다.

## 1. 준비물

| 항목 | 확인 방법 |
|---|---|
| 이 저장소 설치 | [설치가 없을 때만 준비](MOBILE_UPLOAD_START.md#설치가-없을-때만)한 `.venv`가 있어야 한다. 폰 도구(`requirements-mobile.txt`)는 스크립트가 없으면 자동 설치한다. |
| PC WireGuard | PC의 WireGuard 앱에서 터널이 **활성**이어야 한다. |
| 폰 WireGuard | 폰도 **같은 VPN**의 터널이 켜져 있어야 한다. 폰 WireGuard 앱 → 터널 → 주소(Addresses)의 IP(예: `10.9.0.50`)가 필요하다. 이 IP는 Wi-Fi가 바뀌어도 그대로다. |
| 폰 Wi-Fi | **무선 디버깅은 Wi-Fi에 연결돼 있어야 켜진다.** 모바일 데이터만으로는 켜지지 않는다. Wi-Fi 이름은 PC와 달라도 된다(통신은 VPN으로 한다). |
| 개발자 옵션 | 갤럭시: 설정 → 휴대전화 정보 → 소프트웨어 정보 → **빌드번호 7번 탭**. 다른 폰은 "빌드 번호"를 찾아 같은 방식으로 켠다. |
| Android 버전 | 무선 디버깅은 Android 11 이상. |

## 2. 처음 한 번: 페어링 (`phone-pair.cmd`)

1. 폰: Wi-Fi 켜기 → WireGuard 켜기 → 설정 → 개발자 옵션 → **무선 디버깅** 켜기. 처음이면 "이 네트워크에서 허용"을 누른다.
2. PC: 파일 탐색기에서 저장소 폴더의 **`phone-pair.cmd`를 더블클릭**한다.
3. 창의 질문에 차례로 답한다.

   | 질문 | 어디서 보나 |
   |---|---|
   | `Phone WireGuard IP` | 폰 WireGuard 앱의 주소. 예: `10.9.0.50` |
   | `Connect port` | 무선 디버깅 화면 "IP 주소 및 포트"의 **콜론 뒤 숫자**. 앞의 Wi-Fi IP는 쓰지 않는다. |
   | `Pairing port` | 무선 디버깅 → **"페어링 코드로 기기 페어링"** 팝업의 콜론 뒤 숫자. 연결 포트와 다른 번호다. |
   | `6-digit Wi-Fi pairing code` | 같은 팝업의 **"Wi-Fi 페어링 코드"** 6자리. |

4. `"paired": true`와 `"connected": true`가 나오면 끝이다. 폰의 "페어링된 기기" 목록에도 이 PC가 보인다.

주의:
- 팝업을 닫으면 코드와 페어링 포트가 **둘 다 바뀐다.** 팝업을 연 채로 입력하고, 닫았다면 새 값으로 다시 실행한다.
- 코드는 **그 창에만** 입력한다. 채팅·문서·메신저에 적지 않는다. 스크립트는 코드를 저장하거나 명령줄에 남기지 않는다.
- AI 앱(Claude Code·Codex 등)에 내장된 터미널 패널에서는 키 입력이 전달되지 않을 수 있다. 입력해도 반응이 없으면 **탐색기에서 더블클릭**해 열린 일반 창을 쓴다.

## 3. 다음부터: 포트만 바뀌었을 때 (`phone-reconnect.cmd`)

**다시 페어링할 필요는 없다.** 페어링 정보는 폰과 PC(`%USERPROFILE%\.android\adbkey`)에 남는다. 다만 다음 경우 무선 디버깅의 **연결 포트가 바뀐다.**

- 폰 재부팅
- Wi-Fi 변경·끊김 (갤럭시는 이때 무선 디버깅이 꺼지는 경우가 많다)
- 무선 디버깅 껐다 켜기

이때는 폰에서 무선 디버깅을 다시 켜고, `phone-reconnect.cmd`를 더블클릭해 **새 연결 포트만** 입력한다. 등록된 폰 IP와 기기 식별자 확인은 그대로 유지된다.

### 새로운 Wi-Fi로 이동한 경우

모바일 업로드를 시작하거나 이어갈 때 Wi-Fi가 바뀌었다면, 이전 연결 성공 기록만으로 폰이 연결돼 있다고 판단하지 않는다. 다음 순서로 연결을 복원한다.

1. 폰이 새 Wi-Fi에 연결돼 있는지 확인하고 PC·폰의 기존 WireGuard 터널을 켠다. PC와 폰이 같은 Wi-Fi에 있을 필요는 없다. 기존 터널을 유지했다면 폰의 WireGuard IP는 그대로 쓰며, 무선 디버깅 화면에 표시되는 새 Wi-Fi IP로 바꾸지 않는다.
2. 폰의 설정 → 개발자 옵션 → **무선 디버깅**을 확인한다. Wi-Fi 변경으로 꺼졌으면 다시 켜고, 새 네트워크의 디버깅 허용 창이 나오면 사용자가 직접 확인한다. Wi-Fi 연결만으로 디버깅이 다시 켜졌다고 가정하지 않는다.
3. 무선 디버깅 **첫 화면**의 "IP 주소 및 포트"에서 현재 연결 포트를 읽는다. 페어링 코드 팝업의 포트를 쓰지 않는다. 에이전트는 저장된 폰이 있으면 이 연결 포트만 요청하며, 폰 IP·페어링 코드·Wi-Fi 비밀번호를 다시 요구하지 않는다.
4. `phone-reconnect.cmd`에 현재 연결 포트를 입력한다. 에이전트가 값을 전달받았다면 `configure --adb-port N` → `connect`로 처리한다. `--phone-ip`를 생략해 등록된 폰 IP와 기기 식별자 검사를 유지한다. Wi-Fi 변경 자체는 재페어링 사유가 아니다.
5. 실제 `connect` 성공과 등록된 기기 일치를 확인한 뒤 기존 업로드 작업·폰의 현재 화면·계정을 확인한다. `doctor`의 `configured_not_connected`는 저장된 설정 확인이며 실시간 연결 성공이 아니다. 작성기와 기존 작업을 처음부터 다시 열지 않고 현재 단계부터 이어간다.

연결 실패가 계속되면 PC·폰의 터널, 폰의 Wi-Fi/무선 디버깅/네트워크 허용, 현재 연결 포트를 구분해 확인한다. PC의 WireGuard 경로가 있다는 사실만으로 폰이나 ADB 포트가 정상이라고 단정하지 않는다. 같은 포트 재시도나 페어링 초기화를 반복하지 않고 실패 근거와 필요한 사용자 조치를 남긴다. 재페어링은 아래의 실제 사유를 확인했을 때만 한다.

업로드 도중 Wi-Fi가 바뀌어 연결이 끊겼다면 기존 작업 ID·패키지·공유 시도 이력을 보존한다. 공유 시도 뒤 결과가 불명확한 작업은 재연결로 재게시 잠금을 해제하지 않으며, [게시 워크플로우](MOBILE_REELS_WIREGUARD.md)의 `reconcile` 절차로 결과만 확인한다.

다시 페어링(`phone-pair.cmd`)이 필요한 경우는 다음뿐이다.
- 폰에서 "USB 디버깅 권한 승인 취소" 또는 "페어링된 기기"에서 이 PC 삭제
- 폰 초기화·교체
- 다른 PC에서 처음 연결 (PC마다 한 번씩 페어링한다)

폰의 WireGuard IP만 바뀐 경우는 페어링이 유지된다. `configure --phone-ip 새IP --adb-port 연결포트` 후 `connect`로 다시 등록한다.

## 4. 연결 확인

저장소 폴더에서 PowerShell로 실행한다.

```powershell
.venv\Scripts\python.exe -X utf8 -m hotpost.mobile_reels_cli doctor
.venv\Scripts\python.exe -X utf8 -m hotpost.mobile_reels_cli connect
```

`connect`의 `android_serial`, `android_version`, `route`의 `WireGuard Tunnel`을 확인한다. 화면 확인이 필요하면 `app instagram`으로 Instagram을 열고 `data/mobile-reels/device-screens/app-instagram.png`를 본다. 이 명령은 앱을 열고 캡처만 하며 게시하지 않는다. 처음 화면을 다룰 때 uiautomator2가 폰에 도우미 앱을 설치한다.

## 5. 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| 무선 디버깅이 켜지지 않음 | 폰이 Wi-Fi에 연결돼 있지 않다. 아무 Wi-Fi나 연결한다. |
| `이 PC의 WireGuard 대역에 휴대폰 IP가 없습니다` | PC 터널이 꺼져 있거나 폰 IP를 잘못 입력했다. PC 터널을 켜고 폰 WireGuard 앱의 주소를 다시 확인한다. 대역이 특수하면 `configure --vpn-network 10.x.x.0/24`로 지정한다. |
| `휴대폰 페어링 포트에 닿지 않습니다` | 팝업이 닫혔거나 포트가 틀렸거나 폰 WireGuard가 꺼졌다. 팝업을 다시 열고 새 포트로 실행한다. `ping 폰IP`로 VPN 응답부터 확인한다. |
| `ADB 페어링이 완료되지 않았습니다` / 성공 응답 없음 | 코드가 틀렸거나 만료됐다. 팝업을 닫았다 열어 새 포트·코드로 다시 실행한다. |
| `ADB 연결이 승인되지 않았습니다` | 아직 페어링 전이거나, 연결 포트 자리에 페어링 포트를 넣었다. 무선 디버깅 첫 화면의 포트를 넣는다. |
| `WireGuard 경로는 있지만 휴대폰 ADB 포트에 닿지 않습니다` | 새 Wi-Fi의 디버깅 허용·무선 디버깅 켜짐·PC/폰 터널·현재 연결 포트를 확인한 뒤 `phone-reconnect.cmd`. PC 경로만으로 폰의 연결 상태를 판단하지 않는다. |
| `등록된 휴대폰과 실제 장치가 다릅니다` | 같은 IP에 다른 폰이 연결됐다. 맞는 폰인지 확인하고, 교체한 것이면 `phone-pair.cmd`로 다시 등록한다. |
| 코드를 입력해도 아무 반응이 없음 | 내장 터미널 패널이 키 입력을 전달하지 않는 경우다. 탐색기에서 `phone-pair.cmd`를 더블클릭한다. |
| `Shell does not have permission to access user 10/150` | 보안 폴더 등 별도 사용자 공간 때문에 나오는 안내다. 기본 공간 작업에는 영향이 없다. |

`%TEMP%\adb.log`에서 원인을 좁힐 수 있다. `Failed to decrypt`는 코드가 틀린 경우, `CERTIFICATE_UNKNOWN`은 아직 페어링되지 않은 PC가 연결을 시도한 경우다.

## 6. 보안

- 폰 IP·포트·기기 식별자는 `data/.mobile-device.json`에만 저장되며 Git에서 제외된다. 커밋하지 않는다.
- PC의 ADB 키(`%USERPROFILE%\.android\adbkey`)는 이 PC가 폰을 제어할 수 있는 열쇠다. 복사·공유·커밋하지 않는다.
- 연결 해제는 폰의 무선 디버깅 → "페어링된 기기"에서 해당 PC를 삭제하면 된다.
- 공개 포트 개방, `adb tcpip`, 루팅, 잠금 해제 우회는 하지 않는다.

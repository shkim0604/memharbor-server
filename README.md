# Memharbor Server

Django 기반 Agora RTC 토큰 발급, 로컬 녹음, 통화 관리 서버

## 주요 기능

- **Agora RTC 토큰 발급** - 음성 통화용 토큰 생성
- **로컬 녹음** - 서버가 채널에 참여하여 오디오 녹음 (Cloud Recording 미사용)
- **통화 관리** - 채널명 생성, 푸시 알림, 통화 상태 관리
- **Firebase 연동** - Firestore 기반 데이터 저장 (서버 DB 미사용)

---

## API Endpoints

Base URL: `https://memory-harbor.delight-house.org`

### 기본 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/health` | 서버 상태 확인 (Firestore 연결 상태 포함) |
| POST | `/api/token` | RTC 토큰 발급 |

### 녹음 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/recording/start` | 녹음 시작 |
| POST | `/api/recording/stop` | 녹음 중지 |
| GET | `/api/recording/status` | 진행 중인 녹음 세션 목록 |
| GET | `/api/recording/list` | 저장된 녹음 파일 목록 |

### 통화 관리 API (Firestore 기반)

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/call/invite` | 통화 시작 (채널 생성 + 푸시 전송) |
| POST | `/api/call/answer` | 통화 수락/거절 |
| POST | `/api/call/cancel` | 통화 취소 (발신자) |
| POST | `/api/call/missed` | 통화 부재중 처리 (클라이언트 타이머) |
| POST | `/api/call/timeout/sweep` | 서버 타임아웃 스윕 (pending → missed) |
| POST | `/api/call/end` | 통화 종료 |
| GET | `/api/call/status/<call_id>` | 통화 상태 조회 |

> **참고**: 디바이스 토큰은 앱에서 직접 Firestore `users/{uid}`에 저장합니다.

### POST /api/token

```json
{
  "channel": "groupId_user1_user2",
  "uid": 12345,
  "role": "publisher",
  "expire": 86400
}
```

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `channel` | ✅ | 채널명 |
| `uid` 또는 `user_account` | ✅ | 사용자 식별자 (정수) |
| `role` | | `publisher` / `subscriber` (기본값: subscriber) |
| `expire` | | 토큰 유효기간 초 (기본값/최대: 86400) |

**응답:**
```json
{
  "token": "006...",
  "expire_at": 1770260182,
  "expire_in": 86400
}
```

### POST /api/recording/start

녹음 봇이 채널에 참여하여 녹음 시작

```json
{
  "channel": "groupId_user1_user2"
}
```

- 채널명 형식: `{groupId}_{user1}_{user2}`
- 파일명(시작 시): `{channel}_{timestamp}.webm`

**응답:**
```json
{
  "sid": "uuid-session-id",
  "channel": "groupId_user1_user2",
  "uid": 999999,
  "filename": "groupId_user1_user2_2026-02-03T12-00-00.webm",
  "status": "recording"
}
```

### POST /api/recording/stop

```json
{
  "sid": "uuid-session-id"
}
```
또는
```json
{
  "channel": "groupId_user1_user2"
}
```

**응답:**
```json
{
  "sid": "uuid-session-id",
  "channel": "groupId_user1_user2",
  "groupId": "groupId",
  "user1": "user1",
  "user2": "user2",
  "filename": "groupId_user1_user2_2026-02-03T12-00-00.wav",
  "format": "wav",
  "duration": 120000,
  "firebase": {
    "url": "https://storage.googleapis.com/...",
    "firestoreId": "abc123",
    "storagePath": "recordings/groupId_user1_user2_2026-02-03T12-00-00.wav"
  },
  "status": "stopped"
}
```
> 변환 실패 시 `format`은 `webm`, `filename`은 `.webm` 유지됨. Firebase 설정이 없으면 `firebase`는 `null`.

### POST /api/call/invite

통화 시작 - 채널명 생성, Firestore에 통화 기록 저장, 수신자에게 푸시 전송

```json
{
  "group_id": "group1",
  "caller_id": "user123",
  "receiver_id": "user456",
  "caller_name": "John Doe",
  "group_name_snapshot": "Boston Care Group",
  "receiver_name_snapshot": "김영옥"
}
```

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `group_id` | ✅ | 그룹 ID |
| `caller_id` | ✅ | 발신자 ID |
| `receiver_id` | ✅ | 수신자 ID |
| `caller_name` | | 발신자 표시명 (기본값: caller_id) |
| `group_name_snapshot` | | 그룹명 스냅샷 |
| `receiver_name_snapshot` | | 수신자 이름 스냅샷 |

**응답:**
```json
{
  "success": true,
  "callId": "uuid",
  "channelName": "group1_user123_user456_1234567890123",
  "pushSent": true,
  "pushPlatform": "ios"
}
```

> 채널명 형식: `{groupId}_{callerId}_{receiverId}_{timestamp}`
> 통화 기록은 Firestore `calls/{callId}`에 저장됩니다.
> 서버는 `pending` 상태로 저장한 뒤 60초 타임아웃을 예약합니다.

### POST /api/call/answer

통화 수락 또는 거절

```json
{
  "call_id": "uuid",
  "action": "accept"
}
```

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `call_id` | ✅ | 통화 ID |
| `action` | ✅ | `accept` / `decline` |

**응답:**
```json
{
  "success": true,
  "callId": "uuid",
  "channelName": "group1_user123_user456_1234567890123",
  "status": "accepted"
}
```

### POST /api/call/cancel

발신자가 통화 취소 (수신자가 응답하기 전)

```json
{
  "call_id": "uuid"
}
```

**응답:**
```json
{
  "success": true,
  "callId": "uuid",
  "status": "cancelled"
}
```

### POST /api/call/missed

클라이언트 타이머(예: 60초) 만료 시 부재중 처리

```json
{
  "call_id": "uuid"
}
```

**응답:**
```json
{
  "success": true,
  "callId": "uuid",
  "status": "missed"
}
```

### POST /api/call/timeout/sweep

서버에서 주기적으로 호출하여 60초 이상 `pending` 상태인 통화를 `missed`로 변경
(`call/invite` 시 예약된 타이머가 누락될 경우의 백업)

```json
{
  "timeout_seconds": 60
}
```

**응답:**
```json
{
  "success": true,
  "timeoutSeconds": 60,
  "updatedCount": 3
}
```

### POST /api/call/end

통화 종료

```json
{
  "call_id": "uuid"
}
```

**응답:**
```json
{
  "success": true,
  "callId": "uuid",
  "status": "ended",
  "durationSeconds": 120
}
```

### GET /api/call/status/<call_id>

통화 상태 조회 (Firestore에서 조회)

**응답:**
```json
{
  "callId": "uuid",
  "channelName": "group1_user123_user456_1234567890123",
  "groupId": "group1",
  "receiverId": "user456",
  "caregiverUserId": "user123",
  "groupNameSnapshot": "Boston Care Group",
  "giverNameSnapshot": "Jungwon",
  "receiverNameSnapshot": "김영옥",
  "status": "accepted",
  "createdAt": "2026-02-04T05:49:23.670148",
  "answeredAt": "2026-02-04T05:49:34.770055",
  "endedAt": null,
  "durationSec": 600,
  "humanSummary": "",
  "humanKeywords": [],
  "humanNotes": "",
  "aiSummary": "",
  "reviewCount": 0,
  "lastReviewAt": null
}
```

통화 상태 값:
- `pending`: 대기 중 (푸시 전송됨)
- `accepted`: 수락됨
- `declined`: 거절됨
- `cancelled`: 취소됨 (발신자가 취소)
- `missed`: 부재중
- `ended`: 종료됨

---

## 환경 변수

`.env` 파일에 설정:

```env
# Agora (필수)
AGORA_APP_ID=your_app_id
AGORA_APP_CERT=your_app_cert

# Django (선택)
MEMHARBOR_SECRET_KEY=your-secret-key
MEMHARBOR_DEBUG=0

# Firebase
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com

# === 개발 환경 (에뮬레이터) ===
FIREBASE_USE_EMULATOR=true
FIRESTORE_EMULATOR_HOST=localhost:8080
FIREBASE_STORAGE_EMULATOR_HOST=localhost:9199

# === 프로덕션 ===
# FIREBASE_USE_EMULATOR=false
# FIREBASE_SERVICE_ACCOUNT={"type":"service_account",...}

# Recorder 서비스
RECORDER_SERVICE_URL=http://recorder:3100
RECORDER_PORT=3100
RECORDINGS_DIR=/app/recordings
# Puppeteer 실행 경로 (Docker에서 필요할 수 있음)
# PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# ======================
# 푸시 알림 설정 (통화 기능용)
# ======================

# iOS APNs VoIP Push (Apple Developer Portal에서 발급)
APNS_TEAM_ID=XXXXXXXXXX
APNS_KEY_ID=YYYYYYYYYY
APNS_BUNDLE_ID=com.yourcompany.yourapp
APNS_USE_SANDBOX=1
APNS_KEY_PATH=/path/to/AuthKey_YYYYYYYYYY.p8
# 또는 키 내용 직접 설정 (줄바꿈은 \n으로)
# APNS_KEY_CONTENT=-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----

# Android FCM (Firebase Console에서 발급)
FCM_PROJECT_ID=your-firebase-project-id
FCM_SERVICE_ACCOUNT_PATH=/path/to/service-account.json
# 또는 JSON 내용 직접 설정
# FCM_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

---

## 프로젝트 구조

```
memharbor_server/
├── api/                    # Django API 앱
│   ├── views.py           # API 엔드포인트
│   └── urls.py            # URL 라우팅
├── config/                 # Django 설정
│   └── settings.py        # 로깅 설정 포함
├── recorder/              # 녹음 서비스 (Node.js)
│   ├── Dockerfile
│   ├── server.js          # Express 서버
│   └── public/
│       └── recorder.html  # Agora 채널 참여 + 녹음
├── logs/                   # 로그 파일 (로컬/도커 마운트)
│   ├── api.log            # API 요청 로그
│   └── django.log         # Django 전체 로그
├── recordings/            # 녹음 파일 (개발용)
├── docker-compose.prod.yml # 프로덕션용 (현재 사용)
├── Dockerfile             # Django 이미지
└── nginx.conf             # Nginx 설정
```

> **참고**: 서버는 SQLite 등 로컬 DB를 사용하지 않습니다. 모든 데이터는 Firebase Firestore에 저장됩니다.

---

## Firestore 데이터 구조

### `users/{uid}` 컬렉션 (앱에서 저장)

사용자 정보 및 푸시 토큰을 저장합니다. **앱에서 직접 저장**하며, 서버는 읽기만 합니다.

```json
{
  "fcmToken": "android_fcm_token_string",
  "voipToken": "ios_voip_token_string",
  "platform": "ios",
  ...
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `fcmToken` | string | Android FCM 토큰 |
| `voipToken` | string | iOS VoIP 푸시 토큰 |
| `platform` | string | `ios` 또는 `android` |

### `calls/{callId}` 컬렉션 (서버에서 관리)

통화 기록을 저장합니다. **서버에서 생성 및 업데이트**합니다.

```json
{
  "callId": "uuid",
  "channelName": "group1_user123_user456_1234567890",
  "groupId": "group1",
  "callerId": "user123",
  "receiverId": "user456",
  "callerName": "John Doe",
  "status": "pending",
  "createdAt": "2026-02-04T05:49:23.670148Z",
  "updatedAt": "2026-02-04T05:49:23.670148Z",
  "answeredAt": null,
  "endedAt": null,
  "pushSent": true,
  "pushPlatform": "ios"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `callId` | string | 통화 고유 ID (UUID) |
| `channelName` | string | Agora 채널명 |
| `groupId` | string | 그룹 ID |
| `callerId` | string | 발신자 UID |
| `receiverId` | string | 수신자 UID |
| `callerName` | string | 발신자 표시명 |
| `status` | string | 통화 상태 |
| `createdAt` | timestamp | 생성 시간 |
| `answeredAt` | timestamp | 수락 시간 |
| `endedAt` | timestamp | 종료 시간 |
| `pushSent` | boolean | 푸시 전송 성공 여부 |
| `pushPlatform` | string | 푸시 플랫폼 (ios/android) |

---

## 실행 방법

### 1. 로컬 개발 (Docker 없이)

Django만 실행 (녹음 기능 없음):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8001
```

### 2. 개발 환경 (Docker + Firebase 에뮬레이터)

```bash
# 1. Firebase 에뮬레이터 먼저 실행 (별도 터미널)
firebase emulators:start

# 2. Docker 컨테이너 실행
docker-compose -f docker-compose.prod.yml up -d --build

# 로그 확인
docker-compose -f docker-compose.prod.yml logs -f

# 중지
docker-compose -f docker-compose.prod.yml down
```

- Django: `http://localhost:8001`
- Recorder: `http://localhost:3100`
- 녹음 파일: `./recordings/`
- API 로그: `./logs/api.log`

### 3. 프로덕션 환경 (Docker)

```bash
# 빌드 및 실행
docker-compose -f docker-compose.prod.yml up -d --build

# 로그 확인
docker-compose -f docker-compose.prod.yml logs -f

# 특정 서비스 로그
docker-compose -f docker-compose.prod.yml logs -f recorder

# 중지
docker-compose -f docker-compose.prod.yml down
```

- 외부 접속: `https://memory-harbor.delight-house.org`
- 녹음 파일: `recordings_data` Docker 볼륨
- API 로그: `./logs/api.log`

---

## 로그 확인

### API 로그 (실시간)

```bash
tail -f logs/api.log
```

### 로그 예시

```
[2026-02-04 02:56:22] INFO api [TOKEN] POST from 172.19.0.5
[2026-02-04 02:56:22] INFO api [TOKEN] Request data: {'channel': 'group1_alice_bob', 'uid': 12345}
[2026-02-04 02:56:22] INFO api [TOKEN] Success: channel=group1_alice_bob, uid=12345
```

### Docker 로그

```bash
# nginx (요청 로그)
docker logs -f memharbor_server-nginx-1

# Django
docker logs -f memharbor_server-memharbor_server-1

# Recorder
docker logs -f memharbor_server-recorder-1
```

---

## 아키텍처 (Prod)

```
[인터넷]
    ↓
[Cloudflare Tunnel] (memory-harbor.delight-house.org)
    ↓
[Nginx] (:80, 호스트 8001 매핑)
    ↓
[Django/Gunicorn] (:8001) → logs/api.log
    ↓
[Recorder Service] (:3100)
    ↓
[Agora Channel] → [WAV 파일] → [Firebase Storage]
```

### 통화 흐름

```
[발신자 앱]                    [서버]                    [수신자 앱]
    |                           |                           |
    |  POST /call/invite        |                           |
    |  (groupId, callerId,      |                           |
    |   receiverId)             |                           |
    |-------------------------->|                           |
    |                           |                           |
    |  {callId, channelName}    |  VoIP Push (iOS)          |
    |<--------------------------|  또는 FCM (Android)        |
    |                           |-------------------------->|
    |                           |                           |
    |  Agora 채널 참여           |           CallKit UI 표시  |
    |  (channelName 사용)        |           또는 Full-screen |
    |                           |                           |
    |                           |  POST /call/answer        |
    |                           |  {callId, action:accept}  |
    |                           |<--------------------------|
    |                           |                           |
    |                           |  {channelName}            |
    |                           |-------------------------->|
    |                           |                           |
    |                           |           Agora 채널 참여   |
    |                           |           (channelName)   |
    |<========== 음성 통화 (Agora RTC) ==========>|
    |                           |                           |
    |  POST /call/end           |                           |
    |-------------------------->|                           |
```

**채널명 형식**: `{groupId}_{callerId}_{receiverId}_{timestamp}`

**푸시 페이로드**:
```json
{
  "type": "incoming_call",
  "callId": "uuid",
  "channelName": "group1_user123_user456_1234567890",
  "callerName": "John Doe",
  "callerID": "user123",
  "groupId": "group1",
  "receiverId": "user456"
}
```

### 녹음 흐름

1. 클라이언트가 `/api/recording/start` 호출
   - 채널명 형식: `{groupId}_{user1}_{user2}`
2. Django가 Recorder Service에 요청 전달
3. Recorder가 헤드리스 브라우저(Puppeteer)로 Agora 채널 참여
4. 채널 내 모든 오디오를 실시간 녹음
5. `/api/recording/stop` 호출 시:
   - WebM → WAV 변환 (AI 최적화: 16kHz, 모노)
   - Firebase Storage에 업로드
   - Firestore에 메타데이터 저장
   - 채널 퇴장

### Firebase 데이터 구조

**Storage**: `recordings/{filename}.wav`

**Firestore** `recordings` 컬렉션:
```json
{
  "filename": "group1_alice_bob_2026-02-03T12-00-00.wav",
  "url": "https://storage.googleapis.com/...",
  "channel": "group1_alice_bob",
  "groupId": "group1",
  "user1": "alice",
  "user2": "bob",
  "duration": 120000,
  "fileSize": 3840000,
  "format": "wav",
  "spec": { "sampleRate": 16000, "channels": 1, "bitDepth": 16 },
  "recordedAt": "2026-02-03T12:00:00.000Z",
  "createdAt": "2026-02-03T12:02:00.000Z"
}
```

---

## 문제 해결

### 컨테이너 상태 확인

```bash
docker ps -a
```

### Health Check

```bash
# 로컬
curl http://localhost:8001/api/health

# 프로덕션
curl https://memory-harbor.delight-house.org/api/health
```

### 토큰 테스트

```bash
curl -X POST https://memory-harbor.delight-house.org/api/token \
  -H "Content-Type: application/json" \
  -d '{"channel": "group1_alice_bob", "uid": 12345}'
```

### 녹음 파일 접근

```bash
# 개발 - 로컬 폴더
ls ./recordings/

# 프로덕션 - Docker 볼륨
docker exec -it memharbor_server-recorder-1 ls /app/recordings

# 파일 복사
docker cp memharbor_server-recorder-1:/app/recordings/file.wav ./
```

---

## 참고

### 녹음 파일 스펙 (AI 최적화)

| 항목 | 값 |
|------|-----|
| 포맷 | WAV |
| 샘플레이트 | 16,000 Hz |
| 채널 | 모노 |
| 비트 깊이 | 16-bit |
| 코덱 | PCM (무손실) |

이 형식은 다음 AI 서비스와 바로 호환됩니다:
- OpenAI Whisper
- Google Speech-to-Text
- AWS Transcribe
- Azure Speech Services

### 기타

- 녹음 봇은 **Audience 모드**로 참여 (다른 참가자에게 보이지 않음)
- Cloudflare Tunnel 설정은 [Zero Trust 대시보드](https://one.dash.cloudflare.com/)에서 관리
- 코드 수정 후 `docker-compose restart` 또는 `--build` 필요

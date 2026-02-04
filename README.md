# Memharbor Server

Django 기반 Agora RTC 토큰 발급 및 로컬 녹음 서버

## 주요 기능

- **Agora RTC 토큰 발급** - 음성 통화용 토큰 생성
- **로컬 녹음** - 서버가 채널에 참여하여 오디오 녹음 (Cloud Recording 미사용)
- **Firebase 연동** - 녹음 파일 자동 업로드 및 메타데이터 저장

---

## API Endpoints

Base URL: `https://memory-harbor.delight-house.org`

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/health` | 서버 상태 확인 |
| POST | `/api/token` | RTC 토큰 발급 |
| POST | `/api/recording/start` | 녹음 시작 |
| POST | `/api/recording/stop` | 녹음 중지 |
| GET | `/api/recording/status` | 진행 중인 녹음 세션 목록 |
| GET | `/api/recording/list` | 저장된 녹음 파일 목록 |

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
- 파일명: `{channel}_{timestamp}.wav`

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
├── logs/                   # 로그 파일
│   ├── api.log            # API 요청 로그
│   └── django.log         # Django 전체 로그
├── recordings/            # 녹음 파일 (개발용)
├── docker-compose.yml      # 개발용
├── docker-compose.prod.yml # 프로덕션용
├── Dockerfile             # Django 이미지
└── nginx.conf             # Nginx 설정
```

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
docker-compose up -d --build

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
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
[Nginx] (:80)
    ↓
[Django/Gunicorn] (:8001) → logs/api.log
    ↓
[Recorder Service] (:3100)
    ↓
[Agora Channel] → [WAV 파일] → [Firebase Storage]
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

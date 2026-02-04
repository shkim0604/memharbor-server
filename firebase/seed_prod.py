"""
Firestore seed script (Production)
Run with: python3 firebase/seed_prod.py --confirm-prod [--reset]
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"Missing env: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _init_firebase():
    if os.environ.get("FIREBASE_USE_EMULATOR", "").lower() == "true":
        print("FIREBASE_USE_EMULATOR is set. Refusing to run production seed.", file=sys.stderr)
        sys.exit(1)

    project_id = _require_env("FIREBASE_PROJECT_ID")
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    service_account_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")

    cred = None
    if service_account_json:
        try:
            cred = credentials.Certificate(json.loads(service_account_json))
        except json.JSONDecodeError as exc:
            print(f"Invalid FIREBASE_SERVICE_ACCOUNT JSON: {exc}", file=sys.stderr)
            sys.exit(1)
    elif service_account_path and os.path.exists(service_account_path):
        cred = credentials.Certificate(service_account_path)
    else:
        print(
            "Provide FIREBASE_SERVICE_ACCOUNT or FIREBASE_SERVICE_ACCOUNT_PATH for production.",
            file=sys.stderr,
        )
        sys.exit(1)

    firebase_admin.initialize_app(cred, options={"projectId": project_id})


def _non_empty_str(value, default):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _clear_collection(collection_ref):
    for doc in collection_ref.stream():
        doc.reference.delete()


def clear_all(db):
    print("🧹 Clearing Firestore production data...")
    # _clear_collection(db.collection("users"))
    _clear_collection(db.collection("groups"))
    _clear_collection(db.collection("receivers"))
    _clear_collection(db.collection("calls"))
    _clear_collection(db.collection("meta"))
    print("✅ Clear completed")


def seed(db):
    print("🌱 Seeding Firestore (production) with Python...")

    group_id = "group_1"
    receiver_id = "receiver_1"
    receiver_id_3 = "5tIJ9f6E5TMOVgXsTSB9s9mbtC42"

    group_id_2 = "group_2"
    receiver_id_2 = "receiver_2"

    user_a = "user_jungwon"
    user_b = "user_alice"
    user_c = "user_minho"
    user_d = "user_sora"

    residences = [
        {
            "id": "res_1950s_andong",
            "era": "1950~1965",
            "location": "경상북도 안동시",
            "detail": "태어난 곳, 어린 시절",
        },
        {
            "id": "res_1960s_jongno",
            "era": "1966~1975",
            "location": "서울 종로구",
            "detail": "학창시절, 결혼 전",
        },
        {
            "id": "res_1975s_gangnam",
            "era": "1976~1989",
            "location": "서울 강남구",
            "detail": "신혼, 자녀 양육기",
        },
        {
            "id": "res_1990s_bundang",
            "era": "1990~2010",
            "location": "경기도 분당",
            "detail": "자녀 독립 후",
        },
        {
            "id": "res_2010s_seocho",
            "era": "2011~현재",
            "location": "서울 서초구",
            "detail": "현재 거주지",
        },
    ]

    residences_2 = [
        {
            "id": "res_1940s_yeosu",
            "era": "1945~1958",
            "location": "전라남도 여수시",
            "detail": "피난 이후 정착, 가족과의 추억",
        },
        {
            "id": "res_1960s_mapo",
            "era": "1959~1972",
            "location": "서울 마포구",
            "detail": "직장 생활 시작, 사회 초년기",
        },
        {
            "id": "res_1970s_daejeon",
            "era": "1973~1985",
            "location": "대전 서구",
            "detail": "자녀 출생, 이사와 적응",
        },
        {
            "id": "res_1990s_ilsan",
            "era": "1986~2005",
            "location": "경기도 일산",
            "detail": "가족 중심 생활, 이웃 관계",
        },
        {
            "id": "res_2000s_songpa",
            "era": "2006~현재",
            "location": "서울 송파구",
            "detail": "현재 거주, 건강 관리",
        },
    ]

    calls = [
        {
            "call_id": "call_001",
            "summary": "안동 어린 시절 이야기",
            "residences": ["res_1950s_andong"],
        },
        {
            "call_id": "call_002",
            "summary": "종로 학창시절 회상",
            "residences": ["res_1960s_jongno"],
        },
        {
            "call_id": "call_003",
            "summary": "강남에서 자녀 양육기 이야기",
            "residences": ["res_1975s_gangnam"],
        },
        {
            "call_id": "call_004",
            "summary": "분당 신도시 정착기",
            "residences": ["res_1990s_bundang"],
        },
        {
            "call_id": "call_005",
            "summary": "서초에서의 현재 일상",
            "residences": ["res_2010s_seocho"],
        },
    ]

    calls_2 = [
        {
            "call_id": "call_101",
            "summary": "여수 피난 이후 기억",
            "residences": ["res_1940s_yeosu"],
        },
        {
            "call_id": "call_102",
            "summary": "마포에서 사회 초년기 이야기",
            "residences": ["res_1960s_mapo"],
        },
        {
            "call_id": "call_103",
            "summary": "대전 이사와 자녀 출생기",
            "residences": ["res_1970s_daejeon"],
        },
        {
            "call_id": "call_104",
            "summary": "일산에서의 가족 생활",
            "residences": ["res_1990s_ilsan"],
        },
        {
            "call_id": "call_105",
            "summary": "송파 현재 일상과 건강 이야기",
            "residences": ["res_2000s_songpa"],
        },
    ]

    now = datetime.now(ZoneInfo("America/New_York"))

    db.collection("users").document(user_a).set({
        "uid": user_a,
        "name": "Jungwon",
        "email": "jungwon@test.com",
        "profileImage": "https://placehold.co/200x200",
        "groupIds": [group_id],
        "createdAt": now,
    })

    db.collection("users").document(user_b).set({
        "uid": user_b,
        "name": "Alice",
        "email": "alice@test.com",
        "profileImage": "https://placehold.co/200x200",
        "groupIds": [group_id],
        "createdAt": now,
    })

    db.collection("users").document(user_c).set({
        "uid": user_c,
        "name": "Minho",
        "email": "minho@test.com",
        "profileImage": "https://placehold.co/200x200",
        "groupIds": [group_id_2],
        "createdAt": now,
    })

    db.collection("users").document(user_d).set({
        "uid": user_d,
        "name": "Sora",
        "email": "sora@test.com",
        "profileImage": "https://placehold.co/200x200",
        "groupIds": [group_id_2],
        "createdAt": now,
    })

    db.collection("groups").document(group_id).set({
        "groupId": group_id,
        "name": "Boston Care Group",
        "careGiverUserIds": [user_a, user_b],
        "receiverId": receiver_id,
        "stats": {
            "totalCalls": len(calls),
            "lastCallId": calls[-1]["call_id"],
            "lastCallAt": now,
        },
    })

    db.collection("groups").document(group_id_2).set({
        "groupId": group_id_2,
        "name": "Seoul Memory Group",
        "careGiverUserIds": [user_c, user_d],
        "receiverId": receiver_id_2,
        "stats": {
            "totalCalls": len(calls_2),
            "lastCallId": calls_2[-1]["call_id"],
            "lastCallAt": now,
        },
    })

    db.collection("receivers").document(receiver_id).set({
        "receiverId": receiver_id,
        "groupId": group_id,
        "name": "김영옥",
        "profileImage": "https://placehold.co/200x200",
        "majorResidences": [
            {
                "residenceId": r["id"],
                "era": _non_empty_str(r.get("era"), "시기 미상"),
                "location": _non_empty_str(r.get("location"), "장소 미상"),
                "detail": _non_empty_str(r.get("detail"), ""),
            }
            for r in residences
        ],
    })

    db.collection("receivers").document(receiver_id_3).set({
        "receiverId": receiver_id_3,
        "groupId": group_id,
        "name": "Seonghoon",
        "profileImage": "https://placehold.co/200x200",
        "majorResidences": [
            {
                "residenceId": r["id"],
                "era": _non_empty_str(r.get("era"), "시기 미상"),
                "location": _non_empty_str(r.get("location"), "장소 미상"),
                "detail": _non_empty_str(r.get("detail"), ""),
            }
            for r in residences
        ],
    })

    db.collection("receivers").document(receiver_id_2).set({
        "receiverId": receiver_id_2,
        "groupId": group_id_2,
        "name": "박정희",
        "profileImage": "https://placehold.co/200x200",
        "majorResidences": [
            {
                "residenceId": r["id"],
                "era": _non_empty_str(r.get("era"), "시기 미상"),
                "location": _non_empty_str(r.get("location"), "장소 미상"),
                "detail": _non_empty_str(r.get("detail"), ""),
            }
            for r in residences_2
        ],
    })

    for r in residences:
        era = _non_empty_str(r.get("era"), "시기 미상")
        location = _non_empty_str(r.get("location"), "장소 미상")
        detail = _non_empty_str(r.get("detail"), "")
        ai_summary = (
            f"{era}({location})의 기억은 일상과 관계 중심으로 정리됩니다."
            + (f" 주요 단서: {detail}." if detail else "")
        )

        db.collection("receivers").document(receiver_id) \
            .collection("residence_stats").document(r["id"]).set({
                "groupId": group_id,
                "receiverId": receiver_id,
                "residenceId": r["id"],
                "era": era,
                "location": location,
                "detail": detail,
                "keywords": ["가족", "추억"],
                "totalCalls": 1,
                "lastCallAt": now,
                "aiSummary": ai_summary,
                "humanComments": ["이 시절 이야기가 자주 등장함"],
            })

        db.collection("receivers").document(receiver_id_3) \
            .collection("residence_stats").document(r["id"]).set({
                "groupId": group_id,
                "receiverId": receiver_id_3,
                "residenceId": r["id"],
                "era": era,
                "location": location,
                "detail": detail,
                "keywords": ["가족", "추억"],
                "totalCalls": 1,
                "lastCallAt": now,
                "aiSummary": ai_summary,
                "humanComments": ["이 시절 이야기가 자주 등장함"],
            })

    for r in residences_2:
        era = _non_empty_str(r.get("era"), "시기 미상")
        location = _non_empty_str(r.get("location"), "장소 미상")
        detail = _non_empty_str(r.get("detail"), "")
        ai_summary = (
            f"{era}({location})의 기억은 생활 변화와 가족 이야기 중심으로 정리됩니다."
            + (f" 주요 단서: {detail}." if detail else "")
        )

        db.collection("receivers").document(receiver_id_2) \
            .collection("residence_stats").document(r["id"]).set({
                "groupId": group_id_2,
                "receiverId": receiver_id_2,
                "residenceId": r["id"],
                "era": era,
                "location": location,
                "detail": detail,
                "keywords": ["이사", "가족", "직장"],
                "totalCalls": 1,
                "lastCallAt": now,
                "aiSummary": ai_summary,
                "humanComments": ["중요한 전환점이 된 시기"],
            })

    for i, c in enumerate(calls):
        call_ref = db.collection("calls").document(c["call_id"])

        created_at = (now - timedelta(days=3 - i))
        answered_at = created_at + timedelta(seconds=5)
        ended_at = created_at + timedelta(seconds=600)
        channel_name = f"{group_id}_{user_a}_{receiver_id}_{int(created_at.timestamp() * 1000)}"

        call_ref.set({
            "callId": c["call_id"],
            "channelName": channel_name,
            "groupId": group_id,
            "receiverId": receiver_id,
            "caregiverUserId": user_a,
            "groupNameSnapshot": "Boston Care Group",
            "giverNameSnapshot": "Jungwon",
            "receiverNameSnapshot": "김영옥",
            "createdAt": created_at,
            "answeredAt": answered_at,
            "endedAt": ended_at,
            "durationSec": 600,
            "status": "ended",
            "humanSummary": "",
            "humanKeywords": [],
            "humanNotes": "",
            "aiSummary": "",
            "reviewCount": 1,
            "lastReviewAt": now,
        })

        call_ref.collection("reviews").add({
            "callId": c["call_id"],
            "writerUserId": user_a,
            "writerNameSnapshot": "Jungwon",
            "mentionedResidences": c["residences"],
            "humanSummary": "대화가 자연스럽고 감정이 잘 드러났음",
            "humanKeywords": ["따뜻함"],
            "mood": "warm",
            "comment": "다음에도 비슷한 질문을 이어가면 좋겠다",
            "createdAt": now,
        })

    for i, c in enumerate(calls_2):
        call_ref = db.collection("calls").document(c["call_id"])

        created_at = (now - timedelta(days=10 - i))
        answered_at = created_at + timedelta(seconds=7)
        ended_at = created_at + timedelta(seconds=540)
        channel_name = f"{group_id_2}_{user_c}_{receiver_id_2}_{int(created_at.timestamp() * 1000)}"

        call_ref.set({
            "callId": c["call_id"],
            "channelName": channel_name,
            "groupId": group_id_2,
            "receiverId": receiver_id_2,
            "caregiverUserId": user_c,
            "groupNameSnapshot": "Seoul Memory Group",
            "giverNameSnapshot": "Minho",
            "receiverNameSnapshot": "박정희",
            "createdAt": created_at,
            "answeredAt": answered_at,
            "endedAt": ended_at,
            "durationSec": 540,
            "status": "ended",
            "humanSummary": "",
            "humanKeywords": [],
            "humanNotes": "",
            "aiSummary": "",
            "reviewCount": 1,
            "lastReviewAt": now,
        })

        call_ref.collection("reviews").add({
            "callId": c["call_id"],
            "writerUserId": user_c,
            "writerNameSnapshot": "Minho",
            "mentionedResidences": c["residences"],
            "humanSummary": "기억이 선명하고 디테일이 풍부함",
            "humanKeywords": ["추억", "변화"],
            "mood": "reflective",
            "comment": "다음에는 가족 구성원 이야기를 더 물어보자",
            "createdAt": now,
        })

    print("✅ Seed completed successfully (production)")


def seed_receiver_copy(db):
    print("🌱 Seeding single receiver copy (production)...")

    group_id = "group_1"
    receiver_id_3 = "5tIJ9f6E5TMOVgXsTSB9s9mbtC42"

    residences = [
        {
            "id": "res_1950s_andong",
            "era": "1950~1965",
            "location": "경상북도 안동시",
            "detail": "태어난 곳, 어린 시절",
        },
        {
            "id": "res_1960s_jongno",
            "era": "1966~1975",
            "location": "서울 종로구",
            "detail": "학창시절, 결혼 전",
        },
        {
            "id": "res_1975s_gangnam",
            "era": "1976~1989",
            "location": "서울 강남구",
            "detail": "신혼, 자녀 양육기",
        },
        {
            "id": "res_1990s_bundang",
            "era": "1990~2010",
            "location": "경기도 분당",
            "detail": "자녀 독립 후",
        },
        {
            "id": "res_2010s_seocho",
            "era": "2011~현재",
            "location": "서울 서초구",
            "detail": "현재 거주지",
        },
    ]

    now = datetime.now(ZoneInfo("America/New_York"))

    db.collection("receivers").document(receiver_id_3).set({
        "receiverId": receiver_id_3,
        "groupId": group_id,
        "name": "Seonghoon",
        "profileImage": "https://placehold.co/200x200",
        "majorResidences": [
            {
                "residenceId": r["id"],
                "era": _non_empty_str(r.get("era"), "시기 미상"),
                "location": _non_empty_str(r.get("location"), "장소 미상"),
                "detail": _non_empty_str(r.get("detail"), ""),
            }
            for r in residences
        ],
    })

    for r in residences:
        era = _non_empty_str(r.get("era"), "시기 미상")
        location = _non_empty_str(r.get("location"), "장소 미상")
        detail = _non_empty_str(r.get("detail"), "")
        ai_summary = (
            f"{era}({location})의 기억은 일상과 관계 중심으로 정리됩니다."
            + (f" 주요 단서: {detail}." if detail else "")
        )

        db.collection("receivers").document(receiver_id_3) \
            .collection("residence_stats").document(r["id"]).set({
                "groupId": group_id,
                "receiverId": receiver_id_3,
                "residenceId": r["id"],
                "era": era,
                "location": location,
                "detail": detail,
                "keywords": ["가족", "추억"],
                "totalCalls": 1,
                "lastCallAt": now,
                "aiSummary": ai_summary,
                "humanComments": ["이 시절 이야기가 자주 등장함"],
            })

    print("✅ Receiver copy completed (production)")


def main():
    if "--confirm-prod" not in sys.argv:
        print("Refusing to run without --confirm-prod flag.", file=sys.stderr)
        sys.exit(1)

    _init_firebase()
    db = firestore.client()

    if "--reset" in sys.argv:
        clear_all(db)

    if "--add-receiver3" in sys.argv:
        seed_receiver_copy(db)
        return

    seed(db)


if __name__ == "__main__":
    main()

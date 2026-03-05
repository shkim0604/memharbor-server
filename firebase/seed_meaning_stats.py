"""
Seed fixed meaning-based topic stats into Firestore Emulator.

Usage:
  python firebase/seed_meaning_stats.py --receiver-id receiver_1 --group-id group_1
  python firebase/seed_meaning_stats.py --receiver-id receiver_1,receiver_2 --reset
  python firebase/seed_meaning_stats.py --receiver-id receiver_1 --emulator
"""

import argparse
import os
import socket
from dataclasses import dataclass
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError


@dataclass(frozen=True)
class MeaningQuestion:
    meaning_id: str
    order: int
    title: str
    question: str
    interview_guide: list[dict[str, object]]


FIXED_MEANING_QUESTIONS = [
    MeaningQuestion(
        meaning_id="meaning_legacy_event",
        order=1,
        title="꼭 남기고 싶은 사건",
        question="남은 사람들이 꼭 기억해줬으면 하는 사건은 무엇인가요?",
        interview_guide=[
            {
                "step": 1,
                "key": "memory",
                "label": "Memory",
                "prompts": [
                    "가족들이 꼭 기억해줬으면 하는 일이 하나 있다면, 어떤 사건이 먼저 떠오르세요?"
                ],
            },
            {
                "step": 2,
                "key": "moment",
                "label": "Moment",
                "prompts": [
                    "그때 어디에 계셨고, 누가 함께 있었나요?",
                    "그 순간 가장 강하게 느껴졌던 감정은 뭐였나요?",
                ],
            },
            {
                "step": 3,
                "key": "meaning",
                "label": "Meaning",
                "prompts": [
                    "지금 돌아보면 그 사건은 어르신 인생에서 어떤 의미였나요?",
                    "후손들이 그 이야기에서 꼭 배웠으면 하는 점은 무엇일까요?",
                ],
            },
        ],
    ),
    MeaningQuestion(
        meaning_id="meaning_work_memory",
        order=2,
        title="직장생활 기억",
        question="직장생활에서 가장 기억에 남는 사건은 무엇인가요?",
        interview_guide=[
            {
                "step": 1,
                "key": "memory",
                "label": "Memory",
                "prompts": [
                    "직장생활 중에 '아, 그 일은 잊을 수 없다' 싶은 사건이 있으세요?"
                ],
            },
            {
                "step": 2,
                "key": "moment",
                "label": "Moment",
                "prompts": [
                    "그날 상황이 어떻게 흘러갔는지 장면처럼 들려주실 수 있을까요?",
                    "그때 제일 부담됐던 점이나, 반대로 힘이 됐던 사람은 누구였나요?",
                ],
            },
            {
                "step": 3,
                "key": "meaning",
                "label": "Meaning",
                "prompts": [
                    "그 일을 겪고 나서 일이나 사람을 대하는 방식이 달라진 게 있었나요?",
                    "지금 세대에게 그 경험으로 전하고 싶은 조언이 있다면요?",
                ],
            },
        ],
    ),
    MeaningQuestion(
        meaning_id="meaning_church_memory",
        order=3,
        title="교회생활 기억",
        question="교회생활에서 가장 기억에 남는 사건은 무엇인가요?",
        interview_guide=[
            {
                "step": 1,
                "key": "memory",
                "label": "Memory",
                "prompts": [
                    "교회생활에서 가장 마음에 남아 있는 일이 하나 있다면 어떤 일인가요?"
                ],
            },
            {
                "step": 2,
                "key": "moment",
                "label": "Moment",
                "prompts": [
                    "그날 예배나 모임 분위기는 어땠는지 기억나세요?",
                    "그 순간에 위로나 용기를 받았던 말이 있었나요?",
                ],
            },
            {
                "step": 3,
                "key": "meaning",
                "label": "Meaning",
                "prompts": [
                    "그 사건이 신앙이나 삶의 태도에 어떤 변화를 줬나요?",
                    "가족이 그 이야기를 기억하면 어떤 힘이 될까요?",
                ],
            },
        ],
    ),
    MeaningQuestion(
        meaning_id="meaning_influential_person",
        order=4,
        title="영향을 준 사람",
        question="인생에서 가장 큰 영향을 받은 사람은 누구인가요?",
        interview_guide=[
            {
                "step": 1,
                "key": "memory",
                "label": "Memory",
                "prompts": ["어르신 삶에 가장 큰 영향을 준 분은 누구세요?"],
            },
            {
                "step": 2,
                "key": "moment",
                "label": "Moment",
                "prompts": [
                    "그분이 해주신 말이나 행동 중 아직도 선명한 장면이 있으세요?",
                    "그때 어르신 마음이 어떻게 움직였는지 들려주실 수 있을까요?",
                ],
            },
            {
                "step": 3,
                "key": "meaning",
                "label": "Meaning",
                "prompts": [
                    "그분을 통해 배운 걸 한 문장으로 말하면 뭐라고 하고 싶으세요?",
                    "그 가르침이 지금의 어르신을 어떻게 만들었다고 느끼세요?",
                ],
            },
        ],
    ),
    MeaningQuestion(
        meaning_id="meaning_rewind_moment",
        order=5,
        title="돌아가고 싶은 순간",
        question="인생에서 다시 돌아가고 싶은 순간이 있다면 언제인가요?",
        interview_guide=[
            {
                "step": 1,
                "key": "memory",
                "label": "Memory",
                "prompts": [
                    "다시 돌아가 보고 싶은 인생의 한 순간이 있다면 언제인가요?"
                ],
            },
            {
                "step": 2,
                "key": "moment",
                "label": "Moment",
                "prompts": [
                    "그 장면을 영화 한 컷처럼 묘사해주신다면 어떤 모습일까요?",
                    "그때로 돌아간다면 똑같이 하고 싶은 선택, 바꾸고 싶은 선택이 각각 있을까요?",
                ],
            },
            {
                "step": 3,
                "key": "meaning",
                "label": "Meaning",
                "prompts": [
                    "지금의 시점에서 그 순간이 주는 메시지는 무엇인가요?",
                    "그 경험을 가족에게 어떻게 전하고 싶으세요?",
                ],
            },
        ],
    ),
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Seed fixed meaning_stats for one or more receivers."
    )
    parser.add_argument(
        "--receiver-id",
        required=True,
        help="Single receiver id or comma-separated receiver ids.",
    )
    parser.add_argument(
        "--group-id",
        default="",
        help="Optional group id snapshot to store into each meaning_stats doc.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing meaning_stats documents before seeding.",
    )
    parser.add_argument(
        "--receivers-collection",
        default="receivers",
        help="Root collection name (default: receivers).",
    )
    parser.add_argument(
        "--project-id",
        default="memory-harbor",
        help="Firebase project id (default: memory-harbor).",
    )
    parser.add_argument(
        "--emulator",
        action="store_true",
        help="Use Firestore emulator instead of production Firestore.",
    )
    parser.add_argument(
        "--emulator-host",
        default="localhost:8081",
        help="Firestore emulator host:port (default: localhost:8081).",
    )
    parser.add_argument(
        "--service-account",
        default="",
        help="Path to Firebase service account JSON for production mode.",
    )
    return parser.parse_args()


def init_firestore(project_id, emulator, service_account):
    if not firebase_admin._apps:
        if emulator:
            cred = AnonymousCredentials()
            firebase_admin.initialize_app(cred, options={"projectId": project_id})
        else:
            service_account = service_account.strip()
            if service_account:
                cred = credentials.Certificate(service_account)
                firebase_admin.initialize_app(cred, options={"projectId": project_id})
            else:
                firebase_admin.initialize_app(options={"projectId": project_id})
    try:
        return firestore.client()
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Production Firestore 인증 정보를 찾지 못했습니다. "
            "`--service-account /path/to/service-account.json` 를 사용하거나 "
            "`gcloud auth application-default login` 으로 ADC를 설정하세요."
        ) from exc


def resolve_service_account_path(raw_path: str) -> str:
    path = (raw_path or "").strip()
    if path:
        if not os.path.isfile(path):
            raise RuntimeError(f"서비스 계정 파일을 찾을 수 없습니다: {path}")
        return path

    # Resolve from repo conventions when --service-account is omitted.
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / "firebase" / "memory-harbor-firebase-adminsdk-fbsvc-bbc0229e7c.json"
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return ""


def ensure_emulator_available(host_port):
    host_port = host_port.strip()
    if not host_port:
        raise RuntimeError("FIRESTORE_EMULATOR_HOST is not set.")

    if ":" not in host_port:
        raise RuntimeError(
            f"Invalid FIRESTORE_EMULATOR_HOST '{host_port}'. Expected host:port."
        )

    host, port_text = host_port.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid FIRESTORE_EMULATOR_HOST '{host_port}'. Port must be a number."
        ) from exc

    try:
        with socket.create_connection((host, port), timeout=1.5):
            return
    except OSError as exc:
        raise RuntimeError(
            f"Firestore emulator is not reachable at {host}:{port}. "
            "Start it first (e.g. `firebase emulators:start --only firestore`)."
        ) from exc


def clear_subcollection(subcollection_ref):
    for doc in subcollection_ref.stream():
        doc.reference.delete()


def seed_meaning_stats(db, receiver_id, group_id, receivers_collection, reset):
    receiver_ref = db.collection(receivers_collection).document(receiver_id)
    meaning_ref = receiver_ref.collection("meaning_stats")

    if reset:
        clear_subcollection(meaning_ref)

    for q in FIXED_MEANING_QUESTIONS:
        doc_ref = meaning_ref.document(q.meaning_id)
        payload = {
            "groupId": group_id,
            "receiverId": receiver_id,
            "meaningId": q.meaning_id,
            "topicType": "meaning",
            "isFixedQuestion": True,
            "active": True,
            "order": q.order,
            "title": q.title,
            "question": q.question,
            "interviewGuide": q.interview_guide,
            "exampleQuestions": [
                prompt
                for step in q.interview_guide
                for prompt in step.get("prompts", [])
                if isinstance(prompt, str)
            ],
            # Residence stats parity fields
            "keywords": [],
            "totalCalls": 0,
            "totalReviews": 0,
            "lastCallAt": None,
            "lastReviewAt": None,
            "aiSummary": "",
            "humanComments": [],
            # Useful for update/versioning
            "version": 1,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        # createdAt is only set once.
        existing = doc_ref.get()
        if not existing.exists:
            payload["createdAt"] = firestore.SERVER_TIMESTAMP
        doc_ref.set(payload, merge=True)


def main():
    args = parse_args()
    if args.emulator:
        os.environ["FIRESTORE_EMULATOR_HOST"] = args.emulator_host
        ensure_emulator_available(args.emulator_host)

    service_account = resolve_service_account_path(args.service_account)

    db = init_firestore(
        project_id=args.project_id,
        emulator=args.emulator,
        service_account=service_account,
    )

    receiver_ids = [rid.strip() for rid in args.receiver_id.split(",") if rid.strip()]
    if not receiver_ids:
        raise ValueError("--receiver-id 값이 비어 있습니다.")

    for rid in receiver_ids:
        seed_meaning_stats(
            db=db,
            receiver_id=rid,
            group_id=args.group_id,
            receivers_collection=args.receivers_collection,
            reset=args.reset,
        )
        print(f"seeded meaning_stats: receiver={rid}")

    print("done")


if __name__ == "__main__":
    main()

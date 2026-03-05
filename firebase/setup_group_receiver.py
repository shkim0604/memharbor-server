"""
Interactive Firestore setup script for group/receiver bootstrap.

Creates or updates:
  - groups/{groupId}
  - receivers/{receiverId}
  - (optional) receivers/{receiverId}/residence_stats/{residenceId}
  - (optional) receivers/{receiverId}/meaning_stats/{meaningId}

Usage:
  python firebase/setup_group_receiver.py
  python firebase/setup_group_receiver.py --input-json firebase/bootstrap_group_receiver.template.json
  python firebase/setup_group_receiver.py --project-id memory-harbor \
    --service-account firebase/memory-harbor-firebase-adminsdk-fbsvc-bbc0229e7c.json
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List

import firebase_admin
from firebase_admin import credentials, firestore


DEFAULT_PROJECT_ID = "memory-harbor"
DEFAULT_SERVICE_ACCOUNT = "firebase/memory-harbor-firebase-adminsdk-fbsvc-bbc0229e7c.json"


@dataclass
class SetupPayload:
    group_id: str
    group_name: str
    caregiver_uids: List[str]
    receiver_id: str
    receiver_name: str
    receiver_profile_image: str
    major_residences: List[Dict[str, str]]
    residence_stats: List[Dict[str, Any]]
    meaning_stats: List[Dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap group/receiver docs in Firestore.")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID, help="Firebase project id")
    parser.add_argument(
        "--service-account",
        default=DEFAULT_SERVICE_ACCOUNT,
        help="Path to Firebase Admin SDK service account JSON",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip final confirmation prompt and write immediately",
    )
    parser.add_argument(
        "--input-json",
        default="",
        help="Path to bootstrap JSON. If provided, group/receiver info is read from this file.",
    )
    parser.add_argument(
        "--residence-stats-json",
        default="",
        help="Optional path to residence_stats JSON array (can be used with or without --input-json).",
    )
    return parser.parse_args()


def init_db(project_id: str, service_account_path: str):
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    if not os.path.exists(service_account_path):
        raise FileNotFoundError(f"service account file not found: {service_account_path}")

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(
            credentials.Certificate(service_account_path),
            {"projectId": project_id},
        )
    return firestore.client()


def ask(prompt: str, required: bool = False, default: str = "") -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default:
            raw = default
        if required and not raw:
            print("  -> 필수 입력입니다.")
            continue
        return raw


def parse_csv_list(raw: str) -> List[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def load_json_file(path: str) -> Any:
    if not path:
        return None
    if not os.path.exists(path):
        raise FileNotFoundError(f"json file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_residence_stats(raw_items: Any, receiver_id: str, group_id: str) -> List[Dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []

    out: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        residence_id = str(item.get("residenceId") or "").strip()
        if not residence_id:
            continue
        out.append(
            {
                "residenceId": residence_id,
                "receiverId": str(item.get("receiverId") or receiver_id).strip(),
                "groupId": str(item.get("groupId") or group_id).strip(),
                "era": str(item.get("era") or "").strip(),
                "location": str(item.get("location") or "").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else [],
                "humanComments": item.get("humanComments") if isinstance(item.get("humanComments"), list) else [],
                "aiSummary": str(item.get("aiSummary") or "").strip(),
                "totalCalls": int(item.get("totalCalls") or 0),
                "lastCallAt": None,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )
    return out


def collect_major_residences() -> List[Dict[str, str]]:
    residences: List[Dict[str, str]] = []
    count_raw = ask("majorResidences 개수", default="0")
    try:
        count = max(0, int(count_raw))
    except ValueError:
        count = 0

    for idx in range(count):
        print(f"\n[majorResidence #{idx + 1}]")
        residence_id = ask("residenceId", required=True)
        era = ask("era (예: 1970s)", default="")
        location = ask("location", default="")
        detail = ask("detail", default="")
        label = ask("label (비우면 era+location 기반으로 자동)", default="")
        if not label:
            label = " ".join([x for x in [era, location] if x]).strip() or residence_id
        residences.append(
            {
                "residenceId": residence_id,
                "era": era,
                "location": location,
                "detail": detail,
                "label": label,
            }
        )
    return residences


def collect_meaning_stats(receiver_id: str, group_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    enabled = ask("meaning_stats도 생성할까요? (y/N)", default="N").lower() == "y"
    if not enabled:
        return out

    count_raw = ask("meaning_stats 개수", default="0")
    try:
        count = max(0, int(count_raw))
    except ValueError:
        count = 0

    for idx in range(count):
        print(f"\n[meaning_stats #{idx + 1}]")
        meaning_id = ask("meaningId", required=True)
        title = ask("title", required=True)
        question = ask("question", required=True)
        order_raw = ask("order", default=str(idx + 1))
        try:
            order = int(order_raw)
        except ValueError:
            order = idx + 1
        out.append(
            {
                "meaningId": meaning_id,
                "topicType": "meaning",
                "title": title,
                "question": question,
                "order": order,
                "active": True,
                "receiverId": receiver_id,
                "groupId": group_id,
                "isFixedQuestion": True,
                "interviewGuide": [],
                "exampleQuestions": [],
                "keywords": [],
                "humanComments": [],
                "totalReviews": 0,
                "totalCalls": 0,
                "lastReviewAt": None,
                "lastCallAt": None,
                "aiSummary": "",
                "version": 1,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        )
    return out


def collect_payload() -> SetupPayload:
    print("=== Group / Receiver 초기 데이터 입력 ===")
    group_id = ask("groupId", required=True)
    group_name = ask("group name", required=True)
    caregiver_uids_raw = ask("careGiverUserIds (쉼표구분)", required=True)
    caregiver_uids = parse_csv_list(caregiver_uids_raw)
    if not caregiver_uids:
        raise ValueError("careGiverUserIds must not be empty")

    receiver_id = ask("receiverId", required=True)
    receiver_name = ask("receiver name", required=True)
    receiver_profile_image = ask("receiver profileImage URL", default="")

    major_residences = collect_major_residences()
    residence_stats: List[Dict[str, Any]] = []
    meaning_stats = collect_meaning_stats(receiver_id=receiver_id, group_id=group_id)

    return SetupPayload(
        group_id=group_id,
        group_name=group_name,
        caregiver_uids=caregiver_uids,
        receiver_id=receiver_id,
        receiver_name=receiver_name,
        receiver_profile_image=receiver_profile_image,
        major_residences=major_residences,
        residence_stats=residence_stats,
        meaning_stats=meaning_stats,
    )


def collect_payload_from_json(input_json_path: str) -> SetupPayload:
    raw = load_json_file(input_json_path)
    if not isinstance(raw, dict):
        raise ValueError("--input-json must be a JSON object")

    group = raw.get("group") if isinstance(raw.get("group"), dict) else {}
    receiver = raw.get("receiver") if isinstance(raw.get("receiver"), dict) else {}

    group_id = str(group.get("groupId") or "").strip()
    group_name = str(group.get("name") or "").strip()
    caregiver_uids = [str(x).strip() for x in (group.get("careGiverUserIds") or []) if str(x).strip()]

    receiver_id = str(receiver.get("receiverId") or "").strip()
    receiver_name = str(receiver.get("name") or "").strip()
    receiver_profile_image = str(receiver.get("profileImage") or "").strip()
    major_residences = receiver.get("majorResidences") if isinstance(receiver.get("majorResidences"), list) else []

    if not group_id or not group_name or not caregiver_uids:
        raise ValueError("group.groupId, group.name, group.careGiverUserIds are required in input json")
    if not receiver_id or not receiver_name:
        raise ValueError("receiver.receiverId and receiver.name are required in input json")

    residence_stats = normalize_residence_stats(raw.get("residenceStats"), receiver_id=receiver_id, group_id=group_id)

    meaning_stats_raw = raw.get("meaningStats")
    meaning_stats: List[Dict[str, Any]] = []
    if isinstance(meaning_stats_raw, list):
        for row in meaning_stats_raw:
            if not isinstance(row, dict):
                continue
            meaning_id = str(row.get("meaningId") or "").strip()
            if not meaning_id:
                continue
            meaning_stats.append(
                {
                    "meaningId": meaning_id,
                    "topicType": "meaning",
                    "title": str(row.get("title") or "").strip(),
                    "question": str(row.get("question") or "").strip(),
                    "order": int(row.get("order") or 0),
                    "active": bool(row.get("active", True)),
                    "receiverId": str(row.get("receiverId") or receiver_id).strip(),
                    "groupId": str(row.get("groupId") or group_id).strip(),
                    "isFixedQuestion": bool(row.get("isFixedQuestion", True)),
                    "interviewGuide": row.get("interviewGuide") if isinstance(row.get("interviewGuide"), list) else [],
                    "exampleQuestions": row.get("exampleQuestions") if isinstance(row.get("exampleQuestions"), list) else [],
                    "keywords": row.get("keywords") if isinstance(row.get("keywords"), list) else [],
                    "humanComments": row.get("humanComments") if isinstance(row.get("humanComments"), list) else [],
                    "totalReviews": int(row.get("totalReviews") or 0),
                    "totalCalls": int(row.get("totalCalls") or 0),
                    "lastReviewAt": None,
                    "lastCallAt": None,
                    "aiSummary": str(row.get("aiSummary") or "").strip(),
                    "version": int(row.get("version") or 1),
                    "createdAt": firestore.SERVER_TIMESTAMP,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                }
            )

    return SetupPayload(
        group_id=group_id,
        group_name=group_name,
        caregiver_uids=caregiver_uids,
        receiver_id=receiver_id,
        receiver_name=receiver_name,
        receiver_profile_image=receiver_profile_image,
        major_residences=major_residences,
        residence_stats=residence_stats,
        meaning_stats=meaning_stats,
    )


def apply_residence_stats_json(payload: SetupPayload, residence_stats_json_path: str) -> SetupPayload:
    if not residence_stats_json_path:
        return payload
    raw = load_json_file(residence_stats_json_path)
    residence_stats = normalize_residence_stats(raw, receiver_id=payload.receiver_id, group_id=payload.group_id)
    payload.residence_stats = residence_stats
    return payload


def preview(payload: SetupPayload) -> None:
    group_doc = {
        "groupId": payload.group_id,
        "name": payload.group_name,
        "receiverId": payload.receiver_id,
        "careGiverUserIds": payload.caregiver_uids,
    }
    receiver_doc = {
        "receiverId": payload.receiver_id,
        "groupId": payload.group_id,
        "name": payload.receiver_name,
        "profileImage": payload.receiver_profile_image,
        "majorResidences": payload.major_residences,
    }

    print("\n=== 저장 예정 데이터 ===")
    print("[groups/{groupId}]")
    print(json.dumps(group_doc, ensure_ascii=False, indent=2))
    print("\n[receivers/{receiverId}]")
    print(json.dumps(receiver_doc, ensure_ascii=False, indent=2))
    if payload.residence_stats:
        print(f"\n[receivers/{payload.receiver_id}/residence_stats/*] count={len(payload.residence_stats)}")
        for row in payload.residence_stats:
            print(f"- {row['residenceId']}: era={row['era']}, location={row['location']}, totalCalls={row['totalCalls']}")
    if payload.meaning_stats:
        print(f"\n[receivers/{payload.receiver_id}/meaning_stats/*] count={len(payload.meaning_stats)}")
        for row in payload.meaning_stats:
            print(f"- {row['meaningId']}: title={row['title']}, order={row['order']}")


def write_payload(db, payload: SetupPayload) -> None:
    now = firestore.SERVER_TIMESTAMP

    group_ref = db.collection("groups").document(payload.group_id)
    group_ref.set(
        {
            "groupId": payload.group_id,
            "name": payload.group_name,
            "receiverId": payload.receiver_id,
            "careGiverUserIds": payload.caregiver_uids,
            "updatedAt": now,
        },
        merge=True,
    )

    receiver_ref = db.collection("receivers").document(payload.receiver_id)
    receiver_ref.set(
        {
            "receiverId": payload.receiver_id,
            "groupId": payload.group_id,
            "name": payload.receiver_name,
            "profileImage": payload.receiver_profile_image,
            "majorResidences": payload.major_residences,
            "updatedAt": now,
        },
        merge=True,
    )

    for row in payload.meaning_stats:
        meaning_id = row["meaningId"]
        receiver_ref.collection("meaning_stats").document(meaning_id).set(row, merge=True)

    for row in payload.residence_stats:
        residence_id = row["residenceId"]
        receiver_ref.collection("residence_stats").document(residence_id).set(row, merge=True)


def main() -> None:
    args = parse_args()
    db = init_db(project_id=args.project_id, service_account_path=args.service_account)
    if args.input_json:
        payload = collect_payload_from_json(args.input_json)
    else:
        payload = collect_payload()
    payload = apply_residence_stats_json(payload, args.residence_stats_json)
    preview(payload)

    if not args.yes:
        confirm = ask("\nFirestore에 저장할까요? (y/N)", default="N").lower()
        if confirm != "y":
            print("취소되었습니다. 저장하지 않았습니다.")
            return

    write_payload(db, payload)
    print("\n저장 완료:")
    print(f"- groups/{payload.group_id}")
    print(f"- receivers/{payload.receiver_id}")
    if payload.residence_stats:
        print(f"- receivers/{payload.receiver_id}/residence_stats ({len(payload.residence_stats)} docs)")
    if payload.meaning_stats:
        print(f"- receivers/{payload.receiver_id}/meaning_stats ({len(payload.meaning_stats)} docs)")


if __name__ == "__main__":
    main()

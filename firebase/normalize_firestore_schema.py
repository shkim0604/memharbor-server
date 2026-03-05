"""
Normalize live Firestore documents to the canonical schema used by this server.

Default mode is dry-run. Use --apply to write updates.

Examples:
  python firebase/normalize_firestore_schema.py
  python firebase/normalize_firestore_schema.py --apply
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import firebase_admin
from firebase_admin import credentials, firestore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Firestore schema consistency.")
    parser.add_argument("--project-id", default="memory-harbor", help="Firebase project id")
    parser.add_argument(
        "--service-account",
        default="firebase/memory-harbor-firebase-adminsdk-fbsvc-bbc0229e7c.json",
        help="Path to service account JSON",
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    return parser.parse_args()


def init_db(project_id: str, service_account: str):
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    if not os.path.exists(service_account):
        raise FileNotFoundError(f"service account not found: {service_account}")
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(
            credentials.Certificate(service_account),
            {"projectId": project_id},
        )
    return firestore.client()


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def maybe_set(update: Dict[str, Any], key: str, value: Any) -> None:
    if key not in update:
        update[key] = value


def normalize_calls(doc_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    update: Dict[str, Any] = {}

    if doc_data.get("status") == "completed":
        update["status"] = "ended"

    created_at = doc_data.get("createdAt")
    if isinstance(created_at, str):
        parsed = parse_dt(created_at)
        if parsed:
            update["createdAt"] = parsed
    elif created_at is None:
        fallback = parse_dt(doc_data.get("startedAt")) or parse_dt(doc_data.get("endedAt"))
        if fallback:
            update["createdAt"] = fallback

    started_at = doc_data.get("startedAt")
    if isinstance(started_at, str):
        parsed = parse_dt(started_at)
        if parsed and doc_data.get("answeredAt") is None:
            update["answeredAt"] = parsed

    # Legacy fields not used by API schema.
    if "channelId" in doc_data:
        update["channelId"] = firestore.DELETE_FIELD
    if "isConfirmed" in doc_data:
        update["isConfirmed"] = firestore.DELETE_FIELD
    if "startedAt" in doc_data:
        update["startedAt"] = firestore.DELETE_FIELD

    return update, bool(update)


def normalize_user(doc_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    update: Dict[str, Any] = {}

    for key in ("createdAt", "lastActivityAt"):
        if isinstance(doc_data.get(key), str):
            parsed = parse_dt(doc_data.get(key))
            if parsed:
                update[key] = parsed

    return update, bool(update)


def normalize_deletion_request(doc_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    update: Dict[str, Any] = {}
    if isinstance(doc_data.get("emailSentAt"), str):
        parsed = parse_dt(doc_data.get("emailSentAt"))
        if parsed:
            update["emailSentAt"] = parsed
    return update, bool(update)


def normalize_review(doc_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    update: Dict[str, Any] = {}

    call_memo = str(doc_data.get("callMemo") or "").strip()
    legacy_comment = str(doc_data.get("comment") or "").strip()
    if not call_memo and legacy_comment:
        update["callMemo"] = legacy_comment
        call_memo = legacy_comment

    emotion_word = str(doc_data.get("emotionWord") or "").strip()
    legacy_mood = str(doc_data.get("mood") or "").strip()
    if not emotion_word and legacy_mood:
        update["emotionWord"] = legacy_mood

    mentioned = doc_data.get("mentionedResidences")
    if not isinstance(mentioned, list):
        update["mentionedResidences"] = []
        mentioned = []

    if "humanSummary" not in doc_data:
        maybe_set(update, "humanSummary", call_memo)
    if "humanKeywords" not in doc_data:
        maybe_set(update, "humanKeywords", mentioned)
    if "mood" not in doc_data:
        maybe_set(update, "mood", str(doc_data.get("emotionWord") or "").strip())
    if "comment" not in doc_data:
        maybe_set(update, "comment", call_memo)

    # Ensure new review schema keys exist.
    maybe_set(update, "selectedTopicType", str(doc_data.get("selectedTopicType") or ""))
    maybe_set(update, "selectedTopicId", str(doc_data.get("selectedTopicId") or ""))
    maybe_set(update, "selectedTopicLabel", str(doc_data.get("selectedTopicLabel") or ""))
    maybe_set(update, "selectedTopicQuestion", str(doc_data.get("selectedTopicQuestion") or ""))
    maybe_set(update, "selectedResidenceId", str(doc_data.get("selectedResidenceId") or ""))
    maybe_set(update, "selectedMeaningId", str(doc_data.get("selectedMeaningId") or ""))
    maybe_set(update, "requiredQuestionDurationSec", int(doc_data.get("requiredQuestionDurationSec") or 0))
    maybe_set(update, "requiredStepOpenedAt", str(doc_data.get("requiredStepOpenedAt") or ""))

    return update, bool(update)


def run(apply_changes: bool, project_id: str, service_account: str) -> None:
    db = init_db(project_id, service_account)
    mode = "APPLY" if apply_changes else "DRY-RUN"
    print(f"[{mode}] project={project_id}")

    totals = {
        "calls": 0,
        "users": 0,
        "userDeletionRequests": 0,
        "reviews": 0,
    }

    for doc in db.collection("calls").stream():
        data = doc.to_dict() or {}
        update, needed = normalize_calls(data)
        if needed:
            totals["calls"] += 1
            if apply_changes:
                doc.reference.set(update, merge=True)

        for rev in doc.reference.collection("reviews").stream():
            review_data = rev.to_dict() or {}
            rev_update, rev_needed = normalize_review(review_data)
            if rev_needed:
                totals["reviews"] += 1
                if apply_changes:
                    rev.reference.set(rev_update, merge=True)

    for doc in db.collection("users").stream():
        data = doc.to_dict() or {}
        update, needed = normalize_user(data)
        if needed:
            totals["users"] += 1
            if apply_changes:
                doc.reference.set(update, merge=True)

    for doc in db.collection("userDeletionRequests").stream():
        data = doc.to_dict() or {}
        update, needed = normalize_deletion_request(data)
        if needed:
            totals["userDeletionRequests"] += 1
            if apply_changes:
                doc.reference.set(update, merge=True)

    print("updated_docs:", totals)


if __name__ == "__main__":
    args = parse_args()
    run(
        apply_changes=args.apply,
        project_id=args.project_id,
        service_account=args.service_account,
    )

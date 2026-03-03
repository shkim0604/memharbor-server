import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..firebase_service import firestore_service

logger = logging.getLogger("api")

UPSERT_ALLOWED_KEYS = {
    "callId",
    "existingReviewId",
    "listeningScore",
    "notFullyHeardMoment",
    "nextSessionTry",
    "emotionWord",
    "emotionSource",
    "smallReset",
    "callMemo",
    "selectedTopicType",
    "selectedTopicId",
    "selectedTopicLabel",
    "selectedTopicQuestion",
    "selectedResidenceId",
    "selectedMeaningId",
    "mentionedResidences",
    "requiredQuestionDurationSec",
    "requiredStepOpenedAt",
}


def _ok(payload: Dict[str, Any]) -> JsonResponse:
    body = {"ok": True}
    body.update(payload)
    return JsonResponse(body)


def _err(status: int, code: str, message: str, extra: Optional[Dict[str, Any]] = None) -> JsonResponse:
    body: Dict[str, Any] = {"ok": False, "code": code, "message": message}
    if extra:
        body.update(extra)
    return JsonResponse(body, status=status)


def _firebase_uid(request) -> Optional[str]:
    return getattr(request, "firebase_uid", None)


def _request_id(request) -> str:
    rid = request.headers.get("X-Request-Id") or request.headers.get("X-Correlation-Id")
    return rid.strip() if rid else str(uuid.uuid4())


def _json_body(request) -> Tuple[Optional[Dict[str, Any]], Optional[JsonResponse]]:
    try:
        raw = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, _err(400, "invalid_json", "JSON body must be an object.")
        return data, None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _err(400, "invalid_json", "Malformed JSON body.")


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_list_str(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_dt(value: Any) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.get_current_timezone())
    if hasattr(value, "to_datetime"):
        value = value.to_datetime()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                if text.endswith("Z"):
                    text = text.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(text)
                if timezone.is_naive(parsed):
                    return timezone.make_aware(parsed, timezone.get_current_timezone())
                return timezone.localtime(parsed)
            except ValueError:
                pass
    return datetime.min.replace(tzinfo=timezone.get_current_timezone())


def _iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "to_datetime"):
        value = value.to_datetime()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return ""


def _log_result(
    name: str,
    request_id: str,
    uid: str,
    group_id: str = "",
    call_id: str = "",
    started_at: Optional[datetime] = None,
    status: int = 200,
) -> None:
    now = timezone.now()
    started = started_at or now
    latency_ms = int((now - started).total_seconds() * 1000)
    logger.info(
        "[%s] requestId=%s uid=%s group_id=%s call_id=%s latency_ms=%s status=%s",
        name,
        request_id,
        uid or "",
        group_id or "",
        call_id or "",
        latency_ms,
        status,
    )


def _group_members(group_data: Dict[str, Any]) -> Set[str]:
    members = group_data.get("careGiverUserIds") or group_data.get("caregiverUserIds") or []
    if not isinstance(members, list):
        return set()
    return {str(v).strip() for v in members if str(v).strip()}


def _validate_method(request, expected: str) -> Optional[JsonResponse]:
    if request.method != expected:
        return _err(400, "invalid_method", f"Expected {expected} request.")
    return None


def _find_my_review_doc(reviews_ref, uid: str):
    try:
        from firebase_admin import firestore as fb_firestore

        docs = list(
            reviews_ref.where("writerUserId", "==", uid)
            .order_by("createdAt", direction=fb_firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if docs:
            return docs[0]
    except Exception:
        pass

    docs = []
    for doc in reviews_ref.stream():
        data = doc.to_dict() or {}
        if _as_str(data.get("writerUserId")) == uid:
            docs.append(doc)
    if not docs:
        return None
    docs.sort(key=lambda d: _to_dt((d.to_dict() or {}).get("createdAt")), reverse=True)
    return docs[0]


def _load_call_and_authorize(db, call_id: str, uid: str):
    call_ref = db.collection("calls").document(call_id)
    call_snap = call_ref.get()
    if not call_snap.exists:
        return None, None, None, _err(404, "call_not_found", "Call not found.")

    call_data = call_snap.to_dict() or {}
    group_id = _as_str(call_data.get("groupId"))
    if not group_id:
        return None, None, None, _err(404, "group_not_found", "Group not found.")

    group_snap = db.collection("groups").document(group_id).get()
    if not group_snap.exists:
        return None, None, None, _err(404, "group_not_found", "Group not found.")

    group_data = group_snap.to_dict() or {}
    if uid not in _group_members(group_data):
        return None, None, None, _err(403, "forbidden", "No permission for this group.")

    return call_ref, call_data, group_id, None


def _topic_option_from_residence(row: Dict[str, Any]) -> Dict[str, Any]:
    residence_id = _as_str(row.get("residenceId"))
    era = _as_str(row.get("era"))
    location = _as_str(row.get("location"))
    detail = _as_str(row.get("detail"))
    label = _as_str(row.get("label"))
    if not label:
        label = " ".join([v for v in [era, location] if v]).strip() or residence_id
    return {
        "topicType": "residence",
        "topicId": residence_id,
        "label": label,
        "question": "",
        "residencePayload": {
            "residenceId": residence_id,
            "era": era,
            "location": location,
            "detail": detail,
        },
    }


def _topic_option_from_meaning(doc_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "topicType": "meaning",
        "topicId": _as_str(row.get("meaningId"), doc_id),
        "label": _as_str(row.get("title")),
        "question": _as_str(row.get("question")),
        "residencePayload": {},
    }


def _normalize_my_review(review_id: str, review_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reviewId": _as_str(review_id),
        "listeningScore": _as_int(review_data.get("listeningScore"), 0),
        "notFullyHeardMoment": _as_str(review_data.get("notFullyHeardMoment")),
        "nextSessionTry": _as_str(review_data.get("nextSessionTry")),
        "emotionWord": _as_str(review_data.get("emotionWord")),
        "emotionSource": _as_str(review_data.get("emotionSource")),
        "smallReset": _as_str(review_data.get("smallReset")),
        "selectedTopicType": _as_str(review_data.get("selectedTopicType")),
        "selectedTopicId": _as_str(review_data.get("selectedTopicId")),
        "selectedResidenceId": _as_str(review_data.get("selectedResidenceId")),
        "selectedMeaningId": _as_str(review_data.get("selectedMeaningId")),
        "mentionedResidences": _as_list_str(review_data.get("mentionedResidences")),
    }


@csrf_exempt
def reviews_feed(request):
    started_at = timezone.now()
    request_id = _request_id(request)
    uid = _firebase_uid(request) or ""
    group_id = _as_str(request.GET.get("group_id"))
    call_id = ""
    status_code = 200

    try:
        invalid_method = _validate_method(request, "GET")
        if invalid_method:
            status_code = invalid_method.status_code
            return invalid_method
        if not uid:
            status_code = 401
            return _err(401, "unauthorized", "Authentication required.")
        if not group_id:
            status_code = 400
            return _err(400, "missing_group_id", "group_id is required.")

        limit = _as_int(request.GET.get("limit"), 10)
        cursor = _as_str(request.GET.get("cursor"))
        if limit <= 0 or limit > 50:
            status_code = 400
            return _err(400, "invalid_limit", "limit must be in range 1..50.")

        db = firestore_service.db
        if not db:
            status_code = 500
            return _err(500, "firestore_unavailable", "Firestore unavailable.")

        group_snap = db.collection("groups").document(group_id).get()
        if not group_snap.exists:
            status_code = 404
            return _err(404, "group_not_found", "Group not found.")
        if uid not in _group_members(group_snap.to_dict() or {}):
            status_code = 403
            return _err(403, "forbidden", "No permission for this group.")

        from firebase_admin import firestore as fb_firestore

        query = (
            db.collection("calls")
            .where("groupId", "==", group_id)
            .where("reviewCount", ">", 0)
            .order_by("reviewCount", direction=fb_firestore.Query.DESCENDING)
            .order_by("createdAt", direction=fb_firestore.Query.DESCENDING)
        )

        if cursor:
            cursor_doc = db.collection("calls").document(cursor).get()
            if not cursor_doc.exists:
                status_code = 400
                return _err(400, "invalid_cursor", "cursor is invalid.")
            cursor_data = cursor_doc.to_dict() or {}
            if _as_str(cursor_data.get("groupId")) != group_id:
                status_code = 400
                return _err(400, "invalid_cursor", "cursor is invalid.")
            query = query.start_after(cursor_doc)

        call_docs = list(query.limit(limit + 1).stream())
        page_calls = call_docs[:limit]
        has_more = len(call_docs) > limit

        items: List[Dict[str, Any]] = []
        for call_doc in page_calls:
            call_data = call_doc.to_dict() or {}
            this_call_id = _as_str(call_data.get("callId"), call_doc.id)
            call_id = this_call_id
            review_docs = list(
                call_doc.reference.collection("reviews")
                .order_by("createdAt", direction=fb_firestore.Query.DESCENDING)
                .stream()
            )
            for review_doc in review_docs:
                row = review_doc.to_dict() or {}
                items.append(
                    {
                        "reviewId": _as_str(review_doc.id),
                        "callId": _as_str(row.get("callId"), this_call_id),
                        "writerUserId": _as_str(row.get("writerUserId")),
                        "writerNameSnapshot": _as_str(row.get("writerNameSnapshot")),
                        "mentionedResidences": _as_list_str(row.get("mentionedResidences")),
                        "humanSummary": _as_str(row.get("humanSummary")),
                        "humanKeywords": _as_list_str(row.get("humanKeywords")),
                        "mood": _as_str(row.get("mood")),
                        "comment": _as_str(row.get("comment")),
                        "createdAt": _iso_or_empty(row.get("createdAt")),
                    }
                )

        items.sort(key=lambda x: _to_dt(x.get("createdAt")), reverse=True)
        next_cursor = ""
        if has_more and page_calls:
            last_call_data = page_calls[-1].to_dict() or {}
            next_cursor = _as_str(last_call_data.get("callId"), page_calls[-1].id)

        status_code = 200
        return JsonResponse({"items": items, "nextCursor": next_cursor, "hasMore": has_more})
    except Exception as exc:
        logger.exception("[REVIEWS/FEED] failed: requestId=%s error=%s", request_id, exc)
        status_code = 500
        return _err(500, "internal_error", "Internal server error.")
    finally:
        _log_result("REVIEWS/FEED", request_id, uid, group_id=group_id, call_id=call_id, started_at=started_at, status=status_code)


@csrf_exempt
def reviews_context(request):
    started_at = timezone.now()
    request_id = _request_id(request)
    uid = _firebase_uid(request) or ""
    call_id = _as_str(request.GET.get("call_id"))
    group_id = ""
    status_code = 200

    try:
        invalid_method = _validate_method(request, "GET")
        if invalid_method:
            status_code = invalid_method.status_code
            return invalid_method
        if not uid:
            status_code = 401
            return _err(401, "unauthorized", "Authentication required.")
        if not call_id:
            status_code = 400
            return _err(400, "missing_call_id", "call_id is required.")

        db = firestore_service.db
        if not db:
            status_code = 500
            return _err(500, "firestore_unavailable", "Firestore unavailable.")

        call_ref, call_data, group_id, auth_error = _load_call_and_authorize(db, call_id, uid)
        if auth_error:
            status_code = auth_error.status_code
            return auth_error

        receiver_id = _as_str(call_data.get("receiverId"))
        topic_options: List[Dict[str, Any]] = []

        if receiver_id:
            receiver_doc = db.collection("receivers").document(receiver_id).get()
            receiver_data = receiver_doc.to_dict() if receiver_doc.exists else {}
            major_residences = receiver_data.get("majorResidences")
            if isinstance(major_residences, list):
                for row in major_residences:
                    if isinstance(row, dict):
                        topic_options.append(_topic_option_from_residence(row))

            try:
                meaning_docs = list(
                    db.collection("receivers")
                    .document(receiver_id)
                    .collection("meaning_stats")
                    .where("active", "==", True)
                    .order_by("order")
                    .stream()
                )
            except Exception:
                meaning_docs = list(
                    db.collection("receivers").document(receiver_id).collection("meaning_stats").stream()
                )
                meaning_docs = [
                    d for d in meaning_docs if bool((d.to_dict() or {}).get("active", False))
                ]
                meaning_docs.sort(key=lambda d: _as_int((d.to_dict() or {}).get("order"), 0))

            for doc in meaning_docs:
                topic_options.append(_topic_option_from_meaning(doc.id, doc.to_dict() or {}))

        status_code = 200
        return _ok(
            {
                "humanNotes": _as_str(call_data.get("humanNotes")),
                "selectedTopicType": _as_str(call_data.get("selectedTopicType")),
                "selectedTopicId": _as_str(call_data.get("selectedTopicId")),
                "selectedResidenceId": _as_str(call_data.get("selectedResidenceId")),
                "selectedMeaningId": _as_str(call_data.get("selectedMeaningId")),
                "topicOptions": topic_options,
            }
        )
    except Exception as exc:
        logger.exception("[REVIEWS/CONTEXT] failed: requestId=%s error=%s", request_id, exc)
        status_code = 500
        return _err(500, "internal_error", "Internal server error.")
    finally:
        _log_result("REVIEWS/CONTEXT", request_id, uid, group_id=group_id, call_id=call_id, started_at=started_at, status=status_code)


@csrf_exempt
def reviews_my(request):
    started_at = timezone.now()
    request_id = _request_id(request)
    uid = _firebase_uid(request) or ""
    call_id = _as_str(request.GET.get("call_id"))
    group_id = ""
    status_code = 200

    try:
        invalid_method = _validate_method(request, "GET")
        if invalid_method:
            status_code = invalid_method.status_code
            return invalid_method
        if not uid:
            status_code = 401
            return _err(401, "unauthorized", "Authentication required.")
        if not call_id:
            status_code = 400
            return _err(400, "missing_call_id", "call_id is required.")

        db = firestore_service.db
        if not db:
            status_code = 500
            return _err(500, "firestore_unavailable", "Firestore unavailable.")

        call_ref, call_data, group_id, auth_error = _load_call_and_authorize(db, call_id, uid)
        if auth_error:
            status_code = auth_error.status_code
            return auth_error
        _ = call_data

        review_doc = _find_my_review_doc(call_ref.collection("reviews"), uid)
        if not review_doc:
            status_code = 404
            return _err(404, "review_not_found", "Review not found.")

        review_data = review_doc.to_dict() or {}
        status_code = 200
        return _ok(_normalize_my_review(review_doc.id, review_data))
    except Exception as exc:
        logger.exception("[REVIEWS/MY] failed: requestId=%s error=%s", request_id, exc)
        status_code = 500
        return _err(500, "internal_error", "Internal server error.")
    finally:
        _log_result("REVIEWS/MY", request_id, uid, group_id=group_id, call_id=call_id, started_at=started_at, status=status_code)


def _validate_upsert_payload(data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[JsonResponse]]:
    unknown_keys = sorted([k for k in data.keys() if k not in UPSERT_ALLOWED_KEYS])
    if unknown_keys:
        return None, _err(400, "invalid_fields", "Unknown fields provided.", {"fields": unknown_keys})

    call_id = _as_str(data.get("callId"))
    if not call_id:
        return None, _err(400, "missing_call_id", "callId is required.")

    if "mentionedResidences" in data and not isinstance(data.get("mentionedResidences"), list):
        return None, _err(400, "invalid_field_type", "mentionedResidences must be an array.", {"field": "mentionedResidences"})

    normalized = {
        "callId": call_id,
        "existingReviewId": _as_str(data.get("existingReviewId")),
        "listeningScore": _as_int(data.get("listeningScore"), 0),
        "notFullyHeardMoment": _as_str(data.get("notFullyHeardMoment")),
        "nextSessionTry": _as_str(data.get("nextSessionTry")),
        "emotionWord": _as_str(data.get("emotionWord")),
        "emotionSource": _as_str(data.get("emotionSource")),
        "smallReset": _as_str(data.get("smallReset")),
        "callMemo": _as_str(data.get("callMemo")),
        "selectedTopicType": _as_str(data.get("selectedTopicType")),
        "selectedTopicId": _as_str(data.get("selectedTopicId")),
        "selectedTopicLabel": _as_str(data.get("selectedTopicLabel")),
        "selectedTopicQuestion": _as_str(data.get("selectedTopicQuestion")),
        "selectedResidenceId": _as_str(data.get("selectedResidenceId")),
        "selectedMeaningId": _as_str(data.get("selectedMeaningId")),
        "mentionedResidences": _as_list_str(data.get("mentionedResidences")),
        "requiredQuestionDurationSec": _as_int(data.get("requiredQuestionDurationSec"), 0),
        "requiredStepOpenedAt": _as_str(data.get("requiredStepOpenedAt")),
    }
    return normalized, None


def _selected_topic_ref(payload: Dict[str, Any]) -> Tuple[str, str]:
    topic_type = _as_str(payload.get("selectedTopicType"))
    if topic_type == "residence":
        return "residence", _as_str(payload.get("selectedResidenceId") or payload.get("selectedTopicId"))
    if topic_type == "meaning":
        return "meaning", _as_str(payload.get("selectedMeaningId") or payload.get("selectedTopicId"))
    return "", ""


def _decrement_counter(transaction, ref, field_name: str):
    snap = ref.get(transaction=transaction)
    current = _as_int((snap.to_dict() or {}).get(field_name), 0) if snap.exists else 0
    transaction.set(ref, {field_name: max(current - 1, 0), "updatedAt": timezone.now()}, merge=True)


@csrf_exempt
def reviews_upsert(request):
    started_at = timezone.now()
    request_id = _request_id(request)
    uid = _firebase_uid(request) or ""
    call_id = ""
    group_id = ""
    status_code = 200

    try:
        invalid_method = _validate_method(request, "POST")
        if invalid_method:
            status_code = invalid_method.status_code
            return invalid_method
        if not uid:
            status_code = 401
            return _err(401, "unauthorized", "Authentication required.")

        data, parse_error = _json_body(request)
        if parse_error:
            status_code = parse_error.status_code
            return parse_error

        normalized, validation_error = _validate_upsert_payload(data or {})
        if validation_error:
            status_code = validation_error.status_code
            return validation_error

        call_id = normalized["callId"]
        db = firestore_service.db
        if not db:
            status_code = 500
            return _err(500, "firestore_unavailable", "Firestore unavailable.")

        from firebase_admin import firestore as fb_firestore

        call_ref = db.collection("calls").document(call_id)
        now = timezone.now()

        @fb_firestore.transactional
        def _txn(transaction):
            nonlocal group_id

            call_snap = call_ref.get(transaction=transaction)
            if not call_snap.exists:
                return {"ok": False, "error": "call_not_found"}
            call_data = call_snap.to_dict() or {}
            group_id = _as_str(call_data.get("groupId"))
            receiver_id = _as_str(call_data.get("receiverId"))
            if not group_id:
                return {"ok": False, "error": "group_not_found"}

            group_snap = db.collection("groups").document(group_id).get(transaction=transaction)
            if not group_snap.exists:
                return {"ok": False, "error": "group_not_found"}
            if uid not in _group_members(group_snap.to_dict() or {}):
                return {"ok": False, "error": "forbidden"}

            reviews_ref = call_ref.collection("reviews")
            existing_review_id = normalized.get("existingReviewId") or ""
            existing_snap = None

            if existing_review_id:
                existing_snap = reviews_ref.document(existing_review_id).get(transaction=transaction)
                if not existing_snap.exists:
                    return {"ok": False, "error": "review_not_found"}
                existing_data = existing_snap.to_dict() or {}
                if _as_str(existing_data.get("writerUserId")) != uid:
                    return {"ok": False, "error": "forbidden"}
                review_ref = reviews_ref.document(existing_review_id)
                review_id = existing_review_id
                mode = "edit"
            else:
                existing_doc = _find_my_review_doc(reviews_ref, uid)
                if existing_doc:
                    existing_snap = existing_doc
                    review_ref = reviews_ref.document(existing_doc.id)
                    review_id = existing_doc.id
                    mode = "edit"
                else:
                    review_id = str(uuid.uuid4())
                    review_ref = reviews_ref.document(review_id)
                    mode = "create"

            existing_data = existing_snap.to_dict() if existing_snap and existing_snap.exists else {}
            prev_topic_type, prev_topic_id = _selected_topic_ref(existing_data or {})
            next_topic_type, next_topic_id = _selected_topic_ref(normalized)

            review_doc = {
                "callId": call_id,
                "writerUserId": uid,
                "listeningScore": normalized["listeningScore"],
                "notFullyHeardMoment": normalized["notFullyHeardMoment"],
                "nextSessionTry": normalized["nextSessionTry"],
                "emotionWord": normalized["emotionWord"],
                "emotionSource": normalized["emotionSource"],
                "smallReset": normalized["smallReset"],
                "callMemo": normalized["callMemo"],
                "selectedTopicType": normalized["selectedTopicType"],
                "selectedTopicId": normalized["selectedTopicId"],
                "selectedTopicLabel": normalized["selectedTopicLabel"],
                "selectedTopicQuestion": normalized["selectedTopicQuestion"],
                "selectedResidenceId": normalized["selectedResidenceId"],
                "selectedMeaningId": normalized["selectedMeaningId"],
                "mentionedResidences": normalized["mentionedResidences"],
                "requiredQuestionDurationSec": normalized["requiredQuestionDurationSec"],
                "requiredStepOpenedAt": normalized["requiredStepOpenedAt"],
                "updatedAt": now,
                "createdAt": existing_data.get("createdAt") or now,
            }
            transaction.set(review_ref, review_doc, merge=True)

            call_updates: Dict[str, Any] = {
                "lastReviewAt": now,
                "humanNotes": normalized["callMemo"],
                "selectedTopicType": normalized["selectedTopicType"],
                "selectedTopicId": normalized["selectedTopicId"],
                "selectedTopicLabel": normalized["selectedTopicLabel"],
                "selectedTopicQuestion": normalized["selectedTopicQuestion"],
                "selectedResidenceId": normalized["selectedResidenceId"],
                "selectedMeaningId": normalized["selectedMeaningId"],
            }
            if mode == "create":
                call_updates["reviewCount"] = fb_firestore.Increment(1)
            transaction.set(call_ref, call_updates, merge=True)

            if receiver_id:
                receiver_ref = db.collection("receivers").document(receiver_id)
                if prev_topic_type and prev_topic_id and (prev_topic_type != next_topic_type or prev_topic_id != next_topic_id):
                    prev_col = "residence_stats" if prev_topic_type == "residence" else "meaning_stats"
                    prev_ref = receiver_ref.collection(prev_col).document(prev_topic_id)
                    _decrement_counter(transaction, prev_ref, "totalCalls")
                if next_topic_type and next_topic_id and (prev_topic_type != next_topic_type or prev_topic_id != next_topic_id):
                    next_col = "residence_stats" if next_topic_type == "residence" else "meaning_stats"
                    next_ref = receiver_ref.collection(next_col).document(next_topic_id)
                    transaction.set(
                        next_ref,
                        {"totalCalls": fb_firestore.Increment(1), "lastCallAt": now, "updatedAt": now},
                        merge=True,
                    )

            log_ref = call_ref.collection("write_logs").document(str(uuid.uuid4()))
            transaction.set(
                log_ref,
                {
                    "requestId": request_id,
                    "uid": uid,
                    "callId": call_id,
                    "groupId": group_id,
                    "reviewId": review_id,
                    "mode": mode,
                    "createdAt": now,
                },
                merge=True,
            )

            return {"ok": True, "reviewId": review_id, "mode": mode}

        result = _txn(db.transaction())
        if not result.get("ok"):
            error = result.get("error")
            if error == "call_not_found":
                status_code = 404
                return _err(404, "call_not_found", "Call not found.")
            if error == "group_not_found":
                status_code = 404
                return _err(404, "group_not_found", "Group not found.")
            if error == "review_not_found":
                status_code = 404
                return _err(404, "review_not_found", "Review not found.")
            if error == "forbidden":
                status_code = 403
                return _err(403, "forbidden", "No permission for this resource.")
            status_code = 500
            return _err(500, "upsert_failed", "Failed to upsert review.")

        status_code = 200
        return _ok(
            {
                "reviewId": _as_str(result.get("reviewId")),
                "mode": _as_str(result.get("mode")),
            }
        )
    except Exception as exc:
        logger.exception("[REVIEWS/UPSERT] failed: requestId=%s error=%s", request_id, exc)
        status_code = 500
        return _err(500, "internal_error", "Internal server error.")
    finally:
        _log_result("REVIEWS/UPSERT", request_id, uid, group_id=group_id, call_id=call_id, started_at=started_at, status=status_code)

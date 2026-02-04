import logging
import threading
import uuid
from datetime import datetime, timedelta

from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from ..constants import MISSED_TIMEOUT_SECONDS
from ..firebase_service import firestore_service
from ..http import json_body
from ..push_service import push_service
from ..utils import run_async, generate_channel_name, normalize_datetime

logger = logging.getLogger("api")

_missed_timers = {}
_missed_timers_lock = threading.Lock()


def _schedule_missed_timeout(call_id: str, timeout_seconds: int = MISSED_TIMEOUT_SECONDS) -> None:
    def _timeout_handler():
        try:
            call_record = firestore_service.get_call_record(call_id)
            if not call_record or call_record.get("status") != "pending":
                return
            firestore_service.update_call_status(call_id, "missed", endedAt=datetime.utcnow())
        finally:
            with _missed_timers_lock:
                _missed_timers.pop(call_id, None)

    with _missed_timers_lock:
        existing = _missed_timers.get(call_id)
        if existing:
            existing.cancel()
        timer = threading.Timer(timeout_seconds, _timeout_handler)
        timer.daemon = True
        _missed_timers[call_id] = timer
        timer.start()


def _cancel_missed_timeout(call_id: str) -> None:
    with _missed_timers_lock:
        timer = _missed_timers.pop(call_id, None)
        if timer:
            timer.cancel()


@csrf_exempt
def call_invite(request):
    """
    Initiate a call - generates channel name, creates call record in Firestore,
    and sends push notification to receiver.
    """
    logger.info(f"[CALL/INVITE] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    logger.info(f"[CALL/INVITE] Request data: {data}")

    group_id = data.get("group_id")
    caller_id = data.get("caller_id")
    receiver_id = data.get("receiver_id")
    caller_name = data.get("caller_name", caller_id)
    group_name_snapshot = data.get("group_name_snapshot")
    receiver_name_snapshot = data.get("receiver_name_snapshot")

    if not all([group_id, caller_id, receiver_id]):
        return JsonResponse({
            "error": "missing_fields",
            "required": ["group_id", "caller_id", "receiver_id"],
        }, status=400)

    if not firestore_service.is_available():
        return JsonResponse({
            "error": "firestore_unavailable",
            "message": "Firebase Firestore is not configured",
        }, status=503)

    call_id = str(uuid.uuid4())
    channel_name = generate_channel_name(group_id, caller_id, receiver_id)

    call_record = firestore_service.create_call_record(
        call_id=call_id,
        channel_name=channel_name,
        group_id=group_id,
        caller_id=caller_id,
        receiver_id=receiver_id,
        caller_name=caller_name,
        group_name_snapshot=group_name_snapshot,
        receiver_name_snapshot=receiver_name_snapshot,
    )

    if not call_record:
        return JsonResponse({
            "error": "failed_to_create_call_record",
        }, status=500)

    logger.info(f"[CALL/INVITE] Created call record: {call_id}, channel={channel_name}")

    _schedule_missed_timeout(call_id, MISSED_TIMEOUT_SECONDS)

    user_tokens = firestore_service.get_user_tokens(receiver_id)

    push_sent = False
    push_platform = ""
    push_error = None

    if user_tokens and user_tokens.get("exists"):
        platform = user_tokens.get("platform", "")
        fcm_token = user_tokens.get("fcmToken")
        voip_token = user_tokens.get("voipToken")

        result = run_async(push_service.send_incoming_call_push(
            platform=platform,
            fcm_token=fcm_token,
            voip_token=voip_token,
            call_id=call_id,
            channel_name=channel_name,
            caller_name=caller_name,
            group_id=group_id,
            receiver_id=receiver_id,
            caller_id=caller_id,
        ))

        if result.success:
            push_sent = True
            push_platform = result.platform
        else:
            push_error = result.error
            logger.warning(f"[CALL/INVITE] Push failed: {result.error}")
    else:
        if user_tokens is None:
            push_error = "firestore_error"
        else:
            push_error = "user_not_found"
        logger.warning(f"[CALL/INVITE] No tokens found for receiver={receiver_id}")

    response_data = {
        "success": True,
        "callId": call_id,
        "channelName": channel_name,
        "pushSent": push_sent,
    }

    if push_sent:
        response_data["pushPlatform"] = push_platform
    else:
        response_data["pushError"] = push_error

    return JsonResponse(response_data)


@csrf_exempt
def call_answer(request):
    """
    Answer (accept or decline) a call.
    """
    logger.info(f"[CALL/ANSWER] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    logger.info(f"[CALL/ANSWER] Request data: {data}")

    call_id = data.get("call_id")
    action = data.get("action")

    if not call_id:
        return JsonResponse({"error": "missing_call_id"}, status=400)

    if action not in ["accept", "decline"]:
        return JsonResponse({"error": "invalid_action", "valid": ["accept", "decline"]}, status=400)

    call_record = firestore_service.get_call_record(call_id)

    if not call_record:
        return JsonResponse({"error": "call_not_found"}, status=404)

    if call_record.get("status") != "pending":
        return JsonResponse({
            "error": "call_not_pending",
            "currentStatus": call_record.get("status"),
        }, status=409)

    new_status = "accepted" if action == "accept" else "declined"
    update_kwargs = {}
    if action == "accept":
        update_kwargs["answeredAt"] = datetime.utcnow()
    else:
        update_kwargs["endedAt"] = datetime.utcnow()

    updated = firestore_service.update_call_status(call_id, new_status, **update_kwargs)

    if not updated:
        return JsonResponse({"error": "failed_to_update_status"}, status=500)

    logger.info(f"[CALL/ANSWER] Call {call_id} {action}ed")

    _cancel_missed_timeout(call_id)

    return JsonResponse({
        "success": True,
        "callId": call_id,
        "channelName": call_record.get("channelName"),
        "status": new_status,
    })


@csrf_exempt
def call_cancel(request):
    """
    Cancel a call (caller hangs up before answer).
    """
    logger.info(f"[CALL/CANCEL] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    logger.info(f"[CALL/CANCEL] Request data: {data}")

    call_id = data.get("call_id")

    if not call_id:
        return JsonResponse({"error": "missing_call_id"}, status=400)

    call_record = firestore_service.get_call_record(call_id)

    if not call_record:
        return JsonResponse({"error": "call_not_found"}, status=404)

    if call_record.get("status") != "pending":
        return JsonResponse({
            "error": "call_not_pending",
            "currentStatus": call_record.get("status"),
        }, status=409)

    updated = firestore_service.update_call_status(call_id, "cancelled", endedAt=datetime.utcnow())

    if not updated:
        return JsonResponse({"error": "failed_to_update_status"}, status=500)

    receiver_id = call_record.get("receiverId")
    user_tokens = firestore_service.get_user_tokens(receiver_id)

    if user_tokens and user_tokens.get("exists"):
        platform = user_tokens.get("platform", "")
        run_async(push_service.send_call_cancelled_push(
            platform=platform,
            fcm_token=user_tokens.get("fcmToken"),
            voip_token=user_tokens.get("voipToken"),
            call_id=call_id,
            channel_name=call_record.get("channelName"),
        ))

    logger.info(f"[CALL/CANCEL] Call {call_id} cancelled")

    _cancel_missed_timeout(call_id)

    return JsonResponse({
        "success": True,
        "callId": call_id,
        "status": "cancelled",
    })


@csrf_exempt
def call_missed(request):
    """
    Mark a call as missed (client timeout).
    """
    logger.info(f"[CALL/MISSED] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    call_id = data.get("call_id")
    if not call_id:
        return JsonResponse({"error": "missing_call_id"}, status=400)

    call_record = firestore_service.get_call_record(call_id)
    if not call_record:
        return JsonResponse({"error": "call_not_found"}, status=404)

    if call_record.get("status") != "pending":
        return JsonResponse({
            "error": "call_not_pending",
            "currentStatus": call_record.get("status"),
        }, status=409)

    updated = firestore_service.update_call_status(call_id, "missed", endedAt=datetime.utcnow())
    if not updated:
        return JsonResponse({"error": "failed_to_update_status"}, status=500)

    _cancel_missed_timeout(call_id)

    return JsonResponse({
        "success": True,
        "callId": call_id,
        "status": "missed",
    })


@csrf_exempt
def call_timeout_sweep(request):
    """
    Sweep pending calls and mark as missed if expired.
    """
    logger.info(f"[CALL/TIMEOUT_SWEEP] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    timeout_seconds = data.get("timeout_seconds", MISSED_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(timeout_seconds)
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_timeout_seconds"}, status=400)

    cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
    updated_count = firestore_service.mark_missed_expired(cutoff)

    return JsonResponse({
        "success": True,
        "timeoutSeconds": timeout_seconds,
        "updatedCount": updated_count,
    })


@csrf_exempt
def call_end(request):
    """
    End an active call.
    """
    logger.info(f"[CALL/END] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
    if error:
        return error

    call_id = data.get("call_id")

    if not call_id:
        return JsonResponse({"error": "missing_call_id"}, status=400)

    call_record = firestore_service.get_call_record(call_id)

    if not call_record:
        return JsonResponse({"error": "call_not_found"}, status=404)

    if call_record.get("status") != "accepted":
        return JsonResponse({
            "error": "call_not_active",
            "currentStatus": call_record.get("status"),
        }, status=409)

    ended_at = datetime.utcnow()

    answered_at = normalize_datetime(call_record.get("answeredAt"))
    created_at = normalize_datetime(call_record.get("createdAt"))
    duration_base = answered_at or created_at
    duration = None
    if duration_base:
        duration = int((ended_at - duration_base).total_seconds())

    updated = firestore_service.update_call_status(
        call_id,
        "ended",
        endedAt=ended_at,
        durationSec=duration if duration is not None else 0,
    )

    if not updated:
        return JsonResponse({"error": "failed_to_update_status"}, status=500)

    logger.info(f"[CALL/END] Call {call_id} ended, duration={duration}s")

    _cancel_missed_timeout(call_id)
    return JsonResponse({
        "success": True,
        "callId": call_id,
        "status": "ended",
        "durationSeconds": duration,
    })


@csrf_exempt
def call_status(request, call_id):
    """
    Get call status from Firestore.
    """
    logger.info(f"[CALL/STATUS] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    call_record = firestore_service.get_call_record(call_id)

    if not call_record:
        return JsonResponse({"error": "call_not_found"}, status=404)

    def format_timestamp(ts):
        if ts is None:
            return None
        if hasattr(ts, "isoformat"):
            return ts.isoformat()
        if hasattr(ts, "timestamp"):
            return datetime.fromtimestamp(ts.timestamp()).isoformat()
        return str(ts)

    return JsonResponse({
        "callId": call_record.get("callId"),
        "channelName": call_record.get("channelName"),
        "groupId": call_record.get("groupId"),
        "receiverId": call_record.get("receiverId"),
        "caregiverUserId": call_record.get("caregiverUserId"),
        "groupNameSnapshot": call_record.get("groupNameSnapshot"),
        "giverNameSnapshot": call_record.get("giverNameSnapshot"),
        "receiverNameSnapshot": call_record.get("receiverNameSnapshot"),
        "status": call_record.get("status"),
        "createdAt": format_timestamp(call_record.get("createdAt")),
        "answeredAt": format_timestamp(call_record.get("answeredAt")),
        "endedAt": format_timestamp(call_record.get("endedAt")),
        "durationSec": call_record.get("durationSec"),
        "humanSummary": call_record.get("humanSummary"),
        "humanKeywords": call_record.get("humanKeywords"),
        "humanNotes": call_record.get("humanNotes"),
        "aiSummary": call_record.get("aiSummary"),
        "reviewCount": call_record.get("reviewCount"),
        "lastReviewAt": format_timestamp(call_record.get("lastReviewAt")),
    })

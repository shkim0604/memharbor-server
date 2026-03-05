import logging
import os
import time
from datetime import timedelta
from typing import Optional

from django.core.mail import send_mail
from django.http import JsonResponse, HttpResponseNotAllowed
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..firebase_service import firestore_service, get_firebase_app
from ..http import json_body

logger = logging.getLogger("api")

DELETION_GRACE_DAYS = 30

MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}

def _token_fingerprint(token: Optional[str]) -> str:
    if not token:
        return "missing"
    tail = token[-6:] if len(token) >= 6 else token
    return f"len={len(token)},tail={tail}"


def _firebase_uid(request) -> Optional[str]:
    return getattr(request, "firebase_uid", None)


def _as_datetime_or_none(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value
    if isinstance(value, str):
        parsed = parse_datetime(value.strip())
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    return None


@csrf_exempt
def user_exists(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    exists = firestore_service.user_exists(uid)
    if exists is None:
        return JsonResponse({"error": "firestore_unavailable"}, status=503)

    return JsonResponse({"exists": bool(exists)})


@csrf_exempt
def user_create(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data, error = json_body(request)
    if error:
        return error

    now = timezone.now()
    payload = {
        "uid": uid,
        "name": data.get("name") or "",
        "email": data.get("email") or "",
        "profileImage": data.get("profileImage") or "",
        "introMessage": data.get("introMessage") or "",
        "groupIds": data.get("groupIds") or [],
        "createdAt": now,
        "lastActivityAt": now,
    }

    created = firestore_service.create_user(uid, payload)
    if not created:
        return JsonResponse({"error": "failed_to_create_user"}, status=500)

    return JsonResponse({"ok": True})


@csrf_exempt
def user_update(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data, error = json_body(request)
    if error:
        return error

    update_payload = {}
    for key in ["name", "email", "profileImage", "introMessage", "groupIds"]:
        if key in data:
            update_payload[key] = data.get(key)

    update_payload["lastActivityAt"] = timezone.now()

    if not update_payload:
        return JsonResponse({"ok": True})

    updated = firestore_service.update_user(uid, update_payload)
    if not updated:
        return JsonResponse({"error": "failed_to_update_user"}, status=500)

    return JsonResponse({"ok": True})


@csrf_exempt
def user_delete(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    deleted = firestore_service.delete_user(uid)
    if not deleted:
        return JsonResponse({"error": "failed_to_delete_user"}, status=500)

    return JsonResponse({"ok": True})


@csrf_exempt
def user_push_tokens(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data, error = json_body(request)
    if error:
        return error

    update_payload = {}
    for key in ["fcmToken", "apnsToken", "voipToken", "platform"]:
        if key in data:
            update_payload[key] = data.get(key)

    if "platform" in update_payload and update_payload["platform"] not in {"ios", "android"}:
        return JsonResponse({"error": "invalid_platform"}, status=400)

    update_payload["tokensUpdatedAt"] = timezone.now()

    updated = firestore_service.update_push_tokens(uid, update_payload)
    if not updated:
        return JsonResponse({"error": "failed_to_update_tokens"}, status=500)

    logger.info(
        "[USER/PUSH_TOKENS] Updated: uid=%s platform=%s fcm=%s apns=%s voip=%s",
        uid,
        update_payload.get("platform"),
        _token_fingerprint(update_payload.get("fcmToken")),
        _token_fingerprint(update_payload.get("apnsToken")),
        _token_fingerprint(update_payload.get("voipToken")),
    )

    return JsonResponse({"ok": True})


@csrf_exempt
def user_profile_image(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    logger.info("[PROFILE_IMAGE] Upload request: uid=%s FILES=%s content_type=%s",
                uid, list(request.FILES.keys()), request.content_type)

    file_obj = request.FILES.get("file")
    if not file_obj:
        logger.warning("[PROFILE_IMAGE] No file in request: uid=%s", uid)
        return JsonResponse({"error": "missing_file"}, status=400)

    logger.info("[PROFILE_IMAGE] File received: uid=%s name=%s size=%s type=%s",
                uid, file_obj.name, file_obj.size, file_obj.content_type)

    if file_obj.size > MAX_PROFILE_IMAGE_SIZE:
        logger.warning("[PROFILE_IMAGE] File too large: uid=%s size=%s", uid, file_obj.size)
        return JsonResponse({"error": "file_too_large"}, status=400)

    if file_obj.content_type not in ALLOWED_IMAGE_TYPES:
        logger.warning("[PROFILE_IMAGE] Invalid type: uid=%s type=%s", uid, file_obj.content_type)
        return JsonResponse({"error": "invalid_file_type"}, status=400)

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    if not bucket_name:
        logger.error("[PROFILE_IMAGE] FIREBASE_STORAGE_BUCKET not set")
        return JsonResponse({"error": "missing_storage_bucket"}, status=500)

    app = get_firebase_app()
    if app is None:
        logger.error("[PROFILE_IMAGE] Firebase app not initialized")
        return JsonResponse({"error": "firestore_unavailable"}, status=503)

    try:
        from firebase_admin import storage
    except Exception as exc:
        logger.error("[PROFILE_IMAGE] Failed to import storage: %s", exc)
        return JsonResponse({"error": "storage_unavailable"}, status=500)

    filename = f"profile_images/{uid}/{int(time.time())}_{file_obj.name}"
    try:
        bucket = storage.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_file(file_obj, content_type=file_obj.content_type)
        blob.make_public()
        url = blob.public_url
        logger.info("[PROFILE_IMAGE] Uploaded: uid=%s path=%s url=%s", uid, filename, url)
    except Exception as exc:
        logger.error("[PROFILE_IMAGE] Upload failed: uid=%s error=%s", uid, exc)
        return JsonResponse({"error": "upload_failed", "detail": str(exc)}, status=500)

    firestore_service.update_user(uid, {
        "profileImage": url,
        "profileImagePath": filename,
        "profileImageUpdatedAt": timezone.now(),
        "lastActivityAt": timezone.now(),
    })
    logger.info("[PROFILE_IMAGE] Firestore updated: uid=%s", uid)

    return JsonResponse({"ok": True, "url": url})


@csrf_exempt
def user_profile_image_delete(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    if not firestore_service.db:
        return JsonResponse({"error": "firestore_unavailable"}, status=503)

    logger.info("[PROFILE_IMAGE_DELETE] Request: uid=%s", uid)

    doc = firestore_service.db.collection("users").document(uid).get()
    data = doc.to_dict() if doc.exists else {}
    image_path = data.get("profileImagePath")
    logger.info("[PROFILE_IMAGE_DELETE] Current path: uid=%s path=%s", uid, image_path)

    if image_path:
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
        if bucket_name:
            try:
                from firebase_admin import storage
                bucket = storage.bucket(bucket_name)
                blob = bucket.blob(image_path)
                if blob.exists():
                    blob.delete()
                    logger.info("[PROFILE_IMAGE_DELETE] Blob deleted: %s", image_path)
                else:
                    logger.info("[PROFILE_IMAGE_DELETE] Blob not found: %s", image_path)
            except Exception as exc:
                logger.warning("[PROFILE_IMAGE_DELETE] Delete failed: %s", exc)

    firestore_service.update_user(uid, {
        "profileImage": "",
        "profileImagePath": "",
        "profileImageUpdatedAt": timezone.now(),
        "lastActivityAt": timezone.now(),
    })
    logger.info("[PROFILE_IMAGE_DELETE] Firestore cleared: uid=%s", uid)

    return JsonResponse({"ok": True})


@csrf_exempt
def user_delete_request(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    token_uid = _firebase_uid(request)
    if not token_uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data, error = json_body(request)
    if error:
        return error

    body_uid = data.get("uid")
    email = data.get("email")
    notify_email = data.get("notifyEmail")

    if not body_uid or not email or not notify_email:
        return JsonResponse(
            {"error": "missing_fields", "required": ["uid", "email", "notifyEmail"]},
            status=400,
        )

    if body_uid != token_uid:
        logger.warning("[DELETE_REQUEST] uid mismatch: token=%s body=%s", token_uid, body_uid)
        return JsonResponse({"error": "uid_mismatch"}, status=403)

    if not firestore_service.db:
        return JsonResponse({"error": "firestore_unavailable"}, status=503)

    now = timezone.now()
    requested_at_raw = data.get("requestedAt")
    if requested_at_raw:
        requested_at = parse_datetime(requested_at_raw) or now
    else:
        requested_at = now

    scheduled_delete_raw = data.get("scheduledDeleteAt")
    if scheduled_delete_raw:
        scheduled_delete_at = parse_datetime(scheduled_delete_raw) or (requested_at + timedelta(days=DELETION_GRACE_DAYS))
    else:
        scheduled_delete_at = requested_at + timedelta(days=DELETION_GRACE_DAYS)

    deletion_ref = firestore_service.db.collection("userDeletionRequests").document(body_uid)
    existing_doc = deletion_ref.get()
    existing_data = (existing_doc.to_dict() or {}) if existing_doc.exists else {}
    is_repeat = existing_doc.exists and existing_data.get("status") == "requested"
    already_emailed = existing_data.get("emailSent", False)

    email_sent = False
    should_send_email = not is_repeat or not already_emailed
    if should_send_email:
        try:
            subject = "[MemHarbor] 계정 삭제 요청"
            body_text = (
                f"MemHarbor 계정 삭제 요청이 접수되었습니다.\n\n"
                f"요청 UID: {body_uid}\n"
                f"계정 이메일: {email}\n"
                f"요청 시각: {requested_at.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                f"예정 삭제 시각: {scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                f"요청자 인증 UID (토큰): {token_uid}\n\n"
                f"이 요청은 {DELETION_GRACE_DAYS}일 후 처리 예정입니다.\n"
                f"문의: 관리자에게 연락하세요."
            )
            send_mail(
                subject,
                body_text,
                None,  # DEFAULT_FROM_EMAIL
                [notify_email],
                fail_silently=False,
            )
            email_sent = True
            logger.info("[DELETE_REQUEST] Email sent: uid=%s to=%s", body_uid, notify_email)
        except Exception as exc:
            logger.error("[DELETE_REQUEST] Email failed: uid=%s error=%s", body_uid, exc)
    else:
        logger.info("[DELETE_REQUEST] Repeat request, email already sent — skipping: uid=%s", body_uid)

    try:
        email_sent_at = now if email_sent else _as_datetime_or_none(existing_data.get("emailSentAt"))
        deletion_ref.set({
            "uid": body_uid,
            "email": email,
            "status": "requested",
            "requestedAt": requested_at,
            "scheduledDeleteAt": scheduled_delete_at,
            "emailSent": email_sent or already_emailed,
            "emailSentAt": email_sent_at,
            "notifyEmail": notify_email,
            "tokenUid": token_uid,
            "updatedAt": now,
        }, merge=True)
        logger.info("[DELETE_REQUEST] Firestore userDeletionRequests/%s written", body_uid)
    except Exception as exc:
        logger.error("[DELETE_REQUEST] Firestore write failed (deletionRequests): uid=%s error=%s", body_uid, exc)
        return JsonResponse({"error": "firestore_write_failed"}, status=500)

    try:
        firestore_service.update_user(body_uid, {
            "deletionStatus": "requested",
            "deletionRequestedAt": requested_at,
            "scheduledDeletionAt": scheduled_delete_at,
        })
        logger.info("[DELETE_REQUEST] Firestore users/%s status updated", body_uid)
    except Exception as exc:
        logger.error("[DELETE_REQUEST] Firestore user update failed: uid=%s error=%s", body_uid, exc)

    scheduled_str = scheduled_delete_at.isoformat()
    return JsonResponse({
        "ok": True,
        "status": "requested",
        "uid": body_uid,
        "scheduledDeleteAt": scheduled_str,
        "emailSent": email_sent,
        "isRepeat": is_repeat,
    })

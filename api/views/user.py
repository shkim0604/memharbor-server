import logging
import os
import time
from typing import Optional

from django.http import JsonResponse, HttpResponseNotAllowed
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..firebase_service import firestore_service, get_firebase_app
from ..http import json_body

logger = logging.getLogger("api")

MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}

def _token_fingerprint(token: Optional[str]) -> str:
    if not token:
        return "missing"
    tail = token[-6:] if len(token) >= 6 else token
    return f"len={len(token)},tail={tail}"


def _firebase_uid(request) -> Optional[str]:
    return getattr(request, "firebase_uid", None)


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

    file_obj = request.FILES.get("file")
    if not file_obj:
        return JsonResponse({"error": "missing_file"}, status=400)

    if file_obj.size > MAX_PROFILE_IMAGE_SIZE:
        return JsonResponse({"error": "file_too_large"}, status=400)

    if file_obj.content_type not in ALLOWED_IMAGE_TYPES:
        return JsonResponse({"error": "invalid_file_type"}, status=400)

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    if not bucket_name:
        return JsonResponse({"error": "missing_storage_bucket"}, status=500)

    app = get_firebase_app()
    if app is None:
        return JsonResponse({"error": "firestore_unavailable"}, status=503)

    try:
        from firebase_admin import storage
    except Exception:
        return JsonResponse({"error": "storage_unavailable"}, status=500)

    filename = f"profile_images/{uid}/{int(time.time())}_{file_obj.name}"
    bucket = storage.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_file(file_obj, content_type=file_obj.content_type)
    blob.make_public()

    url = blob.public_url

    firestore_service.update_user(uid, {
        "profileImage": url,
        "profileImagePath": filename,
        "profileImageUpdatedAt": timezone.now(),
        "lastActivityAt": timezone.now(),
    })

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

    doc = firestore_service.db.collection("users").document(uid).get()
    data = doc.to_dict() if doc.exists else {}
    image_path = data.get("profileImagePath")

    if image_path:
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
        if bucket_name:
            try:
                from firebase_admin import storage
                bucket = storage.bucket(bucket_name)
                blob = bucket.blob(image_path)
                if blob.exists():
                    blob.delete()
            except Exception as exc:
                logger.warning("[PROFILE_IMAGE_DELETE] Delete failed: %s", exc)

    firestore_service.update_user(uid, {
        "profileImage": "",
        "profileImagePath": "",
        "profileImageUpdatedAt": timezone.now(),
        "lastActivityAt": timezone.now(),
    })

    return JsonResponse({"ok": True})

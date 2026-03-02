import logging
from typing import Optional

from django.http import JsonResponse

from .firebase_service import get_firebase_app
from .http import json_body

logger = logging.getLogger("api")

PROTECTED_PATHS = {
    "/api/call/invite",
    "/api/call/answer",
    "/api/call/cancel",
    "/api/call/missed",
    "/api/call/end",
    "/api/token",
    "/api/recording/start",
    "/api/recording/stop",
    "/api/user/exists",
    "/api/user/create",
    "/api/user/update",
    "/api/user/delete",
    "/api/user/push-tokens",
    "/api/user/profile-image",
    "/api/user/profile-image/delete",
    "/api/group/assign-receiver",
}

UID_FIELDS = {
    "caller_id",
    "callerId",
    "caregiverUserId",
    "uid",
    "user_id",
    "userId",
}

SKIP_UID_CHECK_PATHS = {
    "/api/recording/start",
    "/api/recording/stop",
}


class FirebaseAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            return self.get_response(request)

        path = request.path.rstrip("/")
        if path not in PROTECTED_PATHS:
            return self.get_response(request)

        token = _extract_bearer_token(request)
        if not token:
            return JsonResponse({"error": "missing_authorization"}, status=401)

        decoded = _verify_firebase_token(token)
        if decoded is None:
            return JsonResponse({"error": "invalid_token"}, status=401)

        request.firebase_uid = decoded.get("uid")
        request.firebase_token = decoded

        if path not in SKIP_UID_CHECK_PATHS:
            body_uid = _extract_body_uid(request)
            if body_uid and request.firebase_uid and body_uid != request.firebase_uid:
                logger.warning(
                    "[AUTH] UID mismatch: token=%s body=%s path=%s",
                    request.firebase_uid,
                    body_uid,
                    path,
                )
                return JsonResponse({"error": "uid_mismatch"}, status=403)

        return self.get_response(request)


def _extract_bearer_token(request) -> Optional[str]:
    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION")
    if not auth_header:
        return None
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _verify_firebase_token(token: str) -> Optional[dict]:
    try:
        app = get_firebase_app()
        if app is None:
            logger.error("[AUTH] Firebase app not initialized")
            return None
        from firebase_admin import auth
        return auth.verify_id_token(token, app=app)
    except Exception as exc:
        logger.warning("[AUTH] Token verification failed: %s", exc)
        return None


def _extract_body_uid(request) -> Optional[str]:
    if request.method not in {"POST", "PUT", "PATCH"}:
        return None
    content_type = request.META.get("CONTENT_TYPE", "")
    if content_type.startswith("multipart/"):
        return None
    data, error = json_body(request)
    if error:
        return None
    for key in UID_FIELDS:
        value = data.get(key)
        if value:
            return str(value)
    return None

import json
import logging
import os
import time
from typing import Tuple

import requests
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from agora_token_builder import RtcTokenBuilder

logger = logging.getLogger("api")

DEFAULT_TOKEN_EXPIRE_SECONDS = 86400
MAX_TOKEN_EXPIRE_SECONDS = 86400

ROLE_PUBLISHER = 1
ROLE_SUBSCRIBER = 2

# Local recording service URL
RECORDER_SERVICE_URL = os.environ.get("RECORDER_SERVICE_URL", "http://localhost:3100")


def _json_body(request) -> Tuple[dict, JsonResponse]:
    try:
        body = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data, None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, JsonResponse({"error": f"invalid_json: {exc}"}, status=400)


def _require_env(*keys):
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        return JsonResponse({"error": "missing_env", "missing": missing}, status=500)
    return None


def _parse_role(value):
    if value is None:
        return ROLE_SUBSCRIBER
    if isinstance(value, int):
        return ROLE_PUBLISHER if value == ROLE_PUBLISHER else ROLE_SUBSCRIBER
    if isinstance(value, str):
        value = value.lower()
        if value in {"publisher", "host", "broadcaster"}:
            return ROLE_PUBLISHER
        if value in {"subscriber", "audience"}:
            return ROLE_SUBSCRIBER
    return None


def _clamp_expire(expire):
    try:
        expire = int(expire)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_EXPIRE_SECONDS
    if expire <= 0:
        return DEFAULT_TOKEN_EXPIRE_SECONDS
    return min(expire, MAX_TOKEN_EXPIRE_SECONDS)


def _recorder_service_post(endpoint: str, payload: dict):
    """Call local recording service"""
    url = f"{RECORDER_SERVICE_URL.rstrip('/')}/{endpoint}"
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        return JsonResponse(body, status=response.status_code)
    except requests.exceptions.ConnectionError:
        return JsonResponse({"error": "recorder_service_unavailable"}, status=503)
    except requests.exceptions.Timeout:
        return JsonResponse({"error": "recorder_service_timeout"}, status=504)


@csrf_exempt
def health(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"status": "ok"})


@csrf_exempt
def token(request):
    logger.info(f"[TOKEN] {request.method} from {request.META.get('REMOTE_ADDR')}")
    
    if request.method != "POST":
        logger.warning(f"[TOKEN] Method not allowed: {request.method}")
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID", "AGORA_APP_CERT")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        logger.error(f"[TOKEN] Invalid JSON body")
        return error

    logger.info(f"[TOKEN] Request data: {data}")

    channel = data.get("channel") or data.get("cname")
    if not channel:
        logger.error(f"[TOKEN] Missing channel")
        return JsonResponse({"error": "missing_channel"}, status=400)

    uid = data.get("uid")
    user_account = data.get("user_account") or data.get("account")
    if uid is None and not user_account:
        return JsonResponse({"error": "missing_uid_or_account"}, status=400)

    role = _parse_role(data.get("role"))
    if role is None:
        return JsonResponse({"error": "invalid_role"}, status=400)

    expire = _clamp_expire(data.get("expire", DEFAULT_TOKEN_EXPIRE_SECONDS))
    expire_ts = int(time.time()) + expire

    app_id = os.environ.get("AGORA_APP_ID")
    app_cert = os.environ.get("AGORA_APP_CERT")

    if user_account:
        token_value = RtcTokenBuilder.buildTokenWithAccount(
            app_id, app_cert, channel, str(user_account), role, expire_ts
        )
    else:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            return JsonResponse({"error": "uid_must_be_int"}, status=400)
        token_value = RtcTokenBuilder.buildTokenWithUid(
            app_id, app_cert, channel, uid_int, role, expire_ts
        )

    logger.info(f"[TOKEN] Success: channel={channel}, uid={uid or user_account}")
    return JsonResponse({
        "token": token_value,
        "expire_at": expire_ts,
        "expire_in": expire,
    })


@csrf_exempt
def recording_start(request):
    """Start local recording - server joins channel and records audio"""
    logger.info(f"[RECORDING/START] {request.method} from {request.META.get('REMOTE_ADDR')}")
    
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        return error

    channel = data.get("cname") or data.get("channel")
    if not channel:
        return JsonResponse({"error": "missing_channel"}, status=400)

    # Generate token for recorder bot (optional, for token-secured apps)
    token = data.get("token")
    if not token:
        # Auto-generate token for recorder
        app_id = os.environ.get("AGORA_APP_ID")
        app_cert = os.environ.get("AGORA_APP_CERT")
        if app_cert:
            recorder_uid = data.get("uid", 999999)
            expire_ts = int(time.time()) + 86400
            token = RtcTokenBuilder.buildTokenWithUid(
                app_id, app_cert, channel, recorder_uid, ROLE_SUBSCRIBER, expire_ts
            )

    payload = {
        "channel": channel,
        "token": token,
        "uid": data.get("uid"),
    }

    return _recorder_service_post("start", payload)


@csrf_exempt
def recording_stop(request):
    """Stop local recording"""
    logger.info(f"[RECORDING/STOP] {request.method} from {request.META.get('REMOTE_ADDR')}")
    
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = _json_body(request)
    if error:
        return error

    logger.info(f"[RECORDING/STOP] Request data: {data}")

    sid = data.get("sid")
    channel = data.get("cname") or data.get("channel")

    if not sid and not channel:
        return JsonResponse({"error": "missing_sid_or_channel"}, status=400)

    payload = {}
    if sid:
        payload["sid"] = sid
    if channel:
        payload["channel"] = channel

    return _recorder_service_post("stop", payload)


@csrf_exempt
def recording_status(request):
    """Get recording status / list active sessions"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    try:
        response = requests.get(
            f"{RECORDER_SERVICE_URL}/sessions",
            timeout=10,
        )
        return JsonResponse(response.json(), status=response.status_code)
    except requests.exceptions.ConnectionError:
        return JsonResponse({"error": "recorder_service_unavailable"}, status=503)


@csrf_exempt
def recording_list(request):
    """List saved recordings"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    try:
        response = requests.get(
            f"{RECORDER_SERVICE_URL}/recordings",
            timeout=10,
        )
        return JsonResponse(response.json(), status=response.status_code)
    except requests.exceptions.ConnectionError:
        return JsonResponse({"error": "recorder_service_unavailable"}, status=503)

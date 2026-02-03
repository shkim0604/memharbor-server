import json
import os
import time
from typing import Tuple

import requests
from requests.auth import HTTPBasicAuth
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from agora_token_builder import RtcTokenBuilder

DEFAULT_TOKEN_EXPIRE_SECONDS = 86400
MAX_TOKEN_EXPIRE_SECONDS = 86400

ROLE_PUBLISHER = 1
ROLE_SUBSCRIBER = 2


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


def _agora_base_url():
    return os.environ.get("AGORA_CLOUD_RECORDING_BASE_URL", "https://api.sd-rtn.com")


def _agora_auth():
    return HTTPBasicAuth(
        os.environ.get("AGORA_CUSTOMER_ID", ""),
        os.environ.get("AGORA_CUSTOMER_SECRET", ""),
    )


def _agora_post(path: str, payload: dict):
    url = f"{_agora_base_url().rstrip('/')}{path}"
    response = requests.post(
        url,
        json=payload,
        auth=_agora_auth(),
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return JsonResponse(body, status=response.status_code)


@csrf_exempt
def health(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    return JsonResponse({"status": "ok"})


@csrf_exempt
def token(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID", "AGORA_APP_CERT")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        return error

    channel = data.get("channel") or data.get("cname")
    if not channel:
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

    return JsonResponse({
        "token": token_value,
        "expire_at": expire_ts,
        "expire_in": expire,
    })


@csrf_exempt
def recording_acquire(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID", "AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        return error

    cname = data.get("cname") or data.get("channel")
    uid = data.get("uid")
    if not cname or uid is None:
        return JsonResponse({"error": "missing_cname_or_uid"}, status=400)

    payload = {
        "cname": str(cname),
        "uid": str(uid),
        "clientRequest": data.get("clientRequest", {}),
    }

    app_id = os.environ.get("AGORA_APP_ID")
    return _agora_post(f"/v1/apps/{app_id}/cloud_recording/acquire", payload)


@csrf_exempt
def recording_start(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID", "AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        return error

    resource_id = data.get("resourceId") or data.get("resource_id")
    mode = data.get("mode", "individual")
    cname = data.get("cname") or data.get("channel")
    uid = data.get("uid")
    client_request = data.get("clientRequest")

    if not resource_id or not cname or uid is None:
        return JsonResponse({"error": "missing_resource_cname_uid"}, status=400)
    if not client_request:
        return JsonResponse({"error": "missing_clientRequest"}, status=400)

    payload = {
        "cname": str(cname),
        "uid": str(uid),
        "clientRequest": client_request,
    }

    app_id = os.environ.get("AGORA_APP_ID")
    path = f"/v1/apps/{app_id}/cloud_recording/resourceid/{resource_id}/mode/{mode}/start"
    return _agora_post(path, payload)


@csrf_exempt
def recording_stop(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = _require_env("AGORA_APP_ID", "AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET")
    if missing_env:
        return missing_env

    data, error = _json_body(request)
    if error:
        return error

    resource_id = data.get("resourceId") or data.get("resource_id")
    sid = data.get("sid")
    mode = data.get("mode", "individual")
    cname = data.get("cname") or data.get("channel")
    uid = data.get("uid")

    if not resource_id or not sid or not cname or uid is None:
        return JsonResponse({"error": "missing_resource_sid_cname_uid"}, status=400)

    payload = {
        "cname": str(cname),
        "uid": str(uid),
        "clientRequest": data.get("clientRequest", {}),
    }

    app_id = os.environ.get("AGORA_APP_ID")
    path = f"/v1/apps/{app_id}/cloud_recording/resourceid/{resource_id}/sid/{sid}/mode/{mode}/stop"
    return _agora_post(path, payload)

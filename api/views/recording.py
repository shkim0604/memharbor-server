import logging
import os
import time

import requests
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from agora_token_builder import RtcTokenBuilder

from ..constants import RECORDER_SERVICE_URL, ROLE_SUBSCRIBER
from ..http import json_body, require_env
from ..recording_client import recorder_service_post

logger = logging.getLogger("api")


@csrf_exempt
def recording_start(request):
    """Start local recording - server joins channel and records audio."""
    logger.info(f"[RECORDING/START] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    missing_env = require_env("AGORA_APP_ID")
    if missing_env:
        return missing_env

    data, error = json_body(request)
    if error:
        return error

    channel = data.get("cname") or data.get("channel")
    if not channel:
        return JsonResponse({"error": "missing_channel"}, status=400)

    # Generate token for recorder bot (optional, for token-secured apps).
    token = data.get("token")
    if not token:
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
        "groupId": data.get("group_id"),
        "callerId": data.get("caller_id"),
        "receiverId": data.get("receiver_id"),
    }

    return recorder_service_post("start", payload, allow_conflict_ok=True)


@csrf_exempt
def recording_stop(request):
    """Stop local recording."""
    logger.info(f"[RECORDING/STOP] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    data, error = json_body(request)
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

    return recorder_service_post("stop", payload)


@csrf_exempt
def recording_status(request):
    """Get recording status / list active sessions."""
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
    """List saved recordings."""
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

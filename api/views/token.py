import logging
import os
import time

from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from agora_token_builder import RtcTokenBuilder

from ..constants import DEFAULT_TOKEN_EXPIRE_SECONDS
from ..http import json_body, require_env
from ..utils import parse_role, clamp_expire

logger = logging.getLogger("api")


@csrf_exempt
def token(request):
    logger.info(f"[TOKEN] {request.method} from {request.META.get('REMOTE_ADDR')}")

    if request.method != "POST":
        logger.warning(f"[TOKEN] Method not allowed: {request.method}")
        return HttpResponseNotAllowed(["POST"])

    missing_env = require_env("AGORA_APP_ID", "AGORA_APP_CERT")
    if missing_env:
        return missing_env

    data, error = json_body(request)
    if error:
        logger.error("[TOKEN] Invalid JSON body")
        return error

    logger.info(f"[TOKEN] Request data: {data}")

    channel = data.get("channel") or data.get("cname")
    if not channel:
        logger.error("[TOKEN] Missing channel")
        return JsonResponse({"error": "missing_channel"}, status=400)

    uid = data.get("uid")
    user_account = data.get("user_account") or data.get("account")
    if uid is None and not user_account:
        return JsonResponse({"error": "missing_uid_or_account"}, status=400)

    role = parse_role(data.get("role"))
    if role is None:
        return JsonResponse({"error": "invalid_role"}, status=400)

    expire = clamp_expire(data.get("expire", DEFAULT_TOKEN_EXPIRE_SECONDS))
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

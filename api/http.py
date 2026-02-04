import json
import os
from typing import Tuple

from django.http import JsonResponse


def json_body(request) -> Tuple[dict, JsonResponse]:
    try:
        body = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data, None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, JsonResponse({"error": f"invalid_json: {exc}"}, status=400)


def require_env(*keys):
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        return JsonResponse({"error": "missing_env", "missing": missing}, status=500)
    return None

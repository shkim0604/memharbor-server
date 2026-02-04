import requests
from django.http import JsonResponse

from .constants import RECORDER_SERVICE_URL


def recorder_service_post(endpoint: str, payload: dict, allow_conflict_ok: bool = False):
    """Call local recording service."""
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
        if allow_conflict_ok and response.status_code == 409:
            body["idempotent"] = True
            return JsonResponse(body, status=200)
        return JsonResponse(body, status=response.status_code)
    except requests.exceptions.ConnectionError:
        return JsonResponse({"error": "recorder_service_unavailable"}, status=503)
    except requests.exceptions.Timeout:
        return JsonResponse({"error": "recorder_service_timeout"}, status=504)

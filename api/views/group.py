import logging

from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from ..firebase_service import firestore_service
from ..http import json_body

logger = logging.getLogger("api")


def _firebase_uid(request):
    return getattr(request, "firebase_uid", None)


@csrf_exempt
def group_assign_receiver(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    uid = _firebase_uid(request)
    if not uid:
        return JsonResponse({"error": "unauthorized"}, status=401)

    data, error = json_body(request)
    if error:
        return error

    group_id = data.get("groupId")
    receiver_id = data.get("receiverId")
    if not group_id or not receiver_id:
        return JsonResponse({"error": "missing_fields", "required": ["groupId", "receiverId"]}, status=400)

    result = firestore_service.assign_group_receiver(group_id, receiver_id, uid)
    if not result.get("ok"):
        error = result.get("error")
        if error == "group_not_found":
            return JsonResponse({"error": "group_not_found"}, status=404)
        if error == "not_member":
            return JsonResponse({"error": "not_member"}, status=403)
        return JsonResponse({"error": "failed_to_assign"}, status=500)

    return JsonResponse({"assigned": bool(result.get("assigned"))})

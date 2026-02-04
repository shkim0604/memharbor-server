from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from ..firebase_service import firestore_service


@csrf_exempt
def health(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    firestore_ok = firestore_service.is_available()

    return JsonResponse({
        "status": "ok",
        "firestore": "connected" if firestore_ok else "not_configured",
    })

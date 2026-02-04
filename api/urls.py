from django.urls import path
from . import views

urlpatterns = [
    # Health check
    path("health", views.health, name="health"),
    
    # Agora token
    path("token", views.token, name="token"),
    
    # Recording endpoints
    path("recording/start", views.recording_start, name="recording_start"),
    path("recording/stop", views.recording_stop, name="recording_stop"),
    path("recording/status", views.recording_status, name="recording_status"),
    path("recording/list", views.recording_list, name="recording_list"),
    
    # Call management (Firestore-based)
    # Note: Device tokens are stored by app directly in Firestore users/{uid}
    path("call/invite", views.call_invite, name="call_invite"),
    path("call/answer", views.call_answer, name="call_answer"),
    path("call/cancel", views.call_cancel, name="call_cancel"),
    path("call/missed", views.call_missed, name="call_missed"),
    path("call/timeout/sweep", views.call_timeout_sweep, name="call_timeout_sweep"),
    path("call/end", views.call_end, name="call_end"),
    path("call/status/<str:call_id>", views.call_status, name="call_status"),
]

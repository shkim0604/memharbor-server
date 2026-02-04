from django.urls import path
from . import views

urlpatterns = [
    path("token", views.token, name="token"),
    path("recording/start", views.recording_start, name="recording_start"),
    path("recording/stop", views.recording_stop, name="recording_stop"),
    path("recording/status", views.recording_status, name="recording_status"),
    path("recording/list", views.recording_list, name="recording_list"),
    path("health", views.health, name="health"),
]

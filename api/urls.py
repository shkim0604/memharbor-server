from django.urls import path
from . import views

urlpatterns = [
    path("token", views.token, name="token"),
    path("recording/acquire", views.recording_acquire, name="recording_acquire"),
    path("recording/start", views.recording_start, name="recording_start"),
    path("recording/stop", views.recording_stop, name="recording_stop"),
    path("health", views.health, name="health"),
]

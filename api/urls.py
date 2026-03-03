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

    # User management
    path("user/exists", views.user_exists, name="user_exists"),
    path("user/create", views.user_create, name="user_create"),
    path("user/update", views.user_update, name="user_update"),
    path("user/delete", views.user_delete, name="user_delete"),
    path("user/push-tokens", views.user_push_tokens, name="user_push_tokens"),
    path("user/profile-image", views.user_profile_image, name="user_profile_image"),
    path("user/profile-image/delete", views.user_profile_image_delete, name="user_profile_image_delete"),
    path("user/delete-request", views.user_delete_request, name="user_delete_request"),
    path("user/deletion-request", views.user_delete_request, name="user_deletion_request"),

    # Group management
    path("group/assign-receiver", views.group_assign_receiver, name="group_assign_receiver"),

    # Reviews
    path("reviews/feed", views.reviews_feed, name="reviews_feed"),
    path("reviews/upsert", views.reviews_upsert, name="reviews_upsert"),
    path("reviews/context", views.reviews_context, name="reviews_context"),
    path("reviews/my", views.reviews_my, name="reviews_my"),
]

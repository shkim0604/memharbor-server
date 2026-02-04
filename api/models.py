# Models are stored in Firebase Firestore, not Django DB.
# This file is kept for Django app structure compatibility.
#
# Firestore Collections:
# - users/{uid}: User data including push tokens (fcmToken, voipToken, platform)
# - calls/{callId}: Call records with status, participants, timestamps
#
# See firebase_service.py for Firestore operations.

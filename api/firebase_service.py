"""
Firebase service for Django - Firestore integration for call management.

Firestore Collections:
- users/{uid}: Contains fcmToken, voipToken for push notifications
- calls/{callId}: Call records with status, participants, timestamps
"""
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger("api")

# Firebase Admin initialization
_firebase_app = None
_firestore_client = None
_firebase_init_attempted = False


def get_firebase_app():
    """Get or initialize Firebase Admin app"""
    global _firebase_app, _firebase_init_attempted
    
    if _firebase_app is not None:
        return _firebase_app
    
    if _firebase_init_attempted:
        # Already tried and failed
        return None
    
    _firebase_init_attempted = True
    
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.error("firebase-admin package not installed")
        return None
    
    use_emulator = os.environ.get("FIREBASE_USE_EMULATOR", "false").lower() == "true"
    project_id = os.environ.get("FIREBASE_PROJECT_ID")
    
    logger.info(f"Firebase init: use_emulator={use_emulator}, project_id={project_id}")
    logger.info(f"FIRESTORE_EMULATOR_HOST={os.environ.get('FIRESTORE_EMULATOR_HOST')}")
    
    if use_emulator:
        # Emulator mode - ensure environment variable is set BEFORE initializing
        firestore_host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
        os.environ["FIRESTORE_EMULATOR_HOST"] = firestore_host
        
        try:
            # For emulator, use ApplicationDefault credentials with project override
            _firebase_app = firebase_admin.initialize_app(
                credential=None,  # Use default credentials
                options={
                    "projectId": project_id or "demo-project",
                }
            )
            logger.info(f"Firebase Admin initialized with EMULATOR (Firestore: {firestore_host})")
        except ValueError as e:
            # Already initialized
            try:
                _firebase_app = firebase_admin.get_app()
                logger.info("Firebase Admin already initialized")
            except ValueError:
                logger.error(f"Firebase init failed: {e}")
                return None
        except Exception as e:
            logger.error(f"Firebase emulator init failed: {e}")
            return None
    else:
        # Production mode - need credentials
        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        service_account_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")
        
        cred = None
        if service_account_json:
            import json
            try:
                sa_dict = json.loads(service_account_json)
                cred = credentials.Certificate(sa_dict)
                logger.info("Using FIREBASE_SERVICE_ACCOUNT env var")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid FIREBASE_SERVICE_ACCOUNT JSON: {e}")
        elif service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            logger.info(f"Using service account from {service_account_path}")
        
        if cred:
            try:
                _firebase_app = firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin initialized (production)")
            except ValueError:
                try:
                    _firebase_app = firebase_admin.get_app()
                except ValueError:
                    pass
        else:
            logger.warning("Firebase credentials not found - Firestore operations will fail")
            return None
    
    return _firebase_app


def get_firestore():
    """Get Firestore client"""
    global _firestore_client
    
    if _firestore_client is not None:
        return _firestore_client
    
    app = get_firebase_app()
    if app is None:
        return None
    
    try:
        from firebase_admin import firestore
        _firestore_client = firestore.client()
        return _firestore_client
    except Exception as e:
        logger.error(f"Failed to get Firestore client: {e}")
        return None


class FirestoreService:
    """Service class for Firestore operations"""
    
    # Collection names
    USERS_COLLECTION = "users"
    CALLS_COLLECTION = "calls"
    
    def __init__(self):
        self._db = None
    
    @property
    def db(self):
        """Lazy initialization of Firestore client"""
        if self._db is None:
            self._db = get_firestore()
        return self._db
    
    def is_available(self) -> bool:
        """Check if Firestore is available"""
        return self.db is not None
    
    # =========================================================================
    # User Token Operations
    # =========================================================================
    
    def get_user_tokens(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get push tokens for a user from Firestore.
        
        Expected document structure at users/{uid}:
        {
            "fcmToken": "android_fcm_token",
            "voipToken": "ios_voip_token",
            "platform": "ios" | "android",
            ...
        }
        
        Returns:
            Dict with token info or None if not found
        """
        if not self.db:
            logger.warning("Firestore not available")
            return None
        
        try:
            doc_ref = self.db.collection(self.USERS_COLLECTION).document(user_id)
            doc = doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                return {
                    "fcmToken": data.get("fcmToken"),
                    "voipToken": data.get("voipToken"),
                    "platform": data.get("platform"),
                    "exists": True
                }
            else:
                logger.info(f"User document not found: {user_id}")
                return {"exists": False}
                
        except Exception as e:
            logger.error(f"Error getting user tokens for {user_id}: {e}")
            return None
    
    # =========================================================================
    # Call Record Operations
    # =========================================================================
    
    def create_call_record(
        self,
        call_id: str,
        channel_name: str,
        group_id: str,
        caller_id: str,
        receiver_id: str,
        caller_name: str = "",
        group_name_snapshot: str = "",
        receiver_name_snapshot: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new call record in Firestore.
        
        Document structure at calls/{callId}:
        {
            "callId": "uuid",
            "channelName": "group_caller_receiver_timestamp",
            "groupId": "group_id",
            "receiverId": "receiver_user_id",
            "caregiverUserId": "caller_user_id",
            "groupNameSnapshot": "Boston Care Group",
            "giverNameSnapshot": "Jungwon",
            "receiverNameSnapshot": "김영옥",
            "createdAt": Timestamp,
            "answeredAt": null,
            "endedAt": null,
            "durationSec": 0,
            "status": "pending",
            "humanSummary": "",
            "humanKeywords": [],
            "humanNotes": "",
            "aiSummary": "",
            "reviewCount": 0,
            "lastReviewAt": null
        }
        """
        if not self.db:
            logger.warning("Firestore not available")
            return None
        
        try:
            now = timezone.now()
            call_data = {
                "callId": call_id,
                "channelName": channel_name,
                "groupId": group_id,
                "receiverId": receiver_id,
                "caregiverUserId": caller_id,
                "groupNameSnapshot": group_name_snapshot or "",
                "giverNameSnapshot": caller_name or caller_id,
                "receiverNameSnapshot": receiver_name_snapshot or "",
                "createdAt": now,
                "answeredAt": None,
                "endedAt": None,
                "durationSec": None,
                "status": "pending",
                # 앱에서 리뷰 후에 저장해야될 것들
                "humanSummary": "",
                "humanKeywords": [],
                "humanNotes": "",
                "aiSummary": "",
                "reviewCount": 0,
                "lastReviewAt": None,
                "pushSent": False,
            }
            
            doc_ref = self.db.collection(self.CALLS_COLLECTION).document(call_id)
            doc_ref.set(call_data)
            
            logger.info(f"Created call record: {call_id}")
            return call_data
            
        except Exception as e:
            logger.error(f"Error creating call record: {e}")
            return None

    def reserve_push_send(self, call_id: str):
        """
        Attempt to reserve push send for a call (idempotency guard).
        Returns:
            True if reserved now,
            False if already reserved/sent,
            None on error.
        """
        if not self.db:
            return None

        try:
            from firebase_admin import firestore as fb_firestore
        except Exception as e:
            logger.error(f"Failed to import firestore for transaction: {e}")
            return None

        try:
            doc_ref = self.db.collection(self.CALLS_COLLECTION).document(call_id)

            @fb_firestore.transactional
            def _txn(transaction):
                snapshot = doc_ref.get(transaction=transaction)
                if not snapshot.exists:
                    return None
                data = snapshot.to_dict() or {}
                if data.get("pushSent"):
                    return False
                transaction.update(doc_ref, {
                    "pushSent": True,
                    "pushReservedAt": timezone.now(),
                })
                return True

            return _txn(self.db.transaction())
        except Exception as e:
            logger.error(f"Error reserving push send: {e}")
            return None
    
    def get_call_record(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get a call record by ID"""
        if not self.db:
            return None
        
        try:
            doc_ref = self.db.collection(self.CALLS_COLLECTION).document(call_id)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            return None
            
        except Exception as e:
            logger.error(f"Error getting call record {call_id}: {e}")
            return None
    
    def update_call_status(
        self,
        call_id: str,
        status: str,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Update call status.
        
        Valid statuses: pending, accepted, declined, cancelled, missed, ended
        
        Additional kwargs:
            - answeredAt: datetime when call was answered
            - endedAt: datetime when call ended
            - durationSec: int duration in seconds
            - lastReviewAt: datetime when last reviewed
        """
        if not self.db:
            return None
        
        try:
            doc_ref = self.db.collection(self.CALLS_COLLECTION).document(call_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                logger.warning(f"Call record not found: {call_id}")
                return None
            
            update_data = {
                "status": status,
            }
            
            # Add optional fields
            for key in ["answeredAt", "endedAt", "durationSec", "lastReviewAt"]:
                if key in kwargs:
                    update_data[key] = kwargs[key]
            
            doc_ref.update(update_data)
            
            # Return updated document
            updated_doc = doc_ref.get()
            return updated_doc.to_dict()
            
        except Exception as e:
            logger.error(f"Error updating call status: {e}")
            return None
    
    def update_push_status(
        self,
        call_id: str,
        push_sent: bool,
        push_platform: str = ""
    ) -> bool:
        """Update push notification status for a call"""
        if not self.db:
            return False
        
        try:
            doc_ref = self.db.collection(self.CALLS_COLLECTION).document(call_id)
            doc_ref.update({
                "pushSent": push_sent,
                "pushPlatform": push_platform,
                "updatedAt": timezone.now(),
            })
            return True
        except Exception as e:
            logger.error(f"Error updating push status: {e}")
            return False

    def mark_missed_expired(self, cutoff_time: datetime) -> int:
        """
        Mark pending calls as missed if createdAt <= cutoff_time.

        Returns number of updated documents.
        """
        if not self.db:
            return 0

        try:
            query = (
                self.db.collection(self.CALLS_COLLECTION)
                .where("status", "==", "pending")
                .where("createdAt", "<=", cutoff_time)
            )
            docs = list(query.stream())
            if not docs:
                return 0

            batch = self.db.batch()
            for doc in docs:
                batch.update(doc.reference, {
                    "status": "missed",
                    "endedAt": timezone.now(),
                })
            batch.commit()
            return len(docs)
        except Exception as e:
            logger.error(f"Error marking missed calls: {e}")
            return 0


# Singleton instance
firestore_service = FirestoreService()

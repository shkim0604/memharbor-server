"""
Push notification service for iOS (APNs VoIP) and Android (FCM via Firebase Admin SDK)
"""
import json
import logging
import os
import time
import jwt
import httpx
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger("api")


@dataclass
class PushResult:
    """Result of a push notification attempt"""
    success: bool
    platform: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class APNsVoIPService:
    """
    Apple Push Notification service for VoIP pushes.
    Uses HTTP/2 with JWT authentication.
    """
    
    APNS_PRODUCTION_HOST = "api.push.apple.com"
    APNS_SANDBOX_HOST = "api.sandbox.push.apple.com"
    
    def __init__(self):
        self.team_id = os.environ.get("APNS_TEAM_ID")
        self.key_id = os.environ.get("APNS_KEY_ID")
        self.bundle_id = os.environ.get("APNS_BUNDLE_ID")
        self.use_sandbox = os.environ.get("APNS_USE_SANDBOX", "0") == "1"
        
        # Private key can be provided as file path or direct content
        key_path = os.environ.get("APNS_KEY_PATH")
        key_content = os.environ.get("APNS_KEY_CONTENT")
        
        self.private_key = None
        if key_path and os.path.exists(key_path):
            with open(key_path, 'r') as f:
                self.private_key = f.read()
        elif key_content:
            # Handle escaped newlines in env var
            self.private_key = key_content.replace('\\n', '\n')
    
    def is_configured(self) -> bool:
        """Check if APNs is properly configured"""
        return all([
            self.team_id,
            self.key_id,
            self.bundle_id,
            self.private_key
        ])
    
    def _generate_token(self) -> str:
        """Generate JWT token for APNs authentication"""
        headers = {
            "alg": "ES256",
            "kid": self.key_id
        }
        payload = {
            "iss": self.team_id,
            "iat": int(time.time())
        }
        return jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
    
    async def send_voip_push(
        self,
        device_token: str,
        payload: Dict[str, Any],
        call_id: str
    ) -> PushResult:
        """
        Send VoIP push notification to iOS device.
        
        Args:
            device_token: The VoIP device token
            payload: The push payload
            call_id: Unique call identifier for idempotency
        
        Returns:
            PushResult with success status and details
        """
        if not self.is_configured():
            return PushResult(
                success=False,
                platform="ios",
                error="APNs not configured",
                error_code="not_configured"
            )
        
        host = self.APNS_SANDBOX_HOST if self.use_sandbox else self.APNS_PRODUCTION_HOST
        url = f"https://{host}/3/device/{device_token}"
        
        # VoIP push uses .voip suffix on bundle ID
        topic = f"{self.bundle_id}.voip"
        
        headers = {
            "authorization": f"bearer {self._generate_token()}",
            "apns-topic": topic,
            "apns-push-type": "voip",
            "apns-priority": "10",  # High priority for VoIP
            "apns-expiration": "0",  # Immediate delivery only
            "apns-collapse-id": call_id,
        }
        
        try:
            async with httpx.AsyncClient(http2=True) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    apns_id = response.headers.get("apns-id")
                    logger.info(f"[APNs] VoIP push sent successfully: {apns_id}")
                    return PushResult(
                        success=True,
                        platform="ios",
                        message_id=apns_id
                    )
                else:
                    try:
                        error_body = response.json()
                        reason = error_body.get("reason", "Unknown")
                    except:
                        reason = response.text or "Unknown error"
                    
                    logger.error(f"[APNs] Push failed: {response.status_code} - {reason}")
                    return PushResult(
                        success=False,
                        platform="ios",
                        error=reason,
                        error_code=str(response.status_code)
                    )
                    
        except httpx.TimeoutException:
            logger.error("[APNs] Push timeout")
            return PushResult(
                success=False,
                platform="ios",
                error="Request timeout",
                error_code="timeout"
            )
        except Exception as e:
            logger.error(f"[APNs] Push exception: {e}")
            return PushResult(
                success=False,
                platform="ios",
                error=str(e),
                error_code="exception"
            )


class FCMService:
    """
    Firebase Cloud Messaging service for Android.
    Uses Firebase Admin SDK for sending messages.
    """
    
    def __init__(self):
        self._messaging = None
        self._initialized = False
    
    def _get_messaging(self):
        """Get Firebase messaging module (lazy initialization)"""
        if self._messaging is not None:
            return self._messaging
        
        try:
            from firebase_admin import messaging
            from .firebase_service import get_firebase_app
            
            app = get_firebase_app()
            if app is not None:
                self._messaging = messaging
                self._initialized = True
                logger.info("[FCM] Firebase messaging initialized")
            else:
                logger.warning("[FCM] Firebase app not initialized")
                
        except ImportError as e:
            logger.error(f"[FCM] Firebase Admin SDK not installed: {e}")
        except Exception as e:
            logger.error(f"[FCM] Initialization error: {e}")
        
        return self._messaging
    
    def is_configured(self) -> bool:
        """Check if FCM is properly configured"""
        return self._get_messaging() is not None
    
    async def send_data_message(
        self,
        device_token: str,
        data: Dict[str, str],
        call_id: str,
        ttl: int = 60
    ) -> PushResult:
        """
        Send high-priority data message to Android device.
        
        Args:
            device_token: The FCM device token
            data: Data payload (all values must be strings)
            call_id: Unique call identifier
            ttl: Time to live in seconds
        
        Returns:
            PushResult with success status and details
        """
        messaging = self._get_messaging()
        if messaging is None:
            return PushResult(
                success=False,
                platform="android",
                error="FCM not configured",
                error_code="not_configured"
            )
        
        # Ensure all data values are strings
        string_data = {k: str(v) for k, v in data.items()}
        
        try:
            # Create FCM message
            message = messaging.Message(
                token=device_token,
                data=string_data,
                android=messaging.AndroidConfig(
                    priority="high",
                    ttl=ttl,
                    direct_boot_ok=True,
                )
            )
            
            # Send message (synchronous, but fast)
            response = messaging.send(message)
            
            logger.info(f"[FCM] Message sent successfully: {response}")
            return PushResult(
                success=True,
                platform="android",
                message_id=response
            )
            
        except messaging.UnregisteredError:
            logger.warning(f"[FCM] Token unregistered: {device_token[:20]}...")
            return PushResult(
                success=False,
                platform="android",
                error="Token unregistered",
                error_code="UNREGISTERED"
            )
        except messaging.SenderIdMismatchError:
            logger.error("[FCM] Sender ID mismatch")
            return PushResult(
                success=False,
                platform="android",
                error="Sender ID mismatch",
                error_code="SENDER_ID_MISMATCH"
            )
        except Exception as e:
            logger.error(f"[FCM] Send error: {e}")
            return PushResult(
                success=False,
                platform="android",
                error=str(e),
                error_code="exception"
            )


class PushNotificationService:
    """
    Unified push notification service that handles both iOS and Android.
    """
    
    def __init__(self):
        self.apns = APNsVoIPService()
        self.fcm = FCMService()
    
    async def send_incoming_call_push(
        self,
        platform: str,
        fcm_token: Optional[str],
        voip_token: Optional[str],
        call_id: str,
        channel_name: str,
        caller_name: str,
        group_id: str,
        receiver_id: str,
        caller_id: str
    ) -> PushResult:
        """
        Send incoming call push notification.
        
        Args:
            platform: 'ios' or 'android'
            fcm_token: Android FCM token (for Android)
            voip_token: iOS VoIP token (for iOS)
            call_id: Unique call identifier
            channel_name: Agora channel name
            caller_name: Display name of caller
            group_id: Group identifier
            receiver_id: Receiver's user ID
            caller_id: Caller's user ID
        
        Returns:
            PushResult with success status
        """
        payload = {
            "type": "incoming_call",
            "callId": call_id,
            "channelName": channel_name,
            "callerName": caller_name,
            "callerId": caller_id,
            "groupId": group_id,
            "receiverId": receiver_id,
        }
        
        if platform == "ios" and voip_token:
            # iOS VoIP push - uses APNs with special topic
            apns_payload = {
                "aps": {
                    "alert": {
                        "title": "Incoming Call",
                        "body": f"{caller_name} is calling..."
                    },
                    "sound": "default"
                },
                **payload
            }
            return await self.apns.send_voip_push(voip_token, apns_payload, call_id)
        
        elif platform == "android" and fcm_token:
            # Android FCM data message
            return await self.fcm.send_data_message(fcm_token, payload, call_id)
        
        else:
            missing = "voipToken" if platform == "ios" else "fcmToken"
            return PushResult(
                success=False,
                platform=platform,
                error=f"Missing {missing} for {platform}",
                error_code="missing_token"
            )
    
    async def send_call_cancelled_push(
        self,
        platform: str,
        fcm_token: Optional[str],
        voip_token: Optional[str],
        call_id: str,
        channel_name: str
    ) -> PushResult:
        """
        Send call cancelled push notification (caller hung up before answer).
        """
        payload = {
            "type": "call_cancelled",
            "callId": call_id,
            "channelName": channel_name,
        }
        
        if platform == "ios" and voip_token:
            apns_payload = {
                "aps": {
                    "content-available": 1
                },
                **payload
            }
            return await self.apns.send_voip_push(voip_token, apns_payload, call_id)
        
        elif platform == "android" and fcm_token:
            return await self.fcm.send_data_message(fcm_token, payload, call_id)
        
        else:
            return PushResult(
                success=False,
                platform=platform,
                error="No valid token",
                error_code="missing_token"
            )


# Singleton instance
push_service = PushNotificationService()

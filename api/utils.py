import asyncio
from datetime import datetime

from .constants import DEFAULT_TOKEN_EXPIRE_SECONDS, MAX_TOKEN_EXPIRE_SECONDS, ROLE_PUBLISHER, ROLE_SUBSCRIBER


def parse_role(value):
    if value is None:
        return ROLE_SUBSCRIBER
    if isinstance(value, int):
        return ROLE_PUBLISHER if value == ROLE_PUBLISHER else ROLE_SUBSCRIBER
    if isinstance(value, str):
        value = value.lower()
        if value in {"publisher", "host", "broadcaster"}:
            return ROLE_PUBLISHER
        if value in {"subscriber", "audience"}:
            return ROLE_SUBSCRIBER
    return None


def clamp_expire(expire):
    try:
        expire = int(expire)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_EXPIRE_SECONDS
    if expire <= 0:
        return DEFAULT_TOKEN_EXPIRE_SECONDS
    return min(expire, MAX_TOKEN_EXPIRE_SECONDS)


def run_async(coro):
    """Helper to run async code in sync Django views."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def generate_channel_name(group_id: str, caller_id: str, receiver_id: str) -> str:
    """Generate channel name: {groupId}_{callerId}_{receiverId}_{timestamp}."""
    timestamp = int(datetime.utcnow().timestamp() * 1000)  # milliseconds
    return f"{group_id}_{caller_id}_{receiver_id}_{timestamp}"


def normalize_datetime(value):
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return datetime.fromtimestamp(value.timestamp())
    if isinstance(value, datetime):
        return value
    return None

"""Firebase Cloud Messaging push notifications — stub for Phase 1."""
import logging

logger = logging.getLogger(__name__)


async def send_push(fcm_token: str, title: str, body: str, data: dict | None = None):
    """Send FCM push notification. Requires firebase-credentials.json in Phase 2+."""
    # TODO: initialize firebase_admin and call messaging.send()
    logger.info(f"[PUSH STUB] token={fcm_token[:10]}... title={title} body={body}")

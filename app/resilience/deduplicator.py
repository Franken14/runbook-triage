import hashlib
import json
import logging
from typing import Dict, Any, Optional, Tuple

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from app.config import settings

logger = logging.getLogger(__name__)


class AlertDeduplicator:
    """
    Redis alert deduplicator to suppress alert storms.
    Computes deterministic fingerprint from alert labels/attributes,
    uses sliding window TTL with atomic Redis operations.
    """

    def __init__(self, redis_url: str = settings.REDIS_URL, window_seconds: int = settings.DEDUPLICATION_WINDOW_SECONDS):
        self.redis_url = redis_url
        self.window_seconds = window_seconds
        self._redis_client: Optional[redis.Redis] = None
        self._memory_cache: Dict[str, float] = {}

    async def get_client(self):
        if redis is None:
            raise RuntimeError("Redis module not installed")
        if not self._redis_client:
            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis_client

    async def close(self):
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None

    def compute_fingerprint(self, alert_payload: Dict[str, Any]) -> str:
        """
        Derives stable SHA-256 fingerprint from service, alert_name, host/pod, and severity.
        """
        service = alert_payload.get("service") or alert_payload.get("labels", {}).get("service", "unknown")
        alert_name = alert_payload.get("alert_name") or alert_payload.get("name") or "alert"
        entity = (
            alert_payload.get("pod")
            or alert_payload.get("host")
            or alert_payload.get("instance")
            or alert_payload.get("labels", {}).get("instance", "cluster")
        )
        severity = alert_payload.get("severity", "medium").lower()

        canonical_str = f"{service}:{alert_name}:{entity}:{severity}".lower()
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    async def check_and_record(self, alert_payload: Dict[str, Any]) -> Tuple[bool, str, int]:
        """
        Checks if alert is a duplicate within the deduplication window.
        Returns:
            Tuple of (is_duplicate: bool, fingerprint: str, count: int)
        """
        fingerprint = self.compute_fingerprint(alert_payload)
        key = f"alert_dedup:{fingerprint}"
        count_key = f"alert_count:{fingerprint}"

        try:
            r = await self.get_client()
            # SET NX sets the key only if it does not already exist
            is_new = await r.set(key, json.dumps({"first_seen": alert_payload.get("timestamp")}), ex=self.window_seconds, nx=True)
            
            if is_new:
                # First alert in window
                await r.set(count_key, 1, ex=self.window_seconds)
                logger.info(f"New alert registered [fp={fingerprint[:8]}]. Triggering runbook agent.")
                return False, fingerprint, 1
            else:
                # Duplicate alert during storm
                count = await r.incr(count_key)
                logger.warning(f"Duplicate alert suppressed [fp={fingerprint[:8]}]. Storm count: {count}")
                return True, fingerprint, int(count)

        except Exception as e:
            # Fallback gracefully if Redis is unavailable
            logger.debug(f"Redis deduplication unavailable ({e}), falling back to in-memory debounce.")
            import time
            now = time.time()
            if fingerprint in self._memory_cache and (now - self._memory_cache[fingerprint]) < self.window_seconds:
                return True, fingerprint, 2
            self._memory_cache[fingerprint] = now
            return False, fingerprint, 1

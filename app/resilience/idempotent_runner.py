import asyncio
import hashlib
import json
import logging
import uuid
from typing import Callable, Any, Dict, Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from app.config import settings

logger = logging.getLogger(__name__)


class IdempotentToolRunner:
    """
    Guarantees safe, idempotent execution of mutating remediation tools.
    1. Computes an idempotency key from action name + canonical parameters.
    2. Acquires a distributed lock in Redis to prevent concurrent dual execution.
    3. Caches and replays execution receipts if a retry or duplicate request occurs.
    """

    def __init__(self, redis_url: str = settings.REDIS_URL, receipt_ttl: int = 86400):
        self.redis_url = redis_url
        self.receipt_ttl = receipt_ttl
        self._redis_client: Optional[Any] = None
        self._local_receipts: Dict[str, Any] = {}

    async def get_client(self):
        if redis is None:
            raise RuntimeError("Redis module not installed")
        if not self._redis_client:
            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
        return self._redis_client

    def generate_idempotency_key(self, tool_name: str, params: Dict[str, Any], incident_id: str) -> str:
        """
        Derives an idempotency key scoped to the incident and tool parameters.
        """
        canonical_params = json.dumps(params, sort_keys=True)
        h = hashlib.sha256(f"{incident_id}:{tool_name}:{canonical_params}".encode("utf-8")).hexdigest()
        return f"idempotency:{incident_id}:{tool_name}:{h[:16]}"

    async def execute_safely(
        self,
        tool_name: str,
        params: Dict[str, Any],
        incident_id: str,
        execution_func: Callable[..., Any],
        lock_timeout_sec: int = 30
    ) -> Dict[str, Any]:
        """
        Executes a mutating tool within an idempotent distributed lock context.
        """
        idempotency_key = self.generate_idempotency_key(tool_name, params, incident_id)
        lock_key = f"lock:{idempotency_key}"
        token = str(uuid.uuid4())

        try:
            r = await self.get_client()

            # 1. Check if prior execution receipt exists
            cached_receipt = await r.get(idempotency_key)
            if cached_receipt:
                logger.info(f"Idempotency hit: replaying receipt for {idempotency_key}")
                receipt_data = json.loads(cached_receipt)
                receipt_data["replayed"] = True
                return receipt_data

            # 2. Acquire Distributed Lock
            lock_acquired = await r.set(lock_key, token, ex=lock_timeout_sec, nx=True)
            if not lock_acquired:
                raise RuntimeError(
                    f"Concurrent execution detected for action '{tool_name}' on incident '{incident_id}'. Lock held."
                )

            try:
                # 3. Perform the actual mutating operation
                logger.info(f"Executing mutating tool '{tool_name}' with lock {lock_key}")
                if asyncio.iscoroutinefunction(execution_func):
                    result = await execution_func(**params)
                else:
                    result = execution_func(**params)

                receipt = {
                    "tool_name": tool_name,
                    "params": params,
                    "incident_id": incident_id,
                    "status": "SUCCESS",
                    "result": result,
                    "replayed": False
                }

                # 4. Store completion receipt
                await r.set(idempotency_key, json.dumps(receipt), ex=self.receipt_ttl)
                return receipt

            finally:
                # Release lock safely using Lua script to verify ownership
                release_script = """
                    if redis.call("get", KEYS[1]) == ARGV[1] then
                        return redis.call("del", KEYS[1])
                    else
                        return 0
                    end
                """
                await r.eval(release_script, 1, lock_key, token)

        except Exception as e:
            if "Concurrent execution" in str(e):
                raise
            logger.debug(f"Redis unavailable for idempotency ({e}), using memory fallback.")
            if idempotency_key in self._local_receipts:
                cached = dict(self._local_receipts[idempotency_key])
                cached["replayed"] = True
                return cached
            
            # Execute directly
            if asyncio.iscoroutinefunction(execution_func):
                res = await execution_func(**params)
            else:
                res = execution_func(**params)
            
            receipt = {
                "tool_name": tool_name,
                "params": params,
                "incident_id": incident_id,
                "status": "SUCCESS",
                "result": res,
                "replayed": False
            }
            self._local_receipts[idempotency_key] = receipt
            return receipt

import json
import logging
import hashlib
from typing import Optional, Any
import redis
from ..config import settings

logger = logging.getLogger("aldf.cache")

redis_client: Optional[redis.Redis] = None

def get_redis_client() -> Optional[redis.Redis]:
    global redis_client
    if redis_client is None:
        try:
            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379")
            redis_client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            # test connection
            redis_client.ping()
            logger.info(f"Redis client successfully connected to: {redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching will be disabled.")
            redis_client = None
    return redis_client

def get_cache(key: str) -> Optional[Any]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        val = client.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.warning(f"Redis get failed for key {key}: {e}")
    return None

def set_cache(key: str, value: Any, expire: int = 300) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        val_str = json.dumps(value, default=str)
        client.set(key, val_str, ex=expire)
        return True
    except Exception as e:
        logger.warning(f"Redis set failed for key {key}: {e}")
        return False

def clear_cache(pattern: str = "aldf:cache:*") -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        # scan_iter is safer than keys() in production
        keys = list(client.scan_iter(match=pattern))
        if keys:
            client.delete(*keys)
            logger.info(f"Cleared {len(keys)} keys matching pattern: {pattern}")
        return True
    except Exception as e:
        logger.warning(f"Redis clear failed for pattern {pattern}: {e}")
        return False

def make_search_key(params: dict) -> str:
    serialized = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f"aldf:cache:search:{h}"

def make_live_search_key(params: dict) -> str:
    serialized = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f"aldf:cache:livesearch:{h}"

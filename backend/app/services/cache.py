import json
import logging
import hashlib
import time
import fnmatch
from typing import Optional, Any
import redis
from ..config import settings

logger = logging.getLogger("aldf.cache")

class InMemoryCache:
    def __init__(self):
        self._data = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> Optional[str]:
        if key not in self._data:
            return None
        val_str, expire_at = self._data[key]
        if expire_at is not None and time.time() > expire_at:
            del self._data[key]
            return None
        return val_str

    def set(self, key: str, value_str: str, ex: Optional[int] = None) -> bool:
        expire_at = time.time() + ex if ex is not None else None
        self._data[key] = (value_str, expire_at)
        return True

    def scan_iter(self, match: str = "*"):
        for key in list(self._data.keys()):
            _, expire_at = self._data[key]
            if expire_at is not None and time.time() > expire_at:
                del self._data[key]
                continue
            if fnmatch.fnmatch(key, match):
                yield key

    def delete(self, *keys) -> int:
        count = 0
        for key in keys:
            if self._data.pop(key, None) is not None:
                count += 1
        return count

in_memory_cache = InMemoryCache()
redis_client: Optional[Any] = None

def get_redis_client() -> Optional[Any]:
    global redis_client
    if redis_client is None:
        try:
            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379")
            client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            # test connection
            client.ping()
            redis_client = client
            logger.info(f"Redis client successfully connected to: {redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory caching.")
            redis_client = in_memory_cache
    return redis_client

def get_cache(key: str) -> Optional[Any]:
    global redis_client
    client = get_redis_client()
    if client is None:
        return None
    try:
        val = client.get(key)
        if val:
            return json.loads(val)
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
        logger.warning(f"Redis connection failed during get: {e}. Switching to in-memory fallback cache.")
        redis_client = in_memory_cache
        return get_cache(key)
    except Exception as e:
        logger.warning(f"Cache get failed for key {key}: {e}")
    return None

def set_cache(key: str, value: Any, expire: int = 300) -> bool:
    global redis_client
    client = get_redis_client()
    if client is None:
        return False
    try:
        val_str = json.dumps(value, default=str)
        client.set(key, val_str, ex=expire)
        return True
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
        logger.warning(f"Redis connection failed during set: {e}. Switching to in-memory fallback cache.")
        redis_client = in_memory_cache
        return set_cache(key, value, expire)
    except Exception as e:
        logger.warning(f"Cache set failed for key {key}: {e}")
        return False

def clear_cache(pattern: str = "aldf:cache:*") -> bool:
    global redis_client
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
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
        logger.warning(f"Redis connection failed during clear: {e}. Switching to in-memory fallback cache.")
        redis_client = in_memory_cache
        return clear_cache(pattern)
    except Exception as e:
        logger.warning(f"Cache clear failed for pattern {pattern}: {e}")
        return False

def make_search_key(params: dict) -> str:
    serialized = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f"aldf:cache:search:{h}"

def make_live_search_key(params: dict) -> str:
    serialized = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f"aldf:cache:livesearch:{h}"


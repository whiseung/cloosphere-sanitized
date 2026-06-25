import json
import logging
import uuid

import redis

from open_webui.utils.redis import get_redis_connection

log = logging.getLogger(__name__)


class RedisLock:
    def __init__(self, redis_url, lock_name, timeout_secs, redis_sentinels=[]):
        self.lock_name = lock_name
        self.lock_id = str(uuid.uuid4())
        self.timeout_secs = timeout_secs
        self.lock_obtained = False
        self.redis = get_redis_connection(
            redis_url, redis_sentinels, decode_responses=True
        )

    def aquire_lock(self):
        try:
            # nx=True will only set this key if it _hasn't_ already been set
            self.lock_obtained = self.redis.set(
                self.lock_name, self.lock_id, nx=True, ex=self.timeout_secs
            )
            return self.lock_obtained
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, lock acquire skipped: {e}")
            return False

    def renew_lock(self):
        try:
            # xx=True will only set this key if it _has_ already been set
            return self.redis.set(
                self.lock_name, self.lock_id, xx=True, ex=self.timeout_secs
            )
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, lock renew skipped: {e}")
            return False

    def release_lock(self):
        try:
            lock_value = self.redis.get(self.lock_name)
            if lock_value and lock_value == self.lock_id:
                self.redis.delete(self.lock_name)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, lock release skipped: {e}")


class RedisDict:
    def __init__(self, name, redis_url, redis_sentinels=[]):
        self.name = name
        self.redis = get_redis_connection(
            redis_url, redis_sentinels, decode_responses=True
        )

    def __setitem__(self, key, value):
        try:
            serialized_value = json.dumps(value)
            self.redis.hset(self.name, key, serialized_value)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, skipping set for {self.name}[{key}]: {e}")

    def __getitem__(self, key):
        try:
            value = self.redis.hget(self.name, key)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(
                f"Redis unavailable, key lookup failed for {self.name}[{key}]: {e}"
            )
            raise KeyError(key) from e
        if value is None:
            raise KeyError(key)
        return json.loads(value)

    def __delitem__(self, key):
        try:
            result = self.redis.hdel(self.name, key)
            if result == 0:
                raise KeyError(key)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(
                f"Redis unavailable, skipping delete for {self.name}[{key}]: {e}"
            )

    def __contains__(self, key):
        try:
            return self.redis.hexists(self.name, key)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(
                f"Redis unavailable, contains check failed for {self.name}: {e}"
            )
            return False

    def __len__(self):
        try:
            return self.redis.hlen(self.name)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, len failed for {self.name}: {e}")
            return 0

    def keys(self):
        try:
            return self.redis.hkeys(self.name)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, keys failed for {self.name}: {e}")
            return []

    def values(self):
        try:
            return [json.loads(v) for v in self.redis.hvals(self.name)]
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, values failed for {self.name}: {e}")
            return []

    def items(self):
        try:
            return [
                (k, json.loads(v)) for k, v in self.redis.hgetall(self.name).items()
            ]
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, items failed for {self.name}: {e}")
            return []

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def clear(self):
        try:
            self.redis.delete(self.name)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            log.warning(f"Redis unavailable, clear failed for {self.name}: {e}")

    def update(self, other=None, **kwargs):
        if other is not None:
            for k, v in other.items() if hasattr(other, "items") else other:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

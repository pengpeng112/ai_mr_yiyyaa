# -*- coding: utf-8 -*-
"""线程安全轻量 TTL 缓存（WP01 T1，064 总计划）。

- 标准库 threading + time，零第三方依赖；
- `time.monotonic()` 判过期（不受系统时钟跳变影响）；
- `get_or_set` 未命中时**释放锁执行 loader**，防止慢 SQL 阻塞所有其他线程
  （并发未命中可能出现重复 loader 调用，属可接受的最终一致——调用方多为幂等只读 SQL）；
- 超过 maxsize 先清理已过期项，仍超限淘汰最早过期项。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    """最小 TTL 缓存：get/set/get_or_set/invalidate_prefix/clear。"""

    def __init__(self, maxsize: int = 512) -> None:
        self._maxsize = max(1, int(maxsize))
        self._data: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        """命中返回值；不存在或已过期返回 None（过期项顺带清理）。"""
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires_at = item
            if now >= expires_at:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        ttl = max(0.001, float(ttl_seconds))
        with self._lock:
            self._data[key] = (value, time.monotonic() + ttl)
            self._evict_if_needed_locked()

    def get_or_set(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        """命中返回缓存值；未命中释放锁执行 loader 后写回（锁内不执行慢 loader）。"""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = loader()
        self.set(key, value, ttl_seconds)
        return value

    def invalidate_prefix(self, prefix: str) -> int:
        """按前缀失效，返回删除条数。"""
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                self._data.pop(k, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    # ---- 内部 ----

    def _evict_if_needed_locked(self) -> None:
        """调用方必须已持锁。超限先清过期项，仍超限淘汰最早过期项。"""
        if len(self._data) <= self._maxsize:
            return
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._data.items() if now >= exp]
        for k in expired:
            self._data.pop(k, None)
        while len(self._data) > self._maxsize:
            oldest_key = min(self._data, key=lambda k: self._data[k][1])
            self._data.pop(oldest_key, None)


# 全局共享实例（stats/logs/预检等模块复用）
app_ttl_cache = TTLCache(maxsize=512)

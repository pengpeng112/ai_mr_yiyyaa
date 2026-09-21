# -*- coding: utf-8 -*-
"""046 T4/F04：可刷新规则集（发布后新任务读到新版本，无需重启服务）。

- RefreshableRuleSet：loader + TTL 缓存（缺省 60s，可配 rule_registry.refresh_ttl_seconds）；
- 单次 evaluate 内快照一致（PrecheckProcessor 每患者取一次 snapshot）；
- 发布/回滚后 force_refresh() 可立即生效（管理 API 调用），否则最迟 TTL 后生效。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Tuple


class RefreshableRuleSet:
    def __init__(self, loader: Callable[[], Tuple[list, str]],
                 ttl_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.loader = loader
        self.ttl_seconds = float(ttl_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self._specs: Optional[list] = None
        self._version: str = ""
        self._loaded_at: float = -1.0
        self.refresh_count = 0

    def snapshot(self) -> Tuple[list, str]:
        """取当前规则快照；过期（TTL）才重新加载（fail-open：加载失败沿用旧快照）。"""
        now = self.clock()
        with self._lock:
            if self._specs is None or (now - self._loaded_at) > self.ttl_seconds:
                try:
                    specs, version = self.loader()
                    self._specs, self._version = specs, version
                    self.refresh_count += 1
                except Exception:   # noqa: BLE001 —— 刷新失败沿用旧快照（可用性优先）
                    if self._specs is None:
                        raise
                self._loaded_at = now
            return self._specs, self._version

    def force_refresh(self) -> Tuple[list, str]:
        with self._lock:
            self._loaded_at = -1.0
        return self.snapshot()

    @property
    def version(self) -> str:
        return self._version

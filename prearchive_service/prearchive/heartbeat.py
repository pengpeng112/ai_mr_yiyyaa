# -*- coding: utf-8 -*-
"""自监控心跳（028 R13）：轮询每轮写心跳文件，外部可探测服务是否停跳。

心跳文件内容：{"ts": ISO时间, "alive": true, "watermark": ..., "iterations": N, ...}
外部探测：读文件判断 ts 距今是否超过 max_age_seconds。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Heartbeat:
    def __init__(self, path):
        self.path = Path(path)

    def write(self, extra: Optional[dict] = None) -> dict:
        """原子写心跳（临时文件 + replace），失败静默（心跳自身不能拖垮轮询）。"""
        try:
            record = {"ts": _now_iso(), "alive": True}
            if extra:
                record.update(extra)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                            prefix=".heartbeat_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(record, handle, ensure_ascii=False)
                os.replace(tmp_name, str(self.path))
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return record
        except Exception:
            return {}

    def read(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def is_alive(self, max_age_seconds: int) -> bool:
        record = self.read()
        if not record or not record.get("alive"):
            return False
        try:
            ts = datetime.fromisoformat(str(record.get("ts")))
        except ValueError:
            return False
        age = (datetime.now() - ts).total_seconds()
        return 0 <= age <= max_age_seconds

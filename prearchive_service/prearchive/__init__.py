# -*- coding: utf-8 -*-
"""归档前病历预检服务（028 一期原型）。

独立于 Med-Audit 主服务（隔离边界见 docs/ACTIVE/028 §2）：
- 本包内禁止 import app.*（由 check_isolation.py 强制检查）；
- 凭据加密独立实现（不共享主服务 SECRET_KEY）；
- 结果表独立（MED_PREARCHIVE_*），DDL 随码但不自动执行。
"""

__version__ = "0.1.0"

# -*- coding: utf-8 -*-
"""pytest 路径引导：把 prearchive_service/ 加入 sys.path（包名 prearchive）。"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

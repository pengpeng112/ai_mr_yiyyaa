"""兼容入口：统一调用脱敏 Vastbase 只读诊断。"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("debug_emr.py")), run_name="__main__")

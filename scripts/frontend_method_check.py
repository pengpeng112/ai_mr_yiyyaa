"""核查 9: 模板调用的关键 JS 方法是否在 app.js / modules 中定义"""
from pathlib import Path
import re

STATIC = Path(__file__).parent.parent / "static"
TPL = STATIC / "templates" / "pages"
APP_JS = (STATIC / "scripts" / "app.js").read_text(encoding="utf-8")

modules = ""
for f in (STATIC / "scripts" / "modules").glob("*.js"):
    modules += f.read_text(encoding="utf-8")

all_js = APP_JS + modules

# 阶段 7-11 新增/依赖的关键方法
methods_to_check = [
    ("schedulerModeLabel", "定时任务模式标签"),
    ("dischargeModeLabel", "出院终末模式标签"),
    ("schedulerStatusTagType", "调度状态 tag"),
    ("schedulerSuccessRate", "成功率计算"),
    ("schedulerSuccessRateLabel", "成功率标签"),
    ("schedulerLatestHistory", "最近执行"),
    ("schedulerRuntimeWarnings", "配置风险"),
    ("ppDurationLabel", "推送进度耗时格式化"),
    ("ppProgressPct", "推送进度百分比"),
    ("ppProgressStatus", "推送进度状态"),
    ("ppProgressLabel", "推送进度标签"),
    ("ppStatusLabel", "推送进度状态标签"),
    ("ppStatusTagType", "推送进度 tag"),
    ("viewPPLogs", "推送进度查看日志"),
    ("configStatusText", "配置状态文本"),
    ("configStatusTagType", "配置状态 tag"),
    ("auditTypeBuilderLabel", "审计类型构建器标签"),
    ("auditTypeRuntimeWarnings", "审计类型风险"),
    ("saveRelayAlertDeptFilter", "保存告警科室过滤"),
    ("relayPreview", "推送预览"),
    ("buildSchedulerWindow", "调度时间窗口"),
    ("viewSchedulerHistoryLogs", "查看调度历史日志"),
]

problems = []
for method, label in methods_to_check:
    # 检查定义（方法名( 或 方法名: 或 async 方法名()
    defined = bool(re.search(rf"\b{method}\s*[(\(:]", all_js))
    if defined:
        print(f"  [OK] {method} ({label})")
    else:
        print(f"  [高] {method} 未定义 ({label})")
        problems.append(method)

print(f"\n未定义方法: {len(problems)}")

"""Static frontend regression checks for the non-build Vue frontend."""
from pathlib import Path
import re

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "static"
TPL = STATIC / "templates" / "pages"
CSS = STATIC / "styles" / "pages"
APP_JS = STATIC / "scripts" / "app.js"
NAV_JS = STATIC / "scripts" / "navigation.js"
INDEX = STATIC / "index.html"


def read(path):
    return path.read_text(encoding="utf-8")


problems = []


def check(cond, ok_msg, fail_msg, severity="medium"):
    if cond:
        print(f"  [OK] {ok_msg}")
    else:
        print(f"  [{severity}] {fail_msg}")
        problems.append((severity, fail_msg))


print("=" * 70)
print("check 1: template root classes")
print("=" * 70)

root_class_checks = [
    ("dashboard.html", "dashboard-tech-v2"),
    ("patient_qc.html", "page-patient-qc"),
    ("relay_alert.html", "page-relay-alert"),
    ("feedback.html", "page-feedback"),
    ("audit.html", "page-logs"),
    ("push.html", "page-push"),
    ("scheduler.html", "page-scheduler"),
    ("push_progress.html", "page-push-progress"),
    ("config.html", "page-config"),
    ("audit_types.html", "page-audit-types"),
    ("relay.html", "page-relay-config"),
    ("health.html", "page-health"),
    ("debug.html", "page-debug"),
    ("access.html", "page-access"),
    ("placeholder.html", "page-oracle-status"),
    ("placeholder.html", "page-system-logs"),
]
for fname, cls in root_class_checks:
    html = read(TPL / fname)
    check(cls in html, f"{fname} has {cls}", f"{fname} missing root class {cls}", "high")

print()
print("=" * 70)
print("check 2: medical-data-table usage")
print("=" * 70)

mdt_checks = [
    ("patient_qc.html", "patient qc"),
    ("relay_alert.html", "relay alert"),
    ("feedback.html", "feedback"),
    ("audit.html", "logs"),
    ("scheduler.html", "scheduler"),
    ("push_progress.html", "push progress"),
    ("audit_types.html", "audit types"),
    ("relay.html", "relay config"),
    ("access.html", "access"),
]
for fname, label in mdt_checks:
    html = read(TPL / fname)
    count = html.count("medical-data-table")
    check(count > 0, f"{fname}({label}) medical-data-table x{count}",
          f"{fname}({label}) missing medical-data-table", "medium")

print()
print("=" * 70)
print("check 3: index.html asset/template versions")
print("=" * 70)
idx = read(INDEX)

version_checks = [
    ("app.css", "20260708-stage7-v2"),
    ("sidebar.css", "20260708-stage7-v3"),
    ("header.css", "20260708-stage7-v1"),
    ("dashboard.css", "20260708-dashboard-v4"),
    ("logs.css", "20260708-logs-v2"),
    ("feedback.css", "20260708-stage4-v1"),
    ("patient_qc.css", "20260708-stage4-v1"),
    ("push_compact.css", "20260708-stage5-v1"),
    ("push_progress.css", "20260708-stage5-v1"),
    ("relay_alert.css", "20260708-stage4-v1"),
    ("scheduler.css", "20260708-stage5-v1"),
    ("config.css", "20260708-stage6-v1"),
    ("audit_types.css", "20260708-stage3-v1"),
    ("patient_qc.html", "20260708-patient-qc-v3"),
    ("config.html", "20260716-dify-pool-v1"),
    ("health.html", "20260708-stage6-v1"),
    ("debug.html", "20260708-stage6-v1"),
    ("app.js", "20260716-dify-pool-v1"),
]
for fname, ver in version_checks:
    needle = f"{fname}?v={ver}"
    check(needle in idx, f"index.html: {needle}", f"index.html missing/mismatched {needle}", "high")

print()
print("=" * 70)
print("check 4: app.js import versions")
print("=" * 70)
appjs = read(APP_JS)

import_checks = [
    ("./navigation.js", "20260708-stage7-v1"),
    ("modules/dashboard.js", "20260708-dashboard-v5"),
    ("modules/logs.js", "20260708-logs-v2"),
    ("modules/feedback.js", "20260708-stage3-v1"),
    ("modules/push.js", "20260716-dify-pool-v1"),
    ("modules/push_progress.js", "20260628-push-progress-v1"),
    ("modules/patient_qc.js", "20260708-patient-qc-v3"),
    ("modules/stats.js", "20260708-dashboard-v4"),
    ("modules/scheduler.js", "20260628-scheduler-v1"),
    ("modules/config.js", "20260716-dify-pool-v1"),
    ("modules/audit_types.js", "20260708-stage3-v1"),
]
for path, ver in import_checks:
    needle = f"{path}?v={ver}"
    check(needle in appjs, f"app.js import: {needle}", f"app.js import version mismatch: {needle}", "high")

print()
print("=" * 70)
print("check 5: page feature markers")
print("=" * 70)

feature_checks = [
    ("dashboard.html", ["dashboard-kpi-core", "dashboard-kpi-aux", "完整闭环", "ai-flow-line"], "dashboard v3"),
    ("patient_qc.html", ["pq-summary-strip", "总病例", "本页高危"], "patient qc summary"),
    ("relay_alert.html", ["relay-alert-summary-strip", "发送成功率", "医生查看率"], "relay alert summary"),
    ("scheduler.html", ["scheduler-status-strip", "scheduler-pulse-dot", "schedulerModeLabel()", "scheduler-flow-strip"], "scheduler status"),
    ("push_progress.html", ["pp-summary-strip", "pp-summary-pulse", "ppDurationLabel", "pp-flow-strip"], "push progress summary"),
    ("config.html", ["config-summary-strip", "config-secret-hint", "config-secret-item", "config-flow-note", "runtime-page-intro"], "config summary"),
    ("health.html", ["ops-page-intro", "ops-health-strip", "Object.values(healthComps || {})"], "health ops summary"),
    ("debug.html", ["ops-page-intro", "debug-workbench", "debug-result-strip"], "debug ops summary"),
    ("audit_types.html", ["audit-type-summary-strip", "mr_txt", "medical-data-table"], "audit type summary"),
    ("relay.html", ["relay-summary-strip", "medical-data-table"], "relay config summary"),
]
for fname, needles, label in feature_checks:
    html = read(TPL / fname)
    for needle in needles:
        check(needle in html, f"{fname}: has {needle}", f"{fname}: missing {needle} ({label})", "medium")

print()
print("=" * 70)
print("check 6: CSS scope markers")
print("=" * 70)

css_scope_checks = [
    ("dashboard.css", ".dashboard-tech-v2"),
    ("scheduler.css", ".page-scheduler .medical-data-table"),
    ("push_progress.css", ".page-push-progress .medical-data-table"),
    ("push_compact.css", ".push-flow-strip"),
    ("config.css", ".page-config .config-summary-strip"),
    ("config.css", ".ops-page-intro"),
    ("config.css", ".ops-health-strip"),
    ("config.css", ".debug-workbench"),
    ("config.css", ".page-relay-config .relay-summary-strip"),
    ("audit_types.css", ".page-audit-types .audit-type-summary-strip"),
    ("audit_types.css", ".page-audit-types .medical-data-table"),
]
for fname, sel in css_scope_checks:
    css = read(CSS / fname)
    check(sel in css, f"{fname}: has {sel}", f"{fname}: missing scoped selector {sel}", "medium")

print()
print("=" * 70)
print("check 6b: stage 7 navigation/login markers")
print("=" * 70)
navjs = read(NAV_JS)
appcss = read(STATIC / "styles" / "app.css")
sidebarcss = read(STATIC / "styles" / "components" / "sidebar.css")
headercss = read(STATIC / "styles" / "components" / "header.css")
stage7_checks = [
    (idx, "group.iconKey || group.id", "index.html group css icon key"),
    (idx, "item.iconKey || item.id", "index.html item css icon key"),
    (navjs, "MENU_ICON_KEYS", "navigation.js menu icon keys"),
    (navjs, "GROUP_ICON_KEYS", "navigation.js group icon keys"),
    (sidebarcss, ".menu-icon::before", "sidebar.css css icon drawing"),
    (sidebarcss, ".mobile-drawer-menu .menu-icon", "sidebar.css mobile drawer icon"),
    (headercss, ".header-title::before", "header.css module marker"),
    (appcss, "Stage 7: login and product shell polish", "app.css login polish"),
    (appjs, "utils/formatters.js?v=20260708-stage7-v1", "app.js formatter cache key"),
]
for haystack, needle, label in stage7_checks:
    check(needle in haystack, label, f"missing stage 7 marker: {needle}", "medium")

print()
print("=" * 70)
print("check 7: rough section tag balance")
print("=" * 70)
for fname in ["dashboard.html", "patient_qc.html", "config.html", "audit_types.html",
              "scheduler.html", "push_progress.html", "relay.html", "access.html"]:
    html = read(TPL / fname)
    open_sec = html.count("<section")
    close_sec = html.count("</section>")
    check(open_sec == close_sec, f"{fname}: section {open_sec}/{close_sec} balanced",
          f"{fname}: unbalanced section open={open_sec} close={close_sec}", "high")

print()
print("=" * 70)
print("check 8: suspicious unrendered Vue expressions")
print("=" * 70)
for path in TPL.glob("*.html"):
    html = read(path)
    suspicious = re.findall(r"\{\{[^a-zA-Z\s!<>=/].*?\}\}", html)
    real = [s for s in suspicious if not re.match(r"\{\{[\s]", s)]
    check(not real, f"{path.name}: no suspicious Vue expressions",
          f"{path.name}: suspicious expressions {real[:3]}", "medium")

print()
print("=" * 70)
print("summary")
print("=" * 70)
high = [p for p in problems if p[0] == "high"]
medium = [p for p in problems if p[0] == "medium"]
print(f"high severity: {len(high)}")
print(f"medium severity: {len(medium)}")
if problems:
    print("\nproblems:")
    for sev, msg in problems:
        print(f"  [{sev}] {msg}")
    raise SystemExit(1)

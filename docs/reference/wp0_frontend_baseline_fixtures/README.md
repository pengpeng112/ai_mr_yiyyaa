# WP0 前端基线夹具（脱敏）

生成日期：2026-08-09  
用途：017 前端迁移对照；不含患者姓名、病历正文、密钥明文。

## 页面入口（17）

| menu_id | legacy 入口 | 新路由（Hash） | 风险 |
| --- | --- | --- | --- |
| dashboard | activeMenu=dashboard | #/workbench | readonly |
| patient-qc | patient-qc | #/quality/patients | readonly |
| audit | audit | #/quality/records | business-write |
| relay-alert-logs | relay-alert-logs | #/closure/alerts | business-write |
| feedback | feedback | #/closure/feedback | business-write |
| push | push | #/tasks/push | system-write |
| push-progress | push-progress | #/tasks/progress | readonly |
| scheduler | scheduler | #/tasks/scheduler | system-write |
| audit-types | audit-types | #/governance/audit-types | system-write |
| config | config | #/governance/config | system-write |
| relay | relay | #/governance/relay | system-write |
| config-runtime | config + tab runtime-summary | #/system/runtime | readonly |
| health | health | #/system/health | readonly |
| access | access | #/system/access | system-write |
| debug | debug (dev_only) | #/system/debug | system-write |
| oracle-status | placeholder | 隐藏 | — |
| system-logs | placeholder | 隐藏 | — |

## 角色菜单矩阵（默认 RoleMenu 未分配时）

| 角色 | menu_ids |
| --- | --- |
| admin | 全部 17（导航过滤 hidden + 生产过滤 dev_only） |
| dept_manager | dashboard, patient-qc, audit, feedback, scheduler, health |
| auditor | dashboard, patient-qc, audit, feedback, health |
| clinician | dashboard, audit, feedback |

## Vendor 体积基线（legacy static/vendor）

- 合计约 2.70 MB（未 gzip）
- element-plus.full.min.js ~1.0 MB
- echarts.min.js ~1.1 MB
- vue.global.prod.js ~160 KB
- element-plus.css ~353 KB
- 启动时并行加载 17 个模板（任一失败阻断挂载）

## 浏览器基线视口

- 1366×768（桌面）
- 768×1024（平板）
- 390×844（手机）

> 真实截图与 Console/Network 录制需人工浏览器会话；本轮自动化以 Playwright mock API 覆盖交互，不宣称生产视觉验收已通过。

## Node 决策

- Node >=20 <26，npm >=10
- 锁文件：`frontend/package-lock.json`
- 生产构建目标：`npm ci --offline` + Docker multi-stage
- 禁止构建时访问生产 OpenAPI

## 脱敏 API fixture

见同目录 `*.json`。

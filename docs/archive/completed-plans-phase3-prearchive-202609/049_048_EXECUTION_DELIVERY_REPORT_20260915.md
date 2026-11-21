# 049 — 048 系统可靠性与工作台完善一次性执行交付报告

> 版本：v1.0（执行交付）；执行日期：2026-09-15；执行者：ZCode/GLM-5.3。
> 作业书：`docs/ACTIVE/048_SYSTEM_HARDENING_ONESHOT_PLAN_20260915.md` v1.0（八包 T0–T7）。
> 执行请求：`开发起步包/PROMPT-20260915_系统可靠性与工作台完善一次性执行.md`。
> 基线：HEAD=`58ea350`，工作区 126 项已登记未提交改动全部保留（043–047+09-12+048 计划，T0 证据=§2）。
> 边界：零生产、零真实患者、零真实模型/Relay/JHEMR 外呼、未 commit/tag/push/PR。

## 1. 执行摘要

T0–T7 八个必做包全部完成，本地交付完成（未提交）。核心成果：

- **T2**：核查列表 `GET /api/admin/checks` 从「limit 截断 + total=本页数 + 全表加载 IssueRow」重构为**真实分页**（page/page_size，旧 limit 兼容、同传 page_size 优先、非法参数 422 不 500）、**真实 total**（全部筛选后计数）、**稳定排序**（created_at+id 同秒不重不漏）、**有界聚合**（只查本页 (patient,visit) 元组 IN + GROUP BY；SQL 事件证明空页零 issue 查询）；详情/缺陷详情/人工动作新增 `enforce_dept_code` 科室范围强制（BFF 注入、预检侧同事务校验，越科室 403）。
- **T3**：两套前端工作台（UI Next `WorkbenchPage.vue` + legacy `prearchive_rule_center.js`/`audit_types.html`）重构为可连续使用页面：工具栏移出错误分支（F1，失败可重试恢复）、列表/详情/trial 列表/trial 观察独立 loading/error、晚到请求序号守卫、分页接入（筛选变化回第一页）、权限驱动按钮（复用 `/users/me` permissions，后端 403 最终门）、五态/人工状态/reason_code 中文（未知枚举回退原码）、409 刷新版本/403 无权/502/503 可重试分类提示、防重复提交、390px 移动宽度验证。
- **T4**：匹配任务事务健壮性——候选持久化+游标推进合并单事务（同 (task_id,fid) 先替换后插入，崩溃重跑不重复）；run 启动条件 UPDATE（并发重复 run 只有一个执行器）；终态条件 UPDATE（取消竞争不被 completed 覆盖）；执行中任务被删除返回明确 ValueError（原 `refresh(None)` 必崩）。6 项故障注入测试全绿。
- **T5**：四项真后端专项全部通过——JHEMR L1 复跑（自足双栈 18601/18602+mock_client+3 负向）、legacy 工作台双轮（正向非空链路+降级）、UI Next 非空工作台真后端链路（desktop+mobile-390）、幂等造数脚本。
- **新发现并修复**：BFF `issue_action` 双保险硬编码 `prearchive_issue_feedback` 导致 review-only 角色（auditor）经 BFF 必 403（与端点 any-of 依赖和预检侧契约矛盾）——改为 any-of（§4 D-B1）。
- **新发现未修（范围外）**：JHEMR GET 在 run 终态后存在毫秒级 issues 未齐瞬态窗口（finish_run 先于 materialize_for_run；`trigger.py`/`integration_api.py` 不在 048 §2.2 白名单，记 §4 D-J1 与 §10 待授权清单）。

## 2. T0–T7 逐包状态

| 包 | 状态 | 关键证据 |
| --- | --- | --- |
| T0 现场冻结与基线 | ✅ 完成 | `review/system-hardening-20260915/{baseline.txt,before/,before-sha256.txt,t0-quick-gates.log}`；quick 4/4 PASS（gate-runs/20260915-212023）；18080-82/18600/18601-02/4173 全空闲；既有 126 项未提交改动全部保留 |
| T1 功能/架构/历史交付矩阵 | ✅ 完成 | §3 矩阵（16 域逐行可追溯）；锚三类数字区分（机器锚 main=1295 / 20260907 实跑 1327 / 20260911 实跑 1376，047 §10「锚1327」系实跑数误标——已按 048 T7.3 在 047 追加更正节） |
| T2 分页/total/有界聚合 | ✅ 完成 | 新测试 8（`test_pa_checks_pagination.py`）+BFF 3（`test_prearchive_admin_bff.py`）；perf：100/1000/10000 行 0.008/0.010/0.031s（`t2-perf.txt`）；Oracle 方言编译检查通过（非真实库执行） |
| T3 双前端可恢复操作 | ✅ 完成 | typecheck 干净、unit 62 全绿；动态验收=T5 双轮 E2E（legacy 2 passed+降级 1 passed；UI Next 2 passed 含 mobile-390） |
| T4 匹配故障恢复与事务 | ✅ 完成 | `test_pa_match_recovery.py` 6 用例（事务中断/取消竞争/重复执行/任务消失/幂等重跑/单事务回滚）；既有 13 匹配测试不回归 |
| T5 真后端专项 | ✅ 完成 | `t5-commands.md`+`jhemr-l1.log`；JHEMR L1 ALL PASS；legacy 双轮+UI Next 真后端链路全过 |
| T6 全量门禁 | ✅ 完成 | §6 门禁表（`review/gate-runs/<ts>/summary.md`；锚比较=全部不低于锚；legacy 双轮=rule-center+workbench 双 spec 实跑无 SKIPPED） |
| T7 交付/回退/登记 | ✅ 完成 | 本 049 + 047 追加更正节 + 023 §0.6 行 + INDEX/README/01 登记；回退=以 T0 before 副本+本次 diff 为单位（§9）；进程收尾见 §8 |

## 3. T1 全系统功能/架构与历史交付追踪矩阵

口径：每行=入口/关键实现/测试定位/最近可核实证据/本地与外部状态/缺口/本次包号。「本地完成」=代码+自动化测试在隔离环境可复跑；「外部」=需要本批次之外的输入或授权。历史任务（045/046）已按 047 声明抽查核销，未重做。

| 域 | 入口/关键实现 | 现有测试 | 最近可核实证据 | 本地状态 / 外部状态 | 缺口 | 包 |
| --- | --- | --- | --- | --- | --- | --- |
| 认证/RBAC | `app/auth.py`（JWT+HttpOnly Cookie 双轨，023 P1-03）；`app/permissions.py`；BFF 权限双保险 `app/routers/prearchive_admin.py` | `tests/test_auth_security.py`、`tests/test_prearchive_rbac_matrix.py`、`tests/test_prearchive_admin_bff.py` | T5 legacy E2E 真实四角色链路（cookie 通道+CSRF） | 本地完成 / 外部=生产角色实配核对 | BFF issue 动作 any-of 修复前 auditor 必 403（本批已修，§4 D-B1） | T2/T5 |
| 六类 AI 质控与 payload | `app/services/payload_composer.py`（4 builder 注册）、`audit_result_mapper` | `tests/test_dify_pusher.py`、`tests/test_push_executor.py` | 09-11 全量门禁 main 1376 | 本地完成 / 外部=生产 Dify 工作流版本核对 | — | T1 |
| serial/bulk/retry 推送 | `app/services/push_executor.py`（serial）/`bulk_push_executor.py`（并行+熔断） | `tests/test_push_executor.py`、`tests/test_bulk_push_executor.py` | 同上；synthetic-demo-real.spec 真实 fixture 推送 2/2 | 本地完成 / 外部=真实 Dify 目标（未授权） | — | T1 |
| 双调度（daily/discharge） | `app/services/scheduler.py` 双 job 独立 DB 锁（lock_name=job_id）；`scheduler_run_modes.py` | `tests/test_scheduler_dual_send_policy.py`、`tests/test_scheduler_lock_history.py` | 同上 | 本地完成 / 外部=生产调度观察 | — | T1 |
| 日志/导出 | `app/routers/logs.py`（NULL 容忍+Python 侧科室去空）、导出审计 `record_export_audit()` | `tests/test_logs_regression.py`、`tests/test_patient_visit_export_*.py` | 同上 | 本地完成 | — | T1 |
| 反馈/Relay/H5 | `relay_alert_service.py`（HMAC+科室过滤）、`QCFeedback`/`suppress_ai_push` | `tests/test_relay_alert_service.py`、`tests/test_qc_feedback_api.py`、`tests/test_mobile_qc_*.py` | synthetic-demo-real.spec（mock receiver:18082+H5 反馈闭环） | 本地完成 / 外部=真实企业微信中继（未授权） | — | T1/T5 |
| 规则编辑/发布/刷新 | 预检 `rule_service.py`/`rule_repository.py`（发布单事务+TTL 引擎刷新+compare 全量）；sidecar 隔离 | `prearchive_service/tests/test_pa_rule_center_lifecycle.py`、`test_pa_publish_atomic.py` | 047 §1；legacy rule-center.spec 双轮（T6 门禁实跑） | 本地完成 / 外部=临床规则变更授权（未给） | — | T1/T6 |
| 工作台/Issue | `closed_loop_api.py` checks/issues 五态+人工状态分离（`issue_service.py` 状态机+乐观锁） | `test_pa_workbench.py`、**本批** `test_pa_checks_pagination.py` | 本批 T2/T3/T5 全链证据 | 本地完成 / 外部=真实就诊流量验证 | **D-J1**（§4）；分页前后端已闭环 | T2/T3/T5 |
| 匹配/trial | `match_service.py`（精确命中/校验器/断点恢复）；`trial_service.py`（隔离执行） | `test_pa_match_service.py`、**本批** `test_pa_match_recovery.py`、`test_pa_trial_run.py` | 本批 T4 故障注入 6 用例 | 本地完成 / 外部=真实 AI 通道+临床抽检（§10） | — | T4 |
| Outbox | `outbox.py`+`delivery_wiring.py`（bounded reconcile 补偿+治理过滤） | `test_pa_delivery_outbox.py`、`test_pa_delivery_wiring.py` | 047 §1 | 本地完成 / 外部=真实投递目标凭据 | — | T1 |
| JHEMR 五接口 | 预检 `integration_api.py`；主服务 `jhemr_integration.py`（HMAC 四件套+nonce 重放+±300s） | `test_pa_jhemr_check.py`、`tests/test_jhemr_integration.py`、`test_pa_integration_package.py` | **本批 T5 L1 复跑 ALL PASS**（`jhemr-l1.log`） | L1 本地完成 / L2/L3 外部（§10） | **D-J1** 瞬态窗口；终态↔物化顺序 | T5 |
| SQLite/Oracle 迁移 | 预检三套 DDL `prearchive_service/sql/*.sql`（启动零自动 DDL）；`migrate_qc_permissions_20260910.py`（默认 dry-run） | `test_pa_state_and_oracle.py`（DSN/驱动/方言级）、`tests/test_qc_permission_migration_20260910.py` | 047 §5；本批 T2 Oracle 方言编译检查 | 本地=方言/驱动可用性 / 外部=**真实 Oracle 执行未做**（需 DBA，§10） | 真库执行+压测 | T1/T2 |
| legacy 前端 | `static/`（audit_types 页+规则中心 tab） | `frontend/tests/e2e-legacy/*.spec.ts` | T5/T6 legacy 双轮实跑 | 本地完成 | — | T3/T5 |
| UI Next 前端 | `frontend/src`（Vue3+Element Plus；governance/workbench） | `frontend/tests/e2e/*.spec.ts`、unit 62 | T5 workbench-real 2 passed | 本地完成 / 外部=真实角色 canary（§10） | — | T3/T5 |
| 覆盖账本/规则资产 | `coverage.py`+`rules/paperless_coverage_v1.json`（123 条款行）；两轨规则文件 | `test_pa_coverage_ledger.py`、`test_pa_rules*.py` | 047 §1；legacy E2E 幂等导入（skipped=92/upserted=123） | 本地完成 / 外部=质控科目录正式快照源 | 检验/首页族 fid 待数据源 | T1/T5 |
| 门禁/效率基建 | `scripts/run_gates_20260906.py`（唯一入口）+gate_anchors.json+3 Skill | `tests/test_gate_scripts_20260906.py`（24） | 本批 T6 全量+锚比较；门禁脚本扩双 spec 后 24 单测全过 | 本地完成 | — | T5/T6 |

skip 分类（T6 全量）：e2e 的 17+6 skipped=设备分工/环境门（SYNTHETIC_DEMO_E2E/WORKBENCH_E2E/LEGACY_E2E 未注入时自动跳过，属可重复编排的正常运行门，非缺失覆盖）；prearchive 1 skip=cx_Oracle 缺失的驱动集成冒烟（设备分工）；Oracle 现场测试=外部依赖未授权，明确不属于本地验收覆盖。

## 4. 逐缺陷证据（048 §0.2 + 本批新发现）

| ID | 结论 | 证据与处置 |
| --- | --- | --- |
| F1 工具栏在错误分支内 | **已修** | UI Next 工具栏移出 `v-if="!loadError"`；错误 alert 内置重试按钮；legacy 工作台同步。动态验证=workbench 双轮+UI Next 真后端链路 |
| F2 角色名近似权限+原码展示 | **已修** | 权限=复用 `/users/me` `permissions`（`types.ts` 补字段；缺失时角色名回退+后端 403 兜底）；五态/人工状态/reason_code 中文映射（词表=engine 全枚举，未知回退原码+技术码 tooltip） |
| F3 limit 截断+假 total+无分页 | **已修** | T2 全套（§1）；UI Next+legacy 均接入分页 |
| A1 全量加载 IssueRow | **已修** | `browse_check_runs` 元组 IN+GROUP BY；SQL 事件断言（`test_issue_aggregation_is_bounded_by_sql`）；空页零 issue 查询；计数语义=就诊当前缺陷状态（已用测试固化文档化） |
| A2 匹配事务分叉 | **已证实并修复** | 旧代码 `_persist_candidates`/`_advance_progress` 两事务+`refresh(None)` 崩溃路径均以故障注入复现；修复见 T4（§1）；证据=`test_pa_match_recovery.py` 6 用例 |
| Q1 工作台专项未进门禁 | **已修** | `run_legacy_rule_center_e2e` spec 清单扩为 rule-center+workbench 双 spec（正向+降级双轮）；门禁单测 24 全过；T6 全量实跑双轮 PASS |
| Q2 spec 空表+整体豁免 | **已修** | 重写 workbench.spec：非空合成就诊链路（列表→详情→已查看→整改→复检通过；人工状态与引擎结论分别断言）；失败断言改显式允许清单（users/me、刻意 409/403、降级轮 prearchive-admin 仅 502/503）；零 pageerror 断言 |
| Q3 锚数字三类混用 | **已澄清** | 机器锚（gate_anchors.json，main=1295，2026-09-07 定格）≠ 20260907 实跑 1327 ≠ 20260911 实跑 1376；047 §10「锚1327」为实跑数误标——已在 047 追加更正节；锚文件本批未动，T6 比锚=全部不低于 |
| D1 047 危险回退建议 | **已更正** | 047 追加更正节：「丢弃整个工作区」回退建议失效；新回退=本报告 §9（before 副本+diff 单位） |
| **D-B1**（本批新发现，已修） | BFF issue 动作双保险硬编码 feedback → review-only（auditor）经 BFF 必 403 | 动态复现（standalone 脚本 clinician 200/auditor 403）；修复=`_proxy` 支持 any-of 权限组；测试 3 项新增（`test_issue_action_bff_injects_enforce_dept_for_clinician` 等） |
| **D-J1**（本批新发现，未修） | JHEMR GET 终态瞬态窗口：`trigger.py::process` 先 `finish_run`（置 completed）后 `materialize_for_run`（写 issues）——轮询方在 completed 后毫秒级内可能读到 issues 空/不齐（L1 实测 first observed=0，稳定态=4 条去重 rule+event） | `trigger.py`/`integration_api.py` 不在 048 §2.2 白名单，按升级出口记 §10 待授权；L1 脚本如实记录首次观测值+有界重试验证稳定态契约（非掩盖） |

## 5. 修改清单（本批新增/修改；before 副本=`review/system-hardening-20260915/before/`）

**预检服务**（分页/聚合/科室强制/匹配事务）：
- `prearchive_service/prearchive/closed_loop_api.py`（list_checks 重写+enforce_dept_code 三端点）
- `prearchive_service/prearchive/issue_service.py`（新增 `browse_check_runs` 服务层查询）
- `prearchive_service/prearchive/match_service.py`（T4 事务修复：`_commit_fid_progress`/条件启动/条件终态/消失任务明确报错）
- `prearchive_service/tests/test_pa_checks_pagination.py`（新）、`test_pa_match_recovery.py`（新）

**主服务 BFF**：
- `app/routers/prearchive_admin.py`（checks 分页透传+详情/动作 enforce_dept_code 注入+`_proxy` any-of）
- `tests/test_prearchive_admin_bff.py`（+3 用例）

**前端**：
- `frontend/src/features/governance/WorkbenchPage.vue`（重构）
- `frontend/src/api/endpoints/prearchiveAdmin.ts`（wbChecksApi 分页参数）、`frontend/src/api/types.ts`（UserInfo.permissions）
- `static/scripts/modules/prearchive_rule_center.js`（workbenchMethods 重写）、`static/scripts/app.js`（wb 状态字段）、`static/templates/pages/audit_types.html`（工作台 tab+详情抽屉模板）
- `frontend/tests/e2e-legacy/workbench.spec.ts`（重写）、`frontend/tests/e2e/workbench-real.spec.ts`（新）
- `static/ui-next/`（build 同步产物，非手工编辑）

**脚本/门禁**：
- `scripts/run_gates_20260906.py`（legacy e2e 双 spec）
- `scripts/seed_workbench_demo_20260915.py`（新，造数）、`scripts/run_jhemr_l1_20260915.py`（新，L1 编排）

**文档**：本 049、047 追加更正节、023 §0.6 行、`docs/INDEX.md`、起步包 README/01、048 状态行。

## 6. 测试命令与结果

### 6.1 全量门禁（正式入口）

```
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```

<!-- 门禁产物：review/gate-runs/20260915-223559/（summary.md/result.json/逐门禁 log） -->

| 门禁 | 结果 | 计数 | 耗时(s) | 备注 |
| --- | --- | --- | --- | --- |
| compileall | PASS | - | 7 | app/tests/scripts/prearchive_service |
| naming | PASS | - | 4 | |
| isolation | PASS | - | 1 | 96 文件零 `import app.*` |
| sidecar_check | PASS | - | 6 | |
| main_pytest | PASS | passed=1379 | 95 | 锚 1295；较 09-11 基线 1376 净增 3（BFF 新用例） |
| prearchive_pytest | PASS | passed=452 skipped=1 | 55 | 锚 283；438 基线+8 分页+6 匹配恢复；1 skip=cx_Oracle 驱动冒烟（延续） |
| typecheck | PASS | - | 19 | |
| frontend_unit | PASS | passed=62 | 50 | |
| build | PASS | - | 34 | 含 static/ui-next 同步 |
| frontend_e2e | PASS | passed=52 skipped=23 | 68 | 锚 52；skipped 17→23（+6=workbench-real 无环境门时 2 测试×3 视口，运行门非缺失覆盖；专项实跑见 §6.2） |
| legacy_rule_center_e2e | PASS | - | 42 | 正向:PASS(3=rule-center 1+workbench 2)；降级:PASS(2=rule-center 1+workbench 1)；双 spec 双轮实跑无 SKIPPED |

**整体：PASS；锚比较：全部不低于锚；exit 0**

### 6.2 专项（full 之外，各自独立命令；均真实隔离栈）

| 专项 | 命令 | 结果 |
| --- | --- | --- |
| JHEMR L1（双栈+3 负向） | `python scripts/run_jhemr_l1_20260915.py` | ALL PASS（`jhemr-l1.log`） |
| UI Next 非空工作台 | `WORKBENCH_E2E=true PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/ PLAYWRIGHT_SKIP_WEBSERVER=1 npx playwright test tests/e2e/workbench-real.spec.ts`（frontend/ 下） | 2 passed（desktop+mobile-390） |
| legacy 工作台独立双轮 | 见 `t5-commands.md` | 正向 2 passed；降级 1 passed+1 skip |
| 造数幂等 | `python scripts/seed_workbench_demo_20260915.py --status` | 2 run+2 open issue，重复执行复位 |

### 6.3 用例集合对比（T0 vs 最终）

- 主 pytest：09-11 基线 1376 → **1379**（+3=BFF 分页透传/详情科室注入/动作 any-of 用例；无删除断言、无既有用例改动）。
- prearchive pytest：438+1skip → **452+1skip**（+8=`test_pa_checks_pagination.py`；+6=`test_pa_match_recovery.py`；唯一 1 skip=cx_Oracle 驱动冒烟延续）。
- frontend unit：62 → 62（无变化）。
- frontend e2e：52 passed 不变；skipped 17→23（+6=workbench-real 环境门跳过，§6.2 已实跑通过）。
- 门禁脚本单测：19 → **24 全过**（045 承接 19+本批双 spec 扩展兼容验证，无断言削弱）。

## 7. 用户怎么点开（验收路径）

| 项 | 路径 |
| --- | --- |
| UI Next 核查工作台 | `http://127.0.0.1:18080/ui-next/#/governance/workbench`（demo 栈：`demo_env.py serve`+sidecar；分页/中文状态/权限按钮/重试） |
| legacy 核查工作台 | `http://127.0.0.1:18080/index.html` → 规则与配置 → 质控类型 → 归档前规则中心卡片 →「核查工作台」tab |
| 详情/人工动作 | 列表「详情」→ 抽屉内 已查看/提交整改（feedback 权限）· 复检通过/误报（review 权限，原因必填） |
| 试运行观察 | 同卡片「试运行观察」tab（trial 仅隔离执行） |
| 匹配/账本 | 同卡片其余 tab（覆盖账本/AI 匹配/Outbox） |

## 8. 进程与端口收尾

T5/T6 启动的进程与本批端口状态：demo 主服务（18080-18082，run-id=sh048）、sidecar（18600，T6 门禁自管自回收）、L1 双栈（18601/18602，脚本 finally 已停并核验释放）、4173/4174 未占用。交付前执行 `demo_env.py stop` 与端口核验（见 §9 回退命令；`clean_demo_ports_20260906.py` dry-run 零残留为准）。未杀任何未知 PID。

## 9. 回退步骤（以本批 diff 为单位，保留其他会话改动）

1. 本批全部改动均在 `review/system-hardening-20260915/before/` 有修改前副本+`before-sha256.txt`；
2. 回退=逐文件用 before 副本覆盖（或按 §5 清单 `git diff` 该文件后手工还原），**禁止 `git reset/clean/stash` 整工作区**（047 原建议已更正）；
3. 新增文件（测试/脚本/049）删除即回退；`static/ui-next/` 重跑 `npm run build`（旧 dist 同步产物）；
4. 回退后跑 `python scripts/run_gates_20260906.py --quick` 验证现场一致。

## 10. 外部未完成清单（下一批次候选，按 048 §4 排序）

| 事项 | 具体工作 | 负责方 | 必需输入 | 批准要求 | 成功证据 |
| --- | --- | --- | --- | --- | --- |
| JHEMR L2 联调验收 | 外部开发方按联调包接入真实 JHEMR 测试环境后联调 | JHEMR 开发方+本仓执行 AI | `prearchive_service/integration/jhemr/`（已交付）+对方 client_id/secret 与测试环境地址 | 生产/测试环境写入另批授权 | L2 联调记录+签名对拍通过 |
| JHEMR L3 现场验收 | 真实科室医生在真实系统内完成查看-反馈-复检闭环 | 医院信息科+质控科 | L2 通过+培训 | 临床流程变更授权 | 现场验收单 |
| **D-J1 瞬态修复（需白名单扩展）** | `trigger.py` 将 materialize 移入 finish_run 前（或 integration GET 稳定读）+回归测试 | 本仓执行 AI（待授权 trigger.py/integration_api.py 修改） | 本报告 §4 D-J1 | 文件白名单扩展批准 | 竞态注入测试：completed 即 issues 齐 |
| 真实 AI 匹配通道 | 院内 OpenAI 兼容通道配置+92 项真实匹配+候选人工审阅 | 质控科+信息科 | 通道 base_url/api_key+预算 | 真实模型调用授权（本批未授权） | 匹配任务 completed+候选审阅记录 |
| 真实回测 | 人工扣分样本回测（backtest v2 已就绪） | 质控科 | 脱敏历史扣分样本+临床核验口径 | 患者数据使用授权 | 回测报告（FP 原因聚合） |
| W10 系统推送清单 | `system_push_rules.json` 待签清单确认 | 质控科 | W10 清单文档 | 签字口径 | 已签规则文件入库 |
| 生产 DBA 迁移 | `sql/create_prearchive_closed_loop_oracle_20260910.sql` 真库执行+备份回滚点 | DBA+运维 | DDL 文件+应用库账号 | 生产写入授权（另批） | 迁移记录+ORM 奇偶核对 |
| UI Next 真实角色 canary | 生产/试点角色小流量使用 UI Next 工作台 | 运营+信息科 | 生产发布 | 生产变更授权 | canary 观察报告 |

## 11. 偏差说明

1. **JHEMR L1 issues 稳定态重试**：L1 脚本对 GET issues 采用有界重试至稳定——原因=D-J1 瞬态窗口（范围外），已如实记录首次观测值，非掩盖；修复列 §10。
2. **legacy spec 三处环境事实修正**：`__dirname`（ESM）→`import.meta.url`；localStorage token→HttpOnly Cookie+CSRF 头（023 P1-03 迁移后旧 spec 早已失配，因从未进门禁未被发现——Q1 的直接印证）；Element 默认英文 locale 的 OK 按钮/分页文案按实际渲染断言。
3. **UI Next 造数走 DB 直写**（seed 脚本，EvalRunStore+IssueService 真实代码路径）：预检服务无正式 run 的 HTTP 创建端点（trigger 由 poller 驱动，sidecar 无 poller）——属既有架构事实，未新增端点。
4. **049 §6.1 门禁表**以后台完成结果为准填入；如门禁失败，按 048 T6.4 定位修复后复跑，不以部分绿冒充。

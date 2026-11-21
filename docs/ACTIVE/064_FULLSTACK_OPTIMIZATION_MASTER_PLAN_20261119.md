# 064 · Med-Audit 全栈性能根治、业务重构与 UI/UX 全面升级总计划（WP-01 ~ WP-10）

> **建立日期**：2026-11-19（v1.1 同日 19:40 修订，见 §7）  
> **状态**：**WP-01~WP-09 本地交付完成（2026-11-21，全仓 --full 门禁全绿、锚比较全部不低于锚，详见各 review/064-wpNN/DELIVERY.md 与 01_统一修改记录.md）；待 WP-10 生产发布分步审批。**方案 v1.1 定稿（已纳入用户 2026-11-19 对 6 项核心口径的正式裁定与逐项勘误）。  
> **编制依据**：2026-11-19 对生产环境 `10.10.8.84`（`med-audit` / `med-prearchive`）、业务与应用 Oracle `10.10.8.216`（`JHEMR.MED_*` / `V_QYBR`）、Vastbase `10.10.8.177` 的只读实测证据，全栈代码审查，《全息视图对接文档2.0-血透.docx》，以及无纸化 CDMS（`10.10.10.93`）活库字典。  
> **执行定位**：面向多 AI 分段接力（含对前端较弱的执行 AI），拆分为 **9 个本地开发包 `WP-01` ~ `WP-09` + 1 个分步审批的生产发布包 `WP-10`**（每包预计 **2.5～3.5 小时**），每包均有独立防呆提示词，另有所有包共用的 `PROMPT-00` 事实基线（见 `开发起步包/prompts-064/`）。  
> **安全与授权边界**：本文档仅授权**本地仓库代码/文档/测试开发与验证**，**不构成对任何生产服务器（`10.10.8.84`）、生产数据库（`10.10.8.177` / `10.10.8.216` / `10.10.10.93`）的写入授权，也不构成 Git 提交/推送授权**。生产 DDL/配置/部署均在 WP-10 中按单步审批执行。

---

## §1 用户 2026-11-19 正式拍板的 6 项核心业务与架构口径

以下 6 项已由用户明确裁定，所有工作包必须严格遵照执行，不得擅自偏离：

| 序号 | 决策主题 | 正式拍板口径 | 落位工作包 |
| :---: | :--- | :--- | :---: |
| **D1** | **360 全息视图参数** | 全部做成后台可配置项；默认 `base_url=http://10.10.8.231:8281/holography-platform/consultationView`、`sys_code="S28"`；`userCode` 由后端按当前登录人计算：全院同步员工 `username` 即 HIS 工号（`User` 表无 `emp_no` 字段），符合工号格式（默认 `^[0-9]{4,10}$`）且不在非员工账号列表中时直接使用；**`admin` 等非员工工号账号兜底传 `wfy`**（配置项 `fallback_user_code="wfy"`）；仅院内 PC 端展示，移动端/企微 H5 默认隐藏（`enable_on_mobile=false`，可配置） | WP-02 / WP-03~08 |
| **D2** | **内涵质控重复菜单合并** | 侧栏合并为唯一入口 **「内涵质控工作台」**（保留 `patient-qc` 菜单 ID）；页内顶部提供清晰双视角切换：**「按患者汇总（默认）」** vs **「按核查流水（排障/复核/重推/批量删除）」**；隐藏重复旧菜单 `audit`，保留其路由 `/quality/records` 自动重定向到 `/quality/patients?view=records` 并透传查询参数 | WP-02 / WP-05 |
| **D3** | **归档前核查影子模式与无纸化推送** | 两步走：① 先接已通的 `177 JHEMR + 216 HIS/SM` 按 `anchor_mode="discharge"` 开启纯观察影子模式（`push.enabled=false`）；② 待无纸化 `10.10.10.93 CDMS` 只读账号到位后跑 `T_MARK_DETAIL`/`T_MSS_REWORK` 金标准回测并可切 `paperless_rpa`。后期推送无纸化**以 HTTP/WebService 接口为主，同时架构上双路支持「受控中间表写入」适配层** | WP-07 |
| **D4** | **AI 高危问题推送 JHEMR 提交提醒路线** | **双路兼容，主推路线 B**（嘉和客户端提交病历前调用本系统 HTTP 接口拉取未闭环高危提醒，配合后续客户端对接），同时兼容路线 A（`177 FILEVERIFY` 受控写入）。WP-06 落稳每条规则的 `jhemr_reminder_policy` 配置与标准化拉取接口 `GET /api/integrations/jhemr/ai-reminders` | WP-06 |
| **D5** | **全院菜单 + 科室数据双层 RBAC** | 终结 `timeliness_access_json` 与 `RoleDepartment` 两套割裂逻辑，建立全系统唯一的 **「菜单可见性 + 科室数据范围（`all` 全院 / `home` 仅本科室 / `selected` 指定多科室，用户个人覆盖角色）」**，统一覆盖 **质控总览、病历时效、AI 内涵质控、整改反馈、企微告警、归档前形式核查** 全部 6 大板块（解除企微告警硬编码 `admin` 限制） | WP-02 / WP-08 |
| **D6** | **Oracle 增量 DDL & 177 只读授权** | ① WP-01 产出纯增量、零破坏的 Oracle 索引与 `DISCHARGE_DEPT` 补列审批脚本（不代执行，由用户低峰期审阅执行）；② 177 Vastbase 为 `aizk_user` 补齐只读 `SELECT` 权限 SQL 由用户审阅执行，随后复核 `39+6` 日间模板解绑状态 | WP-01 / 见 §7 |

---

## §2 线上只读实测核心发现（全部工作包的事实基线）

### 2.1 数据库规模与慢查根因（`10.10.8.216` Oracle + `10.10.8.84` 实测）
- **`MED_PUSH_LOG`**：245,555 行（表 464 MB）+ **4 个 CLOB 共 7.45 GB**（`AI_RESULT` 3.09 GB、`REQUEST_JSON` 1.86 GB、`RESPONSE_JSON` 1.79 GB、`MR_TEXT` 714 MB）；`MED_AUDIT_DIMENSION_RESULT` 1,085,750 行（696 MB）；`MED_AUDIT_CONCLUSION` 154,056 行（88 MB）；`MED_TL_EVENT` 15,478 行；`MED_USERS` 2,383 人；`MED_DEPARTMENTS` 640 科。
- **质控总览慢根因（10～14 个请求分 3 批串行）**：
  - `/api/stats/severity` **841.2 ms**、`/api/stats/anomaly-top` **292.1 ms**（无当前结果复合索引全表扫 + `_stats_metadata()` 二次全表扫 `MIN/MAX(query_date)`）；
  - `/api/stats/today` 发 4 条 `COUNT(*)`（22 ms → 单 SQL `SUM(CASE)` 3.7 ms）；`/relay-alert/summary` 发 10 条 `COUNT(*)`（35.5 ms → 单 SQL 11.6 ms）；
  - `loadHighRiskEvents()` 串行在 Batch 1 之后最多发 4 次 `/api/logs`，每次载入 4 个大 CLOB 并解析 `request_json` 两次；
  - 3 次 `/timeliness/*?limit=1` 只为拿 `total`，却每次加载 640 科室 + `HIS.STAFF_DICT` + `V_QYBR`（改单 SQL `GROUP BY` 仅 5.7 ms + 1.7 ms）。
- **隐藏 P0 炸弹 — `timeliness_scan` 每 5 分钟耗时 105～116 秒**：
  - `app/timeliness/scanner.py`（890–919 行）对全部 **8,188 条既有事件**（含已完结的 `COMPLETED_ON_TIME=9,178` / `COMPLETED_LATE=1,945` 终态记录）无条件赋值 `event.last_scan_at = now` / `event.updated_at = now`，导致每 5 分钟向 Oracle 执行 8,200 次逐行 `UPDATE`！修复业务字段脏检查后可降至 **<10 秒**。
- **其他后端瓶颈**：
  - `patient_qc.py` 的 `discharge_dept_name` 筛选用 `dbms_lob.instr(request_json, ...)` 扫 1.86 GB CLOB；列表页加载 CLOB；
  - `/api/logs/dept-options` 与 `/filters/options` 无 TTL 缓存每次直连业务库 + 多次全表计数；
  - `daily_push` 72 min / `discharge_push` 82 min 串行慢，`2026-11-18` `progress_vs_nursing` 遇 `ORA-12609` 超时 59s 无单类型自动退避重试；
  - `timeliness.py` `_monthly_rows` 全表拉取 14,810 条到 Python 聚合（101 ms → SQL `GROUP BY` 17 ms）；`MED_TL_EVENT` 存在 106 条 `dept_code=None`（含 93 条超时）。
- **归档前形式核查（`med-prearchive`）0 行根因**：
  - 容器虽运行 8 周且 Oracle 18 张 `MED_PREARCHIVE_*` 表已就绪，但 `/app/config/prearchive.prod.json` 中 `anchor_mode="finished"`（177 上 100% NULL）且 13 个源全为 `enabled: false` + `<..._PLACEHOLDER>`，规则表也为空。
  - 无纸化 CDMS（`10.10.10.93` Schema `CDMS`）真实人工打回核心表：`T_MARK_MAIN/DETAIL/ITEM`（7.3 万评分/385 万明细/8,200+ 扣分备注）、`T_MSS_MAIN`、`T_MSS_REWORK`（14 列）、`T_MSS_CONTROLLOG`、`T_MSS_MRCONTROL`、`T_MSS_CONTROLDISCUSSFROM`、`T_MSS_BBS`、`RPA_PRINTRPT_AGGREGATED`。
- **Vastbase `177` 只读实证**：业务 Schema 共 6 个（`jhemr` 1,004 表、`jhnis` 370 表、`report` 34 表、`jhcdr` 13 表、`jhfile` 10 表、`public` 8 表）；模板主表为 `jhemr.jhmr_templet_index`（非 `mr_templet_index`）。

---

## §3 10 个分阶段工作包总览与提示词索引（v1.1：WP-01~09 本地开发，WP-10 生产发布）

> **执行顺序铁律**：每个包开工前必须先读 [PROMPT-00 通用事实基线与勘误](../../开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md)（已对照真实代码核验路由、端点、字段、测试位置）。`WP-01` → `WP-02` 先行；`WP-03` ~ `WP-09` 按序号串行；`WP-10` 为生产发布，**每个生产步骤单独审批**。**每次仅向执行 AI 投喂 1 个工作包提示词，验收通过后再发下一包。**

| 工作包 | 预计耗时 | 覆盖反馈项 | 核心交付内容 | 独立防呆提示词 |
| :---: | :---: | :---: | :--- | :--- |
| **PROMPT-00** | 阅读 15 min | 全部 | 代码事实基线（真实路由/端点/字段/测试命令）+ 通用铁律，冲突时以它和真实代码为准 | [PROMPT-00](../../开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md) |
| **WP-01** | ~3.0 h | 0、1、2(后端) | `scanner.py` 脏写修复（复用 `TERMINAL_STATUSES`，`overdue_minutes` 30 分钟阈值，阶段耗时日志）；`GET /api/stats/workbench-overview`（30s TTL、锁定口径=TLApproval、预检走 BFF 白名单 fail-open）；`logs`/`patient_qc` defer CLOB；`discharge_dept` 混合筛选（不丢历史行）+ 回填脚本；`ORA-12609` 重试；Oracle 索引审批脚本 | [PROMPT-WP01](../../开发起步包/prompts-064/PROMPT-WP01_后端性能根治与总览聚合.md) |
| **WP-02** | ~3.0 h | 3、10(后端) | 统一 `data_scope.py`（保持 `timeliness_access` 签名，企微 H5 不受影响）；`/api/users` 追加筛选（沿用 `page/limit/q`）、`batch-update`、`roles/{id}/access-bundle`、`departments/paged`（不改原列表接口）；告警日志/汇总按科室开放（retry 仍 admin）；`/api/config/holography` **后端计算 `user_code`**（username 即工号，`admin`→`wfy`）；新菜单与占位页 | [PROMPT-WP02](../../开发起步包/prompts-064/PROMPT-WP02_统一权限数据范围与360基础件.md) |
| **WP-03** | ~3.0 h | 1、2、4 | 总览单接口 + 四态势卡（真实路由跳转）+ 360；`stats_service.py` + `GET /api/timeliness/stats/analytics`（**科室/医生锁定排名 = TLApproval 次数**）；时效统计分析页 | [PROMPT-WP03](../../开发起步包/prompts-064/PROMPT-WP03_质控总览重构与时效统计专页.md) |
| **WP-04** | ~3.5 h | 3、5、6 | 台账补临床信息/倒计时/审批状态/360/医生筛选；审批页补审批人/原因/汇总卡/同步按钮/360；在现有 `stats/monthly`、`export/monthly` 上扩展**任意日期区间 + 分页 + `format=xlsx`**（默认 csv 兼容）；固定表头冻结左列；日间病历对账口径（可选） | [PROMPT-WP04](../../开发起步包/prompts-064/PROMPT-WP04_时效台账审批与月度考核全面升级.md) |
| **WP-05** | ~3.5 h | 3、6b、7 | `/quality/patients` 双视角「内涵质控工作台」+ `/quality/records` 重定向；复用型 `PatientQcDetailView.vue`（基于现有 `patient-detail` 接口）；反馈/告警页补 360 | [PROMPT-WP05](../../开发起步包/prompts-064/PROMPT-WP05_内涵质控一体化与患者详情重构.md) |
| **WP-06** | ~3.5 h | 9 | 规则中心三轨页；AI 规则 3 步抽屉 + `rawExtras` 往返；`jhemr_reminder_policy`；`GET /api/integrations/jhemr/ai-reminders`（**复用 `_verify_request` HMAC**，路线 B 主推兼容路线 A） | [PROMPT-WP06](../../开发起步包/prompts-064/PROMPT-WP06_质控规则中心三轨重构与JHEMR提醒预留.md) |
| **WP-07** | ~3.5 h | 8 | **复用** `RuleService.import_files` / `backtest_v2` / `outbox.DeliveryWorker`：CDMS 只读盘点与金标准回测脚本、规则导入 CLI、Outbox 内新增中间表投递、影子配置模板、123 Runbook；病案室核查台（复用 issues actions 反馈） | [PROMPT-WP07](../../开发起步包/prompts-064/PROMPT-WP07_归档前核查影子激活与病案室工作台.md) |
| **WP-08** | ~3.5 h | 10 | 用户与权限页（全院级筛选/分页/分批批量/角色一次保存/无平铺科室）；数据源与系统配置页分页签（含 360 配置与预览） | [PROMPT-WP08](../../开发起步包/prompts-064/PROMPT-WP08_全院RBAC用户权限与系统配置页重构.md) |
| **WP-09** | ~3.5 h | 10 + 收口 | 定时调度、手动补推、企微接收人配置三页重构（保留诊断信息、防双击守卫、局部保存）；全仓 `--full` 门禁 + 锚比对 | [PROMPT-WP09](../../开发起步包/prompts-064/PROMPT-WP09_调度补推企微配置重构与全仓门禁.md) |
| **WP-10** | ~2.5 h + 审批 | 发布 | 只读预检（MD5 防撕裂）→ 备份 → 发布 → 只读冒烟矩阵 → 低峰索引 DDL → 分批回填 → 预检影子启用 → 3 天观察报告；**每步单独批准** | [PROMPT-WP10](../../开发起步包/prompts-064/PROMPT-WP10_生产发布DDL与影子模式启用_分步审批.md) |

---

## §4 全工作包共用硬红线（违反任一条即打回）

1. **Oracle 兼容红线**：禁 `FETCH FIRST`；布尔比较只用 `== True`/`== False`（禁 `.is_(True)`）；SQL 层禁 `col != ""`（在 Python 侧过滤）；ORM 新增 CLOB/`Text` 列必须放模型末尾。
2. **`V_QYBR` / `V_CYBR` 视图红线**：所有查询必走 `app/services/oracle_patient_view_compat.py`；批量查询只用单列 `患者ID IN (...)` ≤50 分批；只取真实 40 列（**无 `"床号"`、无 `"在院科室名称"`**）。
3. **预检物理隔离红线**：`prearchive_service/` 下**零 `import app.*`**，主服务 `app/` 亦不反向 `import prearchive_service.*`；改动后必跑 `python prearchive_service/check_isolation.py`。
4. **Dify / 告警 / 审计 / D8 护栏**：Dify payload 键保持 `mr_text`；`POST /api/config/relay-alert` 保持 `exclude_unset=True` 局部合并与密文/地址保护；新增导出必调 `record_export_audit()`；D8 `CHIEF_FIRST_ROUND` 禁锁护栏不可绕过。
5. **前端设计系统铁律（强防“弱 AI 写乱界面”）**：
   - 统一复用 `tokens.css`（`--ma-*`）与 `PageHeader` / `SummaryStrip` / `FilterPanel` / `DataTableShell` / `DetailDrawer` / `RiskTag` / `StatusTag` / `HolographyButton`；
   - 禁止单行压缩 HTML；禁止仅用 `placeholder` 代替中文标签；禁止对用户裸露英文键名（`WARNING`/`OVERDUE`/`pool_min`/`NULL`）或未折叠 `JSON.stringify`；
   - 科室/医生/角色等长选项一律 `<el-select filterable clearable>`，**严禁平铺 >20 个 `<el-checkbox>`**；
   - 保持 `client.ts` `X-Requested-With: XMLHttpRequest` 及规则/配置抽屉 `rawExtras` 无损往返单测。
6. **协作与 Git 边界**：开工读 `git status --short` 并保留他人全部未提交改动；每包完成后在 `开发起步包/01_统一修改记录.md` 追加一行并更新 `02_协作任务板.md`；**未经用户当次明确指令严禁 `git commit/push/reset/clean` 或操作生产服务器/数据库**。

---

## §5 每包交付验收与总门禁规范

每完成一包，执行 AI 必须先自跑本包定向单测 + `npm run typecheck` + `compileall` + `run_gates --quick`，写 `review/064-wpNN/DELIVERY.md`，再向用户汇报修改清单与命令实测输出；由协调/审查 AI 做只读代码走查通过后进入下一包。`WP-09` 终态必须跑通全量门禁：
- `python -m compileall app tests scripts`
- `python scripts/check_naming_convention.py`
- `python prearchive_service/check_isolation.py`
- `python -m pytest -q` & `python -m pytest prearchive_service/tests -q`
- `cd frontend; npm run typecheck; npm run test:unit; npm run build`
- `python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json`
- `python scripts/check_documentation_20261002.py`

---

## §6 附录：Vastbase `10.10.8.177` 只读账号 `aizk_user` 补全只读权限审批 SQL（供用户审阅执行）

> **目的**：2026-11-19 只读探测确认 `10.10.8.177:5432/jhemr` 共有 6 个业务 Schema（`jhemr` 1,004 表、`jhnis` 370 表、`report` 34 表、`jhcdr` 13 表、`jhfile` 10 表、`public` 8 表），当前 `aizk_user` 对 `jhemr.jhmr_templet_index`、`jhemr.pat_master_index` 等表无 `SELECT` 权限。  
> **安全边界**：本 SQL **仅授予纯只读 `USAGE` + `SELECT` 权限**，严禁任何写/DDL 权限；请在 `10.10.8.177:5432` 数据库 `jhemr` 中由超级用户（如 `vbadmin`）审阅后执行。  
> **执行状态（2026-11-19 18:42 只读复核）**：用户已执行。`aizk_user` 对 `jhemr.jhmr_templet_index` / `jhemr.pat_master_index`（91,560 行）/ `jhemr.jhmr_file_cum_fileverify` / `jhcdr.jhcdr_lab_report_items` 均 `SELECT=true`，`UPDATE/INSERT/DELETE=false`。同时确认 **39 个日间/24h 模板已全部改绑 `JH04.03.013`**（`EMR09.00.02` 28 + `EMR09.00.01` 9 + `EMR12.00` 2）、**6 个诊断证明 `monitor_code` 已清空**，`goal_setting_table` 9 个锁定开关与 063 §3.2 一致。

```sql
-- ============================================================================
-- Vastbase (10.10.8.177:5432 / dbname=jhemr) 为只读账号 aizk_user 补齐全业务只读权限
-- 执行账号：数据库超级用户（如 vbadmin）
-- 安全级别：纯只读（仅 USAGE + SELECT，不含 INSERT/UPDATE/DELETE/CREATE/ALTER）
-- ============================================================================

-- 1. 授予 6 个业务 Schema 的 USAGE 访问权
GRANT USAGE ON SCHEMA jhemr, jhnis, jhcdr, jhfile, report, public TO aizk_user;

-- 2. 授予现有全部表与视图的只读 SELECT 权限
GRANT SELECT ON ALL TABLES IN SCHEMA jhemr  TO aizk_user;
GRANT SELECT ON ALL TABLES IN SCHEMA jhnis  TO aizk_user;
GRANT SELECT ON ALL TABLES IN SCHEMA jhcdr  TO aizk_user;
GRANT SELECT ON ALL TABLES IN SCHEMA jhfile TO aizk_user;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO aizk_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aizk_user;

-- 3. 确保未来新建表/视图也自动具备只读 SELECT 权限（按当前执行者与 jhemr 属主分别设置）
ALTER DEFAULT PRIVILEGES IN SCHEMA jhemr, jhnis, jhcdr, jhfile, report, public
  GRANT SELECT ON TABLES TO aizk_user;
-- 如业务表平时由角色 jhemr 创建，可补执行下面一行（若无 jhemr 角色可跳过）：
ALTER DEFAULT PRIVILEGES FOR ROLE jhemr IN SCHEMA jhemr, jhnis, jhcdr, jhfile, report, public
  GRANT SELECT ON TABLES TO aizk_user;

-- 4. 执行后只读验证（预期返回：true, true, false, false）
SELECT
  has_table_privilege('aizk_user', 'jhemr.jhmr_templet_index', 'SELECT') AS can_select_templet,
  has_table_privilege('aizk_user', 'jhemr.pat_master_index',   'SELECT') AS can_select_pat_master,
  has_table_privilege('aizk_user', 'jhemr.jhmr_templet_index', 'UPDATE') AS can_update_templet,
  has_table_privilege('aizk_user', 'jhemr.pat_master_index',   'DELETE') AS can_delete_pat_master;

-- 5. 回滚 SQL（如需收回新增授权，保留原有 9 表时慎用，一般可按需精准 REVOKE）：
-- REVOKE SELECT ON ALL TABLES IN SCHEMA jhnis, jhcdr, jhfile, report FROM aizk_user;
-- REVOKE SELECT ON jhemr.jhmr_templet_index, jhemr.pat_master_index FROM aizk_user;
```


---

## §7 修订记录

### v1.1（2026-11-19 19:40，对照真实代码逐项核查后修订）

v1.0 的提示词部分内容是按「推测的」路由、字段与端点写的，弱执行 AI 照做会直接报错或改坏现有功能。本次逐项核对代码后修正如下：

| # | 问题（v1.0） | 核查到的真实情况 | 修订 |
| :---: | :--- | :--- | :--- |
| 1 | 前端跳转写成 `/patient-qc`、`/timeliness/events`、`/timeliness/monthly`、`/governance/prearchive`、`/timeliness/rules`、`/audit` | 真实路由为 `/quality/patients`、`/quality/timeliness-events`、`/quality/timeliness-monthly`、`/governance/workbench`、`/governance/timeliness-rules`、`/quality/records`；菜单 ID `workbench` 是预检页、总览是 `dashboard` | 新增 PROMPT-00 路由对照表；WP-02~07 全部改为真实路径 |
| 2 | 月度考核接口写成 `/api/timeliness/reports/monthly` | 真实为 `/stats/monthly`（JSON）与 `/export/monthly`（CSV，已有导出审计） | WP-04 改为在现有端点上向后兼容扩展，`format=xlsx` 可选、默认 csv |
| 3 | 时效字段写成 `t0_time / deadline_at / lock_status`，审批写 `exempt_by/exempt_at` | 真实为 `t0 / deadline`，无 `lock_status`；审批无 `exempt_by/at` | 统一按真实字段；「锁定」口径明确为 `TLApproval`（JHEMR `monitor_limit_log`）行数，与现有 `_monthly_rows.approval_count` 一致 |
| 4 | 360 `userCode` 取 `emp_no` | `User` 表无 `emp_no`，全院员工 `username` 即 HIS 工号 | 改为后端按 username+工号正则计算 `user_code`，`admin` 等兜底 `wfy`，前端不做判断 |
| 5 | scanner 终态集合自己定义（含不存在的 `EXEMPTED`）、快照字段不存在 | `state.py` 已有 `TERMINAL_STATUSES`；OVERDUE 事件 `overdue_minutes` 每轮增长 | 复用常量；`overdue_minutes` 增量 ≥30 分钟才写回；加阶段耗时日志以确认瓶颈是否还在取数段 |
| 6 | `discharge_dept` 筛选直接去掉 CLOB 旧逻辑 | 24.5 万历史行该列为空，直接去掉会导致历史患者按出院科室查不到 | 改为「新列 OR（新列为空 AND 旧逻辑）」混合条件 + 回填脚本（生产在 WP-10 分批执行）；ORM 不建索引，索引走人工 DDL |
| 7 | `GET /api/users` 改 `page_size`、`GET /api/departments` 改为分页 | 用户接口已用 `page/limit/q`；科室接口返回列表被多处使用 | 用户接口只追加参数；科室分页另开 `/api/departments/paged` |
| 8 | 告警日志「全部解除 admin」 | `relay-alert/retry`、`alert-status-report` 是写操作/全院账实 | 只开放 logs/export/summary 按科室；retry 与账实报告仍 admin |
| 9 | JHEMR 提醒接口鉴权表述含糊（提到 X-Api-Key） | 已有 `_verify_request` HMAC + 开关 503 | 强制复用 `_verify_request`，不得新增其他鉴权 |
| 10 | WP-07 新建 bootstrap/backtest/delivery 平行模块；配置模板放 `config/` 子目录 | 预检服务已有 `RuleService.import_files`、`backtest_v2`、`outbox.DeliveryWorker`、issues actions；无 `config/` 子目录 | 改为复用现有能力，只写薄 CLI/适配脚本；中间表作为 Outbox 新传输类型；模板放 `config.shadow.prod.template.json` |
| 11 | 文件路径 `app/audit_type_registry.py`、`app/push_log_writer.py` | 实际在 `app/services/` 下 | 已更正 |
| 12 | 前端测试放 `src/**/__tests__/`，命令用 `npx vue-tsc --noEmit`；pytest 用通配符 | 仓库惯例 `frontend/tests/unit/`，脚本 `npm run typecheck/test:unit`；PowerShell 不展开通配符 | 全部改为真实命令与完整文件名 |
| 13 | 原 WP-08 一包含 5 个页面重构 + 全量门禁，弱 AI 难以在 4 小时内完成 | `AccessPage`/`ConfigPage`/`RelayConfigPage` 为压缩单行大模板，另有 4 个契约测试与 E2E 依赖 | 拆为 WP-08（权限+配置）与 WP-09（调度/补推/企微+全量门禁），并要求先盘点测试引用的 `data-testid` |
| 14 | 缺少生产发布环节 | 新增列、索引、回填、预检影子启用都需要有序上线 | 新增 WP-10：MD5 防撕裂预检 → 备份 → 发布 → 只读冒烟 → 低峰 DDL → 分批回填 → 影子启用 → 观察，每步单独审批 |
| 15 | 日间病历：v1.0 待确认 | 用户已执行 177 只读授权；复核 39+6 模板解绑完成；ai_mrzk 按 `mr_class` 判完成，不受 `monitor_code` 影响 | 时效判定无需改；WP-04 增加可选的对账口径归类（日间病历=原生免锁预期差异） |
| 16 | 缺少断点续跑与交付留痕规范 | 技能规程要求 review 报告与检查点 | 每包 `review/064-wpNN/{git_status_before.txt, exec-log.md, DELIVERY.md}` |

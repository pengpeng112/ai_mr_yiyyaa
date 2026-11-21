# 063 · Med-Audit（`ai_mrzk`）独立开发总交接与 JHEMR 接口全景地图

> **建立日期**：2026-11-19  
> **文档定位**：**独立工作区首选总览与接口交接入口**（自 2026-11-19 起，用户已将 `F:\python\前后端代码\ai_mrzk` 单独作为项目目录打开，后续不再经由 `E:\嘉和` 运维分析会话开发改造 AI 病历质控系统）。  
> **安全与授权边界**：本文档仅用于跨会话事实交接、架构/接口映射与开发导航，**不构成对任何生产服务器（`10.10.8.84`）、生产数据库（`10.10.8.177` Vastbase / `10.10.8.216` Oracle）的写入授权，也不构成 Git 提交或推送授权**。代码、配置与本交接文档冲突时，一律以当前仓库可执行代码、真实配置模板及测试为准。

---

## §1 交接声明与新会话必读启动顺序

### 1.1 背景说明
此前 `ai_mrzk` 的部分 JHEMR 反编译、数据库探索、全院锁定上线策略与临床边界排查在主运维仓库 `E:\嘉和` 中完成；从 **2026-11-19** 起，所有关于 AI 病历质控系统的新功能开发、故障排查与文档沉淀均在 **`F:\python\前后端代码\ai_mrzk`** 内闭环推进。本文档将此前分散在 `E:\嘉和` 会话与本仓多份交接中的**生产实态、JHEMR 原生锁定机制与全部对接接口**一次性浓缩，使新打开的任意 AI 会话无需依赖历史聊天记录即可直接上手。

### 1.2 新会话启动 5 步顺序（必走）
1. [AGENTS.md](../../AGENTS.md)：授权边界、数据库/Dify/调度器/V_QYBR/Vastbase/UI-Next 防回归核心约束。
2. [开发起步包/README.md](../../开发起步包/README.md) & [00_AI协作规则.md](../../开发起步包/00_AI协作规则.md)：资产落位与多 AI 协作记账规程。
3. [开发起步包/01_统一修改记录.md](../../开发起步包/01_统一修改记录.md) 末 10 行 & [02_协作任务板.md](../../开发起步包/02_协作任务板.md)：恢复上一任断点并认领文件范围（先执行 `git status --short` 保留他人未提交改动）。
4. **本文档（`063`）**：掌握截至 2026-11-19 全栈现状及全部 `ai_mrzk ↔ JHEMR / HIS` 接口契约。
5. 按任务定向读取 [docs/INDEX.md](../INDEX.md) 指向的专项文档（避免全量通读 `docs/archive/`）。

### 1.3 跨仓只读参考坐标（不作跳转链，仅作物理路径索引）
若需登机实查生产服务器、追溯 JHEMR 反编译/表字典或查医院数据资产全貌，可按以下只读坐标检索（**切勿在跨仓路径下擅自修改**）：
- 服务器只读检查手册：`E:\嘉和\docs\通用-环境与连接\63-服务器只读检查手册与速查卡.md`
- 堡垒机与服务器资产台账：`E:\嘉和\docs\通用-环境与连接\62-堡垒机与服务器资产台账.md`
- 时效锁定原始主设计文档（v3.2）：`E:\嘉和\JHEMR\嘉和病历质控\JHEMR病历时效锁定改造计划及后续质控说明-20261108.md`
- 医院跨库数据资产入口：`F:\python\数据资产\INDEX.md`、`F:\python\数据资产\三仓库互通地图.md`
- 线上只读排障技能（本仓已镜像一份）：[ai-mrzk-triage-and-handoff](../../.agents/skills/ai-mrzk-triage-and-handoff/SKILL.md)

---

## §2 截至 2026-11-19 系统能力与生产环境全景快照

### 2.1 四大已落地业务板块

| 板块 | 核心定位 | 关键后端入口 | 前端入口 | 当前生产状态 |
| :--- | :--- | :--- | :--- | :--- |
| **1. AI 语义内涵质控** | 6 类临床一致性 Dify 工作流抽取、双调度自动扫描、历史补跑、高危告警中继 | `app/data_source_loader.py`、`app/dual_source_loader.py`、`app/dify_pusher.py`、`app/scheduler.py`、`app/services/relay_alert_service.py` | `frontend/src/features/`（`ui-next` 已全面中文化与 `rawExtras` 无损往返） | **生产运行中**：已由 `oracle_patient_view_compat.py` 免疫 `V_QYBR`/`V_CYBR` `ORA-04063` 失效 |
| **2. 病历时效质控** | 18 条规则引擎、5 分钟自动扫描 `timeliness_scan`、全院 JHEMR 解锁审批与 200 元扣罚同步、事件人工豁免、月度考核 | `app/timeliness/`（`scanner.py`、`rules_seed.py`、`jhemr_reader.py`、`his_oracle_reader.py`、`approval_sync.py`、`jhemr_writer.py`、`engine/`）、`app/routers/timeliness.py` | `frontend/src/features/timeliness/`（规则管理/在院台账/审批中心/月度考核） | **生产影子运行中**：已接入 HIS 医嘱/排台/职称 7 规则与全院审批同步；JHEMR 写回双闸关闭 |
| **3. 归档前形式预检** | 独立预检微服务 `prearchive_service/`（与主服务物理零 `import app.*` 隔离）、无纸化 92 项规则中心 | `prearchive_service/`、`app/routers/jhemr_integration.py`、`app/services/prearchive_admin_client.py` | `AuditTypesPage.vue` 双页签（AI 质控 / 归档前预检）、规则中心页 | **本地/容器就绪**：现行 16 条质控科免签字规则（v`2026.09.10-046-t3`）；外部 JHEMR 集成开关关闭 |
| **4. 企微手机端 H5** | 「病历超时解锁查询与时效统计」三 Tab 门户（超时解锁/在院预警/统计通报） | `app/routers/mobile_timeliness.py`（20 路由）、`app/services/timeliness_access.py` | `static/templates/mobile/timeliness_h5.html`、`static/scripts/mobile/timeliness_h5.js`、`static/styles/mobile/timeliness_h5.css` | **生产已上线**：已通过 `:8000` / `:3000` 暴露，按用户/角色科室范围隔离；待配真实企微 `secret` 联调外网 OAuth |

### 2.2 生产服务器 `10.10.8.84`（`med-audit`）部署实态
- **主机与容器**：SSH `10.10.8.84:40022`（`root`，密码通过环境变量 `MED_AUDIT_SSH_PASSWORD` 或凭据台账获取），Compose 目录 `/opt/med-audit-docker/`，容器名 `med-audit`（**强制单 worker**，否则 APScheduler 重复发任务），挂载卷 `./data:/app/data`、`./config:/app/config`、`./logs:/app/logs`。
- **当前固化镜像**：**`9807a3e4c98f`**（2026-11-18 `20261118-prod-onboarding` 持久化提交）。
- **完整回滚链**：
  - 镜像回滚 tag：`med-audit:backup-pre-directory-onboarding-20261118`
  - 宿主机发行前文件备份：`/root/med-audit-onboarding-20261118/before.tar.gz`
  - Oracle 批次变更前快照：`/app/data/ops-backups/directory-sync-20261118-203455/activation-20261118-212113/before.json`
  - 标准回滚顺序（先收回批次角色与激活状态，再回退代码与镜像）见 `review/prod-onboarding-20261118/rollback.md`。
- **入口与端口路由**：
  - `UI_DEFAULT_ENTRY=ui-next`（`.env` 与 `docker-compose.yml` 均已更新，`GET /` 返回 `302 /ui-next/`，侧栏 5 组 22 项菜单）。
  - `http://10.10.8.84:8000`：FastAPI 主服务直连入口。
  - `http://10.10.8.84:3000`：宿主机 Nginx 分流代理，将 `/mobile/qc/`、`/styles/mobile/`、`/scripts/mobile/`、`/api/mobile/`、`/qc-api/` 透传至 `med-audit:8000`，而 `/` 仍保留原血透服务（`:3001`）。
  - 外网访问域名：`ydbi.sdent.com.cn`（前置机反代规范见 [122 企微代理对接规范](../reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md)）。
  - 院内高危告警中继：`http://10.20.1.153:3000/qc-record-alert`。

### 2.3 生产应用库（`10.10.8.216` Oracle `JHEMR.MED_*`）用户与权限体系
- **2026-11-18 全院员工目录同步**：从 `HIS.SYS_EMPLOYEE` 与 `HIS.DEPT_DICT` 只读抽取并写入生产应用库，当前线上实测 **2,383 名用户 / 640 个科室**。
- **分级授权与首登安全机制**：
  - 2,380 名可匹配科室的员工已批量启用并授予 **「时效查看员」**（`timeliness_reader`，默认 `own_dept` 本科室只读，不能跨科、不能审批/豁免）；另配有 **「医疗部」**（`medical_affairs`）只读角色及完整保留的原 `admin` 账号；
  - 另有 2 名无科室员工保持停用待人工补录科室；
  - 批量员工的初始密码采用仅企微验证可识的标记散列保存：PC 端直接用统一初始密码登录会被拒签，必须先经企业微信 OAuth 验证本人身份后通过 `POST /api/mobile/timeliness/me` 设置个人密码；
  - `MOBILE_TIMELINESS_EMPNO_LOGIN` 默认已关闭（受控账号须经验证登录，防止 `?empno=` URL 转发冒充）。
- **时效范围访问控制**：`app/services/timeliness_access.py` 与数据库用户/角色字段统一管辖台账列表、详情、统计及导出的数据可见范围（`own_dept` 本科室 / 指定科室 / 全院），且审批/豁免操作继续独立校验操作权限。

### 2.4 生产安全写闸当前状态（全关）

| 配置/环境变量 | 当前生产值 | 控制范围 | 说明 |
| :--- | :--- | :--- | :--- |
| `timeliness.jhemr_write.enabled` | `False` | 写入 `177` 的总开关 | 未启用；写账号口令 `TIMELINESS_JHEMR_WRITE_PASSWORD` / `password_enc` 亦尚未落入 84 |
| `timeliness.jhemr_write.insert_monitor_enabled` | `False` | 模板 A 外插 `emr_online_monitor` 子开关 | 即使打开总开关，只要子开关为 False，仅允许模板 B 审批解锁写回 |
| `timeliness.notify_mode` | `LOG_ONLY` | 企微实时超时预警推送 | 当前仅在日志与动作台账留痕，不向中继外发通知 |
| `timeliness.oracle_lock_enabled` | `None`（未开） | Oracle 端辅助锁兼容开关 | 保持关闭 |
| `JHEMR_INTEGRATION_ENABLED` | `false` | `/api/integrations/jhemr/*` 外部提交前检查 | 访问返回 HTTP `503` |

### 2.5 本地 Git 工作区现状（极其重要）
- `HEAD` 为 `dccfb21`（`master` 分支，2026-11-17 已同步推至 GitHub `pengpeng112/ai_mr_yiyyaa`）。
- 工作区当前保留着 **2026-11-17 晚 ～ 2026-11-18** 已部署上线或已完成本地验收的**未提交改动**（约 40 个修改/新增文件），涵盖：企微 OAuth 直签发与限流、`app/services/timeliness_access.py` 科室查看范围与首登改密、H5 响应式根修、目录同步兼容字段、`docs/reference/122`、[PROMPT-20261117](../../开发起步包/PROMPT-20261117_企微OAuth真实联调与外网前置机对接交接.md)、多个 `scripts/deploy_*.py` 与测试。
- **铁律**：新会话**必须完整保留**全部既有未提交改动；未经用户针对具体批次回明确批准，严禁 `git commit`、`git push`、`git reset`、`git clean` 或丢弃工作区变更。

---

## §3 JHEMR（`10.10.8.177`）原生锁定与生产侧现状（跨仓核心沉淀）

> 本节沉淀来自 `E:\嘉和` 仓库中对 JHEMR 客户端程序集 IL 反编译及 `10.10.8.177:5432/jhemr` 生产库实证核查结果，供 `ai_mrzk` 团队直接掌握 EMR 原生侧的真实约束，**不再需要切回 `E:\嘉和` 重复排查**。

### 3.1 EMR 主库与接口库身份勘误（永久冻结旧 179 路径）
- **`10.10.8.177:5432/jhemr`（Vastbase / OpenGauss）**：**唯一的真实生产 EMR 主库**，`10.10.8.178` 中间件直接连该库（`pg_is_in_recovery()=false`）。
- **`10.10.8.179`**：嘉和 Web/S4 接口应用服务器，其 Oracle 连接属于 S4 `JHWebInterface` 接口库，不是 EMR 客户端主库。旧 `054`/`055` 以 `179` Oracle 为目标的方案已永久作废。

### 3.2 `jhemr.goal_setting_table` 原生锁定 9 个开关当前生产实态

| 配置键（`goal_item`） | 当前生产值 | 反编译 C# IL 与真实业务语义 |
| :--- | :--- | :--- |
| `20110223L001` | `'1'` | **总开关**：开启病历超时质量控制锁定 |
| `20180409WHL001` | `'0'` | **硬锁人工审批模式**：超时写入 `jhmr_monitor_limit_log`，`FLAG='1'` 待审批锁死 → 审批通过置 `FLAG='2'` 解锁 |
| `20191220WHL001` | `'1'` | **客户端实时算超时**：写端打开/编辑时直接计算超时（不完全依赖后台轮询落表） |
| `20190115WHL002` | `'1'` | **放宽审签层级**：不强校验三级审签即可判定完成 |
| `20150616WHL001` | `'0'` | **完成时间取值**：取首次审签时间 `FIRST_MR_SIGN_DATE_TIME` |
| `20200623WHL002` | `'0'` | **时限来源**：按监控字典时限执行（`JH04.02.001` 入院 24h、`JH04.02.002` 首程 8h、`JH04.02.011` 出院 24h） |
| `20210816WHL001` | `'JH04.02.001\|JH04.02.002\|JH04.02.011'` | **监控码白名单（重要勘误）**：仅该列表内的 `monitor_code` 才触发超时锁！（嘉和厂商说明文档曾误注为“排除不锁”，IL 反编译证实实际为**包含白名单**） |
| `20220620WHL003` | **`'0'`** | **全院生效**：2026-11-16 已由用户从早期的试点四病区（`040112\|030442\|030443\|030427`）切换为 `'0'` **全院启用** |
| `20230505WHL002` | `'1'` | 医生申请解锁时强制弹窗填写解锁原因 |

- **原生审批端**：嘉和客户端 `IPMCWidgetMRMONITORLIMIT`（`canvas_id='mrmonitor-limit-approve-0001'`）已绑定角色 `32`（医务管理）与 `19`（质控管理），可在院内直接审批解锁，并同步进 `ai_mrzk` 台账。

### 3.3 四个关键临床边界与红线

1. **已审签病历永不触发锁定**：JHEMR 客户端 `CheckEditDisable`、`ApplyEdit`、`Sign`、`Delete` 等拦截入口均严格前置 `FILE_FLAG == "T"`（仅针对未审签草稿文书），已审签病历的查看、打印等操作不受影响。
2. **`JH04.02.011`（出院记录）出院前提前审签边界**：若医生在 HIS 办理正式出院登记前已提前写完并审签出院记录，`emr_online_monitor.completed_date` 可能仍为 `NULL`。正常状态下由于 `FILE_FLAG != 'T'` 不会被锁；仅当出院已超过 24 小时后医生再点击「取消审签」改回草稿时才会触发补锁弹窗。对应历史补填 `completed_date` SQL 已于 2026-11-16 交付用户备用。
3. **日间入院记录与日间出院记录免锁边界（重要后续核对点）**：
   - 经核实院内并无独立的日间病房科室编码，无法靠科室号过滤；
   - 2026-11-17 已在 `E:\嘉和` 排查 `177` 模板库并向用户交付方案：将 **39 个日间/24 小时出入类模板**（包含 `EMR09.00.02` 全组 + `EMR09.00.01` 内 9 个日间模板 + `EMR12.00` 内 2 个日间模板）的 `monitor_code` 改绑为白名单外的 `JH04.03.013`，并将误挂在 `EMR12.00` 下的 **6 个「诊断证明」**模板 `monitor_code` 清为 `NULL`（同时提供了可选的出院触发器豁免方案）；
   - **接手注意**：因生产写操作均由用户自行评估执行，新会话在调整 `ai_mrzk` 的 `ADM_REC` / `DISCHARGE_REC` 时效规则或做原生对账时，**务必先只读查询 `177` 核实上述 39+6 模板解绑是否已执行**，并在 `ai_mrzk` 侧增加日间模板过滤条件，防止客户端不锁但质控中心误报超时。
4. **D8 禁锁红线（`CHIEF_FIRST_ROUND` / `JH04.02.008`）**：`ADM_REC`（`JH04.02.001`）已通过全院 65 模板补码与 118 条幽灵行销账解除封锁；但 **`CHIEF_FIRST_ROUND`（`JH04.02.008`）** 在 `177` 仍存在大量历史幽灵未闭合监控行（>250 条），**严禁**将其加入 `20210816WHL001` 白名单或设为 `LOCK_EMR`（后端 `rules_seed.py` 与 API 已硬拦截 400）。

---

## §4 `ai_mrzk ↔ JHEMR / HIS / 外部系统` 接口全景台账

### 4.1 七大对接轨道总览表

| 轨道 | 交互方向 | 目标系统 / 实例 | 通道 / 账号 | 仓库代码 / 契约文档 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **轨道 1** | 只读抽取 | `10.10.8.177:5432/jhemr` | `aizk_user` → `jhemr.v_blws` | `app/emr_vastbase_client.py`、`app/dual_source_loader.py` | **生产在用** |
| **轨道 2** | 只读扫描 & 同步 | `177` Vastbase + `216` Oracle | `aizk_user`（8 表）+ `JHEMR`（5 表+`V_QYBR` 降级） | `app/timeliness/{jhemr_reader,his_oracle_reader,approval_sync,scanner}.py`、`app/services/oracle_patient_view_compat.py` | **生产在用（每 5 分钟）** |
| **轨道 3** | 受控回写（模板 B/A） | `10.10.8.177:5432/jhemr` | `mrzk_timeliness_write`（读写分离） | `app/timeliness/jhemr_writer.py`、`app/routers/{timeliness,mobile_timeliness}.py` | **已编码，双闸关闭** |
| **轨道 4** | 外部 Webhook + 双路回填 | 危急值平台 → `84` → `177` | `X-Webhook-Token` + `jhcdr`/`jhcriticalvalues_msg` | [121 危急值对接契约](../reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md) | **契约冻结，待厂商联调与开发** |
| **轨道 5** | 提交前预检 HTTP API | JHEMR 服务端 ↔ `84` ↔ `prearchive` | `X-Jhemr-*` HMAC-SHA256 + BFF | `app/routers/jhemr_integration.py`、`prearchive_service/` | **已编码，开关关（503）** |
| **轨道 6** | 客户端「病历完成」提醒 | 规则写入 `177` `fileverify` | `jhemr` 账户受控事务脚本 | [056 FILEVERIFY 交接](056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md) §6 | **v4 候选就绪，待 177 写入批准** |
| **轨道 7** | 外部缺失源 & 企微联动 | 输血/手麻/心电；企微中继 `10.20.1.153` / 前置机 `ydbi.sdent.com.cn` | OAuth + `/wecom-oauth/exchange` + `relay_alert` | [122 代理规范](../reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md)、[PROMPT-20261117](../../开发起步包/PROMPT-20261117_企微OAuth真实联调与外网前置机对接交接.md) | **部分上线，待配 `secret` 与补充源** |

---

### 4.2 逐轨道技术规格详解

#### 轨道 1：AI 内涵质控文书取数（`app/emr_vastbase_client.py`）
- **连接与目标**：直连 `10.10.8.177:5432/jhemr`（只读账号 `aizk_user`，通过 `psycopg2` 走 PostgreSQL 协议），读取视图 `jhemr.v_blws`（实测 22 列，时间列为 text，通过 `COALESCE(NULLIF(...))` 组装事件时间）。
- **查询机制与注意事项**：
  - Vastbase `cursor.description` 返回**大写**列名，必须先 `.lower()` 转为小写字典再读取（否则 `patient_id` 等全部取空）。
  - 文书分类过滤统一使用 `progress_template_name`（而非 `progress_type_name`/`title`）：出院用 `= '出院记录'`、病程用 `LIKE '%%病程%%'`、首次病程用 `LIKE '%%首次病程%%'`，防止混入知情同意书等非病程文档。
  - `sslmode` 仅在配置显式指定时传给 `psycopg2.connect()`，不要默认传 `"disable"`。
  - `discharge_final` 模式下，EMR 专属审计类型（如 `admission_vs_first_progress`、`surgery_chain`、`discharge_vs_frontpage`）通过 `Oracle V_QYBR → Vastbase` 协同路径取数，不受通用 SQL `a."出院日期"` 改写影响。

#### 轨道 2：时效质控多表只读扫描与全院审批同步
1. **JHEMR Vastbase 只读访问层（`app/timeliness/jhemr_reader.py`）**：
   - 强制 `set_session(readonly=True, autocommit=True)` + `SET statement_timeout`；固定使用只读账号 `aizk_user`；遇 `SQLSTATE 42501` 抛出 `TimelinessPermissionMissing`；患者对 `(patient_id, visit_id)` 单批上限 **500 对**，全参数化 `%s` 防注入。
   - **已核实读取的 9 张表**（含 770 列实证字典）：
     - 核心 8 表：`jhemr.pats_in_hospital`（在院）、`jhemr.pat_visit`（近期出院）、`jhemr.jhmr_file_index`（文书索引含审签人 6 列：`creator_id/name`、`topic_doctor_id/name`、`last_modify_user_id/name`）、`jhemr.operation`（含手术结束时间 `operating_end_date`、`operator_id` 主刀、`operation_type`、`operating_grade`）、`jhemr.emr_treament_apply`（会诊明细）、`jhemr.emr_treament_apply_master`（急/普会诊类别 `consult_class`）、`jhemr.emr_online_monitor`（原生锁定实时状态）、`jhemr.jhmr_monitor_limit_log`（解锁申请与审批记录）。
     - 院历节假日表：`jhemr.jhmr_mrreceivesignholiday`（已获 SELECT 授权，当前活库 0 行，程序自动降级回退标准周末口径；院方未来填表后自动生效）。
   - **已知只读权限缺口**：`PAT_MASTER_INDEX.NAME` 当前未对 `aizk_user` 授权，患者姓名由下方 Oracle `V_QYBR`（带 compat 降级与缓存）补偿注入。
2. **HIS / 手麻 Oracle 只读访问层（`app/timeliness/his_oracle_reader.py` + `app/services/oracle_patient_view_compat.py`）**：
   - 连接 `10.10.8.216` 应用同实例 Oracle（`JHEMR` 账号），全程只读 `SELECT` + Oracle 11g 兼容语法。
   - **`probe_oracle_tables()` 探测 5 表**：
     - `HIS.ORDERS`：临时医嘱（`REPEAT_INDICATOR='0'`、`ORDER_STATUS IN ('2','3','6')`，硬排作废/草稿 `4/5/8`），使用**精确编码/文本白名单**抽取抢救医嘱（30 分钟窗口合并为同一事件，源ID `HIS-{ORDER_NO}_{SUB_NO}`）与死亡/尸体料理医嘱（严格禁用 `LIKE '%死亡%'` 防误中 PD-L1 基因检测）。
     - `HIS.OPERATION_MASTER` + `HIS.OPERATION_NAME`：手术主记录，标准化 `HIS-{OPER_ID}` 事件主键。
     - `SM.MED_OPERATION_MASTER`：手麻排台表（动态探测 17 列白名单；硬过滤 `CANCEL_DATE_TIME IS NULL AND NVL(OPER_STATUS, 0) >= 0` 以剔除 `-80` 已取消手术；开台时间 `COALESCE(START_DATE_TIME, SCHEDULED_DATE_TIME)`，与主表统一归并 `HIS-{OPER_ID}` 防分裂）。
     - `HIS.STAFF_DICT`：医师职称字典（3600s 内存 TTL 缓存），支持 `ATTENDING_FIRST_ROUND` 校验 `主治医师/副主任医师/主任医师` 审签身份。
   - **全院员工与科室同步源**：`HIS.SYS_EMPLOYEE`、`HIS.DEPT_DICT`（2026-11-18 已完成 2,382 员工 / 638 科室目录对齐）。
   - **`JHEMR.V_QYBR` / `V_CYBR` 失效免疫与缓存（极关键）**：
     - 生产曾发生 ODS 重建 `HIS.*` 表导致 `JHEMR.V_CYBR`/`V_QYBR` 失去显式 `GRANT` 而集体 `INVALID`（`ORA-04063`）。`oracle_patient_view_compat.py` 为全站 **7 个入口**提供 40 列严格对齐的 `HIS.*` 基表内联括号视图等价降级 + **5 分钟进程内熔断记忆** + 在院场景 `V_ZYBR` 平替。
     - 查询 `V_QYBR` **严禁拼数百对 `(患者ID=:p AND 次数=:v) OR ...` 双列条件**（会导致 `UNION ALL` 视图全表扫描卡死并残留调度锁），必须走 `患者ID IN (...)` 单列小批（≤50）+ 每轮封顶 600 + 3600s 线程安全 TTL 缓存（`_visit_meta_cache`）+ 内存精确匹配。
3. **规则体系（`app/timeliness/rules_seed.py` 18 条规则全景）** & **审批同步（`approval_sync.py`）**：
   - `timeliness_scan` 调度每 5 分钟运行，对单规则异常隔离兜底、支持排台顺延引起的合法时钟回退（`WARNING/OVERDUE -> PENDING`）；同步执行 `approval_sync.py` 将全院 `jhemr_monitor_limit_log` 拉入本地 `MED_TL_APPROVAL`（默认 200 元/次，支持人工豁免）。

<details>
<summary>点击展开：18 条病历时效规则种子清单与当前实现状态</summary>

| 规则码 (`rule_code`) | 中文名 | 触发事件 | 目标文书 (`mr_class` / 条件) | 时限 | 监控码 (`monitor_code`) | 当前口径与说明 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ADM_REC` | 入院记录 | `ADMISSION` | `EMR09.00.01/02/03` | 24h | `JH04.02.001` | JHEMR 原生已全院启用；**须跟进排除 39 日间模板** |
| `FIRST_COURSE` | 首次病程记录 | `ADMISSION` | `EMR10.00.01` | 8h | `JH04.02.002` | JHEMR 原生已全院启用 |
| `ATTENDING_FIRST_ROUND` | 主治及以上首次查房 | `ADMISSION` | `EMR10.00.03`（排“术后”） | 48h | `JH04.02.003` | `HIS.STAFF_DICT` 上级职称本人审签/创建；SHADOW 验证已通 |
| `CHIEF_FIRST_ROUND` | 主任/副主任首次查房 | `ADMISSION` | `EMR10.00.03`（含“主任”） | 7d | `JH04.02.008` | **D8 红线禁止 `LOCK_EMR`**（幽灵行 >250） |
| `RESCUE_REC` | 抢救记录 | `RESCUE_ORDER` | `EMR10.00.08/02`（含“抢救”，排“有创”） | 6h | `JH04.02.007` | 接 `HIS.ORDERS` 抢救白名单；SHADOW 已通 |
| `OP_REC` | 手术记录 | `OPERATION_END` | `EMR05.01.02` / `EMR10.00.16` | 24h | `JH04.03.012` | 排 `operation_type='0'`；主刀工号审签校验；SHADOW 已通 |
| `POSTOP_FIRST_COURSE` | 术后首次病程 | `OPERATION_END` | `EMR10.00.12`（排交班/转科/出院） | 6h | `JH04.02.018` | 排 `operation_type='0'`；SHADOW 已通 |
| `PREOP_SUMMARY` | 术前小结/讨论 | `OPERATION_START` | `EMR10.00.10` | 0（术前，提前 2h 预警） | `JH04.03.001` | 三合一豁免（急诊/局麻一级/造影）+连台卡口+排台融合；SHADOW 已通 |
| `ANES_REC` | 麻醉记录 | `ANESTHESIA_END` | — | 24h | 无 | **D4 外部源 `NOT_CONFIGURED`**（手麻系统） |
| `DEATH_DISCUSS` | 死亡病例讨论 | `DEATH` | `EMR10.00.15` | 5 工作日 | `JH04.02.013` | `workday_only=True` |
| `DISCHARGE_REC` | 出院记录 | `DISCHARGE` | `EMR12.00` / `EMR10.00.13` | 24h | `JH04.02.011` | JHEMR 原生已全院启用；**须跟进排除日间模板与 6 诊断证明** |
| `CRITICAL_VALUE_COURSE` | 危急值处置病程 | `CRITICAL_VALUE` | 病程类含危急值 | 6h | `JH04.03.016` | **按 121 契约待厂商联调开发** |
| `DEATH_REC` | 死亡记录 | `DEATH` | `EMR10.00.14` / `EMR09.00.03` | 24h | `JH04.02.012` | 融合 `HIS.ORDERS` 死亡/料理医嘱 earliest t0；SHADOW 已通 |
| `CONSULT_EMERGENCY` | 急会诊 | `CONSULT_APPLY` | `EMR10.00.08/07.00.08/10.00.02` 含“会诊” | 10min | `JH04.02.020` | 回退 `treat_date_time`（`WARN_ONLY`） |
| `CONSULT_NORMAL` | 普通会诊 | `CONSULT_APPLY` | 同上 | 24h | `JH04.02.020` | 已启用试点 `WARN_ONLY` |
| `DIFFICULT_CASE` | 疑难病例讨论 | `MANUAL_OR_INDICATOR` | `EMR10.00.04` | 待定 | 无 | 默认 `SHADOW` |
| `BLOOD_COURSE` | 输血病程 | `TRANSFUSION` | 病程类含“输血” | 24h | `JH04.03.017` | **D4 外部源 `NOT_CONFIGURED`** |
| `BLOOD_REC` | 输血记录 | `TRANSFUSION` | `EMR05.01.04` | 24h | `JH04.03.010` | **D4 外部源 `NOT_CONFIGURED`** |

</details>

#### 轨道 3：JHEMR 受控回写通道（`app/timeliness/jhemr_writer.py`，当前全关）
- **独立读写分离账号**：强制使用 `timeliness.jhemr_write` 配置段（专用账号 **`mrzk_timeliness_write`**），严禁复用 `aizk_user`；口令通过 `TIMELINESS_JHEMR_WRITE_PASSWORD` 或 Fernet `password_enc` 注入。2026-11-12 只读权限矩阵复核已确认 `mrzk_timeliness_write` 在 177 上对 `jhmr_monitor_limit_log` 的 `SELECT 7 列 / UPDATE 3 列` 权限精确匹配。
- **三重防误写门禁**：① `timeliness.jhemr_write.enabled` 严格布尔 `True`；② `patient.dept_code in pilot_dept_codes`（全院放开时需按审批规则配置或扩展白名单）；③ 仅允许两套硬编码模板，动作先落 `tl_action_log`（`BLOCKED` / `DRY_RUN` / `EXECUTED`）。
- **两套写模板分工**：
  - **模板 B（`SQL_APPROVE_LIMIT_LOG_TEMPLATE`，推荐优先启用）**：
    `UPDATE jhemr.jhmr_monitor_limit_log SET approve_user_id=%s, approve_date_time=%s, flag=2 WHERE patient_id=%s AND visit_id=%s AND monitor_code=%s AND apply_date_time=%s AND type=%s AND hospital_no=%s AND flag=1`
    强制校验 `rowcount == 1`，否则立即 `ROLLBACK` 抛 `JhemrWriteRowCountError`。启用后，医务科在 `ai_mrzk` PC 网页端与企微 H5 点击「同意解锁」即可直接解除 JHEMR 客户端锁定。
  - **模板 A（`SQL_INSERT_MONITOR_TEMPLATE`，受 `insert_monitor_enabled=false` 独立封锁，后置启用）**：
    `INSERT INTO jhemr.emr_online_monitor (..., hospital_no, source_system_identity, dept_code) SELECT ..., '49557032X', 'AI_MRZK', %s WHERE NOT EXISTS (...)`。
    硬禁触碰 `completed_date`（由 JHEMR 自行回填），硬拦截原生 5 码 `NATIVE_GENERATED_CODES = {JH04.02.001, 002, 006, 008, 011}` 防重复锁死。仅用于未来为跨系统节点（如手术记录 `JH04.03.012`、术后首程 `JH04.02.018`、抢救 `JH04.02.007`、危急值 `JH04.03.016`）施加 EMR 客户端硬锁；**开启前必须先在 177 给对应模板补全 `monitor_code` 并由 DBA 授予写权限、配置 `goal_setting_table` 白名单**。

#### 轨道 4：危急值 Webhook + JHEMR 临床引用双路赋能（[121 契约](../reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md)，待厂商联调开发）
- **总体架构（已拍板）**：「`10.10.8.84` 统一接数 + 双路赋能」，危急值系统只需对接质控中心一次：
  1. **厂商推送入口（待编码）**：`POST http://10.10.8.84:8000/api/timeliness/webhooks/critical-value`（Header `X-Webhook-Token`，按 `crisis_id` 幂等，支持 `REPORTED` / `RECEIVED` / `HANDLED` / `CANCELLED`，另配只读视图每 2 分钟对账补偿）。
  2. **对内时效接线**：收到 `INP` 且 `RECEIVED` 时以 `receive_time` 启动 `CRISIS_VAL_6H`（`JH04.03.016`）6h 倒计时（达标判定允许追溯至 `report_time`）；收到 `CANCELLED` 自动豁免 `SOURCE_CANCELLED`。
  3. **下行回填 `177` 双通道（经审批与 DBA 授权后开发启用）**：
     - **通道一（首选，零客户端改动）**：更新 `jhcdr.jhcdr_lab_report_items`（`source_type='LAB'`）或 `jhcdr.jhcdr_exam_report`（检查/心电/病理）将 `is_criticalvalues='1'` 及 `criticalvalues_content` 写入，JHEMR 医生站右侧检验/检查面板自动整行标红并支持右键引用入病历（遇 LIS→CDR 同步延迟则由每 5 分钟任务补偿重试）。
     - **通道二（可选进阶）**：幂等插入 `jhemr.jhcriticalvalues_msg`（16 列，`message_content` 按反编译实证的 10 段 `[*SP1*]` 与子项 `[*SP2*]` 协议拼装），驱动客户端「患者危急值管理」弹窗台账与一键创建危急值病程草稿。

#### 轨道 5：JHEMR 提交前/归档前形式质控 HTTP 接口（`app/routers/jhemr_integration.py`）
- **端点清单**（共 6 个，全部强制 `X-Jhemr-Client-Id` / `X-Jhemr-Timestamp`（±300s）/ `X-Jhemr-Nonce`（防重放）/ `X-Jhemr-Signature`（HMAC-SHA256）四件套认证，不走用户 JWT）：
  - `POST /api/integrations/jhemr/submission-checks`：幂等创建提交前预检任务（202 + `check_id`）
  - `GET /api/integrations/jhemr/submission-checks/{check_id}`：查询完整预检结果（未完成不返回假 pass）
  - `POST /api/integrations/jhemr/view-tickets` & `POST /api/integrations/jhemr/view-tickets/{nonce}/redeem`：换取/核销一次性详情查看票据（绑定 `patient+visit+operator`）
  - `POST /api/integrations/jhemr/issues/{issue_id}/feedback`：医生对问题项反馈（看过/已整改/误报/说明）
  - `POST /api/integrations/jhemr/rechecks`：整改后触发复检
- **实现流转**：主服务经 `PrearchiveAdminClient`（BFF 白名单）代理至独立隔离服务 `prearchive_service/`（含 16 条质控科免签字规则 v`2026.09.10-046-t3`）。当前 `JHEMR_INTEGRATION_ENABLED=false`（返回 503），L1 本地契约已过，待嘉和侧/信息科协调 L2/L3 联调。

#### 轨道 6：JHEMR 客户端点「病历完成」弹窗提醒 `FILEVERIFY`（[056 交接](../ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md) §6）
- **实现原理**：向 `10.10.8.177:5432/jhemr` 表 `jhemr.jhmr_file_cum_fileverify` 写入 `CHECK_TYPE=4, TIP_TYPE=1` 校验规则，医生在客户端点击病历完成时原生弹出未签/缺项提示（零改动嘉和 DLL）。
- **当前进度**：已完成 177 现时只读 P0 复核（4 目标 ID `20260922AIQC01`–`04` 均 0 行、本院码 `49557032X`、20 列元数据与中文编码对齐）；Vastbase v4 候选包（`review/jhemr-fileverify-056/v4_vastbase_candidate.json`，SHA-256 `0cccc27361002aa3ae7b180e69ad002ae81579ef7ebd0a7fb6377d8bb209e84f`）及全校验事务执行器 `execute_v4.py` 均已就绪（全部 `ENABLE=0` 灰度引入），**仅待用户在 177 明确签署写入批准**。注意：历史方案中的 `jhmr_rectification` 表因生产缺 `READ_STATUS` 列已弃用。

#### 轨道 7：企微手机端 OAuth / 外网前置机代理 & 待接外部源
1. **企微手机端 H5（`app/routers/mobile_timeliness.py`）**：
   - 20 个路由已在 `app/main.py` 优先注册（**必须早于 `mobile_qc.router`**，否则 `/mobile/qc/timeliness` 会被 `/{alert_id:int}` 捕获报 422）。
   - 核心接口：`GET /mobile/qc/timeliness`（入口页）、`GET /mobile/qc/timeliness/oauth/wecom/callback`（OAuth 直签发 HttpOnly Cookie 后 302 回干净页面，凭证零进 URL）、`POST /api/mobile/timeliness/login`、`GET/POST /api/mobile/timeliness/me`（含首登设置个人密码）、`/dicts`、`/overview`、`/approvals`（含 `/sync` 15s 冷却、`/exempt`、`/approve` 写闸关返 409）、`/events`（含 `/{event_id}`、`/exempt`）、`/stats`。
   - **联调现状**：用户已提供企业微信参数（`corpid=ww9021c8e20f77fb24`、`agentid=1000033`、外网域名 `ydbi.sdent.com.cn`），内网与生产镜像已通过模拟 OAuth + HIS/Oracle 验证；**剩余待办**见 [PROMPT-20261117](../../开发起步包/PROMPT-20261117_企微OAuth真实联调与外网前置机对接交接.md) 与 [122 规范](../reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md)：由用户在 84 宿主机配置真实企微 `secret`，并在外网前置机实现 `/wecom-oauth/exchange`（HMAC-SHA256）及 5 前缀最小暴露面反向代理。
2. **尚未接入的业务外部源（D4）**：
   - **输血系统**（`BLOOD_REC` / `BLOOD_COURSE`）、**手麻麻醉记录**（`ANES_REC` DoCare）、**心电信息**（`prearchive` 源之一）当前均为 `NOT_CONFIGURED`，需院方确认数据源视图后按 `ExternalEventSource` 接口接入。

---

## §5 开发与运维红线、常见陷阱及验证门禁

### 5.1 七条不可逾越的硬红线
1. **生产库写入一律只出方案不代执行**：对任何生产数据库（`177`、`216`）的 `INSERT`/`UPDATE`/`DELETE`/`DDL`/`GRANT`，AI 只能先提交**完整 SQL + 影响面评估 + 回退方案**，仅当用户对该批 SQL 明确说“同意执行”才可在当次单批执行；默认由用户自行审核或执行。
2. **84 容器热更新防版本撕裂**：局部更新前必须比对本地 `app/` 与容器 `/app/app/` 文件 MD5；更新前必须 `docker commit` 打回滚镜像 tag + tar 备份宿主机/容器文件；复制 `.py` 后必须清 `__pycache__/` 并重启、`docker commit` 固化；**严禁触碰 `/app/config/config.json` 已加密密文与 `.env` 的 `SECRET_KEY`**。
3. **只读探查严禁调用 `app.main` 或 `init_db()`**：只读核查必须走独立只读连接与 `readonly=True`，防止自动建表或迁移；保持 uvicorn **单 worker**。
4. **`prearchive_service/` 隔离铁律**：严禁在 `prearchive_service/` 内 `import app.*`，主服务只能通过 HTTP BFF 或只读配置 JSON 与之交互。
5. **脱敏与零密文入仓**：`config/config.json`、`.env`、`data/`、`logs/`、`review/`、根目录 `user*.xlsx` 均不入 Git；代码/文档/日志/响应中严禁出现真实口令、`SECRET_KEY`、API Key 或患者姓名/未脱敏住院号。
6. **保留现场与 Git 禁令**：任何修改前必读 `git status --short` 与 `02_协作任务板.md`；结束前必须追加 `01_统一修改记录.md`（历史行只增不改）并更新 `02_协作任务板.md`；未经当次批准严禁 `git commit/push/reset/clean`。
7. **散文件治理**：所有新建计划/交接文档必须以三位编号放入 `docs/ACTIVE/`（或契约放入 `docs/reference/`）并**同步登记 `docs/INDEX.md`**，不得在根目录或 `docs/` 顶层散放未登记 Markdown。

### 5.2 高频技术陷阱速查

| 领域 | 常见坑点 | 正确做法 / 防线 |
| :--- | :--- | :--- |
| **Oracle `V_QYBR`/`V_CYBR`** | 视图不继承 Role 权限，ODS 重建表即 `ORA-04063`；双列 `OR` 绑定致全表扫拖死进程 | 必须经 `oracle_patient_view_compat.py` 提供 `HIS.*` 内联降级+5 分钟熔断；批量只用单列 `IN`（≤50）+ TTL 缓存 + `finally` 还连接 |
| **Oracle 空串语法** | Oracle 将 `''` 视为 `NULL`，SQL 中写 `col != ''` 会过滤掉全部行；`is_(True)` 报 `ORA-00908` | SQLAlchemy 用 `col == True`；判空移至 Python 过滤 |
| **Vastbase 列名/方言** | `cursor.description` 列名全大写；空表或脏年份（如 `22025-`）抛异常中断整批 | 统一 `.lower()`；触发/文书解析按单行隔离容错并写告警日志 |
| **CSRF 与 `ui-next` 契约** | `security_middleware.py` 对带 Cookie 写请求强制要求 `X-Requested-With`；规则编辑保存可能洗丢后端隐藏键 | `client.ts` / H5 `apiFetch` 恒带 `X-Requested-With: XMLHttpRequest`；表单抽屉用 `rawExtras` 透传+固定中文标签 |
| **企微 H5（CSP 与 Vue3）** | 严格 CSP **零内联 `<script>`、零 `on*=`**；外部闭包改普通 `state` 对象不触发 Vue 视图更新 | 必须外置 JS、使用 `state = Vue.reactive(state)` 并先于 `APP.mount('#app')`；更新 JS 同步升级 HTML `?v=...` 版本参数 |

### 5.3 必跑验证命令速查
- 文档与索引合规检查：`python scripts/check_documentation_20261002.py`
- 仓库快速门禁（4 项聚合）：`python scripts/run_gates_20260906.py --quick`
- 后端单测：`python -m pytest`（全量） / `python -m pytest tests/timeliness -q`（时效专项）
- 预检隔离检查：`python prearchive_service/check_isolation.py`
- 前端检查：`cd frontend && npm run typecheck && npm run test:unit && npm run build`

---

## §6 后续待推进事项优先级清单（Backlog）

| 优先级 | 事项 | 当前阻塞 / 前置依赖 | 参考入口 |
| :--- | :--- | :--- | :--- |
| **P0** | **企微 OAuth 真实全链联调与外网上线** | ① 用户本人于 84 宿主机配置企微 `secret`；② 外网前置机侧实现 `/wecom-oauth/exchange` 与 5 前缀最小暴露面反代；③ 为 2 名待定员工补录科室 | [PROMPT-20261117](../../开发起步包/PROMPT-20261117_企微OAuth真实联调与外网前置机对接交接.md)、[122 规范](../reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md) |
| **P1** | **日间入院/出院免锁双边校验** | 只读核验 `177` 上 39 日间模板（`JH04.03.013`）+ 6 诊断证明（`NULL`）SQL 是否已由用户执行；同步在 `ai_mrzk` 时效 `ADM_REC`/`DISCHARGE_REC` 规则过滤日间模板 | 本文档 §3.3 第 3 条 |
| **P1** | **启用网页/企微端直审解锁回写 & 企微告警实发** | ① 用户注入 `TIMELINESS_JHEMR_WRITE_PASSWORD` 并批准开启 `jhemr_write.enabled=True`（**仅模板 B**，`insert_monitor_enabled` 保持 `False`）；② 确认 `relay_alert` 策略后分批解除 `LOG_ONLY` | `app/timeliness/jhemr_writer.py`、[062 指针](062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md) §5 |
| **P2** | **危急值 Webhook 与 177 双路赋能研发联调** | 危急值厂商按 `121` 对接；编码实现 `/api/timeliness/webhooks/critical-value` + `MED_TL_CRITICAL_VALUE` 建表审批 + `jhcdr`/`jhcriticalvalues_msg` 回填 | [121 契约](../reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md) |
| **P2** | **工作区未提交代码分批 Git 收编** | 按专题检查 2026-11-17～18 约 40 个文件并经用户明确授权后 `commit` / `push` | `git status --short`、`01_统一修改记录.md` |
| **P3** | **JHEMR 深化集成与外部源补全** | ① `FILEVERIFY` 第一批 4 条获批写入 177；② `jhemr_integration` 客户端 L2/L3 联调启用；③ 手术/术后/抢救模板补绑 `monitor_code` 后再评估模板 A；④ 补接输血/麻醉/心电；⑤ 协调 Oracle DBA 显式授权 `HIS.*` 根治 `V_QYBR` 周期性 `INVALID` | [056](056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md) §6、`app/routers/jhemr_integration.py` |

---

## §7 新会话一键接手启动提示词（可直接复制给本仓库新开 AI）

```text
请先按仓库协作规范依次读取以下文件恢复现场（全部只读核查，先不要修改任何代码或执行 Git 写操作）：
1. AGENTS.md
2. 开发起步包/README.md 与 开发起步包/00_AI协作规则.md
3. 开发起步包/01_统一修改记录.md 末尾 15 行 与 开发起步包/02_协作任务板.md 末尾
4. docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md（本文档：含 10.10.8.84 最新生产镜像 9807a3e4c98f、JHEMR 177 原生全院锁定现状及六大 JHEMR/HIS 接口对接全景）
5. 执行 `git status --short`，完整保留工作区内所有既有未提交改动。

核心红线（必须严格遵守）：
- 任何对 10.10.8.177 / 10.10.8.216 生产库的写操作（INSERT/UPDATE/DELETE/DDL/GRANT）严禁擅自代执行，必须先交完整 SQL + 影响面 + 回退方案等我明确说“同意执行”。
- 10.10.8.84 生产容器操作默认严格只读，局部热更新前必须做本地/容器 app/ MD5 比对防版本撕裂、先打回滚镜像 tag + tar 备份并维持 TIMELINESS 写闸门默认关闭。
- 未经我明确指令严禁运行 git commit / push / reset / clean。
- 严禁在文档、脚本或回答中输出任何明文口令、SECRET_KEY、API Key 或真实患者姓名/未脱敏住院号。

读完后先向我简要汇报：① 当前工作区状态与你在任务板上认领的范围；② 针对我接下来提出的本次具体任务，你核对过的接口/代码依据与准备方案。
```

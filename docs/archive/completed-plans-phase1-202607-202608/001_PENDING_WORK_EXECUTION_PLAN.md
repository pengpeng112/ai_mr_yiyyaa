# 待完成功能统一执行计划

> 状态：**历史全局清单证据，执行服从 023**（2026-08-13 起，见 INDEX 使用规则 6）；本行 2026-08-29 按 031/T1-7 回填
> 建立日期：2026-07-11
> 最近修订：2026-07-14 — 工作包 A、B 已实施并通过回归；B 覆盖通知测试鉴权/SSRF、重定向关闭和 HTTP 异常脱敏。原“安全项不得由 AI 修改”决定被本次计划取代，但数据库幂等和推送事务改造仍须单独设计审查后实施。
> **更正注记（2026-08-29，031 D3/D8 裁决）**：① §2.2.3"留存覆盖缺口"已过时——现行 `app/services/retention_service.py:16`（import 含 QCRecordAlertLog/QCAlertFeedback/QCFeedback）与 L3 清理路径已覆盖该缺口，测试见 `tests/test_retention_service.py`；② §11.7 工作包 F 是设计门（首版撤下未实施），幂等能力实际由 **002** 落地（execution/attempt 表与 claim 接线，2026-07-28 生产部署）——禁止从本文拣选已过时待办直接实施。
> 证据来源：对 `docs/` 全部 Markdown、`app/`、`static/`、`tests/` 和 `config/config.json.template` 的静态核验。
> 执行原则：按本文优先级实施；每个工作包单独提交、单独验证，不混入无关界面改动或生产配置变更。

## 1. 已完成与未完成的边界

已具备但仍需验收的能力：患者质控、前置机告警、医生端 H5、告警查看记录、Vastbase 基础接入、双调度框架、终末覆盖字段与服务、出院终末按日 payload、运行总览和首页驾驶舱基础界面。

尚未关闭的功能能力：推送/告警并发幂等、双模式调度配置一致性、Vastbase 生产数据验证、前置机身份透传闭环、部分前端工作台、临床准确性抽检，以及多数据源规则引擎。

### 2026-07-12 核实结论摘要

经逐项代码核实，原清单中以下条目**实际已完成**（清单过时）：2.1.3（QCRecordAlertLog 原子状态）、2.1.4（业务结果先提交再投递）、2.2.1（调度模板默认禁用）、2.2.2（调度锁心跳）、§3 终末覆盖测试（22→29 用例）、§4 mobile_qc 路由+身份透传（代码层）。

以下条目**经项目负责人确认搁置**，不再实施：2.1.2（PushClaim 短租约表，A）、2.1.5（串行执行器事务缩小，B）——理由见对应小节。当前生产单 worker 部署下运行风险低于改造回归风险。

以下条目**本轮已补齐测试**：§4.2.4 mobile_qc 自动化测试（新增 `tests/test_mobile_qc_api.py` 29 用例）、§3.3 终末覆盖删除清引用 + 失败/跳过不触发覆盖（扩展 `test_push_log_supersede.py` +7 用例）。

### 安全改动决策更新（2026-07-14）

原先暂缓的默认管理员/登录兜底、通知测试 SSRF、Dify 病历摘要日志脱敏，现已纳入 §11 的分批实施作业书。执行者不得跳过 P0，也不得一次性混入数据库幂等、调度重构或界面改版。每批必须在独立提交、全量测试和人工复核通过后才能进入下一批。

**2026-07-12 追加暂缓项**：2.1.2（PushClaim 短租约表）和 2.1.5（串行执行器事务缩小）——触及 PushExecutor/BulkPushExecutor 推送主链路，回归风险高。详见 §2.1 对应搁置说明。重启前提：多 worker 部署 / Dify 超时频繁导致写锁阻塞。

## 2. P1：推送与调度可靠性

> **2026-07-11 核实修订**：本节逐项对照主干代码核实，标注实际状态。其中 2.1.2（A）和 2.1.5（B）经项目负责人确认**搁置不实施**——触及 PushExecutor/BulkPushExecutor 推送主链路，回归风险高于当前单 worker 部署下的运行风险。

### 2.1 推送和告警幂等

1. 由业务确认幂等键：至少覆盖 `source_record_key`、`audit_type_code`、`audit_run_mode` 及重试语义。 — **🔒 业务确认**（代码层去重逻辑已具备：`push_skip_policy.py:43-71` 按 `source_record_key` 去重，`record_identity.py:45-72` 区分 run_mode）。
2. 为 Dify 推送增加原子 claim/state，避免"先查询再发送"并发重复调用。 — **⬜ 搁置（不再实施）**。理由见下方"2.1.2 搁置说明"。
3. 为 `QCRecordAlertLog` 增加 `pending -> sending -> success/retry_wait/dead_letter` 原子状态转换或等价 outbox。 — **✅ 已完成**。`relay_alert_service.py:919-928` 原子 claim（`WHERE status IN ('pending','failed') OR (status='sending' AND stale)` → `UPDATE sending`）；`models.py:351` 状态字段含 `pending|sending|success|failed|suppressed`；`models.py:369` 唯一索引 `idx_alert_push_dim`；`test_relay_alert_service.py:151` 验证不重复发送。
4. 业务结果先提交，再异步投递前置机；投递失败按退避策略恢复。 — **✅ 已完成**。`push_executor.py:204 db.commit()` → `:215 dispatch_pending()`；`bulk_push_executor.py:370 commit → :377 dispatch_pending`。主事务提交在前，relay 投递在后。
5. 缩小串行执行器中持有数据库事务的范围，网络调用不占用 SQLite 写锁。 — **⬜ 搁置（不再实施）**。理由见下方"2.1.5 搁置说明"。

#### 2.1.2 搁置说明（A：PushClaim 短租约表）

**决策**：不实施。触及推送主链路（PushExecutor/BulkPushExecutor），回归风险高。

**不实施的风险评估（已核实，可接受）**：
- 生产部署为 `uvicorn --workers 1` 单进程（`Dockerfile:83`），`PushExecutor`（串行路径）无并发——单进程内 for 循环逐条处理，不存在两个线程同时 claim 同一记录。
- `BulkPushExecutor` 虽用 `ThreadPoolExecutor(max_workers=4)`（`bulk_push_executor.py:105`），但其 Dify 调用走 `_push_with_empty_retry`（纯网络无 DB 写），DB 写在独立 `SessionLocal()` 新会话里——bulk 路径已分阶段，不存在"事务内网络调用"问题。
- 真正需要 claim 的场景只在"多实例水平扩展"时出现，而当前单 worker 部署不触发。

**重启该决策的前提**：若未来改为多 worker / 多实例部署，需重新评估并发 claim 需求。届时应先出 PushClaim 表结构 + claim/release/lease 语义 + Dify 失败补偿策略的设计方案，审批后再实施。

#### 2.1.5 搁置说明（B：串行执行器事务缩小）

**决策**：不实施。触及 `PushExecutor.execute` 主路径，回归风险高。

**当前状态（可接受）**：
- `push_executor.py:176` 用 `with db.begin_nested():`（SAVEPOINT）包住 `_push_single_record`，`:339` 的 `push_to_dify`（网络调用）在 savepoint 内。
- SQLite 下 savepoint 持有写锁期间做网络调用，若 Dify 慢会延长占锁；但单 worker 串行处理，锁竞争仅来自其他 HTTP 请求的写操作。
- Oracle 下 savepoint 不锁全表，影响更小。
- `execute_retry` 路径（`:600/:648`）同理，仅重试场景触发。

**不实施的权衡**：改造需把 `_push_single_record` 拆成"Claim→Dify（无DB）→落库"三段，每段的失败补偿、事务边界、异常回滚语义都要重新设计，回归面覆盖全部手动推送和重试路径。在当前"Dify 响应可接受 + 单 worker"的运行条件下，运行风险低于改造回归风险。

**重启该决策的前提**：若观察到 Dify 超时频繁导致 SQLite 写锁阻塞其他请求（可通过日志确认），再重新评估。

### 2.2 调度和留存

1. 将 `scheduler_daily`、`scheduler_discharge` 模板默认设为禁用；首次启用前校验 Dify、数据源和审计类型配置。 — **✅ 已完成**。`config/config.json.template:729,738` 两个调度均 `enabled: false`。
2. 为调度运行锁增加 owner 心跳和安全接管审计。 — **✅ 已完成**。`scheduler_lock_service.py:128 heartbeat_scheduler_run_lock`；`scheduler.py:552-574` 后台守护线程每 60s 周期刷新心跳；`scheduler_lock_service.py:48-60` stale 接管（超 `STALE_LOCK_TIMEOUT` 4h 强制接管）。
3. 留存服务覆盖告警 payload、H5 反馈及文件日志；拒绝非正 `batch_size`，并清理 NULL 病历正文路径。 — **⬜ 部分完成**。batch_size 校验✅（`retention_service.py:30` 强制 ≥1）、NULL 病历正文清理✅（`:201-209`）、文件日志留存✅；**缺口**：未覆盖 `qc_record_alert_log.payload_json` 和 `qc_alert_feedback`（告警 payload 和 H5 反馈）——`retention_service.py:16` import 清单不含这两个 model。
4. 以 SQLite 和 Oracle 分别做并发、长任务、失败重试和锁接管演练。 — **🔒 需运维环境**。`tests/` 无并发测试 fixtures。

### 2.3 验收

- 并发相同任务不会重复调用 Dify 或重复发送同一告警。 — **部分满足**。告警侧✅（2.1.3 原子 claim）；Dify 推送侧在单 worker 下不触发并发（2.1.2 已搁置）。
- 主事务回滚后不产生外部告警。 — **✅ 满足**（2.1.4 commit 先于 dispatch）。
- 有心跳的长调度任务不被接管；失活任务可被记录并安全接管。 — **✅ 满足**（2.2.2 周期心跳 + stale 接管）。
- 初始配置不会自动启动调度。 — **✅ 满足**（2.2.1 模板默认禁用）。
- 非法留存配置不会进入循环。 — **✅ 满足**（2.2.3 batch_size 校验）。

## 3. P1：双模式质控与终末覆盖收口

### 3.1 当前缺口

- `scheduler_daily` 模板引用了不存在或未配置的审计类型；`scheduler_discharge` 只配置 `progress_vs_nursing`。
- `syssvsscbc` 的日增量锚点尚无业务确认。
- `discharge_vs_frontpage` 是否应仅用于出院终末尚未固化到配置。
- `inpatient_date` 已进入内部加载链路，但公开 schema 未覆盖。
- 终末覆盖仍需 Oracle 兼容、删除回滚、重推和真实数据验收。

### 3.2 实施步骤

1. 从运行时 `AuditTypeRegistry` 导出当前有效审计类型，修正模板与实际 code 的不一致。
2. 确认 `syssvsscbc` 日增量策略：昨日手术、昨日术后首次病程，或仅出院终末。未确认前不得启用 daily。
3. 将 `discharge_vs_frontpage` 从 daily 清单移除，除非业务确认有独立在院规则。
4. 让请求 schema、预检和调度内部一致支持 `inpatient_date`，或明确该值只允许内部调度使用。
5. 补齐在院/出院数据集、终末覆盖、删除终末日志清引用、单条/批量重推的自动化测试。
6. 使用真实 Oracle 样本核对每日在院患者、当日文书、当日出院患者全住院期文书数量。

### 3.3 验收

- daily 只处理在院且满足日增量锚点的记录。
- discharge 只处理当天出院患者的完整住院期记录。
- 同患者同住院次同规则的 successful daily 记录会被 successful discharge 结果覆盖。
- 终末日志删除后覆盖引用清空；失败或跳过的终末结果不触发覆盖。

## 4. P1：前置机/H5 闭环与身份策略

### 4.1 已知状态

告警、H5、token、查看记录、反馈及 evidence 摘要已部分落地。企业微信 OAuth 曾导致外链详情页不可访问，当前链路应保持 token 直通，不能在未完成真实手机验证前强制 OAuth。

### 4.2 实施步骤

1. 保持 `/qc-detail/{id}?token=...` 的可用性，先完成真实企业微信浏览器的端到端验收。
2. 确认前置机是否透传 `viewer_userid/viewer_name` query 参数或 `X-WeCom-UserId/X-WeCom-UserName` headers。
3. 若必须 OAuth，先在企业微信后台确认网页授权域名为纯域名、校验文件可访问，并使用真实手机验证 callback；失败时保留 token 绕过作为回退。
4. 补 `mobile_qc`、告警查看、三种反馈、重复提交 409、payload evidence、后台告警列表的自动化测试。 — **✅ mobile_qc 侧已完成**（`tests/test_mobile_qc_api.py` 29 用例：H5 页面 token 校验、详情查看记录、三种反馈+409、verify-token、evidence 提取）。后台告警列表测试待补。终末覆盖测试已补齐（`test_push_log_supersede.py` +7 用例：删除清引用、失败/跳过终末不触发覆盖）。
5. 将 relay secret 只保留加密存储路径，移除模板中的明文字段兼容风险。

### 4.3 验收

- 企业微信消息可稳定打开详情并完成反馈。
- 查看次数、首次/最近查看时间、查看人只在 token 通过后写入。
- 无法获得企业微信身份时功能仍可用，且页面明确采用链接授权模式。
- 前置机/H5/API 的 401、404、409 和超时可以正确呈现。

## 5. P2：Vastbase 接入生产验证与加固

> 执行状态（2026-07-14）：已完成本地加固首版：`batch_size` 范围收敛、`kind_filter` 改为受控文书字段谓词；未连接 Vastbase/Oracle 生产，字段、权限、命中率和回退行为仍待现场验证。

### 实施步骤

1. 在只读生产环境核对 `jhemr.v_blws` 字段、索引、权限、时间字段类型与 `statement_timeout` 行为。
2. 将 `batch_size` 写入模板并进行范围校验。
3. 将 `kind_filter` 改为枚举或受控关键词参数，不允许将可写配置直接拼入 SQL。
4. 补按患者住院次加日期查询、在院患者筛选、文书类型变体和 Oracle 回退的测试。
5. 对病程、首次病程、出院记录各抽样验证命中率；分别验证 Vastbase 正常、空结果和异常回退 Oracle。

### 验收

- 空结果不回退，异常才回退。
- 所有动态 schema/view/字段/过滤条件均受白名单或参数绑定保护。
- 导出内容单元格不超过 Excel 限制，且真实样本可追溯来源。

## 6. P2：多源规则引擎（尚未开始）

### 前置条件

- DBA 确认医嘱、费用、麻醉数据视图、字段、数据量和 SELECT 权限。
- 业务确认规则 DSL 的首批规则、误报容忍度、费用敏感数据权限及规则版本审批人。

### 分阶段实施

1. P0 数据底座：实现 order/fee/anesthesia canonical 契约、受控 SQL、单一示例 audit type 与 loader 测试。
2. P1 规则后端：实现规则 DSL 校验、`QCRuleEngine`、纯规则结论、AI/rule 维度合并、dry-run API 和 `AuditDimensionResult.source` 迁移。
3. P2 前端编辑：审计类型页规则编辑、试运行预览、来源徽章和敏感费用信息展示控制。
4. P3 治理：规则版本、审计、导入导出、命中率/误报率与慢规则监控。

### 验收

- `qc_rules=[]` 时全部既有审计类型行为不变。
- 纯规则模式可以生成可展示、可告警、可反馈的标准结果。
- 正则和时序规则具备超时与数据量保护。
- 规则配置保存前会验证 source、字段、operator、引用和 severity。

## 7. P2：临床准确性与 Dify 输出质量

1. 对每个已启用审计类型抽取经审批的脱敏样本，由临床质控人员标注准确、部分准确、误报、漏报、时间匹配错误或数据问题。
2. 将空 `hcjg` / 空 End 输出标记为解析失败并记录可观测告警，不再将其伪装为正常成功。
3. 出院终末检验逐日 payload 只保留异常检验；检查、病程、护理的保留规则需由临床人员确认。
4. `text_quality` 的阈值和严重度由业务方在 Dify workflow 中确认，不由代码自行降级。

## 8. P3：前端遗留工作

按单页独立迭代，先完成浏览器回归再进入下一页：

1. 患者质控：右侧选中摘要、操作收敛、待反馈统计。
2. 前置机告警：确认是否维持独立页；补右侧摘要和批量操作前必须先有后端能力。
3. 反馈工作台：紧凑指标条、详情锚点、sticky 摘要和固定操作栏。
4. 审计类型：三栏编排控制台和操作菜单收敛。
5. 推送进度：核验现有页面与 API 是否支持完整历史列表；不足时先确认是否新增后端接口。
6. 系统配置、运行总览、调度和手动推送：仅做布局收口，不改变保存、加密、调度或推送语义。
7. 所有页面最终执行浏览器 1366px、768px、390px 回归；不以静态测试替代交互验收。

## 9. 执行顺序

1. 双模式配置和终末覆盖真实数据验收。
2. 调度结果、取消语义与推送/告警幂等。
3. 临床准确性抽检与 Dify workflow 调整。
4. 前置机/H5 身份策略确认及端到端验收。
5. Vastbase 生产验证与 SQL 加固。
6. 规则引擎前置决策后分阶段实施。
7. 前端遗留工作逐页完成。

## 10. 每个工作包的交付要求

- 先更新 `docs/INDEX.md` 的状态和本文件对应章节。
- 代码、迁移、接口、前端、测试和运维说明必须同一工作包同步完成。
- 不访问生产或发送测试消息，除非用户明确授权；企业微信测试仅发送给 `003966`。
- 合并前至少运行聚焦测试、`python -m compileall app tests scripts` 和命名检查；高风险工作包还需全量 pytest。

## 11. 2026-07-14 安全与可靠性实施作业书

> 本节是交给执行 AI 的唯一操作顺序。`reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md` 提供问题证据，本节规定如何修改。二者冲突时先停止并报告，不得自行选择高风险实现。

### 11.1 总体执行控制

#### 11.1.1 开始前必须完成

1. 完整阅读 `AGENTS.md`、`docs/INDEX.md`、101～104 契约、`docs/skills/med-audit-codex.md`、本文和 116 报告。
2. 保存 `git status --short`、`git diff --stat`、当前分支和 HEAD；列出本轮允许修改的文件。不得清理、回滚、覆盖或统一格式化其他人的改动。
3. 建立基线：运行全量 pytest、compileall、命名检查、前端静态检查、全部 JS `node --check` 和 `pip check`。基线失败时先记录既有失败，不得顺手修无关问题。
4. 不连接生产、不保存生产配置、不触发调度、不推送真实患者/Dify/企业微信。部署必须是用户另行明确授权的独立阶段。
5. 每个工作包独立提交或至少独立 diff；前一包未通过验收，不得进入下一包。

#### 11.1.2 禁止事项

- 禁止直接对 `PushLog.source_record_key` 建唯一约束。
- 禁止改变六类审计 code、Dify 输入 `mr_txt` 映射、Builder 输出 `mr_text`、最终 JSON 字段或高危临床门槛。
- 禁止把 Dify/Oracle 不可用纳入容器 liveness 导致容器反复重启。
- 禁止在日志、测试快照或异常响应中写入真实密码、Key、token、患者正文。
- 禁止删除历史字段或旧 API；兼容迁移必须先读旧值、写新值，经过一个发布周期后才能另行清理。
- 禁止在一个提交中同时做认证、PushLog 数据库迁移和调度器重构。

### 11.2 工作包 A：认证 P0 热修

#### 目标

关闭 JWT 默认密钥门禁绕过和默认管理员可重建入口，不改变正常用户、角色、权限和既有非默认管理员登录。

#### 修改文件和步骤

1. `app/auth.py`
   - 新增纯函数解析运行环境，规范化 `ENVIRONMENT`；迁移期可读取 `APP_ENV`，二者同时存在且值不一致时生产启动必须失败并给出不含秘密的错误。
   - 将 `production`、`prod` 视为生产。
   - 生产环境下 JWT Key 缺失、等于 `_DEFAULT_SECRET` 或未达到明确最小熵/长度要求时，在模块初始化阶段失败。
   - 开发/测试允许显式测试 Key；测试不得依赖公开生产默认值。
2. `docker-compose.yml`
   - 显式透传 `ENVIRONMENT=${ENVIRONMENT:-production}`；继续透传 JWT Key，不能在 Compose 中提供公开默认值。
3. `app/database.py`
   - 从 `init_db()` 删除 `_ensure_debug_admin()` 的无条件调用。
   - 暂保函数仅供显式初始化命令复用，或迁移到脚本；不得在应用启动时调用。
4. `app/routers/users.py`
   - 删除 `_ensure_debug_admin_for_login()` 及 login 中的调用。任何登录请求都不得创建账号、角色或提交数据库事务。
5. 新增或修改 `scripts/init_admin.py`
   - 必须由运维显式执行；用户名/密码从交互输入或环境变量取得，密码不回显、不写日志。
   - 强密码校验；账号已存在时默认失败，不自动重置。若仓库已有安全初始化脚本则扩展，不重复创建。
6. `docker_deploy.sh`、部署文档
   - 不再打印 `admin/Admin123456`；首次部署提示显式执行初始化命令。
   - 不在命令行参数中暴露密码。

#### 必测场景

- `ENVIRONMENT=production` + JWT 缺失：启动失败。
- production + 公开默认 Key：启动失败。
- production + 强随机 Key：启动成功。
- development/test + 显式测试 Key：测试可运行。
- `ENVIRONMENT`/`APP_ENV` 冲突：失败，而非静默选一个。
- 数据库不存在 admin 时提交默认用户名/口令：401，且 User/Role 数量不变。
- 已有正常管理员、普通用户、禁用用户的登录行为保持原样；限流仍有效。
- 显式初始化脚本成功一次、重复执行拒绝、弱密码拒绝，输出不含密码。

#### 验收与回滚

- 聚焦认证/用户/数据库初始化测试和全量 pytest 通过。
- 回滚只能回到本包前提交；不得以恢复默认管理员作为生产回滚方案。部署前必须先确认存在至少一个可登录的受控管理员，否则停止部署。

### 11.3 工作包 B：匿名 SSRF 与异常泄露 P0/P1 热修

> **状态：✅ 已完成（本地代码与自动化测试，未部署生产）**。通知测试已要求 `manage_config` 权限，生产默认关闭并支持显式 `NOTIFY_TEST_ENABLED=true`；内置 webhook/SMTP 目标默认拒绝私网、回环、链路本地、多播、保留和未解析地址，可用 `NOTIFY_TEST_ALLOWED_HOSTS` 显式白名单；HTTP 重定向关闭。数据库/驱动异常通过统一 `public_error_message` 脱敏后再返回。自定义内部注册渠道保持兼容，但不属于公开 `NotifyChannel` API 的四种渠道。

#### 修改文件和步骤

1. `app/routers/notify.py`
   - 为 `/api/notify/test` 增加 `get_current_user` 和管理员/配置管理权限依赖。
   - 增加生产开关，默认关闭测试接口；关闭时返回稳定 404 或 403，不回显配置。
2. `app/notifier.py` 或独立安全工具模块
   - webhook 只允许配置中心已保存目标或显式 allowlist。
   - 若必须允许输入 URL：仅 http/https；禁止 userinfo；限制端口；解析所有 A/AAAA 地址，拒绝 loopback、private、link-local、multicast、reserved、unspecified 和云元数据地址；连接前后均校验，重定向默认关闭或逐跳复验。
   - 邮件 SMTP、企业微信、钉钉同样不得接受匿名任意主机。
3. `app/main.py` 和相关路由
   - HTTPException handler 只返回路由提供的稳定业务消息；逐个替换 `detail=str(exc)`。
   - `patients.py`、`patient_qc.py`、`qc_feedback.py`、`audit_types.py` 等数据库异常：日志记录 request_id + `exc_info=True`，响应只给通用错误码。
   - 4xx 业务校验信息可保留，但不得包含 SQL、连接串、表列名、驱动错误或堆栈。

#### 必测场景

- 匿名和普通用户调用通知测试分别为 401/403；管理员在生产开关关闭时不可执行。
- mock DNS 覆盖 127.0.0.1、::1、10/8、172.16/12、192.168/16、169.254/16、metadata hostname、混合公网/私网解析、重定向至内网，全部拒绝。
- allowlist 公网/批准内网中继目标可通过校验，网络发送使用 mock，不发真实请求。
- 模拟 ORA 错误、SQLAlchemy 错误和导出错误，响应不包含 `ORA-`、SELECT、表名、host、用户名；服务端日志含 request_id。

### 11.4 工作包 C：医疗正文日志与秘密返回 P0/P1 热修

> 执行状态（2026-07-14）：已完成本地实现与回归测试，未连接生产、Dify 或企业微信；等待项目负责人确认后进入工作包 D。

#### 修改文件和步骤

1. `app/services/dify_log_utils.py`
   - 删除 `main_input_preview` 和输出正文 preview；默认摘要只保留类型、长度、字段名、目标名、request_id 和不可逆 SHA-256。
   - `full_debug_log` 不得直接恢复原始病历正文；若保留开关，只允许结构元数据或经过测试的脱敏内容。
2. `app/dify_pusher.py` 与日志调用点
   - 确认所有成功、失败、重试、解析失败路径都不拼接 payload/outputs 原文。
3. `app/main.py`
   - audit logger 的级别可配置，但级别变化不能改变隐私规则。
4. `app/routers/config.py`、`app/schemas.py`、相关前端
   - `/api/config/dify/targets` GET 只返回 masked Key 和 `has_secret`，绝不返回解密明文。
   - 保存时空/placeholder 表示保留旧密文；显式清除秘密必须使用单独动作和二次确认，且启用中的 target 不允许无 Key。
   - 保持 `/audit-types` 已有脱敏行为。

#### 必测场景

- 用虚构患者姓名、住院号和病历句子调用日志摘要及 Dify mock，caplog 和临时日志文件中均不得出现原文。
- full_debug_log=true 也不得出现原文。
- GET targets 只含 masked/has_secret；空值更新保留密文；新 Key 可替换；无权限用户不可读取或保存。
- 浏览器保存不因拿不到明文 Key 而清空原密文。

### 11.5 工作包 D：反馈科室权限 P1

> 执行状态（2026-07-14）：已完成本地实现与回归测试，普通用户创建反馈沿用 PushLog 科室可见性，归属和严重度由服务端推导；未连接生产，等待确认进入工作包 E。

#### 修改文件和步骤

1. `app/routers/qc_feedback.py`
   - create 路径先通过与日志列表/详情一致的 `apply_push_log_visibility` 或统一服务检查 PushLog 可见性。
   - `dept_id` 从 PushLog.dept/患者科室映射在服务端推导；普通用户请求体中的 dept_id、severity、assigned_to 不得越权覆盖。
   - 管理员跨科室操作也应留下审计记录。
2. `app/schemas.py`
   - 将仅服务端决定的字段从创建请求移除，或保留兼容但标记 ignored 并计划后续废弃；不得直接造成破坏性 API 变更。

#### 必测场景

- 普通用户对本科技 PushLog 可创建；他科 403；伪造 dept_id 不能改变归属。
- 管理员路径、confirm、update、rectify、view 保持一致。
- 不可见 PushLog 返回 404 或 403 的策略全链路一致，避免通过差异枚举日志 ID。

### 11.6 工作包 E：健康、六类配置与报告兼容 P1/P2

> 执行状态（2026-07-14）：已完成本地实现与回归测试；新增 live/ready 健康探针、builder/source 能力校验及报告旧 ai_result 按 audit_type_code 回退解析。未连接生产，等待确认进入工作包 F。

#### 修改步骤

1. 健康接口
   - 新增最小匿名 `/api/health/live`，只表示进程事件循环可响应；Dockerfile/Compose healthcheck 改用它。
   - `/api/health/ready` 纳入 app DB、业务 DB、启用的 Dify target、daily/discharge job、配置完整性和最近调度状态；详细响应要求运维权限。
   - 保留 `/api/health` 兼容路径，明确其代理 live 或 ready，不能突然破坏现有页面。
2. 六类配置
   - `config/config.json.template` 只保留并完整定义现役六类；调度引用的 code 必须存在。
   - `app/schemas.py`、`audit_type_registry.py` 改为 builder/capability 驱动校验，兼容旧 code 的读取但禁止新保存错误组合。
3. `app/routers/report.py`
   - 旧 ai_result fallback 调用 `parse_dify_structured_output(outputs, audit_type_code=log.audit_type_code)`。
   - 测试回显 high 与正式落库解析一致。

#### 验收

- Dify/Oracle 暂时不可用不会让 liveness 失败；readiness 准确降级并给授权用户原因。
- 六类模板初始化、保存、调度预检全部通过；历史配置仍可加载。
- 报告回退不绕过六类高危兜底。

### 11.7 工作包 F：PushLog 幂等设计门（禁止直接编码）

> 执行状态（2026-07-14 复核修订）：Luna 的 execution/attempt 首版因事务边界、未复核成功状态和 bulk/manual 未接入而撤下，恢复原有跳过策略；设计仍已获业务确认，但必须完成独立事务 claim、全入口接入及 SQLite/Oracle 并发测试后才能重新实施。

本包先产出设计和测试模型，必须由项目负责人确认后才能改 ORM/迁移/执行器。

#### 必须先回答的业务状态表

| 场景 | 期望 |
| --- | --- |
| 同 source/audit/mode 首次执行 | 允许 |
| 首次执行仍 pending/running | 后续执行跳过或附着，不重复调用 Dify |
| 首次 success 且未复核 | `unreviewed_pending` |
| success 已复核且产生新记录版本 | 允许 |
| success 已复核但完全相同版本 | 需业务确认 |
| failed 自动 retry | 复用 execution 还是新 attempt，需明确 |
| manual_override | 谁可操作、是否新 execution，需明确 |
| daily 与 discharge 同患者同文书 | 两个合法 execution，终末成功后 supersede daily |

#### 设计要求

- 区分稳定 `idempotency_key`、一次业务 execution 和多次 attempt；不要把 PushLog 本身强行同时承担三种语义。
- 唯一约束应落在原子 claim/execution 表或可兼容合法重推的组合键上。
- SQLite 与 Oracle 的手工迁移、唯一冲突处理、历史数据回填、NULL/空字符串差异和 `_verify_required_schema()` 同时设计。
- 先写并发失败测试，证明当前 race；再实现使测试通过。
- 需覆盖 serial、bulk、manual、retry、daily、discharge 和 supersede，不得只修一个入口。

#### 停止条件

没有项目负责人对上述状态表的书面确认时，本包状态保持“设计待确认”，Luna 必须停止，不得创建唯一索引或改推送主链路。

### 11.8 工作包 G：调度多进程与留存治理

> 执行状态（2026-07-14 复核修订）：多 worker 一律禁用进程内调度并要求独立 scheduler 进程；retention 使用独立锁和心跳，L3 使用合法 JSON 同步清理多表正文。Oracle 现场留存 SQL 和双实例故障接管仍需专项验收。

1. 保持 Docker 单 worker；启动检测到 workers/实例模式不安全时记录 fatal 或要求 `ENABLE_SCHEDULER=false`。
2. 如需多实例，只有一个明确 scheduler leader 启用 APScheduler；API worker 禁用调度。
3. daily/discharge 继续使用不同业务锁；retention 使用独立 `retention_cleanup` DB 锁和心跳，不能复用 daily 锁。
4. 删除 `_daily_push_job` 前先执行全仓引用扫描并补注册测试，只保留 v2。
5. 留存先形成模型/字段/期限/动作矩阵，经医院数据留存要求确认后实施：PushLog、AuditDimensionResult、QCRecordAlertLog、QCAlertFeedback、QCFeedback、文件日志均列入。
6. L3 到期时维度正文/evidence 与 PushLog 正文同步脱敏；L2 整行删除仍保留。Oracle 空字符串即 NULL，批处理必须保证每轮取得进展。

#### 必测场景

- 两个 scheduler 实例同时触发同名任务，仅一个进入业务体；daily 与 discharge 仍可各自运行。
- 两个 retention 实例仅一个清理；失败释放、失活接管和心跳均可验证。
- SQLite 全量留存测试；Oracle SQL/迁移测试。无 Oracle 环境必须标记“待现场”，不能伪称通过。

### 11.9 工作包 H：可配置 SQL 与 Oracle 超时（独立发布）

> 执行状态（2026-07-14）：已完成本地首版：配置 SQL 校验改为剥离字面量、拒绝多语句/危险语句/普通注释并保留 Oracle hint 兼容；Oracle 查询设置 cursor call timeout 并在异常时 rollback。Oracle 现场驱动验证仍待完成。

1. 先确认业务数据源账号在 Oracle/PostgreSQL/Vastbase 均为数据库级只读；账号非只读时停止上线。
2. 用成熟 parser 验证单一 SELECT/WITH AST；拒绝多语句、DML/DDL、注释绕过、危险函数和未批准 schema/view。动态值继续绑定参数。
3. 不以关键词正则作为唯一边界；保留兼容诊断，避免错误拒绝合法 CTE/UNION 前必须由数据源测试覆盖。
4. Oracle 设置 query/call timeout，不能把 pool acquire timeout 当查询超时；超时后 rollback，并按驱动文档决定是否丢弃连接。
5. 此包涉及三类数据库，必须独立发布和回滚，不与认证热修同批。

### 11.10 每批统一验证命令

```powershell
python -m pytest
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python scripts/frontend_regression_check.py
Get-ChildItem static/scripts -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
pip check
git diff --check
```

任何命令失败都必须报告失败用例、是否为基线既有问题、相关日志和处理决定；不得删测试、放宽断言、加无条件 skip 或吞异常来获得绿色结果。

### 11.11 Luna 每批交付模板

1. 工作包编号与目标。
2. 修改文件及每个函数的行为变化。
3. 未改变的兼容契约。
4. 新增测试及完整测试结果。
5. 数据库迁移、配置迁移和旧数据影响。
6. 安全影响及新增日志是否含敏感信息。
7. 部署前置条件、灰度步骤、监控指标和回滚命令。
8. 未完成事项与需要人工确认的决策。
9. 明确声明是否触碰生产；未授权时必须为“否”。

### 11.12 发布顺序和停止点

1. A 认证热修：部署前必须确认受控管理员初始化方案，否则停止。
2. B SSRF/异常泄露。
3. C 日志/秘密脱敏。
4. D 科室权限。
5. E 健康/配置/报告兼容。
6. F 只做设计；获得书面确认后才实施幂等代码。
7. G 调度/留存。
8. H SQL/Oracle 超时。

每批建议先在测试环境运行至少一个调度周期或等价回放。生产部署、数据库迁移、Dify 更新和企业微信测试均需用户再次明确授权。

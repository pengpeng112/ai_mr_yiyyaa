# 当前系统功能、界面与推送链路复核报告

> 状态：已完成二次独立复核，待项目负责人确认整改范围
> 复核日期：2026-07-14
> 复核方式：本地代码静态审查、全量自动化回归、前端静态回归、生产只读连通性复核
> 复核范围：后端 API、RBAC、数据源、六类 Dify 推送与解析、调度、日志/报告、前置机告警、医生 H5、前端页面、配置、部署与生产运行状态

## 1. 总体结论

当前版本的核心业务代码和自动化回归总体稳定，但暂时不能认定为“所有功能均可正常生产运行”。

主要原因不是单一代码崩溃，而是以下四类未闭环事项同时存在：

1. 六类高危后端安全兜底已经上线，但生产 Dify 两节点提示词是否全部更新、是否输出完整 `extra.issues` 尚未完成联合验收；在此之前，真实高危可能被安全降为 medium/gray，属于可控的漏告警风险。
2. 2026-07-14 复核期间，生产 SSH 可建立 TCP 但不返回 SSH banner，8000 端口可建立 TCP 但 HTTP 返回空响应；因此无法读取当日 09:00 调度结果、推送成功率和容器日志。2026-07-13 21:10 最后一次成功核查时容器、应用数据库、业务 Oracle、调度器均为 healthy/up。
3. 默认管理员、JWT 环境变量错配、匿名通知测试 SSRF、反馈创建跨科室校验、HTTP/Swagger 暴露和病历正文日志预览等生产安全风险仍未关闭。
4. 初始化配置、审计类型校验和两个运维页面仍有明显欠缺，新环境按模板部署不能可靠复现当前生产六类配置。

结论分级：**需整改并完成生产联合验收后，才能确认系统整体正常；当前适合受控内网试运行，不适合扩大访问范围或把高危告警视为已完全验收。**

## 2. 本次实际验证结果

### 2.1 已通过

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| Python 全量测试 | 通过 | `663 passed`，无失败；存在 10 条 Pydantic v2 弃用告警。 |
| Python 编译 | 通过 | `python -m compileall app tests scripts`。 |
| Dify 输入命名守卫 | 通过 | 未发现 Builder 返回 `mr_txt` 或主输入命名漂移。 |
| 前端静态回归 | 通过 | 页面根节点、表格、资源版本、模板表达式、主要功能标记均通过。 |
| JavaScript 语法 | 通过 | `static/scripts/` 下 21 个 JS 文件全部通过 `node --check`。 |
| Python 依赖一致性 | 通过 | `pip check` 未发现破损依赖。 |
| 六类高危后端兜底 | 通过 | 单侧/无证据 high、warn→high、低置信度、非结构化 high 回退均有自动化覆盖。 |
| 合格高危保留 | 通过 | 同一 severe issue、双侧证据、受控安全类别、`confidence>=0.8` 时仍可保留 high。 |
| 告警/H5 自动化 | 通过 | 原子 claim、H5 token、查看记录、反馈和重复提交等已有测试覆盖。 |

### 2.2 只能确认“代码存在”，尚未完成真实环境验收

| 功能 | 当前判断 | 未验收内容 |
| --- | --- | --- |
| Oracle/Vastbase 临床数据加载 | 部分可确认 | 本次未执行真实患者查询；跨库字段、查询量和超时需生产抽样。 |
| 手动推送 | 部分可确认 | 执行器、预检、取消、事务隔离测试通过；本次未调用真实 Dify。 |
| 每日/出院调度 | 部分可确认 | 注册、锁、心跳和历史落库有测试；未取得 2026-07-14 当日运行结果。 |
| 企业微信前置机 | 部分可确认 | 代码和模拟测试通过；未发送真实测试消息。 |
| 医生 H5 | 部分可确认 | 路由和 token 测试通过；未用真实企业微信浏览器验收。 |
| 前端交互 | 部分可确认 | 静态和语法检查通过；未完成 1366/768/390 三分辨率真实浏览器回归。 |
| Dify 六类提示词 | 未验收 | 无法从运行 API 读取 Workflow 提示词版本，需人工在 Dify 确认并回放样本。 |

## 3. 功能模块复核

### 3.1 登录、用户、角色和科室权限

基础 CRUD、菜单权限、角色权限和科室过滤均已实现，并有自动化测试支撑。普通反馈读取路径已有科室权限检查。

但是登录时仍会自动创建调试管理员，生产部署脚本仍公开默认口令；JWT 生产判断读取 `APP_ENV`，主应用和部署脚本使用的是 `ENVIRONMENT`。因此 RBAC 功能“存在”，但认证边界仍不满足医疗数据系统生产要求。

### 3.2 六类质控与 Dify 推送

当前后端已覆盖以下六类：

- `admission_vs_first_progress`
- `discharge_vs_frontpage`
- `surgery_chain`
- `progress_vs_nursing`
- `jyjc_vs_bcnursing`
- `syssvsscbc`

串行推送、批量推送、重推和审计类型测试路径均已传递 `audit_type_code`，高危兜底不会再被批量兼容回退绕过。

当前最重要的运行约束是：后端保留 high 使用**双层复合硬门槛**（`app/services/dify_schema_parser.py` 的 `_qualified_high_risk_issue`），**不是**“仅依赖 `extra.issues`”：

1. **维度级**：`status=fail`、`confidence>=0.8`，且 `medical_evidence` 与 `nursing_evidence` **双方**均为有意义证据；维度码 `other` 一律不触发高危。
2. **issue 级**（同一维度 `extra.issues` 中至少一条）：`level=severe`、`high_eligible=true`、`issue_mode=contradiction`、`source_a`/`source_b` 双方非空且不同、issue 双方 `evidence_a`/`evidence_b` 均有效、issue `confidence>=0.8`，且 `safety_category` 属于该审计类型受控安全类别集合。

两层同时满足才保留 high。如果 Dify 仍使用旧提示词或节点二丢失任一层字段，即使双方确有冲突，也会被降为 medium/gray。这能阻止误告警，但会造成真实高危漏推，因此 Dify 更新和回放是恢复完整告警能力的上线前置条件。

### 3.3 调度和双运行模式

双调度、独立数据库锁、心跳、失活接管、按审计类型隔离失败等实现已存在。`discharge_final` 当前代码包含通用 source 转换逻辑，不再只是三个类型的硬编码分支。

风险点：通用转换依赖 SQL 中存在 `{dept_filter}` 和 Oracle 别名 `a."出院日期"`；不同 backend/source 必须逐类用生产 SQL 验证。配置错误时部分源可能返回空结果而不是显式阻断整个任务。

### 3.4 日志、报告和导出

推送日志、详情、筛选、CSV、报告页、质控反馈导出和导出审计均已实现。日志接口对历史 NULL 有兼容处理。

不足：导航中的“运行日志”页面仍为占位页，运维人员无法在系统界面查看应用日志、Dify 错误和调度错误，只能登录服务器查看挂载日志。

### 3.5 前置机告警和医生 H5

告警已经采用 `pending/failed/sending` 条件更新进行原子 claim，主业务结果先提交再发送，避免事务回滚后仍对外告警。科室过滤、反馈抑制、查看记录和 H5 token 链路均存在。

不足：缺少真实企业微信端到端验收；留存服务也尚未覆盖 `QCRecordAlertLog.payload_json` 和 `QCAlertFeedback`。

### 3.6 前端页面

仪表盘、患者质控、前置机告警、反馈、推送日志、手动推送、推送进度、审计类型、系统配置、调度、健康、Dify 调试和权限管理模板均存在，静态资源依赖为本地 vendor 文件，不依赖公网 CDN。

明确未完成页面：

- Oracle 连接状态：显示“功能建设中”。
- 系统运行日志：显示“功能建设中”。

真实浏览器回归尚未完成，因此不能排除 Element Plus 弹窗层级、表格滚动、移动端抽屉、模板异步加载和浏览器缓存导致的交互问题。

## 4. 阻断性问题

### BLOCK-01：生产实时状态本次无法复核

- 证据：2026-07-14 多次连接中，40022 TCP 成功但无 SSH banner；8000 TCP 成功但 HTTP 请求约 5 秒后返回 empty reply。
- 影响：无法确认当日调度是否完成、是否有 Dify 失败、容器是否健康，也无法确认页面当前是否能打开。
- 建议：运维从服务器本机执行 `docker ps`、`curl http://127.0.0.1:8000/api/health`、`docker logs --since 24h med-audit`，并检查 SSHD、连接限流、防火墙或网络代理。
- 验收：远端健康接口连续 10 次返回 200；SSH 可稳定连接；当日两类调度历史和六类推送统计可查询。

### BLOCK-02：Dify 提示词与后端高危契约尚未联合验收

- 证据：最终提示词文档状态仍为“待 Dify 影子验证”。后端 high **不是**简单“依赖 extra.issues”，而是双层复合硬门槛（见上文 §3.2 / `dify_schema_parser._qualified_high_risk_issue`）：维度级双方证据 + fail/置信度，**且** issue 级 severe/high_eligible/contradiction/双方证据/置信度/受控安全类别。
- 影响：旧 Dify 输出会被安全降级，可能漏掉真实直接安全风险。
- 建议：逐类更新节点一/节点二，使用缺失文书、单侧未提及、一般双侧冲突、合格高危四组样本回放；先关闭外部告警做影子比较。
- 验收：缺失/单侧 high=0；合格双侧高危可保留；JSON 失败不 high；临床专家抽检通过。

### BLOCK-03：生产认证和外部访问安全项未关闭

- 默认管理员不仅会在初始化时创建；`/login` 收到默认用户名和默认口令时，如果账号已删除，还会重新创建管理员账号，构成可重复恢复的默认管理入口：`app/database.py:780-815`、`app/routers/users.py:65-90`、`docker_deploy.sh:129`。
- JWT 生产门禁存在环境变量错配：`auth.py` 使用 `APP_ENV`，主应用/部署使用 `ENVIRONMENT`，Compose 不传递二者。标准 `docker_deploy.sh` 会生成并传入随机 `JWT_SECRET_KEY`，因此不能断言生产必然使用公开默认密钥；但在 JWT Key 缺失或被设为默认值时，生产门禁会因错配而失效，应用可能以公开默认密钥启动。
- `/api/notify/test` 无认证且可发起客户端控制的通知请求，存在匿名 SSRF。
- 服务使用 host 网络，生产 `/docs`、`/redoc` 固定开启，缺少应用侧 TLS 和访问来源限制。
- 建议：生产启动统一读取 `ENVIRONMENT`，缺失/默认 JWT Key 直接失败；彻底删除登录时重建管理员逻辑，首个管理员改为一次性引导或显式初始化命令；匿名通知测试立即下线或加管理员权限和目标白名单。继续按 `docs/系统整体核查与整改计划_20260710.md` 的 P0-01～P0-06 整改；若暂缓，必须形成书面风险接受单。

## 5. 高优先级缺陷与改进项

### P1-01：健康接口可能误报“系统正常”

- 位置：`app/routers/health.py:69-91`。
- 问题：总体状态只计算应用数据库和业务数据库；Dify 固定为 disabled，调度器即使 stopped 也不会影响 overall；且只读取 `daily_push`，不读取 `discharge_push`。
- 影响：Dify 全部不可用或调度器停止时，Docker Healthcheck 和页面顶部仍可能显示 healthy。
- 建议：健康状态区分 liveness/readiness；readiness 纳入启用中的 Dify 目标、daily/discharge 两个 job、配置完整性和最近一次调度结果。

### P1-02：初始化模板不是现役六类生产配置

- 位置：`config/config.json.template`、`app/config.py`。
- 问题：模板仍包含旧 code `lab_exam_vs_progress_nursing`、`frontpage_surgery_diagnosis_vs_first_progress`、`orders_vs_progress`，缺少现役 admission、discharge、surgery；但 scheduler 清单又引用缺失 code。
- 影响：新环境按模板初始化时会忽略审计类型、退回默认类型或产生零推送，无法复现生产。
- 建议：建立唯一六类模板，生产配置去密后反向生成模板测试；调度保存时拒绝不存在或不支持当前运行模式的 code。

### P1-03：现役新 code 绕过部分配置结构校验

- 位置：`app/schemas.py:471-495`、`app/services/audit_type_registry.py`。
- 问题：source/builder/group_key 强校验仍只识别旧 code；新 `jyjc_vs_bcnursing` 和 `syssvsscbc` 不进入对应验证。
- 影响：管理员可能保存缺源、错误 Builder 或错误 group_key 的配置，运行时才表现为空数据或解析异常。
- 建议：将校验迁移到按 Builder/能力声明判断，避免继续硬编码历史 code；为六类分别增加配置保存失败测试。

### P1-04：配置接口返回 Dify 节点明文 API Key

- 位置：`app/routers/config.py:451-468`、`app/schemas.py:276`。
- 问题：具备配置权限的浏览器可读取所有 Dify target 明文 Key。
- 影响：Key 可通过浏览器、代理日志、截图或 XSS 泄露。
- 建议：GET 只返回 masked 值和 `has_secret`；保存时空值保留旧密文，禁止回传明文。

### P1-05：反馈 CRUD 创建路径仍信任客户端科室

- 位置：`app/routers/qc_feedback.py:1163-1189`。
- 问题：创建反馈仅校验 PushLog 存在，直接使用 `request.dept_id`、`severity` 和 `assigned_to`；未从 PushLog 推导科室，也未验证普通用户能否访问该日志。
- 影响：跨科室创建反馈，后续整改可影响 `suppress_ai_push`。
- 建议：从 PushLog/患者科室服务端推导 dept；创建、更新、整改统一调用日志可见性检查；增加跨科室 403 测试。

### P1-06：病历正文仍进入 Dify 审计日志

- 位置：`app/services/dify_log_utils.py:29-45`。
- 问题：摘要函数无条件生成主输入前 300 字预览，`audit.dify` 及 `audit_detail.log` 又被固定设置为 DEBUG；在现有默认日志路径被调用时，该预览会实际落盘，不只是理论上的“可能记录”。
- 影响：挂载日志绕过业务 RBAC，敏感数据长期留存。
- 建议：默认只记录 request_id、长度、SHA-256 和目标名；完整调试需要审批开关、脱敏、短 TTL。

### P1-07：留存范围不完整

- 位置：`app/services/retention_service.py`。
- 问题：已修复 batch_size 和 NULL 文本循环，但仍未清理告警 payload、医生 H5 反馈、QCFeedback 文本和文件日志。`AuditDimensionResult` 的 `medical_content`、`nursing_content`、双方 evidence JSON 等正文列仅在 PushLog 超过 L2 期限后随维度整行删除，在 L3 敏感正文期限到达时不会先行脱敏。
- 影响：医疗和医生反馈数据超过约定期限保留。
- 建议：按数据资产建立完整留存矩阵并为 Oracle/SQLite 增加测试。

### P1-08：生产版本不可追溯

- 证据：当前工作树有大量未提交改动；无 CI 工作流；生产采用热更新后 `docker commit` 固化镜像。
- 影响：无法从 Git commit 精确重建生产镜像，回滚和审计依赖人工备份。
- 建议：整理现有变更为受控 commit/tag；镜像写入 commit SHA、构建时间和配置 schema 版本；禁止把 `docker commit` 作为常规发布方式。

### P1-09：进程内调度器缺少多 worker 启动门禁

- 位置：`app/main.py:101-102`、`app/scheduler.py:137-188`。
- 问题：每个 Uvicorn worker 都会启动一个 `BackgroundScheduler`。当前 Dockerfile 明确使用单 worker，主推送任务也有数据库运行锁，因此现役标准部署并非正在重复写入；但代码没有在多 worker 启动时失败或自动选主。误改启动参数后，多进程会重复注册任务，未获得锁的进程仍会产生连接和日志开销；retention job 还没有同等的跨进程运行锁。
- 建议：保持生产单 worker，并增加启动门禁或显式 scheduler leader 角色；为 retention 增加独立数据库锁。不要仅依赖文档约定。

### P1-10：PushLog 幂等控制存在并发窗口

- 位置：`app/models.py:38-86`、`app/services/push_skip_policy.py:59-71`。
- 问题：PushLog 没有业务幂等键或唯一约束，跳过判断采用“先查询、后写入”。daily/discharge 使用不同运行锁，手工推送、重试和调度也可能并发；两个执行者可能同时判断不存在成功记录并产生重复 PushLog。
- 影响：重复维度、重复告警、统计污染和 supersede 关系不确定。
- 建议：先定义兼容“人工复核后允许重推”的幂等语义，再引入 `execution/idempotency_key` 与唯一约束或原子 claim。不能直接对 `source_record_key` 建唯一约束，否则会破坏合法重推。

### P1-11：部分 HTTPException 透传内部异常

- 位置：`app/main.py:131-139` 及 `patients.py`、`patient_qc.py`、`qc_feedback.py`、`audit_types.py` 中多处 `detail=str(exc)`。
- 问题：统一 HTTPException handler 原样返回 `exc.detail`；部分业务路由把数据库异常直接放入 detail，绕过通用 Exception handler 的对外脱敏。
- 影响：已认证用户可能看到表名、字段名、驱动信息或 SQL 片段。
- 建议：对外只返回稳定错误码和通用消息，详细异常仅写服务端日志并关联 request_id；逐路由清除 `detail=str(exc)`。

### P1-12：匿名通知测试接口形成 SSRF 面

- 位置：`app/routers/notify.py:11-14`、`app/notifier.py:91`。
- 问题：接口无认证，通知渠道配置由请求方提交，webhook 等渠道可访问服务端可达地址。
- 影响：可被用于探测或请求内网服务。该问题同时属于 BLOCK-03，因可直接利用而在整改清单中独立跟踪。
- 建议：立即增加管理员权限；生产默认禁用测试接口；目标执行 DNS/IP 解析后拒绝回环、链路本地、私网和元数据地址，或只允许配置中心已有目标。

### P1-13：可配置 SQL 校验不足以构成安全边界

- 位置：`app/db_client_base.py:34-45`。
- 问题：当前仅校验 SELECT/WITH 开头并以正则扫描部分文本，未可靠处理字符串、注释、CTE、多语句和 UNION 等结构。二次复核所称“把危险词放进字符串即可执行注入”并未由代码直接证明——字符串中的词本身不会成为 SQL 指令；但该实现确实不能作为可靠的只读 SQL 安全解析器。
- 建议：管理权限之外，业务数据源账号必须数据库级只读；拒绝多语句和注释，采用 SQL parser 校验单一查询 AST，并限制允许的 schema/view/function。补 Oracle/PostgreSQL/Vastbase 绕过用例。

## 6. 中低优先级问题

| 编号 | 问题 | 建议 |
| --- | --- | --- |
| P2-01 | Oracle 状态、系统日志两个菜单为占位页。 | 接入已有 `/api/health/oracle` 和受控日志摘要接口，或在未实现前从生产菜单隐藏。 |
| P2-02 | 无真实浏览器自动化，当前前端检查仅验证静态结构。 | 增加 Playwright 登录、菜单、筛选、弹窗、保存、移动端抽屉回归。 |
| P2-03 | Pydantic v2 存在 10 条弃用告警。 | 将 `class Config/from_orm` 迁移为 `ConfigDict/model_validate`，逐步启用 warning 门禁。 |
| P2-04 | 无 `.dockerignore`，无 CI、覆盖率和依赖漏洞扫描。 | 增加构建上下文排除、pytest/前端/依赖扫描/SBOM 流水线。 |
| P2-05 | 依赖中 `cryptography>=42.0.0` 未锁定，基础镜像也缺少 digest 锁定。 | 锁定可复现版本并建立升级窗口。 |
| P2-06 | Dify target GET 回填明文 Key导致前端依赖“取回秘密再保存”。 | 改为 secret placeholder 语义并补部分更新测试。 |
| P2-07 | 当前文档中关于 discharge_final“仅支持三类”的描述已落后于代码通用 fallback。 | 更新 AGENTS/现役文档，并对六类实际 SQL 做验收后再宣称全部支持。 |
| P2-08 | `/api/health` 匿名返回数据库类型、调度和 Dify 状态。匿名 liveness 本身合理，但 readiness 详细信息不宜全部公开。 | 保留最小匿名 `/health/live`，详细 `/health/ready` 和组件诊断要求运维权限。 |
| P2-09 | Oracle 有连接池等待超时，但病历查询未设置数据库调用/statement 超时；Vastbase 已设置 `statement_timeout`。 | 为 Oracle 连接设置 `callTimeout` 或数据库 Resource Manager 限制，超时后明确 rollback/丢弃异常连接并增加慢 SQL 指标。 |
| P2-10 | `report.py:58` 的旧数据回退解析未传 `audit_type_code`。 | 从 PushLog 传入 code，保证报告回显与落库时高危兜底一致，并增加旧数据回显测试。 |
| P2-11 | `scheduler.py:362-535` 的废弃 `_daily_push_job` 无调用方且引用未定义 `db`。 | 确认无外部导入后删除，避免维护人员误调用；删除前补引用扫描/调度注册测试。 |

## 6.1 二次复核意见的独立裁定

| 外部复核项 | 裁定 | 本报告处理 |
| --- | --- | --- |
| BLOCK-02 复合门槛 | 采纳 | 已修正为维度级证据与 issue 级字段的双层复合门槛。 |
| G1 JWT 门禁 | 部分采纳 | 门禁错配属 P0；“生产永远回退默认密钥”不成立，标准部署脚本会生成随机 Key。 |
| G2 默认管理员重建 | 采纳 | 升级 BLOCK-03，强调删除账号后仍可由默认登录请求重建。 |
| G3 多 worker 调度 | 采纳但限定现状 | 作为 P1 部署防误配风险；当前 Dockerfile 单 worker，主任务有 DB 锁，不能描述为现役必然重复写入。 |
| G4 PushLog 并发重复 | 采纳 | 作为 P1；整改应设计幂等键，不能直接用 source_record_key 唯一约束。 |
| G5 异常信息泄露 | 采纳 | 新增 P1。 |
| G6 匿名 SSRF | 采纳 | 保留在阻断项并新增独立 P1 跟踪。 |
| G7 SQL 校验 | 部分采纳 | 安全校验不足成立；“字符串字面量中的危险词会执行”未证实，改按纵深防御整改。 |
| G8 health 匿名 | 采纳 | P2，拆分匿名 liveness 与受控 readiness。 |
| G9 Oracle statement timeout | 采纳 | P2；区别连接池等待超时与 SQL 调用超时。 |
| G10 report 漏 code | 采纳 | P2。 |
| G11 废弃函数 | 采纳 | P2 清理项；函数确无仓库内调用且引用未定义 `db`。 |

## 7. 建议整改顺序

### 第一阶段：恢复可观测性和告警正确性

1. 运维确认生产主机、SSHD、容器和 8000 端口当前状态。
2. 导出 2026-07-14 09:00 调度历史：按六类统计 total/success/failed/skipped/parse_failed。
3. 完成六类 Dify 提示词更新和匿名样本回放。
4. 在不发送企业微信的影子模式下对比原始 high 与后端兜底结果。

### 第二阶段：关闭安全阻断项

1. 统一生产环境变量，修复 JWT 密钥强制启动门禁并增加默认密钥伪造回归测试。
2. 删除初始化和登录路径的默认管理员/默认口令，改为一次性显式初始化。
3. 关闭匿名通知测试 SSRF，增加管理员鉴权和目的地址控制。
4. 修复反馈跨科室创建/整改权限。
5. 停止病历正文日志预览，并补齐敏感字段留存清理。
6. TLS、8000、Swagger 和访问来源限制。
7. 统一异常响应，禁止数据库异常通过 HTTPException detail 返回。

### 第三阶段：配置和界面收口

1. 六类模板和六类配置校验。
2. 健康接口 readiness 重构。
3. Oracle 状态和运行日志页面完成或隐藏。
4. 三分辨率真实浏览器回归。
5. 强化可配置 SQL：数据库只读账号、单查询 AST 校验和跨数据库安全测试。

### 第三阶段补充：并发和调度可靠性

1. 定义 PushLog 合法重推与重复执行的边界，设计幂等键和原子 claim。
2. 增加 daily/discharge/manual/retry 并发测试，证明不会重复告警或污染 supersede。
3. 增加 scheduler 单实例启动门禁或 leader 角色，并为 retention 增加跨进程锁。
4. 为 Oracle 增加查询调用超时和异常连接处置。

### 第四阶段：发布治理

1. 清理并提交当前工作树，建立 release tag。
2. 用 Dockerfile 重建镜像，替代日常 `docker commit`。
3. CI、覆盖率、依赖扫描、SBOM、备份恢复演练。

## 8. 复核验收清单

- [ ] 生产 SSH 和 HTTP 连续稳定，容器 health=healthy。
- [ ] 当日 daily/discharge 调度均有可解释历史记录。
- [ ] 六类 Dify Workflow 版本、提示词、End 输出 key 和 JSON Schema 已登记。
- [ ] 缺失文书和单侧未提及不会 high。
- [ ] 合格双侧直接安全冲突可以保留 high 并生成一条告警。
- [ ] JSON 失败、空输出和兼容回退不会触发 high。
- [ ] 普通用户不能访问或修改其他科室反馈。
- [ ] 未认证通知测试、配置、日志和导出接口均返回 401/403。
- [ ] 页面在 1366px、768px、390px 下完成真实浏览器验收。
- [ ] 生产无默认管理员、默认 JWT、明文 Dify Key 和病历正文日志。
- [ ] 删除管理员账号后，默认用户名/口令登录不能重建任何账号。
- [ ] `ENVIRONMENT=production` 且 JWT Key 缺失或为默认值时，应用启动失败。
- [ ] daily/discharge/manual/retry 并发执行不会产生重复业务推送或重复告警。
- [ ] 多 worker 误配置不会启动多个有效调度执行者，retention 也有跨进程互斥。
- [ ] 数据库内部异常不会通过 API detail 返回。
- [ ] Oracle 长查询可在配置时限内中止并正确释放或废弃连接。
- [ ] 生产镜像可由 Git tag 和锁定依赖重新构建。

## 9. 复核边界

本报告没有执行以下高影响操作：真实患者推送、真实企业微信告警、Dify Workflow 修改、调度手工触发、生产配置保存、数据库写入、密码验证或渗透测试。

因此，本报告对代码和自动化回归结论置信度较高；对 2026-07-14 实时生产运行、真实 Dify 输出质量、Oracle/Vastbase 数据完整性和真实浏览器交互仅能给出“待现场验收”结论。

## 10. 交接给实施 AI 的提示词

```text
你是一名资深 Python/FastAPI 医疗系统工程师和安全审计工程师。请在仓库 F:\python\前后端代码\ai_mrzk 中，严格依据 docs/ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md §11 的顺序和停止点实施整改；docs/reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md 只作为问题证据。两者冲突时停止并报告，不得自行选择高风险实现。

工作约束：
1. 开始前完整阅读 AGENTS.md、docs/INDEX.md、docs/reference/101_FEATURE_BASELINE.md、docs/reference/102_DATA_AND_DIFY_CONTRACTS.md、docs/reference/103_RELAY_AND_MOBILE_CONTRACT.md、docs/reference/104_PORT_AND_ROUTE_MAPPING.md、docs/skills/med-audit-codex.md、docs/ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md 和 116 报告。
2. 当前工作树包含其他人的未提交改动。先执行 git status/diff，禁止覆盖、回滚或格式化无关改动；只修改本次整改必要文件。
3. 直接采用 001 §11 的工作包 A～H，不得重新合并或改序。每阶段独立验证，优先 P0/P1，不要把 P2 清理混进安全热修。
4. 保持六类质控、现有 API 主路径、Oracle/SQLite 兼容、serial/bulk push、daily/discharge、告警/H5、历史数据兼容和现有 JSON 字段不变。不得修改 Dify Workflow 提示词内容；本任务只做后端与部署整改。
5. 不连接或写入生产，不真实推送患者、Dify 或企业微信；完成本地验证后给出部署清单，等待用户明确授权再部署。

第一批（P0 安全热修，必须先完成）：
A. JWT 门禁：auth.py 与系统统一读取 ENVIRONMENT（兼容迁移期 APP_ENV 但冲突时拒绝启动）；ENVIRONMENT=production/prod 且 JWT_SECRET_KEY 缺失、过短或等于公开默认值时必须启动失败。更新 docker-compose 环境透传。增加导入/子进程启动测试，覆盖标准随机 Key 成功、缺失/默认 Key 失败。不要声称现生产必然用了默认 Key。
B. 默认管理员：删除 database.py 启动时无条件创建默认管理员，以及 users.py 登录时通过 admin/Admin123456 重建账号的逻辑；提供显式、一次性的管理员初始化命令或启动参数，要求随机/用户提供强密码，已存在账号不得重置。更新 docker_deploy.sh，不再打印默认口令。测试删除 admin 后默认登录不能重建。
C. 匿名 SSRF：/api/notify/test 增加管理员权限；生产默认关闭测试功能；对 webhook 目标实施 allowlist 或严格地址校验，解析 DNS 后拒绝 loopback、link-local、private、reserved、metadata IP，并考虑 DNS rebinding。测试未认证/普通用户 401/403、内网/回环拒绝、允许目标成功（网络调用 mock）。
D. 立即移除 Dify 日志 main_input_preview/output 正文预览，默认仅记录长度、哈希、request_id、目标和字段名；完整日志开关也不得绕过医疗正文脱敏，除非有明确审批型实现和短 TTL。补日志捕获测试，断言患者姓名/病历片段不出现。

第二批（P1 权限与泄露）：
E. QCFeedback 创建必须先按 PushLog 做可见性/科室权限检查；dept_id 从服务端 PushLog/患者科室推导，不信任请求体；severity、assigned_to 按权限限制。补跨科室 403 和管理员成功测试。
F. 清理各路由 detail=str(exc)；对外使用稳定错误码/通用消息，内部日志保留 request_id 和 exc_info。重点检查 patients.py、patient_qc.py、qc_feedback.py、audit_types.py。补模拟 Oracle/SQL 异常不泄露表名、SQL 和驱动错误的测试。
G. /dify/targets GET 不返回明文 API Key，统一 masked+has_secret；部分保存时空值保留旧密文。保持 /audit-types 已有脱敏语义并补回归。
H. 修复 health：拆分最小匿名 liveness 与详细 readiness；readiness 纳入启用的 Dify、daily/discharge job、配置和最近调度结果，详细组件信息要求运维权限。同步 Docker healthcheck 使用 liveness，避免外部依赖抖动重启容器。
I. 将现役六类配置模板和 schemas/registry 校验统一；按 builder/capability 校验，避免继续硬编码旧 code；不得破坏历史配置读取。

第三批（并发与数据治理，先设计再实现）：
J. PushLog 幂等：本轮只写“同一源首次推送、未复核跳过、复核后合法重推、manual override、retry、daily/discharge supersede”的状态表和设计。禁止直接把 source_record_key 设为唯一；未取得项目负责人对状态表的书面确认，必须停止，不得修改 ORM、迁移或推送执行器。批准后的下一工作包才可设计 execution/idempotency_key、原子 claim、SQLite/Oracle 手工迁移、_verify_required_schema 和并发测试。
K. 调度：保持 Docker 单 worker；增加多 worker 防误配门禁或 scheduler leader 机制；daily/discharge 保持不同业务锁；retention 增加独立跨进程锁。测试两个调度器实例只有一个执行 retention，同名 push job 只有一个进入业务执行。
L. 留存：建立字段级矩阵；L3 到期清理 PushLog 正文时同步清理 AuditDimensionResult 的 medical_content、nursing_content、evidence JSON、extra 中敏感证据，以及 QCRecordAlertLog.payload_json、QCAlertFeedback、QCFeedback 文本和轮转文件日志。明确法规/医院要求后再定天数，SQLite/Oracle 均测试，避免 NULL/批处理死循环。
M. 可配置 SQL：业务数据库账号保持只读；拒绝多语句和注释，使用可靠 SQL parser 验证单一 SELECT/WITH AST，并限制 schema/view/function。覆盖 Oracle/PostgreSQL/Vastbase 的 CTE、UNION、注释、字符串、分号和危险函数测试。不要把简单关键字正则当成唯一安全边界。
N. Oracle 查询超时：区分连接池 acquire timeout 与 SQL call timeout；设置 cx_Oracle/oracledb callTimeout 或等效数据库限制，超时后 rollback 并按驱动规则丢弃异常连接。补 mock/集成测试。

第四批（兼容与清理）：
O. report.py 旧 ai_result 回退调用传入 log.audit_type_code，验证回显 severity 与落库兜底一致。
P. 确认全仓无引用后删除 scheduler.py 的废弃 _daily_push_job；不要删除 _daily_push_job_v2。
Q. 完成或隐藏 Oracle 状态、运行日志占位菜单；真实日志页面只能显示脱敏摘要并受运维权限控制。

验证要求：
- python -m pytest（全量必须通过）
- python -m compileall app tests scripts
- python scripts/check_naming_convention.py
- python scripts/frontend_regression_check.py
- static/scripts 下所有 JS 执行 node --check
- pip check
- 新增安全测试、并发测试、SQLite/Oracle 迁移测试；若 Oracle 集成环境不可用，明确列为待现场验收，不能伪称通过。
- 最终按“修改文件、行为变化、兼容性、测试结果、未完成/现场验收、部署与回滚步骤”报告。同步更新 docs/INDEX.md 和现役计划；不要新建重复总结文档。
```

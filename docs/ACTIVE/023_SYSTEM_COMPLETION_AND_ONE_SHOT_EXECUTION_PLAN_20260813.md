# 023 — Med-Audit 系统未完成功能、完善项与一体化执行计划

> 文档编号：023  
> 制定日期：2026-08-13（Asia/Shanghai）  
> 状态：**唯一执行入口；本地 P0 整改、自动化测试与生产 Stage 0 只读基线已完成；按医疗历史整改门禁暂停在候选范围/脱敏方案复核；未授权生产写入、真实 Dify/Relay、历史补跑、默认入口切换或 Git 推送**  
> 总负责人：Codex 主代理（统一拆解、复核、合并、测试、发布门禁与最终验收）  
> 协作方式：Luna 负责受控子任务实现/复核，Codex 对每个 diff、契约、测试结果和生产动作承担最终责任  
> 依据：当前工作树、`docs/INDEX.md`、ACTIVE 001–022、reference 101–116、项目契约、三路 Luna 只读审计和本轮独立基线测试  
> 目标：项目负责人确认范围后，在不跳过医疗数据安全与生产门禁的前提下，以一个连续执行主线完成获批的本地整改、自动化测试、镜像构建、canary、现场验收、回滚演练与文档收口

---

## 0. 总裁定

### 0.1 一句话结论

系统的认证、RBAC、六类质控主链路、PushExecution/PushAttempt 幂等、双调度锁、历史重跑框架、Relay/H5、留存清理和 UI Next 主体已经存在。审计初始发现的 4 类发布阻断为：

1. Dify 解析失败和 Relay 失败路径仍可能把医疗原文/响应正文写入日志或 `last_error`。
2. `config/config.json.template` 含过期审计类型和大量 `??` 损坏 SQL，新环境不能可靠复现正式六类配置。
3. 最新 UI 改动后的 Playwright 基线为 **38 passed / 8 failed / 8 skipped**，且 `static/ui-next` 累积历史 hash 文件，与最新构建产物不一致。
4. 017/WP6 四角色真实 canary、六类 Dify 影子回放、Oracle/Vastbase 连续观察、Relay/H5 实发、历史整改/补跑仍缺现场证据或人工批准。

截至 2026-08-13 本轮执行检查点，前 3 类本地阻断已经关闭：外部响应/Push 运行日志已脱敏，正式六类安全模板与闭包校验已落地，Playwright 为 **46 passed / 0 failed / 11 expected skipped**，`static/ui-next` 与 `dist` 均为 110 个 asset 且入口 hash 一致。第 4 类现场/人工事项仍是发布阻断，不能由本地测试替代。

因此当前状态应定义为：

| 维度 | 当前裁定 |
| --- | --- |
| 本地后端核心功能 | 本轮获批的隐私、权限、模板、环境和 Pydantic 整改已完成；Python 3.11/本机全量回归通过 |
| UI Next | 本地主体、E2E 和安全镜像同步已通过；真实四角色 canary 仍未获批/未执行 |
| 生产双源 | 已有生产启用与单轮证据；7 个业务日/14 天连续观察未关闭 |
| Dify 高危准确性 | 后端硬门槛已存在；六类工作流影子回放与临床抽检未关闭 |
| Relay/H5 | 代码和模拟测试存在；真实前置机/企业微信闭环未验收 |
| 历史补跑/高危整改 | 工具链和计划存在；未经精确清单、dry-run 与书面批准禁止写生产 |
| 发布工程 | 已增 CI、`.dockerignore`、基础镜像 digest 与依赖 pin；Docker daemon 不可用，正式镜像构建/离线复现/SBOM/签名未关闭 |
| 默认入口 | 生产继续 `legacy`；WP7 不满足 |

### 0.2 “一次性执行完成”的准确含义

本计划获批后，Codex 将把所有**已授权且无需新外部决策**的本地代码、测试、构建、文档和部署准备工作作为一个连续主线执行，不再逐个小改反复询问。

但以下事项不能被“一次性”解释为绕过医疗系统门禁：

- 7 个业务日/14 天观察不能压缩成单次测试。
- 尚未生成的历史整改精确 ID 清单不能预先授权写库。
- 真实 Dify、Relay、调度触发、历史补跑、生产配置保存和默认入口切换必须在对应门禁满足后执行。
- 外部 AI 意见只能形成候选，不等于数据库写入授权。
- 生产失败、权限越界、`load_failed > 0`、重复当前结果或 PHI 泄露时必须停止扩大范围。

### 0.3 与 022 隔离演示计划的边界

`022_ISOLATED_12_DEPARTMENT_INTERACTIVE_DEMO_PLAN_20260813.md` 是独立 SQLite/合成数据/Mock Dify/Mock Relay 的演示专项；本 023 是主系统安全、功能、数据、UI、发布和生产验收的总收口计划。

- 023 不重复实现 022 的 demo lifecycle、12 科室 seed 和演示录屏。
- 023 会先修复 demo/旧初始化脚本的生产安全边界，这些是 022 的前置依赖。
- 若两份计划都获批，先完成 023 的 P0 本地阻断，再按 022 自身 Gate 执行隔离演示。
- 022 的合成环境通过不等于 023 的生产 canary、Dify、Relay 或临床验收通过。

### 0.4 唯一执行入口与旧 ACTIVE 文档定位

自本计划生效起，`docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` 是本项目唯一的综合执行入口、阶段排序依据和最终验收清单。任何 AI、Luna 或人工执行者不得依据其他 ACTIVE 文档自行并行启动工作包；其他文档只能提供下表所列的证据、契约、交接或专项门禁。

| 文档范围 | 当前定位 | 执行规则 |
| --- | --- | --- |
| 001–012 | 历史计划、设计门和专项整改证据 | 不再作为独立执行入口；其仍有效的约束、测试和门禁由 023 对应 WP 引用，冲突时以代码、配置、测试和 023 当前裁定为准。 |
| 013–016 | 盘点、交叉复核、已完成工作包和交接证据 | 仅用于追溯状态、证据和红线；不得从其中单独发起生产动作。 |
| 017–019 | UI Next 架构、迁移和设计专项目录 | 仅作为 WP3/WP11 的前端证据和验收来源；不授权入口切换、legacy 退役或写操作。 |
| 020–021 | WP6 阻塞报告和 UI Next 复核包 | 仅作为当前缺陷、阻塞条件和复核证据；020 的 BLOCKED 状态继续有效，021 不单独授权 Stage B。 |
| 022 | 独立 12 科室合成/Mock 演示专项 | 仅在 023 WP0/P1 安全边界通过后，按 022 自身 Gate 执行；不与 023 并行改变生产。 |
| 023 | **唯一综合执行主线** | 所有本地整改、测试、构建、只读核查、canary、历史和生产阶段均须登记到本计划阶段表，并满足本计划审批栏。 |

旧 ACTIVE 文件不得因仍保留在 `docs/ACTIVE/` 而被解释为“同时获批”。未归档不等于可并行执行；完成后应先把结论合并至 023/INDEX，再按文档治理规则归档。

### 0.5 本轮推荐默认决策（已批准的计划治理范围）

本轮用户指令批准以下**计划治理和默认裁定**，Luna 可据此进行文档收口、本地实现、自动化测试和生产只读准备；该批准不扩大为生产 DML、配置保存、外部消息或历史写入授权：

| 决策 | 本轮默认值 | 状态/限制 |
| --- | --- | --- |
| D1 auditor 反馈权限 | 允许 `create_feedback`；整改、审批、关闭、删除仍需对应权限 | 已作为 WP1 默认；产品另行书面决定可覆盖。 |
| D2 UI 发布 | 先 Stage A，默认入口继续 `legacy`；Stage B 单独审批 | 已批准执行顺序；不代表 canary 已通过。 |
| D3 生产动作 | 先完成本地实现、自动化测试和生产只读；任何写入按精确清单另批 | 已批准；不允许“全部执行”泛化授权。 |
| D4 多源规则引擎 | 独立立项，不阻塞本轮系统收口 | 已批准暂缓。 |
| D5 历史 high/补跑 | 先只读基线、脱敏候选、dry-run；未生成精确 ID/hash 前不写库 | 已批准；继续保持禁止写入。 |
| D6 Relay 实发 | 仅批准测试接收人 + 合成/脱敏记录 | 已批准范围；真实患者批量实发禁止。 |
| D7 Git | 允许本地整理/提交准备；默认不 push、不建 PR | 已批准默认；提交动作仍须负责人另行确认。 |
| D8 Oracle/配置 | 允许生产只读核查；DDL、DML、配置保存另批 | 已批准；密钥、配置和 schema 不得泛化变更。 |

### 0.6 阶段状态与证据总表

以下是本轮唯一汇总清单。`未执行`、`阻塞`、`待人工`和`仅本地`不得写成完成；每次阶段推进必须补齐“证据/报告”栏后再进入下一阶段。

| 阶段 | 范围 | 当前状态 | 证据/报告 | 前置依赖 | 写入授权 |
| --- | --- | --- | --- | --- | --- |
| WP0 | 基线、dirty tree、配置/镜像事实、文档唯一入口 | **本轮完成** | 023 §1.2、§11；生产配置/image hash 已只读登记 | 无 | 仅本地文件/测试 |
| WP1 | 隐私、认证、反馈权限、demo fail-closed、健康错误 | **本轮本地范围完成**；四角色现场验收待 WP11 | 1117 项 pytest；权限/隐私/环境聚焦测试 | WP0 | 无生产写入 |
| WP2 | 六类正式模板、Registry、运行时校验 | **本轮本地范围完成** | 六类模板重建、closure/runtime/template tests；生产配置只读核对为六类 | WP0、脱敏六类配置 | 生产配置保存另批 |
| WP3 | UI Next E2E、021 补丁、静态产物清理 | **本轮本地范围完成**；canary 仍阻塞 | 46 pass / 0 fail / 11 expected skip；110/110 assets、入口 hash 一致 | WP0、前端修复 | 不切默认入口 |
| WP4 | API/schema/SQL/并发/兼容性 | **本轮获批范围完成**；Oracle 现场压测仍待 | Pydantic v2 项目 warning 清零；全量测试 | WP1/WP2 | 无生产写入 |
| WP5 | Oracle/Vastbase、双源、Dify shadow、临床质量 | Stage 0 生产只读完成；shadow/临床/连续观察未完成 | 023 §11 聚合基线；011/012/005 | DBA/临床/业务 | 只读/影子，需逐项批准 |
| WP6 | Relay/企业微信/H5/告警闭环 | 未完成；020 相关真实 canary 阻塞 | 001、020、103/104 | 测试接收人、地址、脱敏数据 | 仅批准测试接收人 |
| WP7 | 历史 high、科室回填、历史补跑 | **Stage 0 只读完成，按 skill 强制停点**；未写生产 | 2082 个 high PushLog 联集、3331 个 high/red 维度；科室缺失聚合见 §11 | WP5 稳定、候选范围确认、脱敏包、dry-run、批准单 | 精确 ID/hash/范围另批 |
| WP8 | 多源规则引擎 | 已批准暂缓 | 001 §6、023 §8 | 产品/DBA 立项 | 不纳入本轮 |
| WP9 | CI、供应链、镜像、监控、备份恢复 | 部分完成 | CI、`.dockerignore`、digest、依赖 pin 已落地；Docker daemon 不可用，镜像/SBOM/签名/恢复待补 | WP3/WP4 | 发布另批 |
| WP10 | 全量测试、独立复核、缺陷清零 | **本地矩阵完成** | 后端 1117、前端 50 unit、E2E 0 fail、构建/命名/依赖检查通过；Luna 三路 + Codex 主审 | WP1–WP9 对应阶段 | 无生产写入 |
| WP11 | Stage A、观察、Stage B、文档归档 | 未开始；Stage A 前置缺失 | 017–021、023 §11 | WP10、人工批准 | Stage A/B 均逐项批准 |

---

## 1. 审计范围、方法与可信边界

### 1.1 已审计范围

- 文档：`docs/INDEX.md`、`docs/ACTIVE/*.md`、`docs/reference/*.md`、项目 skill 与部署文档。
- 后端：`app/`、`scripts/`、`tests/`、配置模板、数据库手工迁移、Oracle/PostgreSQL/Vastbase/Dify/Relay/调度/导出链路。
- 前端：Vue 3 UI Next、legacy 静态页面、路由、RBAC、API 契约、响应式、可访问性、Playwright、构建与静态同步。
- 运维：Dockerfile、Compose、部署脚本、依赖、日志、健康探针、备份/回滚、生产/canary 门禁。

### 1.2 本轮已执行的只读/本地验证

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| Python 3.11 `python -m pytest -q` | PASS | 独立 venv 全量通过；目标运行时复核完成 |
| 本机 `python -m pytest -q` | PASS | 1117 tests collected；全量通过；仅 Python 3.14 sqlite3 adapter 的第三方弃用 warning |
| `python -m compileall -q app tests scripts` | PASS | Python 语法/编译通过 |
| `python scripts/check_naming_convention.py` | PASS | 未发现 Builder 输出 `mr_txt` 漂移 |
| `python -m pip check` | PASS | 本机环境依赖关系无破损 |
| `npm run typecheck` | PASS | Vue/TypeScript 类型检查通过 |
| `npm run test:unit` | PASS | 14 files / 50 tests |
| `npm run build` + 安全镜像同步测试 | PASS | `dist/assets` 与 `static/ui-next/assets` 均 110；入口 SHA-256 一致；Windows 使用已校验目标的 `robocopy /MIR` |
| `npm run test:e2e` | PASS | 57 项：46 passed / 0 failed / 11 expected skipped；真实 canary 用例因未提供授权环境而按设计跳过 |
| `docker build -t med-audit:023-local .` | 环境阻塞 | Docker Desktop daemon 未运行；Dockerfile 静态复核完成，但未生成镜像，不得宣称容器验收通过 |
| 生产 Stage 0 只读基线 | PASS/已停点 | 容器单 worker、六类配置和历史聚合已核；未写库、未调 Dify、未触发调度、未发 Relay，详见 §11 |

### 1.3 基线限制

1. Python 3.11 已在独立 venv 全量复核；Docker daemon 不可用，因此容器构建、Oracle Client 动态库和空 volume 首启仍不能声明通过。
2. 本轮已按批准范围连接生产执行只读聚合；没有调用 Dify、触发调度、发送 Relay/企业微信、保存配置或写数据库。
3. 当前工作树有大量用户未提交改动；它们均被视为在途成果，不允许清理、回退或用旧分支覆盖。
4. `frontend/dist` 已通过受控镜像脚本同步到 `static/ui-next`；目标边界和 stale asset 删除均有自动化测试。
5. 文档含多个时间层次，结论必须按“当前代码 > 后写时间线 > INDEX 当前裁定 > 旧计划早期描述”排序。

---

## 2. 当前功能完成度矩阵

| 模块 | 已具备 | 尚未关闭 | 级别 |
| --- | --- | --- | --- |
| 认证/JWT | 生产强密钥门禁、默认管理员运行时重建移除、显式 `init_admin`、环境别名统一、demo fail-closed | Cookie/CSP 与四角色现场验收未落地 | P1/现场 |
| RBAC/科室 | 用户/角色/权限/菜单/科室、患者可见性、QCFeedback 写权限矩阵 | 四角色实机未验；产品另授 auditor 权限时需更新矩阵 | 现场 |
| 六类质控 | Registry、Builder、Dify、结果映射、高危硬门槛、当前结果替代、正式六类安全模板/闭包 | 六类生产 Workflow/SQL/JSONPath/临床准确性未联合验收 | P0 现场 |
| 数据源 | Oracle/PostgreSQL/Vastbase、双源 adapter/loader、fail-closed、超时；模板不再携带损坏 SQL | DBA 执行计划、键例外、p95/p99、连续观察未关闭 | P0/P1 现场 |
| 推送/幂等 | serial/bulk、PushExecution/Attempt、success-only 当前唯一索引、skip reason | SQLite/Oracle 深度并发压测和全部入口现场验证待完成 | P1 |
| 调度 | daily/discharge 独立锁、心跳、retention 锁、多 worker 禁用 | 六类真实 SQL 模式验收、`syssvsscbc` daily 锚点、生产连续运行证据待完成 | P0/P1 |
| 历史重跑 | preview、持久批次、attempt、current replacement、门禁 | 生产批次未获批；历史 high 整改需脱敏外审+本地规则+临床批准 | P0 |
| Relay/H5 | HMAC、claim、科室过滤、token、查看、反馈、重复 409；失败响应已改安全摘要 | 真实接收人、手机、前置机、反向代理未验收 | P0/P1 现场 |
| 日志/报告/导出 | 外部响应/Push 运行日志已脱敏；匿名 health 最小化；日志 CSV、患者 Excel、反馈 CSV/Excel、ExportAuditLog | 告警页无专用导出；筛选/导出字段需完全对齐 | P1 |
| 留存 | 当前代码覆盖 PushLog、维度、告警 payload、H5/QC 反馈 | Oracle LOB、实际定时作业、审计结果和恢复验证待生产确认 | P1 |
| UI Next | 15 个路由、主页面、入口开关、mock/unit/build、E2E 0 fail、安全静态镜像 | 真实后端/四角色/长数据/WCAG/canary 未验 | P0 现场 |
| 发布/运维 | 单 worker、非 root、healthcheck、资源限制、回滚文档、CI、`.dockerignore`、基础镜像 digest | Docker daemon 未运行；SBOM/签名、离线制品/统一发布入口缺失 | P1/P2 |
| 多源规则引擎 | 有方案和 `orders_progress_stub` 占位 | canonical order/fee/anesthesia、DSL、engine、API、UI、版本治理未实现 | P2/产品立项 |

---

## 3. 待整改问题清单

### 3.1 P0：本地发布阻断

| ID | 问题与证据 | 影响 | 完成判定 |
| --- | --- | --- | --- |
| P0-01 | `dify_pusher.py` JSON 失败记录 `raw_value[:200]`；`dify_schema_parser.py` 记录 `raw_text[:200]`；`relay_alert_service.py` 记录/保存 `resp.text` | 患者姓名、病历、诊断或证据可能进入挂载日志/错误字段 | 日志只含长度、hash、状态、错误码、request_id；PHI caplog 回归通过 |
| P0-02 | `config/config.json.template` 只有 5 类，含旧 code、`orders_progress_stub` 和大段 `??` SQL；scheduler 引用集合也不闭合 | 新部署“启动成功但业务零数据/运行时报错” | 模板与正式能力闭包一致；无 `??`；空配置初始化、SQL/JSONPath/调度引用校验通过 |
| P0-03 | QCFeedback 创建/更新/整改等写接口主要依赖登录与科室检查，未全面绑定 `create_feedback/edit_feedback/approve_qc` 等 permission | 有账号但无业务权限的用户可能直接调用写 API | 权限 + 数据范围双门禁；四角色正反用例全绿 |
| P0-04 | `scripts/init_rbac.py`、`scripts/quick_start.py` 有固定演示账号/密码；`DEMO_MODE` 缺生产 fail-closed | 误运行可创建可预测账号；误启 demo 可暴露真实库数据 | production 拒绝 demo/旧脚本；演示数据只允许显式隔离模式；默认密码扫描通过 |
| P0-05 | Playwright 38/8/8；患者摘要产生选择器歧义，工作台 `.event-item` 契约漂移，独立详情文案/行为漂移 | 021 的旧 46-pass 证据已过期，UI 不能进入 canary | 修业务语义和稳定可访问选择器，不靠放宽断言；三视口 0 fail |
| P0-06 | `static/ui-next/assets` 406 文件，最新 `dist/assets` 85 文件；两份入口引用不同 hash；同步脚本只复制不清理 | 浏览器加载旧 chunk、线上版本不可辨认 | 安全镜像式同步/manifest 清理；目标只含当前产物；入口/build id/hash 一致 |
| P0-07 | 020 缺 canary 地址、四角色凭据、测试科室和脱敏长数据；patient-qc 权限补丁未纳入正式镜像验收 | 自动化通过也不能证明真实 RBAC/Oracle NULL/长数据 | 四角色×三视口×真后端矩阵通过并留脱敏证据 |
| P0-08 | 六类 Dify 影子回放、output key/JSONPath、合格 high 保留、临床抽检未完成 | 真实高危可能安全降级造成漏告警，或旧 workflow 输出不合约 | 六类 shadow + 后端门槛 + 临床双审达到阈值 |
| P0-09 | 011 历史 FAIL 被 012 双源切换缓解，但 7 业务日/14 天连续证据尚未闭环 | 不能证明 ORA-12609、源失败和关系差异已经稳定消失 | 连续观察无 ORA-12609/timeout/required source failure/重复当前 |

本表保留审计初始证据。当前关闭状态：P0-01 至 P0-06 已在本地完成并通过自动化复核；P0-07 至 P0-09 仍开放，必须由真实 canary、六类影子/临床抽检和连续观察关闭。详细证据见 §11。

### 3.2 P1：近期完整性、安全与运维完善

| ID | 改进项 | 目标 |
| --- | --- | --- |
| P1-01 | 统一 `ENVIRONMENT`/`APP_ENV` 解析，覆盖 CORS、docs、demo、scheduler 等 | 冲突时启动失败；`production/prod` 统一；生产无 wildcard CORS |
| P1-02 | 匿名 `/api/health` 收口 | `/live` 最小匿名；`/ready`/深诊断鉴权；外部不返回 ORA/IP/端口/SQL/驱动原文 |
| P1-03 | 前端 JWT 从 localStorage 迁移 | HttpOnly + Secure + SameSite Cookie；CSRF 防护；CSP；兼容期 Bearer 可控退役 |
| P1-04 | 告警导出与筛选契约 | 新增告警导出并调用 `record_export_audit()`；日志/患者/反馈/告警列表与导出过滤完全一致 |
| P1-05 | Pydantic v2 迁移 | `ConfigDict`/`model_validate`；清除项目自身弃用警告；为未来 Pydantic 3 做门禁 |
| P1-06 | 可配置 SQL 安全 | DB 账号只读 + 单语句 AST/白名单校验 + 注释/CTE/UNION/危险函数跨库测试 |
| P1-07 | Push/调度/retention 压测 | SQLite/Oracle 并发 claim、租约接管、双锁、retention 单实例、故障恢复可证明 |
| P1-08 | UI Next 功能对称性 | 患者质控报文详情、独立详情认证/打印、长数据、空/错/NULL、WCAG 人工验收 |
| P1-09 | 可观测性 | 请求错误率、Dify 延迟/parse、调度 funnel、Relay、磁盘、前端异常、SLO/告警 |
| P1-10 | 发布可复现 | Git tag→固定依赖→镜像→配置 schema 可追溯；停止把热复制/`docker commit` 作为正式唯一发布 |

### 3.3 P2：长期能力与技术债

- 多源规则引擎：order/fee/anesthesia canonical、DSL、`QCRuleEngine`、dry-run、规则 UI、版本/审批/导入导出、命中率与慢规则监控。
- 大数据量分页与性能：反馈/统计 SQL 下推、索引与执行计划、前端虚拟化或合理分页。
- 前端体积：Element Plus/ECharts 进一步按页拆分，设置 gzip/brotli budget。
- 供应链：CI、覆盖率、漏洞扫描、SBOM、镜像签名、基础镜像 digest、依赖升级窗口。
- 备份恢复：SQLite/Oracle/配置/日志的自动备份校验与隔离恢复演练。
- 文档治理：合并重复 004，纠正 002/007/008/009 顶部状态，按当前证据更新 001/011/012/017/020/021。

---

## 4. 执行总原则与红线

1. 保留用户所有未提交改动；动手前记录 `git status`、HEAD、diff stat 和目标文件清单。
2. Builder 继续输出 `mr_text`；只有 `dify_pusher.py` 映射 Dify `mr_txt`。
3. daily/discharge 继续使用不同 DB 锁；生产继续单 worker。
4. 不把 Oracle/Vastbase/Dify/Relay 失败纳入 liveness，避免容器重启风暴。
5. 新 ORM 字段必须同步 SQLite/Oracle 手工迁移和 `_verify_required_schema()`。
6. 不覆盖生产加密 secret；部分更新保持“空值保留旧密文”。
7. 不用本地 3 类 `config.json` 覆盖生产 6 类配置；先做脱敏快照和 hash。
8. 不删除 legacy、旧视图、旧 SQL 或历史结果；回滚能力至少保留两个发布周期。
9. 不在日志、截图、文档、测试 fixture、外部 AI 包中放患者标识、姓名、原始正文或密钥。
10. 不直接对宽泛 WHERE 做历史 UPDATE；所有历史写入按批准 ID 清单、optimistic check、小批事务执行。
11. 不以反复 rerun 掩盖 flaky E2E；必须解释每个失败根因。
12. 不自动 commit/push/建 PR，除非项目负责人在复核时明确授权。

---

## 5. 一体化工作包

## WP0 — 冻结基线、统一事实源与执行清单

### 目标

在任何修改前建立可回退、可对照的本地/生产事实基线，消除旧文档相互矛盾。

### 步骤

1. 记录分支、HEAD、dirty files、untracked files、diff stat；生成本轮允许修改清单。
2. 记录 Python/Node/npm/Java/Oracle Client 版本和 Docker 构建环境。
3. 重跑 §1.2 基线并保存机器可读摘要；单独记录当前 E2E 8 fail。
4. 若获生产只读授权：记录容器、镜像 digest、启动时间、单 worker、volume、配置 SHA-256、六类 code、调度列表、锁状态和最近历史。
5. 生成“代码已实现 / 自动化已通过 / 已部署 / 生产已验收”四态矩阵，禁止再用单一“完成”混写。
6. 后续结论以 023 为当前执行主线；旧 ACTIVE 只作专项证据。

### 交付

- 基线报告、允许修改清单、风险清单、回滚点。
- 所有凭据仅走环境变量/秘密存储，不进入报告。

### 门禁

- 工作树范围不清、生产镜像无法识别或配置无法备份时，不进入生产阶段；本地修复仍可继续。

---

## WP1 — 隐私、认证、反馈权限与错误边界

### 目标

关闭 P0-01/P0-03/P0-04 和运行环境错配，不改变正常业务角色的数据范围。

### 实施项

1. Dify/Relay 日志：
   - 删除 `raw_value/raw_text/resp.text` 截断输出。
   - 建立统一 `safe_external_error_summary()`：状态码、长度、短 SHA-256、错误类型、request/run ID。
   - `QCRecordAlertLog.last_error` 只保存受控错误码/通用消息，不保存外部正文。
2. QCFeedback 权限：
   - 创建绑定 `create_feedback`。
   - 编辑/分配/状态流转绑定 `edit_feedback`。
   - 审批/关闭/删除绑定 `approve_qc` 或专门 permission。
   - 整改提交允许获授权临床角色，但仍受本人/本科室/assigned_to 约束。
   - 所有写路径保留科室可见性、服务端 dept 推导、合法状态机和审计日志。
3. Demo/初始化安全（完整隔离演示仍由 022 实施）：
   - `production/prod` 下 `DEMO_MODE=true` 启动失败。
   - demo 路由不得在误启时暴露生产真实表。
   - `init_rbac.py`/`quick_start.py` 生产拒绝，固定密码移除；显式隔离模式才可创建演示用户。
4. 环境解析：
   - 提取统一环境解析函数，auth/config/main/CORS/docs/demo/scheduler 共用。
   - `ENVIRONMENT`/`APP_ENV` 冲突直接失败。
5. 健康与错误：
   - `/live` 只返回进程状态、时间、版本。
   - `/ready` 和详细诊断要求运维权限。
   - 匿名兼容 `/api/health` 不回显异常原文、IP、端口、SQL 或驱动路径。

### 预计修改范围

`app/dify_pusher.py`、`app/services/dify_schema_parser.py`、`app/services/relay_alert_service.py`、`app/routers/qc_feedback.py`、`app/routers/health.py`、`app/main.py`、`app/auth.py`、`app/config.py`、`app/routers/demo.py`、`scripts/init_rbac.py`、`scripts/quick_start.py`、对应 tests。

### 验收

- 包含患者姓名/病历片段的模拟错误不进入任何 logger、`last_error` 或 HTTP response。
- 四角色 × permission × 本科/跨科 × 状态流转正反矩阵通过。
- 生产 demo/固定密码脚本 fail-closed。
- `production/prod` CORS wildcard 均被拒绝；环境冲突启动失败。
- Docker healthcheck 继续只调用 `/api/health/live`。

---

## WP2 — 正式六类配置模板、Registry 与运行时校验

### 目标

让全新部署、配置保存和调度注册在执行前就能发现损坏/过期配置，避免静默零数据。

### 实施项

1. 以生产脱敏六类快照、当前 Registry 和正式 code 为依据，建立唯一审计类型清单：
   - `admission_vs_first_progress`
   - `discharge_vs_frontpage`
   - `surgery_chain`
   - `progress_vs_nursing`
   - `jyjc_vs_bcnursing`
   - `syssvsscbc`
2. 从模板删除/迁移旧 code：`lab_exam_vs_progress_nursing`、`frontpage_surgery_diagnosis_vs_first_progress`、未实现的 `orders_vs_progress` 不得伪装成正式能力。
3. 清除全部 `??`/乱码 SQL。无法获得真实 SQL 时，必须让该类型默认 disabled 并返回明确配置错误，不能放占位 SQL。
4. 新增配置闭包校验：
   - scheduler code 必须存在且 enabled/capability 合法。
   - builder 必须已注册。
   - source role、required、group_key、date_dimension 合法。
   - SQL 单语句只读，必需 placeholder/bind 存在且无未知 placeholder。
   - JSONPath 以 `$` 开头且可解析。
   - Dify target/secret 使用 masked + has_secret 语义。
   - `progress_nursing_multi_source` 与 source_flags 组合一致，混合 flag fail-closed。
5. 从“空目录/空配置”启动测试，证明模板不会创建不可运行的默认调度。
6. 更新 runtime summary/readiness，使错误定位到 section/code/source，而不是泛化 500。

### 数据安全

- 不复制生产密钥、患者数据或连接密码。
- 不以本地 3 类配置覆盖生产。
- 生产配置迁移采用备份→解析→diff→保存→重载验证；任何 secret 解密失败立即回滚。

### 验收

- 模板扫描无 `??`、明文 key、旧正式 code 漂移。
- 六类 code/builder/source/scheduler 闭包测试通过。
- 非法 SQL/JSONPath/flag 保存返回稳定 422，不写坏配置。
- 原有生产配置可无损读取，未提供 secret 时旧密文保留。

---

## WP3 — UI Next 回归修复、功能补齐与静态产物治理

### 目标

修复当前 8 个 E2E 失败，并把 021 的新增 UI 能力纳入自动化门禁和可复现静态交付。

### 实施项

1. 患者质控：
   - 为列表行、右侧摘要和详情建立唯一语义区域/accessible name/test id。
   - 验证选中态在分页、筛选、刷新、空结果和响应式切换后正确。
   - 补报文/响应对称展示时继续复用详情权限，不扩大 PHI 可见范围。
2. 工作台：
   - 统一高风险事件 DOM 契约，使用原生 button、稳定 class 和包含业务上下文的 `aria-label`。
   - 修正 mock，使“有事件/空事件/API 失败”三种状态均有测试。
   - 验证 ECharts init/dispose/resize、0 尺寸重试上限和路由离开资源释放。
3. 质控记录：
   - 明确“独立详情”与“推送详情（JSON）”是两个动作还是一个动作；按产品裁定统一文案、菜单 role 和行为。
   - 测试 `window.open(..., '_blank', 'noopener...')`、认证、打印和 popup blocked。
   - Payload Tab 对非法 JSON、空值、超长值、clipboard fallback 有测试。
4. 导出：
   - 日志 CSV 的 severity/status/date/dept/audit_type/current 等过滤与列表完全对齐。
   - 新增告警记录导出 API/UI，必须 permission + `record_export_audit()`。
   - 患者/反馈/告警导出覆盖 0 条、NULL、分页无关、跨科室 403。
5. 静态同步：
   - 修改 `sync-static.mjs` 为安全 mirror：先解析并验证 `dist` 和目标绝对路径都在仓库指定目录，再删除目标中不在 manifest 的旧 hash 文件。
   - 不对 workspace root 或未解析变量做递归删除。
   - 生成 build manifest（commit、构建时间、入口 hash、文件数、SHA-256）。
   - 入口 HTML `no-store`，hash assets 长缓存 immutable。
6. 增加 Workbench/Payload/PatientQc 组件测试、三视口 E2E 与 accessibility smoke。

### 验收

- `npm run typecheck`、50+ unit、组件测试、54+ E2E 均 0 fail。
- `static/ui-next` 与 `dist` manifest 一致，无孤儿 hash，入口引用存在。
- 1366×768、768×1024、390×844 无不可达按钮、横向页面溢出、重复 accessible name 或焦点陷阱。
- 不修改默认入口；本地和 Stage A 仍 `legacy`。

---

## WP4 — 后端契约、兼容性与技术债收口

### 目标

在不改变六类临床语义的前提下，完成 API、schema、SQL 安全和并发兼容性治理。

### 实施项

1. 将 `schemas.py` 的 class Config/from_orm 迁移为 Pydantic v2 `ConfigDict/model_validate`。
2. 统一外部错误码与 request_id；业务校验保留稳定英文 detail，内部异常只进安全日志。
3. 可配置 SQL 增加单语句 AST/受控 schema/view/function 校验；数据库账号继续只读，parser 不是唯一安全边界。
4. 对 PushExecution/Attempt、success current 唯一索引、manual/retry/daily/discharge/historical 入口做并发测试。
5. 对 scheduler 两把锁、retention 独立锁、心跳、stale takeover、取消和重启恢复做双实例测试。
6. QCFeedback 列表/统计由内存分页改为 DB 分页/聚合（若当前路径仍存在），保留 Oracle/SQLite 方言兼容。
7. 清理确认无调用的死代码/占位路由；Oracle 状态/运行日志要么实现受控摘要，要么保持隐藏并返回明确 404/501。
8. 新导出/报告路径全部纳入 ExportAuditLog；测试审计失败不吞掉主要导出成功/失败语义。

### 验收

- Python 3.11 容器全量 pytest 通过，项目自身 Pydantic warning 清零。
- SQLite 并发测试和 Oracle 集成/模拟测试通过。
- SQL 安全绕过集覆盖分号、注释、CTE、UNION、字符串字面量、危险函数和跨 schema。
- 不改变 `reviewed_flag/manual_override/skip_reason/current/supersede` 既有语义。

---

## WP5 — Oracle/Vastbase、双模式、六类 Dify 与临床质量闭环

### 目标

把“代码存在/单轮成功”提升为“六类在真实环境可解释、稳定、准确”。

### 阶段 A：只读数据与 SQL 验证

1. 保存生产六类配置、镜像、SQL hash、mapping/relation/schema version。
2. DBA 复核 15/16/17 号查询：字段、权限、索引、统计、执行计划、p50/p95/p99、重复执行行数。
3. 复核 `patient_id + visit_number`、稳定 record ID、时间半开区间、三 `mr_class`、`caption_date_time`、护理 572/709 双时间。
4. 六类逐一验证 daily/discharge：候选、源行数、bundle、skip、parse、contract、qc_usable、current、alert。
5. `syssvsscbc` daily 锚点未获业务确认前不得启用；通用 discharge fallback 只有真实 SQL 验证后才能写入 AGENTS/INDEX 为“支持”。

### 阶段 B：Dify 影子

1. 在新/影子 Workflow 导入 110–115，不直接覆盖生产。
2. 每类覆盖：缺文书、单侧未提及、一般冲突、合格直接安全冲突、空输出、非法 JSON、低置信度。
3. 校验 input `mr_txt` 字符串、output key、response JSONPath、固定维度、extra.issues、后端复合 high 门槛。
4. `alert_policy=suppress`；不发企业微信。
5. 临床双审输出准确/部分准确/误报/漏报/时间错误/数据问题，并登记 prompt/workflow 版本。

### 阶段 C：连续观察

1. 双源正常 daily/discharge 至少观察 7 个业务日；生产总体稳定观察 14 天。
2. 指标：ORA-12609、Vastbase timeout、required source failure、query batch、bundle、parse/contract、重复当前、self-supersede、重复告警。
3. 任何未解释数量/关系边差异、p95 超阈值或错误码复现，停止扩大并回滚配置/镜像。

### 验收门槛

- 键非空率 100%，稳定 ID 重复 0，required source failure 0。
- p95 低于调用超时的 1/3，且无无界全文扫描。
- 合格 high 可保留；缺失/单侧/解析失败 high=0。
- 六类 SchedulerHistory 与 PushLog 数量可解释，daily/discharge 不互相抢锁。

---

## WP6 — Relay、企业微信、医生 H5 与告警闭环

### 目标

证明从 high 结论到接收人、H5 查看和反馈的真实链路安全可用。

### 实施与验收

1. 先只读核对 `base_url/endpoint/detail_page/severity_levels/alert_dept_filter/receiver_rules`，不回显 secret。
2. 使用合成/获批测试记录和唯一批准接收人；禁止真实患者批量实发。
3. 验证 HMAC、时间戳、重放拒绝、无重定向、超时、非 2xx 安全摘要、重试/死信/claim。
4. 验证 `alert_dept_filter` 同时匹配 code/name；空列表=全部；`dept_filtered` 不是发送成功。
5. 真实手机验证 detail URL、token、查看次数/身份、401/404/409、三类反馈、重复提交。
6. 失败不能回滚主 PushLog success；已发送事实永久保留。
7. 新增告警列表/详情/重试/导出自动化和生产脱敏证据。

### 停止条件

- 无前置机/Relay 书面批准、无测试接收人、无法证明合成/脱敏数据时，不执行真实发送。

---

## WP7 — 历史 high/red 安全整改、科室补全与历史补跑

> 本工作包强制遵守 `med-audit-history-remediation` skill。它不能被普通批处理步骤替代。

本工作包每完成一个阶段都必须输出报告并停止；除非项目负责人在同一条书面指令中明确批准后续的**指定阶段**。尚未生成精确 ID、before hash 和目标等级的生产写入不能提前授权。

### 阶段 0：只读基线

- 从生产容器内应用库统计 PushLog 顶层与维度层 high/red 并集、类型、时间、解析/复核/告警状态。
- 盘点 evidence 数组、content、extra.issues 路径；重算现行形式门槛，只输出聚合。
- 统计 `PushLog.dept` 和 `request_json.patient_info` 科室缺失；V_QYBR 按 `患者ID + 次数` 统计重复键。
- 输出范围、排除项和风险；不写库。

### 阶段 1–2：脱敏外部复核与本地二次裁决

- 仅外发随机 review_token、类型、维度、最小脱敏双方证据、门槛布尔项；ID 映射和原文留内网。
- 每类只加载 skill 内对应的六类 prompt snapshot，并与当前 110–115 对照；无法脱敏或证据不足转人工。
- 外部 AI 返回只允许 keep_high/downgrade_medium/downgrade_low/manual_review。
- 本地依次执行后端硬门槛、semantic shadow、对应临床提示词规则；AI 意见不直接写库。
- 生成 keep/downgrade/manual/reject 四张精确清单。

### 阶段 3–4：dry-run 与分批写入

- before 快照、SHA-256、批准单、run_id、optimistic check。
- 维度变更后用生产聚合逻辑重算 Conclusion/PushLog 和派生策略；禁止统一设 low。
- 已发送告警事实不删不改不重发；pending/failed 仅在有审计化 suppression 设计时处理。
- 每批最多 100 条维度，每批独立事务和回查；任一数量/聚合异常立即停止。
- **精确 ID/目标等级未生成前，项目负责人不能预先批准该写入集合。**

### 阶段 5：科室回填

- 只按 `PushLog.patient_id + visit_number` ↔ `V_QYBR."患者ID" + "次数"`。
- 只补空值；非空冲突、无匹配、多义、缺键全部不更新。
- 真实字段使用“所在科室/出院科室/入院科室”，禁止不存在的“在院科室”列。
- 修改 `request_json.patient_info` 时保留其他 JSON 键和值。

### 阶段 6：历史补跑

- 仅在 WP5 稳定门禁通过后执行 preview。
- 必须 `load_failed=0`、identity/contract/current/alert 门禁通过，项目负责人批准日期、类型、科室、上限、alert policy。
- 先小批，再按日期扩大；每批 manifest、attempt、对账、回滚点完整。

---

## WP8 — 多源规则引擎（需项目负责人决定是否纳入本轮）

### 推荐裁定

默认将其作为独立产品工作包，不阻塞当前生产安全、UI Next 与六类质控收口。若项目负责人确认本轮必须一起完成，则开始前必须提供首批规则、数据视图、字段、权限、误报容忍度和审批人。

### 分阶段实现

1. 数据底座：order/fee/anesthesia canonical contract、受控只读 SQL、样本 audit type、loader fixture。
2. 规则 DSL：字段/operator/source/引用/severity/schema 校验，正则和时序超时/数据量保护。
3. `QCRuleEngine`：纯规则结果、AI+rule 合并、`AuditDimensionResult.source` 迁移、dry-run API。
4. UI：规则编辑、测试、命中预览、来源徽章、敏感费用权限。
5. 治理：版本、审批、审计、导入导出、回滚、命中率/误报率/慢规则。

### 验收

- `qc_rules=[]` 时既有六类行为零变化。
- 纯规则结果可展示、告警、反馈、导出并可追溯版本。
- 不允许 UI 直接拼接任意 SQL；费用敏感字段按权限最小化。

---

## WP9 — CI、供应链、镜像、监控与备份恢复

### 实施项

1. 新增 `.dockerignore`，排除 `.git`、测试结果、缓存、日志、数据、配置备份、secret、node_modules、dist 临时物等。
2. 固定 Python/Node 基础镜像 digest；锁定可复现依赖，`cryptography` 等不再无上限漂移。
3. 提供院内 npm cache/registry 方案，隔离环境 `npm ci --offline` 必须通过。
4. 建立 CI：Python 3.11、compile、pytest、命名、前端 type/unit/build/E2E、依赖扫描、secret scan、SBOM、镜像扫描。
5. 设置测试/包体/warning 门禁；禁止以跳过失败测试合并。
6. 统一唯一正式发布入口：Compose/脚本的网络、env、health、volume、entry、rollback 语义一致。
7. 镜像写入 commit SHA、build time、schema/config version、frontend build id；生成 checksum 和发布 manifest。
8. 监控应用错误率、Dify latency/parse、Oracle/Vastbase timeout、scheduler funnel、Relay、磁盘/日志、前端异常。
9. 备份配置、SQLite/Oracle 应用数据、日志审计；在隔离环境演练恢复并校验 SHA-256。

### 验收

- 从 Git tag 和锁定制品离线重建与目标镜像文件 hash 一致。
- 正式发布不依赖 `docker cp`/`docker commit`。
- 回滚演练能恢复旧镜像+旧配置且保留数据表向后兼容。

---

## WP10 — 统一测试、独立复核与缺陷清零

### 本地全量矩阵

```powershell
python -m compileall -q app tests scripts
python -m pytest -q
python scripts/check_naming_convention.py
python scripts/frontend_regression_check.py
python scripts/wp6_local_matrix.py
python -m pip check

Set-Location frontend
npm ci --offline
npm run typecheck
npm run test:unit
npm run build:docker
npm run test:e2e
```

### 容器矩阵

- Docker/Python 3.11 全量 pytest。
- 生产 multi-stage build、非 root、Oracle Client 动态库、单 worker、liveness。
- 空 volume 首次启动、SQLite/Oracle 应用库 schema 自检、配置从模板初始化。
- legacy `/`、`/ui-next/`、H5、报告、独立详情均可访问且路由不互相拦截。

### 缺陷处理规则

1. 每个失败必须归类：代码缺陷、测试过期、环境缺失、现场阻塞。
2. 测试过期只能在确认产品契约后修改，不得因 UI 实现不同而盲目放宽断言。
3. 新发现 P0 必须修复并重跑全量；P1/P2 只有项目负责人明确接受风险才可延期。
4. Codex 对 Luna 产出的每个 diff 做逐文件复核、红线 grep、测试复现和反向用例检查。

---

## WP11 — Stage A canary、连续观察、Stage B 与文档收口

### Stage A（默认入口仍 legacy）

1. 用正式 Dockerfile/发布 manifest 构建并部署 canary 镜像。
2. `UI_DEFAULT_ENTRY=legacy`；`/ui-next/` 并行；legacy 不删除。
3. 四角色逐页、三视口、真实 API、401/403/409/422/429、NULL/长数据、Network diff、导出审计。
4. 高风险写页单独开关；Dify/调度/Relay 真实写必须使用本计划对应批准范围。
5. 验证回滚脚本、镜像、配置备份、schema 向后兼容。
6. 观察至少 7 个业务日；数据链路总体观察达到 14 天。

### Stage B（默认入口切换）

只有以下全部满足才可请求单独确认：

- WP1–WP10 完成且无开放 P0。
- Stage A 四角色真实矩阵通过。
- 7 业务日无阻断缺陷，14 天数据链路指标稳定。
- 回滚演练通过。
- 产品负责人签字默认首页、菜单文案、auditor 权限。
- 项目负责人书面批准 `UI_DEFAULT_ENTRY=ui-next`。

切换后 `/index.html`/明确 legacy 回退至少保留两个发布周期；不在同一发布删除 legacy 源码。

### 文档收口

1. 把最终事实合并回 001/011/012/017 和 reference 契约。
2. 更新 020/021 的实际测试与 canary 结论。
3. 合并并归档重复 004、被替代交接/复核计划；不新建重复会话总结。
4. 同步 `docs/INDEX.md` 编号、状态、路径、更新时间。
5. 更新 AGENTS 中 discharge 六类支持描述时，必须先有六类真实 SQL 验收证据。

---

## 6. 工作包依赖与 Codex/Luna 分工

```text
WP0 基线冻结
 ├─ WP1 安全/权限 ─┐
 ├─ WP2 配置闭包 ─┤
 ├─ WP3 UI/E2E ───┤→ WP10 全量清零 → WP11 Stage A/观察/Stage B
 ├─ WP4 后端契约 ─┤
 └─ WP9 发布工程 ─┘

WP2 + WP4 → WP5 数据/Dify → WP6 Relay/H5 → WP7 历史整改/补跑
WP8 规则引擎为产品决策分支，不默认阻塞上述主线
```

分工：

| 角色 | 职责 |
| --- | --- |
| Codex | 确认范围、契约裁定、任务拆解、冲突处理、代码总审、测试总审、生产门禁、最终报告 |
| Luna-Backend | WP1/WP2/WP4 的受控实现与聚焦测试，不独立触发生产 |
| Luna-Frontend | WP3 的页面、测试和静态产物修复，不自行切入口 |
| Luna-Ops/Review | WP5/WP9/WP10 的只读核查、构建/回滚验证、文档交叉检查 |
| DBA/运维 | SQL plan、权限、索引/统计、备份、窗口、容器与网络证据 |
| 临床/质控 | 高危、Dify、历史整改和规则引擎的医学语义批准 |
| 项目负责人 | 产品决策、生产批准、历史精确写入清单、Stage B |

---

## 7. 统一停止条件

任一出现即停止对应生产/扩容阶段并回滚到上一个已验证点：

1. 日志、HTTP response、截图或外部包出现患者标识、姓名、正文或密钥。
2. production 使用默认/弱 JWT 或 SECRET_KEY，或 demo/默认账号可用。
3. 四角色发生越权、跨科室读取/写入或菜单与 API 权限不一致。
4. `load_failed > 0`、required source failure、ORA-12609、Vastbase timeout 或 SQL 计划失控。
5. `mr_text/mr_txt`、维度 code、JSONPath、高危硬门槛或 current/supersede 语义漂移。
6. 重复 Dify 调用、重复当前结果、self-supersede、重复真实告警。
7. E2E/pytest/构建失败或依赖离线不可复现。
8. 配置备份、镜像、回滚脚本或 before 快照不可验证。
9. 历史写入目标与批准 ID/hash 不一致或出现并发冲突。
10. 观察期指标不稳定或出现无法解释的数量/关系差异。

---

## 8. 最终 Definition of Done

只有以下全部成立，才可把本计划标记完成：

- 所有获批 P0/P1 代码与文档项完成；未纳入的 P2 有书面延期决定。
- Python 3.11 容器与本地全量测试通过；前端 E2E 0 fail。
- 正式六类模板/生产配置闭包、Dify shadow、Oracle/Vastbase、双模式和 Relay/H5 验收完成。
- 历史整改/补跑若纳入，严格按精确批准清单完成并可回滚；未纳入则保持禁止状态且不谎称完成。
- Stage A 至少 7 业务日、数据链路 14 天观察通过；Stage B 只有书面批准后实施。
- 正式镜像可由 Git tag 和锁定制品重建，备份恢复/回滚演练通过。
- 导出、写操作、配置、历史变更和外部消息均有审计记录。
- INDEX、现役契约、部署文档与实际代码/生产状态一致；重复计划已归档。
- 最终交付报告包含：修改文件、行为变化、迁移、测试计数、现场证据、风险接受、镜像/config hash、回滚、未完成项（应为 0 或书面延期）。

---

## 9. 项目负责人复核时必须确认的决策

本轮用户指令已批准下表的**推荐默认值作为计划治理基线**。这只批准执行顺序、默认裁定和本地/只读范围；生产写入、外部消息和历史结果变更仍必须满足 §9.1 的精确清单审批，不能由“采用推荐”推导出来。

| 决策 | 推荐默认 | 影响 |
| --- | --- | --- |
| D1 auditor 反馈权限 | 允许 `create_feedback`；不允许整改/审批/关闭/删除，除非另授 | 决定 WP1 permission 矩阵 |
| D2 UI 发布 | 先 Stage A，门禁通过后再单独批 Stage B | 防止 E2E/权限问题影响默认入口 |
| D3 生产动作 | 本次批准先覆盖本地实现与生产只读；写操作按精确清单再批 | 防止泛化授权生产 DML/消息 |
| D4 多源规则引擎 | 独立立项，不阻塞本轮收口 | 缺业务规则/数据视图时无法安全“一次完成” |
| D5 历史 high/补跑 | 先只读基线与脱敏候选；精确 ID/目标生成后再批写入 | 符合医疗整改 skill 强制停点 |
| D6 Relay 实发 | 仅批准测试接收人 + 合成/脱敏记录 | 禁止真实患者批量消息 |
| D7 Git | 允许整理 commit/tag，但默认不 push/不建 PR | 决定发布可追溯方式 |
| D8 Oracle/配置 | 允许生产只读核查；DDL/DML/配置保存另批 | 保护生产数据和 secret |

### 9.1 生产、外部调用与历史写入精确审批清单

下表是本计划唯一有效的动作授权表。未明确列为“本轮默认允许”的动作均为 `NOT_APPROVED`；即使代码、测试或演示环境已经通过，也不能扩大到生产。

| 动作 | 当前状态 | 允许范围 | 继续执行所需精确批准/证据 |
| --- | --- | --- | --- |
| 本地代码、测试、文档、构建准备 | `APPROVED` | 当前工作树内，保留既有脏改动；仅修改本次明确文件 | Codex/Luna 逐 diff 复核，聚焦测试和全量测试；不自动 push。 |
| 生产只读核查 | `APPROVED` | health/ready、配置脱敏快照、镜像/容器、SchedulerHistory、聚合计数、SQL plan；不输出密钥/PHI | 受控凭据、命令清单、脱敏证据和回滚点；不得夹带写操作。 |
| Stage A UI Next 部署/canary | `NOT_APPROVED` | 仅在 020 缺失项补齐后可申请；默认入口仍 `legacy` | `CANARY_BASE_URL`、四角色凭据、测试科室、脱敏长数据、镜像 digest、回滚命令、负责人批准单。 |
| Stage B 默认入口切换 | `NOT_APPROVED` | 不得改 `UI_DEFAULT_ENTRY=ui-next` | Stage A 四角色/三视口通过、至少 7 个业务日观察、回滚演练、产品负责人和项目负责人书面批准。 |
| Dify 真实调用/Workflow 更新 | `NOT_APPROVED` | 只允许新/影子 Workflow 和获批脱敏样本 | Dify 管理员、临床/质控负责人批准；列出 Workflow、版本、样本数、output key、JSONPath、回滚版本。 |
| 调度触发、真实推送、真实 Relay/企业微信 | `NOT_APPROVED` | 仅可在专项批准中列明的测试患者/合成记录和测试接收人 | 环境、审计类型、日期、数量上限、`alert_policy`、接收人、窗口、停止/回滚条件、批准单。 |
| 生产配置保存、DDL/DML、索引/迁移 | `NOT_APPROVED` | 当前仅备份、解析、diff 和只读校验 | 具体环境、表/配置键、变更前 hash、变更脚本、影响范围、备份、回滚、DBA 与项目负责人批准。 |
| 历史 high/red 降级、科室回填 | `NOT_APPROVED` | 先生成脱敏候选、精确 ID 和 before hash；不得宽范围 UPDATE | `run_id`、`PushLog/Dimension/Conclusion/Alert/Feedback` 精确 ID、目标值、optimistic check、批量上限、批准人和回滚方案。 |
| 历史补跑/重推 | `NOT_APPROVED` | 先 preview；不得跨日期、跨类型、跨科室扩展 | 日期、audit type、run mode、科室、候选/排除规则、`load_failed=0`、manifest hash、批次上限、告警策略、批准单。 |
| Git commit/tag | `APPROVED`（本地） | 可整理本地可追溯提交 | 不得 `push`/建 PR；提交前保存 dirty tree、diff stat 和文件清单。 |

历史写入批准单至少必须包含：`environment`、`run_id`、`audit_type_code`、`run_mode`、日期闭区间、科室/患者范围、精确记录 ID、before hash、目标字段/等级、最大批量、并发限制、`alert_policy`、外发开关、操作者、审批人、备份位置、回滚命令和停止条件。缺一项即保持 `NOT_APPROVED`。

---

## 10. 批准后的执行指令格式

项目负责人可使用以下格式批准，避免范围歧义：

```text
批准执行 docs/ACTIVE/023。
D1=采用推荐；D2=采用推荐；D3=本地实现+生产只读；D4=暂缓；
D5=只读基线/脱敏候选，不批准写库；D6=不实发；D7=允许本地 commit，不 push；
D8=允许生产只读，不允许 DDL/DML/配置保存。
Codex 总负责，调用 Luna 实施；完成全部获批本地工作、测试、镜像与只读验收后一次性交付报告。
```

若要同时授权特定生产阶段，必须明确写出环境、类型、日期/科室、数量上限、alert policy、测试接收人、回滚点和批准单；不得只写“全部执行”。

---

## 11. 2026-08-13 执行检查点与 Stage 0 只读报告

### 11.1 Luna 执行与 Codex 主审结论

本轮按用户要求启用三路 Luna，分别负责后端安全/权限、前端/E2E/静态产物、文档/运维交叉复核。Codex 对共享工作树逐文件复核并继续修订；Luna 结论不直接作为生产授权。

| 工作域 | 已完成实现 | Codex 主审补充 |
| --- | --- | --- |
| 后端安全 | Dify/解析器/Relay 外部响应改为 type、size、hash 等安全摘要；QCFeedback 写权限落到 create/edit/approve/view；匿名 health 最小化；环境配置统一 | 继续发现并修复 serial/bulk/async/supersede 的患者 ID 日志；旧诊断脚本去固定患者号、正文输出和 SSH `AutoAddPolicy` |
| 正式六类 | 新增六类能力契约与模板重建脚本；模板六类全部默认禁用且不携带 secret/生产 SQL；Registry/runtime 校验闭包 | 明确“启用但空 SQL”只允许受管 Vastbase，否则 fail-closed；旧 builder 仅保留读兼容，不回写旧 code |
| 前端 | 修复 Workbench 可访问名称和 E2E 契约；新增安全镜像同步与测试 | Windows 首次清理暴露 Node 原生删除崩溃后，改为目标边界校验 + `robocopy /MIR`；最终 110/110 asset 和入口 hash 一致 |
| 兼容/供应链 | Pydantic v2 迁移；CI、`.dockerignore`、Python/Node image digest、`cryptography` pin | CI 排除需要 Oracle Client 构建环境的 `cx_Oracle`，应用镜像仍按 Dockerfile 单独安装 8.3.0；Docker daemon 不可用项明确保留为阻塞 |

### 11.2 自动化验收结果

| 矩阵 | 最终结果 |
| --- | --- |
| Python 3.11 独立环境 | 全量 pytest PASS；FastAPI 0.115.6、SQLAlchemy 2.0.36、Pydantic 2.10.3、pytest 8.3.5、cx_Oracle 8.3.0 |
| 本机 Python | 1117 项 pytest PASS；compileall、命名约定、pip check PASS |
| 前端 unit/type | 14 files / 50 tests PASS；typecheck PASS |
| 前端浏览器 | 46 passed / 0 failed / 11 expected skipped；真实 canary 场景没有授权地址/角色凭据，未伪造执行 |
| 构建/静态镜像 | 前端 build PASS；`dist/assets=110`、`static/ui-next/assets=110`，两个 index SHA-256 一致；安全同步自测 PASS |
| Docker 镜像 | 未完成：本机 Docker Desktop daemon 不可连接；没有镜像 digest、容器首启或 Oracle 动态库运行证据 |

### 11.3 生产 Stage 0 只读基线

执行严格使用已登记 SSH host key 和只读 SQL/容器检查。生产保持原状态：没有复制代码、保存配置、DDL/DML、Dify 调用、调度触发、Relay/企业微信发送或历史补跑。

| 项目 | 只读事实 |
| --- | --- |
| 容器/进程 | `med-audit` healthy；镜像 `sha256:4ee08a…`；单个 Python 3.11 uvicorn 进程，`--workers 1` |
| 配置 | `APP_DB_TYPE=oracle`；生产配置 SHA-256 `2cfd5322…`；六个正式 code 均存在 |
| 调度 | legacy disabled；daily enabled（4 类）；discharge enabled（6 类）。其中 discharge 含 3 个尚无 `discharge_final` SQL 转换的类型，继续列为现场 P0，不做自动配置保存 |
| high/red 联集 | 顶层 high PushLog 1916；维度 high 对应 PushLog 2082；联集 2082 个 PushLog；high/red 维度 3331 条；日期范围 2026-01-01 至 2026-08-11 |
| 类型分布 | admission 1998、discharge 38、jyjc 38、surgery 8；本次联集中 progress/syss 为 0 |
| 硬门槛只读重算 | 3331 条中 2864 条满足当前 high 硬门槛，467 条不满足；不满足分布为 admission 239、discharge 91、jyjc 123、surgery 14 |
| 复核/告警 | 联集 `reviewed_flag` 均为 0；关联告警聚合为 `dept_filtered=1378`、`success=3` |
| 结构质量 | 3331 条 structured evidence 数组均为空；3283 条含 extra issue；大量历史记录依赖 content 而非结构化 evidence，禁止据此自动批量降级 |
| PushLog 科室 | PushLog 总量 165491，`dept` 空 7019；有效患者+次数键 3981 个，经 V_QYBR 精确匹配只有 1 条可唯一回填，其余 7018 条无匹配，不得猜测 |
| payload 结构 | 165491 条中有 98977 条无法解析出 `patient_info`（包括空值、legacy/non-object/不合法内容的混合口径），不能把该聚合误称为全部 JSON 损坏 |
| V_QYBR 键质量 | 全视图按患者 ID + 次数有 138 个重复键组、164 条超额行、单键最多 4 行；所有后续回填必须继续唯一匹配，重复键一律排除 |

### 11.4 强制停点与建议的下一阶段精确范围

依据历史整改 skill，Stage 0 完成后必须先由项目负责人确认候选范围和脱敏规则，才能生成 Stage 1 离线外审包。因此本检查点主动停止，不能把用户此前的“一次执行完成”泛化为历史写入或外部 AI 数据发送授权。

建议下一阶段仅批准以下范围：

1. 高危候选：仅纳入上述 **467 条**不满足当前硬门槛的 high/red 维度，日期闭区间 `2026-01-01` 至 `2026-08-11`，限定 4 个实际出现的 audit code；2864 条门槛合格记录明确排除。
2. 科室候选：仅纳入只读交叉核验得到的 **1 条** V_QYBR 唯一匹配记录；7018 条无匹配和所有重复键明确排除。
3. 脱敏允许字段：随机 candidate token、audit code/run mode、维度 code、severity、confidence、结构化 issue/evidence 标志、硬门槛拒绝原因及去标识后的最小必要证据摘要。
4. 脱敏禁止字段：数据库 ID、患者 ID、次数、姓名、住院号、科室、绝对日期、URL/token/secret、`request_json`/`response_json`、完整病历/护理/检验正文；candidate token 与真实 ID 的映射只保存在院内离线包。
5. Stage 1 只生成候选与外审意见，不写生产。外部意见必须再经过本地硬门槛复核和人工批准；后续 dry-run/写入仍需另列精确 ID、before hash、目标值、批次上限（每批不超过 100）和回滚清单。

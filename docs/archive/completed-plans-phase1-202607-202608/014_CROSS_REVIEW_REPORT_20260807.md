# 交叉核查总报告：系统功能/界面/推送 + ORA-12609 + 病程护理双源 + 历史补跑

> 文档编号：014
> 报告日期：2026-08-07（Asia/Shanghai）
> 报告性质：独立复核与交叉核查报告，供项目负责人和整合 AI 使用；不授权任何生产变更、推送、DDL 或历史补跑
> 复核方式：本地代码静态审查 + 全量自动化回归（891 passed）+ 文档交叉核对；本机未直连业务 Oracle，生产运行时项标 NOT_RUN
> 整合范围：116 系统级复核（G1-G11）、011 ORA-12609 整改、012 病程护理双源、007/008 历史补跑

## 0. 为什么有这份报告

此前有多轮独立核查，结论散落在不同文档和会话中：

1. **116 系统级复核**（`docs/reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md`）：列了 BLOCK-01/02/03 和 P1-01~P1-08，但**遗漏了 G1-G11 共 11 项**（含 2 个 P0 安全项）。
2. **011 ORA-12609 复核**（本轮）：发现计划 S-08/A.7 的 force=True 描述与代码不符；011/P4 已完成错误码落地；A.5 call_timeout 仍有 fanout 缺口。
3. **012 病程护理双源复核**（本轮）：P2 代码未实现（符合原则）；P0/P1 待 DBA + 生产配置冻结。
4. **007/008 历史补跑复核**：发现 M1/M2/M3 计划内不一致 + S1/S2 设计缺口。

本报告把这四轮核查的**全部结论**去重、交叉验证、按主题归并，供整合 AI 制定统一的整改计划。每项都带证据和判定，整合 AI 可据此排期。

---

## 1. 总体结论

当前系统**核心业务代码和自动化回归稳定（891 passed），但存在三类未闭环风险**：

1. **安全阻断项未关闭**（BLOCK-03 + G1/G2）：默认管理员后门、JWT 密钥被 APP_ENV 错配架空——这两个是 P0，比 116 报告描述的更严重。
2. **ORA-12609 整改代码已大幅加固，但生产观察未完成**：011/P4 错误码已落地；但 V_HLJL 仍是性能风险点，012 新数据源尚未上线，连续调度观察 NOT_RUN。
3. **多处计划文档与代码事实不符**：011 的 force=True、007 的"复用 002"——会让后续实施者按错误前提排期。

**未发现患者数据、密码、token 或病历正文泄露。**

---

## 2. 安全类发现（最高优先级，整合时应最先排期）

### 2.1 P0 安全阻断项（必须最先关闭）

| 编号 | 问题 | 位置 | 证据 | 影响 | 判定 |
| --- | --- | --- | --- | --- | --- |
| **G1** | JWT_SECRET_KEY 生产门禁被 APP_ENV 错配架空 | `app/auth.py:28` 读 APP_ENV；`app/main.py:75`/`app/config.py:39` 用 ENVIRONMENT；docker-compose 只传 ENVIRONMENT | 生产 auth.py 读不到 production → 回退公开默认密钥 `your-secret-key-change-in-production` 签发所有 token | **任何人可伪造管理员 token**，比 116 BLOCK-03 描述的"错配"严重得多 | FAIL（代码确认） |
| **G2** | 默认管理员构成持久后门 | `app/users.py:65-91` `_ensure_debug_admin_for_login` 每次 /login 时用 admin/Admin123456 自动重建账号 | 即使部署后删账号，攻击者用默认口令登录即重建管理员 | 删账号无法关闭，等同持久后门 | FAIL（代码确认） |

> 116 报告 BLOCK-03 也列了这两项，但**严重度被低估**：G1 被描述为"错配"，G2 被描述为"登录时自动创建"——实际是"认证可被任意伪造"和"删账号无效"。整合计划应把 G1/G2 列为第一优先级。

### 2.2 P1 安全项（116 报告已准确列出，确认属实）

| 编号 | 问题 | 位置 | 判定 |
| --- | --- | --- | --- |
| BLOCK-03.3 | 匿名 /api/notify/test SSRF（应升格独立 P1） | `app/routers/notify.py:11-14` | 准确，允许任意内网 URL 探测 |
| G7 | validate_configurable_sql 字面量绕过 + 注入面 | `app/db_client_base.py:42` 只查 WHERE 前文本，不剥离字面量 | 准确，中高风险 |
| P1-04 | 配置接口返回明文 API Key（范围可收窄：仅 `/dify/targets`） | `app/routers/config.py:459-464` | 准确，`/audit-types` 已脱敏 |
| P1-05 | 反馈创建信任客户端科室 | `app/routers/qc_feedback.py:1162-1197` | 准确，无日志可见性检查 |
| P1-06 | 病历正文进 Dify 审计日志（默认必然发生） | `app/services/dify_log_utils.py:42` + `app/main.py:53` DEBUG 级 | 准确，应升安全项 |
| G8 | GET /api/health 无鉴权泄露内部拓扑 | `app/routers/health.py:44` | 中优 |

---

## 3. ORA-12609 与病程护理数据源（011 + 012）

### 3.1 已完成（代码层确认）

| 项 | 内容 | 证据 |
| --- | --- | --- |
| 011/P4 错误码 | `classify_oracle_error()` + 7 稳定错误码 + `SchedulerHistory.error_code` 字段 + 双迁移 + 三写入点 | commit `51bb6d5`，891 passed |
| S-04 行为测试 | ORA-12609 二次失败不递归、SQL/权限错误不重试 | `tests/test_oracle_client.py` 新增 3 测试 |
| 011 S-01~S-08 代码保护 | 连接池、ping、陈旧丢弃、有限重试、call_timeout 主路径 | `app/oracle_client.py` |
| 012 业务口径冻结 | 三 mr_class、caption_date_time、护理双时间、572/709、原关联条件 | 012 §3.3、§6 |
| 012 只读 SQL 原型 | 15/16/17 号完成静态校验；17 号单样本活库 550ms | `docs/sql/15,16,17` |

### 3.2 计划与代码不符（必须更新文档）

| 编号 | 计划声称 | 代码实际 | 影响 |
| --- | --- | --- | --- |
| **011-DOC-1** | S-08/A.7：`reset_oracle_pool` 用 `pool.close(force=True)` 会中断在飞查询 | `force=False`（L590/L453）+ 异常处理 + 守护测试 `test_reset_oracle_pool_does_not_force_close` | 若据计划"修复"成 force=True 反而引入新风险 |
| **007-M2** | 007 §6.1"复用 ACTIVE/002" | 002 是纯设计零代码 | 实施者会误判工作量 |
| **007-M1** | 007 §3.1 把"断点续推"列为已有能力 | 只有 `skip_already_succeeded` 幂等跳过，无持久化批次 | 与 007 §3.2 自相矛盾 |
| **007-M3** | 007 §4.2 身份键用 `source_version`/`clinical_source_fingerprint` | 两字段不存在，§6.2 迁移清单未列入 | 实施即卡住 |

### 3.3 待生产/DBA 完成项（NOT_RUN）

| 项 | 内容 | 阻断什么 |
| --- | --- | --- |
| 011/P5 | 连续 3 次同类型调度无 ORA-12609 观察 | 阻断 012/P4 影子和历史补跑 |
| 011/P1 | 镜像 ID、compose tag、客户端动态库路径核对 | 阻断问题关闭 |
| 012/P0 | 生产六类配置快照冻结 + nursing `??ID/??` 乱码修复 | 阻断 012/P2 代码切换 |
| 012/P1 | DBA 提供 15/16/17 号执行计划 + p50/p95/p99 | 阻断 012/P2 |
| 012/P0 | patient+visit/复合键历史例外只读核查 | 阻断 012/P2 |

### 3.4 代码缺口（可在本地修复）

| 编号 | 问题 | 位置 | 严重度 |
| --- | --- | --- | --- |
| **011-CODE-1** | fanout worker 绕过 `_apply_query_timeout`，用驼峰直写且 except 吞错 | `app/services/data_source_loader.py:455-459` | 中（jyjc 护理多源路径超时不一致） |

> 其余服务层调用点（census、patient_dept_query、relay、export）虽未显式调用 _apply_query_timeout，但走池化路径，连接在 acquire 阶段经 `_ping_oracle_connection` 已设置超时——非缺口。

---

## 4. 历史补跑（007/008）

### 4.1 007 计划内不一致（必改）

| 编号 | 问题 | 修正 |
| --- | --- | --- |
| 007-M1 | §3.1 把"断点续推"列为已有能力（与 §3.2 矛盾） | 改为"仅有幂等跳过已完成项" |
| 007-M2 | §6.1"复用 ACTIVE/002"（002 零代码） | 改为"先实施 002（纯设计无代码）" |
| 007-M3 | §4.2 身份键依赖 `source_version`/`clinical_source_fingerprint`（不存在，迁移清单未列） | §6.2 补 PushLog 列迁移，或 §4.2 降级为首版不含来源指纹 |

### 4.2 设计缺口（建议补）

| 编号 | 问题 | 建议 |
| --- | --- | --- |
| 007-S1 | PushLog 无 DB 唯一约束，"同一身份只能一个当前"无法 DB 层强制（应用层 `WHERE superseded_by IS NULL`） | 补 `(source_record_key, audit_type_code, audit_run_mode)` 部分唯一索引 |
| 007-S2 | historical_reaudit 替代必须独立策略函数，不能复用 `mark_daily_logs_superseded`（硬编码 discharge 前置） | 新增 `mark_historical_reaudit_superseded` |

### 4.3 006 多节点池（确认成立）

核查确认 006 是完整代码（pool 语义，非 fan-out）：`resolve_dify_target_pool`（config_parser.py:323）、`_pick_target`（bulk_push_executor.py:577）选单节点、熔断、UI、调度+手动接线全在。007 §9.2"复用 006"成立，无冲突。

---

## 5. 116 报告遗漏项汇总（G1-G11，本轮核查补全）

116 报告本身的 BLOCK-01/02/03 和 P1-01~P1-08 全部属实，但遗漏了以下 11 项：

### 5.1 P0（新增，116 完全漏列）

- **G1** JWT_SECRET_KEY 被架空（见 §2.1）
- **G2** 默认管理员持久后门（见 §2.1）

### 5.2 P1（新增）

- **G3** 多 worker uvicorn 重复执行调度，代码零防护（`app/scheduler.py:148` BackgroundScheduler 进程内，仅靠文档约定单 worker）
- **G4** PushLog 无 DB 唯一约束（见 §4.2 S1）
- **G5** HTTPException detail 透传内部异常泄露 SQL/堆栈（`app/main.py:131-139`；`patients.py:48/76/88/111` 等多处 `detail=str(exc)`）
- **G6** 匿名 SSRF 应升格独立 P1（见 §2.2）
- **G7** validate_configurable_sql 字面量绕过（见 §2.2）

### 5.3 P2（新增）

- **G8** GET /api/health 无鉴权（见 §2.2）
- **G9** Oracle 业务查询无 statement_timeout（主路径有 call_timeout，但 `relay_alert_service` 多处 `except: pass` 吞 close 异常）
- **G10** report.py:58 漏传 audit_type_code（只读显示路径，不影响告警，低优先级）

### 5.4 死代码

- **G11** `_daily_push_job` 死代码引用未定义的 `db`（`app/scheduler.py:362-535`，无调用方，建议删除）

### 5.5 116 报告 BLOCK-02 表述修正

116 报告说"后端 high 依赖 extra.issues"——**不准确**。真实门槛是复合条件：维度级 `medical_evidence`+`nursing_evidence` 双方有意义（`dify_schema_parser.py:480-485`）**且** `extra.issues` 内每条 issue 满足 severe+high_eligible+contradiction+双方证据+confidence≥0.8+受控安全类别（`:488-507`）。报告漏了维度级证据这层硬门槛。

---

## 6. 012 双源计划专项复核

### 6.1 阶段门禁状态

| 阶段 | 内容 | 状态 | 阻断点 |
| --- | --- | --- | --- |
| P0 | 冻结生产六类配置 + 乱码修复 + 关联键核查 | NOT_RUN | 需生产 SSH + 配置 API |
| P1 | DBA 执行计划 + 重复耗时 | NOT_RUN | 需 DBA + 受控环境 |
| P2 | Adapter/RelationPolicy/feature flag 代码 | 未实现（符合原则） | 待 P0/P1 通过 |
| P3 | 自动化回归 | 待 P2 | — |
| P4 | 院内影子对账 | 不允许 | 依赖 P2 + P1 + 业务日期科室 |
| P5 | 小批 canary | 不允许 | 依赖 P4 + alert_policy 确认 |
| P6 | 分类型上线 | 不允许 | 依赖 P5 + 系统负责人批准 |
| P7 | 观察 14 天 + 旧路径退役 | — | 依赖 P6 |

### 6.2 已确认口径（不得重新开放）

- 病程范围：`mr_class IN ('EMR10.00.03','EMR10.00.02','EMR10.00.01')`
- 病程事件时间：`caption_date_time`
- 护理模板：572/709
- 护理双时间：`form_time`（daily）/ `created_date`（discharge）均保留
- 原关联条件：patient+visit、复合键、operation_date、同日窗口、required/anchor 不变
- 人工脱敏样本：跳过，只用院内聚合 + 不可逆哈希

### 6.3 V_HLJL 风险（011/012 交叉点）

V_HLJL 四天聚合 60 秒 ORA-12609；单患者 37 秒仍超时。**不建议在原视图上叠加字段/延长超时/原地修改**。推荐 17 号参数化窄查询（单样本 550ms），但需 DBA 提供执行计划 + p95 才能判定。

---

## 7. 建议整改优先级（供整合 AI 排期）

### 第一优先级：安全阻断（P0，立即）

1. G1：统一 JWT 环境变量为 ENVIRONMENT + 生产门禁硬抛错
2. G2：移除 `_ensure_debug_admin_for_login` 后门逻辑 + 改默认口令

### 第二优先级：可观测性 + 告警正确性

3. 011/P5 生产连续调度观察（运维）
4. 012/P0 配置冻结 + 乱码修复（系统负责人）
5. 012/P1 DBA 执行计划（DBA）

### 第三优先级：关闭 116 安全 P1

6. G6 匿名 SSRF、G7 SQL 校验、P1-04 明文 Key、P1-05 反馈越权、P1-06 病历日志

### 第四优先级：代码加固（本地可做）

7. 011-CODE-1 fanout call_timeout 缺口
8. 011-DOC-1 修正 force=True 过期描述
9. G5 detail=str(exc) 信息泄露
10. G3 多 worker 防护

### 第五优先级：计划文档一致性

11. 007-M1/M2/M3 修正
12. 116 BLOCK-02 表述修正

### 第六优先级：配置/界面收口

13. P1-02 模板六类、P1-03 配置校验、P1-01 健康接口 readiness
14. 012/P2-P7 按门禁推进

### 第七优先级：发布治理

15. G4 PushLog 唯一约束（007/008 前置）
16. 007/008 历史补跑（所有门禁通过 + 书面批准后）

---

## 8. 当前允许执行的最大范围

没有新的书面批准时：

- ✅ 只读核查、本地代码开发（默认关闭的 feature flag）、静态/自动化测试
- ✅ 文档修订（011 force=True、007 M1/M2/M3、116 BLOCK-02 表述）
- ❌ 生产数据库 DDL/DML、配置保存、镜像升级、Dify 调用、推送、告警
- ❌ 历史补推、全量重跑、真实企微/H5 测试
- ❌ 用本地三类配置覆盖生产六类

---

## 9. 强制停止条件

任一发生立即停止扩大范围：

- 生产六类配置未备份，或准备用本地三类覆盖生产
- 要求直接修改/覆盖 V_HLJL、V_BCJL 或业务源表
- SQL 实测出现 ORA-12609、超时、无界扫描或返回数量漂移未解释
- 新旧来源 record/bundle/time/hash/关系边差异未解释
- required 源失败却准备提交部分结果
- canary 未抑制真实告警，或用真实患者数据调用外部 AI
- 历史补推无 preview、candidate hash、精确书面范围
- 患者键/姓名/住院号/正文/密码/token 进入普通日志/文档

---

## 10. 复核边界与置信度

| 结论类型 | 置信度 | 说明 |
| --- | --- | --- |
| 代码层面（G1/G2、011/P4、call_timeout、force=False、PushLog 约束、012/P2 未实现） | 高 | 本地 grep + 测试 + 行号验证 |
| 生产运行时（镜像 ID、连续调度、ORA-12609 复现、配置乱码） | NOT_RUN | 本机不能直连 Oracle，需生产 SSH + DBA |
| 计划文档一致性（007 M1/M2/M3、011 force=True） | 高 | 文档与代码逐条比对 |

本报告未修改任何生产数据库、配置、镜像或推送任务。所有代码改动仅在本地分支 `fix/ora-12609-p4-error-code`（commit `51bb6d5`），未合并 master、未部署。

---

## 附：证据索引（供整合 AI 追溯）

| 发现 | 关键文件:行号 / 文档章节 |
| --- | --- |
| G1 JWT 架空 | `app/auth.py:28`、`app/main.py:75`、`app/config.py:39` |
| G2 默认管理员后门 | `app/routers/users.py:65-91`、`app/database.py:780-830` |
| 011/P4 错误码 | `app/oracle_client.py` classify_oracle_error、`app/models.py` SchedulerHistory.error_code、commit `51bb6d5` |
| 011 force=False | `app/oracle_client.py:590,453`、`tests/test_oracle_client.py:48` |
| 011-CODE-1 fanout 缺口 | `app/services/data_source_loader.py:455-459` |
| 012/P2 未实现 | 全 app/ 树 grep RelationPolicy/Adapter 零命中 |
| 012 SQL 原型 | `docs/sql/15,16,17_*.sql` |
| 007 M1/M2/M3 | `docs/ACTIVE/007` §3.1/§6.1/§4.2 |
| 116 BLOCK-02 表述 | `docs/reference/116` §3.2；实际 `app/services/dify_schema_parser.py:480-507` |
| G4 PushLog 无约束 | `app/models.py:38-86` |
| G5 detail 信息泄露 | `app/main.py:131-139`、`app/routers/patients.py:48,76,88,111` |

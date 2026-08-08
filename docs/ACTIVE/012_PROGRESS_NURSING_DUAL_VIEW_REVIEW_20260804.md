# 病程/护理数据源整改及六类质控标准化实施计划

**文档编号**：012  
**核查日期**：2026-08-05（Asia/Shanghai）  
**适用范围**：六类质控、Oracle 护理记录、Oracle 数据中心病程、Vastbase 海量库病程、daily_increment、discharge_final  
**当前状态**：业务口径已确认、生产只读核查和只读 SQL 原型已完成；待 DBA 评审、影子验证和分阶段批准，禁止直接切换生产  
**关联文档**：011、101、102、105

## 0. 对话需求摘要

- 只读核查 `YDHL.V_HLJL` 的真实定义、依赖和性能风险。
- 评估病程记录由 Oracle 数据中心切换到 Vastbase 海量库的可行性。
- 对六类质控来源进行统一标准化管理，但保持现有关联键、时间窗口、来源角色和运行模式不变。
- 病程范围固定为 `mr_class IN ('EMR10.00.03','EMR10.00.02','EMR10.00.01')`，临床事件时间固定为 `caption_date_time`。
- 护理模板 572/709 均属于护理记录；`form_time` 与 `created_date` 两个时间字段都保留，现行关联条件继续保留。
- 历史数据仅在原患者/住院次/时间关系可验证时补跑；不能可靠关联的历史记录登记原因后跳过。
- 先形成可复核计划，未批准前不修改生产数据库、配置或推送任务。

## 1. 执行结论

### 1.1 总体结论

病程记录切换到 Vastbase 海量库是可行的，但不能把 `JHEMR.V_BCJL` 直接替换成当前 `jhemr.v_blws` 后立即上线。现已确认新病程范围使用三个 `mr_class`，事件时间使用原生 `caption_date_time`；当前 `v_blws` 仍有硬编码日期、文本时间和提前解码正文的问题，因此必须使用新的窄查询/适配层并完成记录 ID 级影子对账。

`YDHL.V_HLJL` 已确认是本次 ORA-12609 的主要 SQL 风险点之一。该视图依赖约 2.075 亿行的护理节点明细表，四天范围聚合在 60 秒调用超时内仍返回 `ORA-12609`。不建议继续在原视图上叠加字段、延长超时或原地修改。模板 572/709 的目标节点在本次活库样本中不存在同表单同节点重复，节点字典也不存在同模板同编码重复，因此可以取消递归 `CONNECT BY`，改为先筛患者和表单、再直接关联目标节点、最后一张表单聚合一行。

推荐最终形态：

1. Oracle `V_QYBR` 只负责患者、住院次、在院/出院和科室锚点。
2. Vastbase 提供标准化病程记录，不再由 Oracle 数据中心 `V_BCJL` 提供病程正文。
3. Oracle YDHL 提供标准化护理记录，查询先按锚点和时间窗缩小范围。
4. 应用层统一记录模型，但六类质控各自使用版本化 `RelationPolicy`，不改变既有关联条件。
5. 病程和护理在 `PatientBundle` 中保持独立数组；需要同日关系时生成可追溯关系边，不生成无边界笛卡尔积。

本轮已生成两份只读原型，均通过静态只读门禁但尚未在生产执行：

- [Oracle 护理记录只读查询](../sql/15_nursing_record_v1_readonly_select.sql)
- [Vastbase 病程记录只读查询](../sql/16_vastbase_progress_record_v1_readonly_select.sql)

按 `$ods-schema-analysis`/`ods-readonly-sql` 的安全约束，本轮不输出也不执行 `CREATE VIEW`。15 号 SQL 含 `:patient_key/:date_from/:date_to`，不能原样包装成 Oracle 视图；它优先作为应用参数化查询使用。若医院明确要求数据库视图，DBA 必须另行生成“无绑定变量”的基础视图定义，并验证应用传入患者/时间条件能够下推到表单和节点明细；旧 `V_HLJL` 保留回滚，不原地覆盖。

### 1.2 当前没有执行的事项

- 未执行 Oracle/Vastbase DDL、DML、授权、索引或统计信息变更。
- 未修改生产 `config.json`、Docker 镜像或调度任务。
- 未调用 Dify，未写 PushLog，未发送企业微信/H5 告警。
- 未读取或输出患者标识、患者姓名、住院号、病历正文。
- 未准备人工脱敏样本；按用户决定跳过该项，影子验收改用院内自动聚合、不可逆哈希和差异原因统计。

## 2. 核查范围与证据等级

本次通过 `10.10.8.84:40022` 服务器内 `med-audit` 容器，复用容器运行时加密配置建立只读连接。本机未直接连接数据库，文档不保存任何密码。

| 核查项 | 判定 | 证据 |
| --- | --- | --- |
| Oracle 连接及 `YDHL.V_HLJL` 元数据 | PASS | 取得视图摘要、46 列定义、DDL、4 个直接依赖对象和索引摘要 |
| `V_HLJL` 四天护理聚合 | FAIL | 2026-08-01 至 2026-08-05，60 秒内返回 `ORA-12609` |
| `V_HLJL` 重复表单、实际执行计划 | NOT_RUN | 首次查询超时后未继续加压；未执行会写 PLAN_TABLE 的操作 |
| Oracle 等待事件/listener 同期日志 | NOT_RUN | 当前账号和本阶段边界未覆盖 DBA 诊断数据 |
| Vastbase `jhemr.v_blws` 元数据与定义 | PASS | 取得 20 列定义、视图定义、底表统计及索引摘要 |
| Vastbase 三类 `mr_class` 单日聚合 | PASS（单日） | 2026-08-04 最新快照 691 条、609 个 patient+visit bundle；患者/住院次/文书 ID/`caption_date_time` 空值均为 0 |
| Vastbase 查询性能 | PARTIAL | 聚合约 0.7–0.8 秒；`EXPLAIN` 仍显示 `jhmr_file_index` 顺序扫描，估算代价约 119,129，尚无匹配 `caption_date_time + mr_class` 的有效索引证据 |
| Oracle 病程与 Vastbase 病程等价性 | FAIL（尚不等价） | Oracle 同日 483 条，当前取数范围包含 308 条查房记录；Vastbase `%病程%` 仅三类 398 条 |
| 生产六类配置读取 | PASS | 六类均启用；daily 配 4 类，discharge 配 6 类 |
| 护理 572/709 单日表单 | PASS（结构/计数） | 2026-08-04：572 为 1,580 张、709 为 1,319 张；表单 ID、patient_uid 均无空值 |
| 护理时间语义 | PASS（字段保留） | `form_time` 位于 8 月 4 日，`created_date` 实际跨 8 月 3–5 日，证明两字段不能互相覆盖 |
| 护理节点直接映射 | PASS（本次范围） | 目标节点同表单同节点重复组 0；`MCS_DOC_NODES` 同模板同编码重复组 0，可取消递归层次展开 |
| 患者级/正文级一致性 | NOT_RUN | 不制作人工样本；须在院内生成不可逆 record/bundle/content hash 对账结果 |

同一活库核查期间 `EMR10.00.03` 从 350 条变为 349 条，总数从 692 变为 691 条，说明业务表在实时更新。本文以较晚的 691 条快照为记录值；这 1 条变化不是漏数结论，影子对账必须冻结查询时点或使用一致性快照。判定只代表 2026-08-05 本次只读窗口，不等于生产切换验收。

## 3. 生产现状

### 3.1 六类质控实际路由

| 质控代码 | 生产 Builder | 当前主要来源 | 当前分组键 | 调度模式 |
| --- | --- | --- | --- | --- |
| `progress_vs_nursing` | `legacy_progress_nursing` | Oracle `V_QYBR + V_BCJL + YDHL`；出院模式使用 `V_HLJL` | patient + visit | daily、discharge |
| `jyjc_vs_bcnursing` | `lab_exam_structured_progress_nursing` | Oracle 检验/检查/护理 + Vastbase 病程 | patient + visit | daily、discharge |
| `syssvsscbc` | `frontpage_surgery_first_progress` | Oracle 首页手术 + `V_shBCJL` | patient + visit + operation_date | discharge |
| `admission_vs_first_progress` | `admission_first_progress` | Vastbase 入院记录 + 首次病程 | patient + visit | daily、discharge |
| `surgery_chain` | `surgery_chain` | Vastbase 术前小结、手术记录、术后首次病程 | patient + visit | daily、discharge |
| `discharge_vs_frontpage` | `discharge_frontpage` | Vastbase 出院记录 + 首次病程 | patient + visit | discharge |

生产调度现状：

- `scheduler_daily` 已启用：`progress_vs_nursing`、`jyjc_vs_bcnursing`、`admission_vs_first_progress`、`surgery_chain`。
- `scheduler_discharge` 已启用：上述四类加 `syssvsscbc`、`discharge_vs_frontpage`。
- 本地 `config/config.json` 只有三类定义，生产有六类，存在配置漂移。实施必须以脱敏导出的生产配置快照为基线，不能用本地三类配置覆盖生产。

### 3.2 `YDHL.V_HLJL` 实测情况

视图定义长度 11,284 字符，输出 46 列，直接依赖：

| 对象 | 统计行数 | 统计时间 | 已见关键索引 |
| --- | ---: | --- | --- |
| `YDHL.INPATIENTS` | 282,019 | 2026-08-05 | `PAT_INDEX_NO` 唯一；`PATIENT_ID,PAT_INDEX_NO,DEPT_CODE` |
| `YDHL.MCS_DOC_FORM` | 12,289,196 | 2026-08-01 | `PATIENT_UID,IS_VALID,FORM_TIME,ID`；`PATIENT_UID,TEMPLATE_CODE,FORM_TIME` |
| `YDHL.MCS_DOC_FORM_RECORDS` | 207,503,590 | 2026-06-06 | `FORM_ID,TEMPLATE_CODE,NODE_CODE`；`FORM_ID` |
| `YDHL.MCS_DOC_NODES` | 34,822 | 2025-12-11 | 主键；`TEMPLATE_CODE,HOSPITAL_ID` |

已确认问题：

1. `active_pat` 名称写“在院患者”，但 `status='in'` 条件已被注释，只保留科室黑名单，不是真正在院集合。
2. `valid_form` 硬编码 `FORM_TIME >= 2026-03-01`，会静默排除历史数据，也要求以后不断改 DDL。
3. 仅支持护理模板 `572/709`，其他模板无法进入视图。
4. 视图输出姓名、性别、年龄、床号、住院号、诊断等本质控不需要的字段，放大聚合和隐私范围。
5. 没有独立 `visit_number`；`患者ID` 实际依赖 `patient_id || '_' || visit` 的隐式复合约定，契约不清晰。
6. `护理记录时间` 来源是 `created_date`，`护理记录表单单创建时间` 来源是 `form_time`。字段名称和业务语义容易混淆，现行关联到底使用哪个时间必须冻结后再切换。
7. 层次节点查询只关联 `PRIOR code = parent_code`，没有同时关联前后层 `template_code`；不同模板复用节点编码时存在交叉扩张风险。
8. 视图把节点字典、2 亿级明细、值转换、层次查询、窗口去重、数十个 `MAX(CASE...)` 和最终排序集中在一次查询中。
9. `IX_DOC_FORM_UID_TIME` 的前导列为 `PATIENT_UID,TEMPLATE_CODE`，视图的全局时间筛选不能直接有效利用第三列 `FORM_TIME`。
10. 四天聚合在 60 秒内出现 `ORA-12609`，证明驱动升级不能替代 SQL/数据模型整改。
11. 数据字典 `READ_ONLY=N` 表示视图未声明 `WITH READ ONLY`；新对象应明确只授予应用账号 `SELECT`，不能依赖视图复杂度阻止写入。

### 3.3 Vastbase `jhemr.v_blws` 实测情况

视图已具备迁移所需的基础字段：`patient_id`、`visit_id`、`progress_guid`、模板/类型/标题、正文、科室和时间信息。`progress_guid` 对应稳定文书 ID，`visit_id` 是 numeric。

主要问题：

1. `record_time_format`、`first_save_time`、`finish_time_format`、`create_date`、`modify_date` 都通过 `TO_CHAR` 转成 text，失去原生时间类型。
2. 视图硬编码 `admission_date_time > 2026-01-01`，无法支持更早历史数据或完整回溯。
3. 文书类型由长 `CASE` 实时推导，外部再对结果执行 `LIKE '%病程%'`，分类不可版本化、不可审计。
4. `safe_convert_from26(mr_content)` 在通用视图层解码正文；若过滤不能下推，会对大量无关文书做高成本转换。
5. 对模板分类、内容、科室均使用内连接；字典缺失或正文暂缺会直接丢失文书，无法区分“无数据”和“映射失败”。
6. 存在单条硬编码排除 ID，应迁移到有版本和原因的排除配置，不应永久写在基础视图中。
7. `EXPLAIN` 显示 `create_date` 条件被展开为 `TO_CHAR(create_date_time)`，导致约 123 万行 `jhmr_file_index` 顺序扫描；估算总代价约 124,395。
8. `jhmr_file_index` 约 1,234,255 live / 237,886 dead，正文表约 1,232,884 live / 227,163 dead，需 DBA 评估 VACUUM/ANALYZE 和膨胀，而不是应用自行维护。

用户已冻结新病程取数口径：

~~~sql
mr_class IN ('EMR10.00.03', 'EMR10.00.02', 'EMR10.00.01')
AND caption_date_time >= :date_from
AND caption_date_time < :date_to
~~~

2026-08-04 最新脱敏聚合：

| `mr_class` | 行数 | 说明 |
| --- | ---: | --- |
| `EMR10.00.01` | 170 | 纳入固定病程范围 |
| `EMR10.00.02` | 172 | 纳入固定病程范围 |
| `EMR10.00.03` | 349 | 纳入固定病程范围；同次核查早期快照为 350 |
| 合计 | 691 | 609 个 patient+visit bundle；关键键和 `caption_date_time` 空值为 0 |

该聚合约 0.7–0.8 秒。早期通过 `v_blws` 的模板名 `%病程%` 得到 398 条，仅代表旧筛选口径；691/692、398 和 Oracle 483 使用的分类、时间字段及查询时点不同，禁止直接相减或据此判断漏数。

### 3.4 Oracle 病程与 Vastbase 病程的口径差异

Oracle `JHEMR.V_BCJL` 同日统计为 483 条、483 个 MRID、452 个 patient+visit bundle，其中：

- 名称含“病程”：165 条；
- 名称含“查房”：308 条；
- 其他：10 条。

当前 `progress_vs_nursing` 日常 SQL 对 `V_BCJL` 没有文书名称过滤，因此查房记录也是现行证据。用户现已确认 Vastbase 新范围按三个 `mr_class` 判断，不再用模板名 `%病程%` 排除查房或其他标题；只要属于上述三个 `mr_class`，均进入候选集合。标题分类只用于 `record_subtype` 标注和差异分析，不能改变取数范围。

该决定关闭了“查房是否纳入”的业务待确认项，但没有自动证明 Oracle/Vastbase 两源等价。上线前仍须按稳定文书 ID、patient+visit、`caption_date_time`、标题分类和正文哈希解释差异；不能只比较总数。

### 3.5 生产配置附加问题

1. `jyjc_vs_bcnursing.nursing.field_mapping` 的 patient/visit 映射在生产读取为 `??ID`、`??`，疑似发生编码损坏，必须以原始 UTF-8 文件和配置 API 再复核；未修复前该源不得判定正常。
2. `admission_vs_first_progress`、`surgery_chain` 的字段映射使用 `inp_no` 作为 `visit_number`，但 `v_blws` 同时提供 numeric `visit_id`。需要确认应用返回的 canonical 值及既有 PushLog 身份，禁止直接改键。
3. `progress_vs_nursing` 仍是单一 `primary` 组合 SQL 和 legacy Builder，尚未使用独立病程/护理数组。
4. `jyjc_vs_bcnursing` 已经使用 Vastbase 病程和 Oracle fanout 护理，可作为新适配器的影子验证入口，但不能把其规则复制到其他五类。

## 4. 目标架构

~~~text
Oracle JHEMR.V_QYBR
  └─ Patient/Visit/Dept/Admission/Discharge Anchor
        ├─ Vastbase v_ai_emr_document_v1（或等价参数化查询）
        │    └─ ProgressRecordAdapter
        ├─ Oracle YDHL.v_ai_nursing_record_v1（或定向 fanout 查询）
        │    └─ NursingRecordAdapter
        └─ Lab / Exam / Frontpage / Surgery 等 SourceAdapter
                         ↓
              CanonicalRecordEnvelope[]
                         ↓
           PatientBundle（各来源保持独立数组）
                         ↓
          RelationPolicy(code, version, run_mode)
                         ↓
              六类现有 Payload Builder
                         ↓
              mr_text 字符串 -> Dify mr_txt
~~~

不建设跨 Oracle/Vastbase 的数据库视图。跨库关联由应用以患者和住院次锚点完成，并对每个源记录耗时、行数和错误状态。

## 5. 统一标准数据契约

### 5.1 PatientContext（内部上下文）

内部保留关联所需稳定键，但不得在普通日志、错误信息、文档、指标标签或外部消息中明文出现：

~~~text
patient_key_internal
visit_number_internal
admission_no_internal（仅确有必要时）
admission_time
discharge_time
dept_code
dept_name
run_mode
audit_date
~~~

日志和指标使用不可逆 `bundle_hash`。Dify 是否需要患者姓名由业务单独确认，默认不因本次标准化扩大传输字段。

### 5.2 CanonicalRecordEnvelope

~~~text
source_system              # oracle_jhemr / oracle_ydhl / vastbase_jhemr
source_name                # progress / nursing / admission / ...
record_kind                # progress / nursing / lab / exam / ...
record_subtype             # first_progress / daily_progress / ward_round / ...
record_id                  # 来源稳定主键
patient_key_internal
visit_number_internal
event_time                 # 临床事件时间；病程固定为 caption_date_time
created_at                 # 创建时间
signed_at                  # 签名/完成时间（存在时）
source_updated_at          # 修改时间（存在时）
template_code
record_name
content
structured_fields
dept_code
author_code
source_status              # ok / missing / mapping_failed / query_failed
schema_version
mapping_version
~~~

约束：

- `record_id + source_system` 必须稳定且可追溯；不能用正文或时间拼接代替真实主键。
- 时间字段在数据库和适配器中保持日期类型，只有展示层格式化。
- 病程 `event_time` 固定取 `caption_date_time`；护理同时保留 `form_time` 与 `created_date`，不得互相覆盖或改名混用。
- 内容按候选集合延迟读取，先取键、类型和时间，再读取正文。
- `query_failed`、`mapping_failed` 与真实 0 行必须严格区分；失败时 fail-closed。
- 六类质控共用字段契约和诊断协议，不共用临床关联规则。

## 6. 必须保持不变的 RelationPolicy

关联条件从 SQL/Builder 中提取为只读、版本化策略。第一版只表达当前行为，不顺带修订临床口径。

| 质控代码/模式 | 锚点与分组 | 必须保留的现行条件 | 标准化后的表达 |
| --- | --- | --- | --- |
| `progress_vs_nursing` daily | patient + visit；当日在院 | 病程标题时间位于 query_date；护理 `form_time` 位于同一 query_date；当前为内连接，两侧均存在才进入 | 两个独立数组，candidate policy 要求两侧存在；关系边标注 same_audit_day |
| `progress_vs_nursing` discharge | 出院日期=query_date；patient + visit | 病程在入院至出院+1；护理按隐式复合键关联，并与每条病程完成时间同日；当前护理为 LEFT JOIN | 保留住院全程病程和 same_calendar_day 边；缺护理不能删除病程 candidate |
| `jyjc_vs_bcnursing` daily/discharge | patient + visit；lab/exam 为可替代锚点 | lab/exam 按结果/报告日期；progress/nursing 为上下文；护理按 patient+visit 定向 fanout 和配置时间窗 | 保留 anchor_sources={lab,exam}、上下文角色和现有时间窗 |
| `syssvsscbc` discharge | patient + visit + operation_date | 首页每台手术展开；术后首次病程按 patient+visit 且病历日期=手术日期 | 显式 operation_date edge，禁止退化为仅 patient+visit |
| `admission_vs_first_progress` daily/discharge | patient + visit | 入院记录与首次病程均必需；当前 Vastbase 分类分别为“入院记录”“首次病程记录” | 保留 required 双源及分类条件；先确认 visit_id/inp_no 映射 |
| `surgery_chain` daily/discharge | patient + visit | 同一住院次内术前小结、手术记录、术后首次病程，Builder 按时间排序 | 保留三亚型和时间顺序，不引入 operation_date 新键 |
| `discharge_vs_frontpage` discharge | patient + visit | 出院记录与首次病程均必需，按出院日期锚定患者 | 保留 required 双源、文书分类和出院锚点 |

注意：用户已确认继续保留护理 `form_time/created_date` 及现行关联。`progress_vs_nursing` 出院模式继续使用 `created_date` 做同日关系，日常模式继续使用 `form_time` 做日期过滤。第一版迁移必须复刻，不在本轮统一时间语义。

## 7. 数据库整改方案

### 7.1 Oracle 护理记录

结论：建议整改护理取数，但首选仍是参数化定向查询，不立即覆盖原视图。除 15 号窄字段原型外，本轮新增 [17 号兼容性只读 SELECT 原型](../sql/17_nursing_record_v2_readonly_select.sql)：保留原质控使用的体征、正文、出入量、皮肤/高危等字段，一张 `FORM_ID` 一行，并显式输出 `form_time` 与 `created_date`。两份 SQL 都只是 SELECT 查询体，不能原样包装为带绑定变量的 Oracle 视图；若 DBA/架构评审明确要求数据库视图，必须另写无绑定变量基础定义，验证外层患者/日期谓词下推后再受控创建。无论采用哪种方式，都不修改原 `YDHL.V_HLJL`。

优先顺序：

1. **首选：锚点后定向查询。** 先从 `V_QYBR` 得到 patient+visit，继续按原条件生成内部复合键，与 `INPATIENTS.PATIENT_ID` 相等后取得 `PAT_INDEX_NO`；护理库内部继续使用正式关系 `MCS_DOC_FORM.PATIENT_UID = INPATIENTS.PAT_INDEX_NO`，再按模板和半开时间窗查询表单及目标节点。
2. **可选：新建 `YDHL.V_AI_NURSING_RECORD_V1`。** 仅提供一张表单一行的窄记录，不在视图中筛“在院患者”，不固化日期，不包含患者姓名等非必要字段；17 号查询体可作为字段和映射的候选基线，但不能直接替换 46 列的旧视图。
3. **最后手段：预聚合/物化。** 只有定向查询 p95 仍不达标且 DBA 批准时，才设计增量刷新表或物化视图。

15 号查询相对 `V_HLJL` 的主要减负点：

1. 先按单个内部患者复合键取得 `PAT_INDEX_NO/SERIES`，不扫描全院患者集合。
2. 在进入 2 亿级 `MCS_DOC_FORM_RECORDS` 前，先按 `PATIENT_UID + TEMPLATE_CODE + FORM_TIME` 筛选表单。
3. 明细只读取现有质控使用的 12 个节点编码，不读取全部护理节点。
4. 删除递归 `CONNECT BY`、患者人口学字段、全局排序和硬编码起始日期。
5. 一张 `FORM_ID` 输出一行，同时原样保留正文、体温、脉搏、呼吸、血氧和护士签名映射。

不影响质控的边界：原患者/住院次锚点、模板 572/709、正文非空门槛、日常 `form_time` 和出院 `created_date` 关联均不变。15 号原型只覆盖当前 12 个核心节点；17 号在此基础上补回旧视图实际使用的血压、氧疗、出入量、皮肤/高危和签名节点，并保留 `mapping_version`。任何新字段或新模板都必须按新映射版本单独验收。

建议护理输出字段：

~~~text
patient_key_internal, visit_number_internal, nursing_record_id,
event_time, created_at, template_code, record_type,
nursing_content, temperature, pulse, respiration,
blood_pressure, oxygen_saturation, recorder_code,
dept_code, source_updated_at, mapping_version
~~~

DBA 设计约束：

- 一张表单一行；`FORM_ID` 为稳定 `nursing_record_id`。
- `visit_number` 显式输出 `INPATIENTS.SERIES`，但第一版患者锚点仍沿用当前复合键条件；不擅自改成新的跨系统 JOIN。
- 模板 `572/709` 已确认代表护理记录，是 V1 固定范围；未来新增模板必须新增映射版本、重复性检查和影子验收，不能直接追加编号上线。
- 2026-08-04 目标节点的同表单同节点重复组为 0，节点字典的同模板同编码重复组也为 0。当前 `MAX(CASE...)` 仅用于把唯一节点转成列，不承担重复值取舍；以后若重复组大于 0，必须停止并先确定取值规则。
- V1 删除递归 `CONNECT BY`，按相同 `template_code + node_code` 直接关联字典；保留 `PARENT_CODE/SEQ` 仅用于映射审计，不参与高成本递归展开。
- `form_time` 与 `created_date` 均以原生 DATE 输出。日常/出院 RelationPolicy 继续分别使用原有字段，不能在视图层合并成一个时间。
- 复用现有 `MCS_DOC_FORM(PATIENT_UID,IS_VALID,FORM_TIME,ID)` 和 `MCS_DOC_FORM_RECORDS(FORM_ID,TEMPLATE_CODE,NODE_CODE)` 前先取得实际执行计划，不重复建相同索引。
- DBA 更新/评估 `MCS_DOC_FORM_RECORDS`、`MCS_DOC_NODES` 统计信息；新索引只能基于执行计划和写入成本批准。
- 应用账号只授予 `SELECT`，视图显式 `WITH READ ONLY`（数据库版本允许时）。

### 7.1.1 2026-08-07 活库只读复核结果

本次通过服务器容器内已验证成功的 Oracle 直连完成，未在本机直连、未执行 DDL/DML、未输出患者明细：

| 项目 | 结果 | 判定/影响 |
| --- | --- | --- |
| 现有视图重查询 | 按单个内部患者键和 2026-08-04 表单时间过滤，约 37 秒后仍返回 `ORA-12609` | `V_HLJL` 不能作为新查询的性能基线；停止继续加压 |
| 17 号查询体 | 同一类脱敏选择键、单日边界执行成功，返回 14 行、49 列，约 550 ms | 仅为单样本可行性证据，不等同 p95 性能通过 |
| 2026-08-04 有效表单 | 模板 572 为 1,587 张，709 为 1,319 张；无效表单另计 | 统计随活库变化，不能写成固定成效 |
| 目标节点重复 | 同表单同模板同节点重复组 0；字典同模板同编码重复组 0 | `ROW_NUMBER` 仅作防御性幂等，若未来重复数大于 0 必须停门 |
| 表单孤儿关系 | 2026-08-04 有效 572/709 表单共 2,906 张，按 `PATIENT_UID=PAT_INDEX_NO` 关联 `INPATIENTS` 孤儿 0 | 正式关联条件可继续保留 |
| 住院键重复 | `INPATIENTS` 的 `PATIENT_ID+SERIES` 有 806 个重复组、816 条多余行；`PAT_INDEX_NO` 为主键 | 不能把 `PATIENT_ID+SERIES` 当数据库唯一键；查询仍先用既有 `PATIENT_ID -> PAT_INDEX_NO`，住院次仅作输出/应用匹配 |
| Oracle 客户端 | 容器 `cx_Oracle.clientversion()` 为 19.25；一次池初始化出现 `ORA-12541`，随后直连成功 | 仍需按 011 观察池/监听瞬态，不能以驱动版本替代 SQL 整改 |

17 号查询体不返回姓名、住院号、诊断等非质控字段，因此不能透明替换任何依赖旧 46 列的外部报表；在切换前必须完成消费者清单和旧/新 `FORM_ID`、时间、字段哈希对账。出院模式不得把 17 号的 `form_time` 过滤误用于 `created_date` 关系，应继续按 012 第 6 节的 RelationPolicy 单独定向查询。

### 7.2 Vastbase 病程记录

建议基于 [16 号只读 SELECT 原型](../sql/16_vastbase_progress_record_v1_readonly_select.sql) 建立 `jhemr.v_ai_emr_document_v1` 或实现等价参数化查询，不直接修改 `v_blws`。本轮未生成、未执行 DDL：

- 输出原生 `create_date_time`、`first_mr_sign_date_time`、`last_modify_date_time`，不在视图内 `TO_CHAR`。
- 不硬编码 `2026-01-01`；历史范围由调用参数和权限控制。
- 保留 `file_unique_id` 作为 `record_id`、`patient_id + visit_id` 作为内部关联键。
- 范围固定为三个已确认 `mr_class`，事件时间固定为原生 `caption_date_time`；不再以模板名 `%病程%` 作为取数门槛。
- 先按 patient+visit、`delete_flag=0`、三个 `mr_class` 和 `caption_date_time` 半开时间窗筛键，再左关联/解码 `mr_content`；正文缺失保留记录并标记 `missing_content`，不能静默丢行。
- 分类规则从长 CASE 迁移为版本化映射表或受控配置，至少区分入院、首次病程、日常病程、查房、术前、手术、术后首次、出院和其他。
- 字典/科室映射缺失不能静默删除文书；保留记录并标记 `mapping_failed`。
- 单条排除 ID 迁移到有原因、审批人、有效期的排除清单。
- 现有 patient+visit 复合主键和 `file_unique_id` 唯一索引适合“先锚点后取文书”。首选先证明 patient+visit 定向查询能利用现有索引；只有批量 fanout 仍慢时，DBA 才比较以 `patient_id, visit_id` 为前导和以 `mr_class, caption_date_time` 为前导的候选索引，不在本文给出可执行 DDL。
- DBA 评估 dead tuple、VACUUM/ANALYZE 和正文表膨胀；应用不得自行执行维护命令。

### 7.3 文书范围迁移规则

在停用 `V_BCJL` 前建立 `progress_scope_mapping_v1`，冻结以下规则：

| 规则 | V1 口径 | 用途 |
| --- | --- | --- |
| 范围 | `mr_class IN ('EMR10.00.03','EMR10.00.02','EMR10.00.01')` | 唯一取数范围；三类内的查房和其他标题不再额外排除 |
| 事件时间 | `caption_date_time` | daily 时间筛选和标准 `event_time` |
| 稳定记录 ID | `file_unique_id` | 去重、幂等、追踪和影子对账 |
| 内部关联 | `patient_id + visit_id` | 继续按原 patient+visit 条件关联 |
| 标题分类 | first/daily/postop/ward_round/other | 只用于 subtype 与差异解释，不改变取数范围 |

若 Oracle `MRID` 与 Vastbase `progress_guid` 可直接对应，应优先按 ID 对账；否则使用院内不可逆哈希对 patient+visit+标题时间+类型做辅助匹配，原始键不出院内。

## 8. 应用整改方案

### 8.1 配置和注册表

1. 先脱敏导出生产六类配置及 SHA-256，修复本地三类/生产六类漂移。
2. 为每类增加 `schema_version`、`mapping_version`、`relation_policy_version` 和来源能力声明。
3. 配置保存前校验 Builder、source 名称、group_key、field_mapping、document_kind、日期锚点及 `join_rules=[]`。
4. 立即复核并修复生产 nursing 映射 `??ID/??`，但必须走备份、配置 API 校验和回滚流程，不能文本替换加密配置。

### 8.2 Loader 和 Adapter

1. 新增 `ProgressRecordAdapter`、`NursingRecordAdapter`，统一大小写、numeric visit、DATE/TIMESTAMP、LOB/bytea 和空值。
2. `load_patient_bundles()` 保持各源独立数组；`join_rules` 不做病程×护理记录级乘积。
3. daily 和 discharge 都先加载 anchor，再批量/分片取 Vastbase 病程和 Oracle 护理。
4. 每个源返回 `row_count/valid_count/skipped_count/error_code/elapsed_ms/retry_count`。
5. 任一 required 源查询失败，整 bundle 或整批 fail-closed；不得把异常写成 0 条。

### 8.3 Builder 和落库

1. 新增 `progress_nursing_multi_source`，分别输出病程时间线、护理时间线和关系边。
2. 保持 `mr_text` 为字符串，仍仅由 `dify_pusher.py` 映射为 `mr_txt`。
3. 保持六类现有 dimension code、response JSONPath、contract_valid、qc_usable、skip_reason、supersede 和告警抑制行为。
4. `source_record_key` 必须包含 relation policy/version 和 audit_date 的既有兼容设计，不能让不同日期互相覆盖。
5. PushLog 保存来源版本、记录数和哈希摘要，不保存完整正文或明文内部键。

## 9. 分阶段执行计划

### P0：冻结现状和已确认口径（禁止写生产）

- [ ] 导出生产六类配置脱敏快照、SQL hash、镜像 ID、调度列表，作为唯一生产基线。
- [x] 病程范围固定为三个 `mr_class`；三类内查房等标题不额外排除。
- [x] 病程 `event_time` 固定为 `caption_date_time`。
- [x] 护理模板 572/709 均代表护理记录；`form_time` 与 `created_date` 均保留，现行两模式差异继续保留。
- [x] 第一版继续使用原 patient+visit、复合键、operation_date、同日窗口、required/anchor 条件，不引入新的关联条件。
- [ ] 对生产六类配置中的字段编码和 `visit_id/inp_no/次数/patient_uid` 实际返回值做只读一致性检查，确认没有历史例外会破坏原关联。

**门禁**：已确认业务口径不得在实施中改写；生产配置快照、编码问题或原关联键一致性未关闭时，不进入 P2/P4。

### P1：数据库设计和只读原型（当前已生成，待 DBA 实测）

- [x] 生成护理窄查询和 Vastbase 标准病程查询；两份文件均为单条只读 SELECT/CTE，静态门禁通过，尚未执行。
- [ ] DBA 对 15/16/17 号查询提供 explain、单日/单科室/单 bundle 的重复执行耗时和返回行数。
- [ ] 对现有索引做利用证明，再决定是否新增索引或只更新统计；禁止仅凭建议直接建索引。
- [ ] 若确需新视图，由 DBA 依据 15 号查询另写无绑定变量的视图定义，在受控变更中验证谓词下推后再创建；只授应用账号 SELECT，旧对象不删除、不改名。15 号带绑定变量的定向查询不能直接作为 `CREATE VIEW` 定义。

这里的 p50/p95/p99 分别表示多次查询中的中位耗时、较慢 5% 和最慢 1% 区间，用于确认偶发慢查询不会再次超过驱动超时。Vastbase 的统计更新、`VACUUM/ANALYZE` 是 DBA 用来帮助优化器和清理死元组的维护动作，不由本系统或本轮 AI 执行。

**门禁**：键非空率 100%、稳定 ID 重复 0、无全表正文解码、p95 低于查询超时的 1/3，并取得 DBA 签字。

### P2：本地代码实现（默认关闭）

- 实现 canonical adapter、RelationPolicy、双源 Builder、源级诊断和配置校验。
- 增加 feature flag：`progress_source=v_bcjl|vastbase_v1`、`nursing_source=legacy|oracle_v1`。
- 默认继续使用旧生产来源；不得在代码合并时自动切换。

**2026-08-08 进展（本地草案，未接线）**：`canonical_record.py`（信封+源级诊断+隐私守卫）、`relation_policy.py`（六类 V1 策略）、`source_feature_flags.py`（flag 默认旧路径、非法值 fail-closed）、`progress_record_adapter.py`（16 号原型）、`nursing_record_adapter.py`（17 号原型，date_field 白名单区分 daily/discharge）已落地，配套 69 个单测全绿、命名守卫 PASS。双源 Builder 与 loader/composer 切换接线**未实现**，须按 016 §3.2 门禁另行批准后方可编写。

### P3：自动化回归

- 完成本文件第 10 节测试。
- `python -m compileall app tests scripts`、命名守卫和相关 pytest 全部通过。
- 对已有 ORA-12609 一次重试、连接关闭、fail-closed、锁和告警门禁做回归。

### P4：院内只读影子对账

- 同一日期、同一科室同时运行旧 Oracle 病程/护理和新来源。
- 不调用 Dify、不写 PushLog、不发告警。
- 比较：record ID 集合、bundle 集合、subtype、event_time 差值、正文哈希、关系边集合、缺失原因。
- 不准备人工脱敏抽检样本；由院内程序仅输出聚合数量、不可逆哈希和差异原因，禁止输出患者键或正文。
- 至少覆盖 7 个业务日、在院与出院、模板 572/709、三个 `mr_class` 及其中的查房/其他标题。

**门禁**：业务键完整率 100%、稳定 ID 重复 0、bundle/关系边差异全部由业务/医务负责人和系统负责人共同确认或签字豁免、查询失败 0；不能只比较总行数。

### P5：小批 canary

- 首批一个日期、一个科室、20–50 个 bundle。
- `alert_policy=suppress`，禁止真实企微/H5；Dify 结果仅内部对账。
- 先只切病程来源，护理保持旧路径；通过后再切护理，避免两个变量同时变化。
- 连续 3 次同类型调度无 ORA-12609、Vastbase timeout、源级失败、重复当前结果或重复告警。

### P6：分类型上线

建议顺序：

1. `jyjc_vs_bcnursing`（已有 Vastbase 病程，可验证 adapter）。
2. `admission_vs_first_progress`、`surgery_chain`、`discharge_vs_frontpage`（已使用 Vastbase，统一契约）。
3. `progress_vs_nursing` daily（先换病程，再换护理）。
4. `progress_vs_nursing` discharge（最后切换，因同日关系和 `V_HLJL` 风险最大）。
5. `syssvsscbc`（保持 operation_date，不与 surgery_chain 合并规则）。

每一步均需独立配置版本、影子报告、canary 记录和回滚点。

### P7：观察和旧路径退役

- 正常运行至少 14 天并覆盖 daily/discharge。
- 旧 SQL 保留只读回滚能力；未经另行批准不删除旧视图和历史配置。
- 满足连续运行、院内聚合/哈希差异验收、性能和数量门禁后，再评估退役 `V_BCJL` 病程路径。
- 历史补跑按“可验证才补”执行：旧记录能继续满足原 patient+visit/复合键/时间关系时纳入独立 preview；无法可靠关联时记录日期范围、数量和原因后跳过，禁止猜键或降级为患者单键关联。

## 10. 必须新增的测试

### 10.1 数据契约

- Oracle 大写/中文列名、Vastbase 小写列名均规范化成功。
- numeric `visit_id` 与 Oracle 次数规范化后不改变既有 bundle 身份。
- 原生时间、时区、半开区间和跨日边界正确。
- record_id 非空、重复检测、修改时间和 schema/mapping version 正确。
- 日志、错误、指标和导出不出现明文患者键或正文。

### 10.2 RelationPolicy

- daily 病程和护理仍按 patient+visit+query_date 形成候选。
- discharge 病程限制入院至出院，护理仍按每条病程同日 LEFT 关联。
- 3 条病程×5 条护理不生成 15 条重复 payload，但关系边与旧条件等价。
- `syssvsscbc` 必须包含 operation_date；`surgery_chain` 不能被强加 operation_date。
- lab/exam 可替代锚点和上下文 requiredness 不变。
- 缺失源、查询失败、映射失败、真实 0 行产生不同诊断。

### 10.3 数据库与可靠性

- Vastbase 查询先按原生时间/患者键过滤，禁止在 WHERE 对时间 `TO_CHAR`。
- 护理查询使用 bind、半开区间和目标模板/节点，不走无界全量。
- bytea/CLOB 正常、空、超长、解码失败均关闭资源并 fail-closed。
- ORA-12609 只重试一次；第二次失败不递归；SQL/权限/字段错误不重试。
- 单批中任一 required 源失败，不提交部分 bundle。

### 10.4 六类回归

- 六个 Builder、六类维度和响应 JSONPath 均通过固定 fixture。
- daily/discharge 独立锁、SchedulerHistory、PushExecution 幂等不回退。
- contract_invalid、fallback、parse_failed 不成为当前结果、不 supersede、不告警。
- Dify 输入仍为字符串，输入字段仍是 `mr_txt` 映射。

## 11. 观测、回滚和停止条件

每源至少记录：查询批次、模式、source、SQL/config hash、候选数、有效数、跳过数、耗时、p95、错误码、重试次数；禁止患者键作为指标标签。

切换前保存：

- 旧镜像 ID、compose、生产配置及 SHA-256；
- 旧/新 SQL 和视图 DDL hash；
- relation/mapping/schema version；
- canary 前 PushLog、SchedulerHistory、PushExecution 聚合快照。

任一以下情况立即停止扩大范围并恢复上一个配置/镜像：

- ORA-12609、Vastbase timeout 或 required 源加载失败；
- bundle/记录/关系边出现未解释差异；
- 患者/住院次键错配、重复当前结果或 self-supersede；
- 解析/契约有效率下降、告警越权或隐私字段进入日志；
- 查询 p95 超门禁或连接池/数据库负载异常。

回滚只恢复应用镜像和配置，不删除新旧历史结果，不执行宽范围 UPDATE，不自动补推。

## 12. 需要医院侧完成的工作

### 12.1 业务/医务/护理

- [x] 病程范围已确认：`mr_class IN ('EMR10.00.03','EMR10.00.02','EMR10.00.01')`。三类中的查房和其他标题都进入候选，不再逐标题排除。
- [x] 病程临床事件时间已确认为 `caption_date_time`。
- [x] 护理 `form_time/created_date` 均继续保留，日常与出院模式沿用当前各自关联字段。
- [x] 模板 572/709 已确认为护理记录。当前 12 个目标节点映射按现行规则保留；本次样本未发现重复节点。
- [x] 人工脱敏抽检样本按用户决定跳过；系统只生成院内聚合与不可逆哈希对账。
- [ ] 指定影子运行日期和科室，并批准 canary 数量（建议 20–50 个 bundle）及 `alert_policy=suppress`。这一步只决定小范围验证，不会直接正式推送告警。

### 12.2 DBA

- [ ] 复核 15/16/17 号只读 SQL、当前表规模、索引和统计日期，确认字段和现有索引仍与活库一致。本文件不含 DDL，DBA 评审通过后再单独准备建视图脚本。
- [ ] 按原有关联条件抽查 `patient_id/visit_id/inp_no/次数/patient_uid` 的映射；只报告总量、异常量和不可逆哈希，不输出实际患者键。历史例外单列，不能擅自改关联规则。
- [ ] 对新护理/病程 SQL 重复执行，记录中位耗时、较慢 5% 和最慢 1% 的耗时，以及每次返回行数；同时保存实际执行计划，确认先筛患者/时间再查大表。
- [ ] 判断是否只需更新数据库统计，还是确实需要新索引。`VACUUM/ANALYZE` 属于 Vastbase 的优化器统计和死元组维护；索引会增加写入和存储成本，均由 DBA 在维护窗口决定，本系统不执行。
- [ ] 新对象只给应用账号读取权限，不给新增、修改、删除权限；旧 `V_HLJL`/`V_BCJL` 保留，切换失败时应用可恢复旧配置。
- [ ] 若再出现 ORA-12609，请 DBA 同期查看数据库等待、listener 和 alert 日志，用于区分“SQL执行慢”“数据库等待”还是“网络连接被中断”。驱动升级不能替代该证据。

### 12.3 系统负责人

- [ ] 变更前备份生产六类配置及其 SHA-256。服务器上的六类配置是权威基线，本地只有三类的文件只能用于开发，绝不能覆盖服务器配置。
- [ ] 按四个检查点批准：P1 为数据库查询/视图设计，P4 为不推送的影子对账，P5 为 20–50 个 bundle 的小批验证，P6 为按质控类型逐步正式启用。前一阶段不通过就不扩大范围。
- [x] 历史规则已确认：只要历史数据仍能按原关联条件正确匹配，就可以另行 preview 后补推；无法可靠关联的历史范围登记为跳过。实际历史补推仍需按 007/008 的门禁另行授权。
- [x] 内部关联键可用于数据库和内存匹配，但普通日志、文档、监控标签、Dify 外附元数据和企业微信/H5 消息中不得出现明文；统一使用不可逆 `bundle_hash`。

## 13. 交给其他 AI 的复核提示词

~~~text
你是 Med-Audit 独立复核 AI。工作目录：F:\python\前后端代码\ai_mrzk。

先完整阅读：AGENTS.md、docs/INDEX.md、docs/reference/101_FEATURE_BASELINE.md、
docs/reference/102_DATA_AND_DIFY_CONTRACTS.md、docs/skills/med-audit-codex.md、
docs/ACTIVE/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md、本 012 文档，
以及 docs/sql/15_nursing_record_v1_readonly_select.sql、docs/sql/16_vastbase_progress_record_v1_readonly_select.sql。

目标：独立复核 012 中的生产只读证据、病程迁移可行性、护理优化方案和六类 RelationPolicy。

硬性边界：
1. 当前只允许只读复核；不得执行 DDL/DML、配置保存、镜像升级、Dify 调用、推送或告警。
2. 只能通过 10.10.8.84 服务器内 med-audit 容器连接数据库；不得在本机直连。
3. 不输出密码、token、患者标识、姓名、住院号或病历正文。
4. 每项按 PASS/PARTIAL/FAIL/NOT_RUN 判定，缺证据不得推断 PASS。
5. 生产配置有六类、本地 config 当前只有三类；不得用本地配置替代生产事实。
6. 不能把 Vastbase 691/692、旧口径 398 与 Oracle 483 简单相减得出漏数；必须按 record ID、类型、时间和 bundle 做院内脱敏对账。
7. 不得改变 patient+visit、operation_date、同日窗口、required/anchor 角色或 daily/discharge 语义。
8. 不得通过延长超时掩盖 V_HLJL 结构问题。
9. 已确认口径不得重新开放讨论：病程范围为三个 mr_class，event_time=caption_date_time；护理保留 form_time/created_date；572/709 均为护理记录；全部原关联条件不变。
10. 不准备人工脱敏样本；复核只允许聚合、不可逆哈希和差异原因。
11. 两份 SQL 只能是单条 SELECT/只读 CTE；不得补写或执行 CREATE VIEW/索引/统计维护/DML。

必须复核：
- V_HLJL DDL、46 列、4 个依赖、表规模、索引、硬编码日期、模板范围、时间别名和 60 秒 ORA-12609；
- v_blws 的 TO_CHAR 时间、硬编码日期、CASE 分类、顺序扫描、稳定 ID 和单日聚合；
- 三个 mr_class + caption_date_time 的 691/692 实时快照漂移，以及它不能与 398/483 简单相减；
- V_BCJL 中病程/查房/其他记录与新范围的 ID 级差异；
- 15 号护理 SQL 是否先筛 patient/form、是否保留两个时间、是否按 form_id 一行、是否删除递归且保持 12 个节点映射；
- 16 号病程 SQL 是否先筛 patient+visit/mr_class/caption_date_time，再读取正文；
- 生产 nursing 映射 ??ID/?? 是否为真实编码损坏；
- 六类 Builder、group_key、source role 和调度模式；
- P0-P7 门禁、测试、灰度和回滚是否可执行。

输出格式：发现项按 P0/P1/P2 排序，每项给文件/函数或数据库对象、脱敏命令、证据、影响、建议、判定；
最后列出未执行项、需要医院/DBA确认的事项和是否允许进入下一阶段。
~~~

## 14. 当前停止点

本次只读核查和 SQL 原型已经完成，生产数据源尚未切换。以下事项未完成前禁止切换生产或启动补推：

- 生产六类配置快照尚未冻结，nursing 字段映射编码问题尚未关闭；
- 原 patient/visit/复合键映射尚未完成只读历史例外核查；
- 15/16/17 号 SQL 尚未取得 DBA 提供的实际执行计划、重复耗时和数据库负载证据；本轮 17 号仅完成单样本只读可行性测试；
- Oracle/Vastbase 记录 ID、bundle、时间、分类、正文哈希和关系边影子对账尚未完成；
- P4 影子日期/科室、P5 小批范围及 P6 分类型上线尚未批准。

已经关闭且不得再次列为阻断：病程三个 `mr_class` 范围、`caption_date_time` 事件时间、护理双时间保留、572/709 模板归属、沿用原关联条件和人工样本跳过。

本文件是整改和独立复核依据，不代表已完成数据库、代码、配置或生产升级。

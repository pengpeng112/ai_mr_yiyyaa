# 归档前病历预检与 JHEMR 强制提醒——执行计划（待独立复核）

> 文档编号：028
> 编制日期：2026-08-27
> 性质：**执行计划 + 待复核**；本文档不授权任何生产写入；P0 全部任务只读
> 编制者：ZCode/GLM-5.3（基于 026/027 分析与用户四轮决策确认）
> 版本：**v2（2026-08-27 夜，按 multi-review round-1 的 24 项修订指令更新，见 §10）**
> 复核对象：本计划的**事实基础、方案设计、任务分解、风险完备性**；复核 AI 按 §9 清单逐项核查并出四张清单（同意/不同意/证据不足须人工/新问题）
> 上游文档：**023（唯一执行入口，本计划从属其 §9.1，获批前不得开工 P1/P2）**、`024/025`（高危严重度纪律来源）、`026`（规则来源与分类）、`027`（对接路径评估）
> 外部证据库：`D:\Users\Administrator\Desktop\嘉和`（嘉和系逆向分析工作区，只读引用其 docs 与 CHANGELOG）

---

## 0. 一页摘要（目标与已定决策）

**目标**：把质控从"病案室/医护事后打回"前置到**医生点击病历完成（待归档）时**——基于无纸化人工质控评分项（CDMS `t_mark_item`）的 A 类确定性规则，直读各系统提供给无纸化的同款 T_ITF_* 视图与 JHEMR 结构化表，发现缺文书/时限/空项/重复问题，在**完成时点给予分钟级强制提醒（置顶弹窗+企微）并支持整改后复检闭环**（非提交流程内拦截）；现有六类 Dify 一致性质控**零改动**。

**用户已确认的六项决策**（2026-08-27 会话）：

| # | 决策 | 内容 |
|---|---|---|
| D1 | 提醒对象 | 默认**完成医生**（first_finished_doctor_id，精确到人）；主管医师作兜底（工号缺失时）；**可配置**扩展科主任与病案室。三者收敛为一条推送数据模型（A4 修订） |
| D2 | 一期数据源 | 核心源先行：JHEMR 病历 + HIS 医嘱/首页 + 手麻 + LIS |
| D3 | 触发时点 | 病历完成即查即推（轮询触发锚点，分钟级） |
| D4 | 一期规则 | 仅 A 类确定性规则（纯代码，不调 Dify）；B 类语义维持每日批 |
| D5 | 部署隔离 | **独立服务隔离**：新模块+独立进程/容器、独立表、独立配置；零改动现有六类质控代码路径与 relay_alert_service |
| D6 | 强制提醒形态 | **双首选并列**：①外挂托盘助手（失败域天然隔离，027-F1）②AppDomainManager 独立 DLL（**降级为待强命名复测的候选**，须 fail-open，round-1 实验：env 通道失败=EMR 启动崩溃）。IL 最小注入为最后退化（须信息科书面同意覆盖）；企微推送并行兜底。不走 CDSS 通道 |

---

## 1. 事实基础（全部可独立复核；标注来源与复核方法）

### 1.1 已 live 只读实证（sjzc 技能，2026-08-27）

| # | 事实 | 来源 | 复核方法 |
|---|---|---|---|
| F1 | **触发锚点存在**：`jhemr.pat_visit` 含 `finished_date_time`、`first_finished_doctor_id`、`first_finished_date_time`、`first_page_submit_date/user_id`、`mr_submitnurse_record_*`（提交护士四字段） | `jhemr_vastbase_10_10_8_177` information_schema | `sjzc live jhemr_vastbase_10_10_8_177 --sql "SELECT column_name FROM information_schema.columns WHERE table_schema='jhemr' AND table_name='pat_visit' AND column_name ~ '(?i)(finish|submit)'"` |
| F2 | `mr_finished_index_callback`（18列，申请/审批流）与 `recordfinished_oper_log`（6列：patient_id/visit_id/operating_time/operating_name/operating_id/status）**存在但 177 副本上 0 行** | 同上 | 同款 SELECT COUNT(*) 两表 |
| F3 | T_ITF 条目层骨架（三源**大体**一致，**描述字段有差异**）：`FID/PATIENTID/FBIHID/FBINCU/报告名(REPORTNAME或FITEMNAME)/PDF名/路径/FCKDATE/FUPDATE/FLOADDATE/FREPORTSTYLE/PAGECOUNT`；HIS 另有 CONSULTATION_ID（会诊关联）；**LIS 的描述列为 `FDESCNUM`（无 FDESC），真实对象是 `dbo.vw_hisinter_T_ITF_Lis`（RMCLOUDLIS7 是数据库名不是 schema）**——采集器按源适配，不得按统一 FDESC 取值 | `his_source_10_10_10_15`（PAPERLESS.T_ITF_HIS，14列）、`docare_oracle_10_10_10_68`（MEDSURGERY.T_ITF_SM，13列）、`lis_sqlserver_10_10_10_73`（dbo.vw_hisinter_T_ITF_Lis，13列） | 各源数据字典查询；round-1 已复核 |
| F4 | HIS 的 `T_ITF_HIS.REPORTNAME` 是 **NUMBER 编码**（2026-07 以来 DISTINCT 仅 0/1/2 三个值，量级 1.1万~1.4万），非文书名文本；手麻/LIS 为 varchar 文本名 | 同上 + 分组计数 | `SELECT REPORTNAME,COUNT(*) FROM PAPERLESS.T_ITF_HIS WHERE FUPDATE>=DATE'2026-07-01' GROUP BY REPORTNAME` |
| F5 | 无纸化人工质控量级：主表 73,011 份（2026 年 41,709、日均~170）；2026 明细 385 万；扣分说明 8,200 条，TOP20 高度模板化（缺核查表/无医嘱单/过敏空项/时限/诊断重复） | `paperless_cdms_oracle_10_10_10_93`（026 §1） | 026 文档 §1 SQL |

### 1.2 嘉和客户端与链路事实（引用嘉和工作区已落盘结论）

| # | 事实 | 证据位置 |
|---|---|---|
| F6 | JHEMR 客户端 = .NET Framework 4.x WinForms（JHEMRCentral.Win.exe + JHCommonLib/JHServicesLib/JHPubServicesLib），**无强名称签名**（IL 可改） | 嘉和 docs/09 |
| F7 | 客户端内嵌 CefSharp，启动加载 CDSS jssdk（`10.10.10.97/hm_static/jssdk/jssdk_cdss_4.0.js`）——用户已决策不走此通道 | 客户端 Config.xml；027 §1 |
| F8 | 嘉和自身有"保存/提交时点校验"框架：`JHMRFirstPages.dll` 的 `FirstPageValidateInfor`，受个性化参数 20250806SW03/20250815SW01 控制 | 嘉和 CHANGELOG 2026-08-25 |
| F9 | 官方旁路通道：`\\.\pipe\JHPipe` 命名管道（JHEMRInfoMonitor 官方跟踪器作服务端实时收客户端 SQL/事件）；客户端写入方字符串疑加密 | 嘉和 docs/27 §1.6 |
| F10 | 客户端副本 `C:\jh_emr_run` 可运行、可登录（D线实测）→ **AppDomainManager 实验具备现场条件**；360 会拦截新 exe/dll（需白名单） | 嘉和 CHANGELOG 2026-08-27 |
| F11 | EMR 主库=179:1521 Oracle（当前未开通，ORA-12547）；**177:5432 Vastbase（jhemr 库）为生产在用只读侧**（Med-Audit 六类质控每天在读）；HTTP 层（179:86 等）被防火墙拦截 | 嘉和 docs/24 §1、docs/27 §1.7；ai_mrzk 生产实践 |
| F12 | 医院自建集成先例：JHWebInterface(179:86) XML 配置分发器 + 视图 + 出站 POST | 嘉和 docs/24 |

### 1.3 Med-Audit 代码事实（探索代理 2026-08-27 核验）

| # | 事实 | 位置 |
|---|---|---|
| F13 | 现有数据源后端仅 oracle/postgresql/emr_vastbase 三种；**无 SQLServer/MySQL 驱动** | `app/services/config_parser.py:29-35`、`app/schemas.py:389-390` |
| F14 | Relay 企微支持按患者定向**主管/管床医师**（attending_doctor 规则，V_QYBR 兜底、ODS.V_AI_ZKUSER 反查 userid）。**注意：该通道验证的是管床医生映射，不是完成医生映射——完成医生（first_finished_doctor_id）→企微 userid 是本计划新工作（P0-6）**。D5 隔离要求下仅复制其 HMAC 协议实现，不改原服务 | `app/services/relay_alert_service.py:236-275,551-667` |
| F15 | 调度器支持 every_n_minutes（cron 化），任务体函数固定为 `_daily_push_job_v2`（执行哪些审计类型来自 audit_type_codes 配置，非硬编码六类）——结论不变：独立服务需自有调度循环，不动 scheduler.py | `app/schemas.py:141`、`app/scheduler.py:209-229` |
| F16 | 缺文书判定有代码先例：`push_skip_policy.get_surgery_chain_skip_reason` 按来源类别计数（术前/手术/术后 <2 类跳过） | `app/services/push_skip_policy.py:121-159` |

### 1.4 凭据边界

用户已提供 14 系统接口清单（含库型/IP/账号/视图/FTP）。**凭据不落仓库**：计划文档与代码只登记"系统名/IP/库名/视图名"，口令由信息科以受控方式配置到预检服务的加密配置（沿用 Fernet 加密体系），复核 AI 不得要求在文档中复述口令。

---

## 2. 总体架构

```text
[触发] 预检服务每 N 分钟（默认5）轮询 jhemr.pat_visit
        WHERE finished_date_time > <检查点>
        检查键 = (patient_id, visit_id, finished_date_time)：完成时间更新即重检（整改后再完成自动复检，A1）
          ↓ 每个新完成 (patient_id, visit_id, first_finished_doctor_id)
[采集] 并行只读查询：
        ① JHEMR: pat_visit(入院/出院/完成) + v_blws(文书清单+progress_status+时间字段)
        ② HIS  : T_ITF_HIS(条目) + 病案首页结构化表(空项/重复，位置P0-3确认)
        ③ 手麻 : T_ITF_SM(条目)      ④ LIS : vw_hisinter_t_itf_lis(条目)
[判定] 规则引擎（纯代码四类判定器，规则=配置文件）
        missing_doc / time_limit / empty_field / duplicate
        → 每 (patient,visit) 产出一份"预检结果"（独立表，含问题清单+对应评分项）
[触达] ① 企微推送：完成医生优先（first_finished_doctor_id → userid），工号缺失时管床医师兜底；
          可配置加主任/病案室；单患者单次合并一条（同一 result_id 只扰一次，双通道去重）
        ② JHEMR 强制弹窗（P2）：客户端独立 DLL 轮询/监听 → 置顶模态弹窗
[留存] 预检结果独立表；病案室签收视图列（P3）
```

**隔离边界（D5，round-1 强化）**：新代码全部在 **独立目录 `prearchive_service/`（仓库根一级，不进 `app/`）**，独立 requirements（`prearchive_service/requirements.txt`，**pyodbc 仅出现在此**）、独立配置文件、独立容器/镜像（部署时与 med-audit 主镜像分离）、独立结果表（`MED_PREARCHIVE_*`，DDL 脚本随码但不自动执行）。**禁止**：`import app.*` 任何现有模块（含 app.config/app.database——凭据解密逻辑独立实现或复制，不共享 SECRET_KEY）、修改 scheduler.py/main.py/relay_alert_service.py/requirements*.txt/Dockerfile。**HMAC 协议红线**：独立实现须带与 relay 服务的契约测试向量（同一签名样例双实现结果一致）；协议变更必须双改（登记维护红线）。

---

## 3. 规则固定化设计（无纸化规则 → 机器规则）

### 3.1 数据分层与可判范围

| 层 | 数据 | 支撑规则类型 | 一期覆盖（round-1 修正：仅保留四源有证据项） |
|---|---|---|---|
| 条目层 | T_ITF_*（F3 骨架，按源适配字段差异） | missing_doc | **手术文书族**（手麻 T_ITF_SM：核查表/手术护理单/术前术后文书）；**检验/检查报告族**（LIS） |
| 结构化层（JHEMR） | pat_visit + v_blws（模板名白名单过滤，防知情同意书误命中） | missing_doc + time_limit | 入院/出院记录缺失（v_blws 判，非 T_ITF）；入院记录超24h(51)/首次病程8h 等时限族 |
| 结构化层（HIS 首页，**硬闸门 P0-3④**） | 177 是否有首页同步副本待证 | empty_field / duplicate | **条件覆盖**：仅当 P0-3④ 证实可读——首页过敏药物未填(211+51)/出生地空项(52)/诊断重复(85)。177 无副本且 179 不开通 → 该族整族不上一期（明确降级，不留悬空） |
| **明确移出一期** | — | — | 体温单（护理系统无接口，四源永无证据）；首页性别属性错（026 B 类语义）；会诊单（P0-3⑥ 核实 CONSULTATION_ID 后定） |
| PDF 内容层 | 各源 PDF | 语义类 | **一期不做** |

### 3.2 规则 DSL（配置文件，每规则一条记录）

```json
{
  "rule_id": "R-MISS-SURGERY-CHECKTABLE",
  "mark_item_fid": 123,             // 对应 CDMS.t_mark_item.FID（质控科签字版）
  "name": "无手术安全核查表",
  "type": "missing_doc",
  "trigger": { "patient_has": "surgery", "surgery_evidence": "his_firstpage_operation | sm_itf_entry" },
  "expect": ["术前小结", "术前讨论", "手术记录", "手术安全核查表", "手术护理记录单", "术后首次病程"],
  "match": { "sources": ["sm_itf", "jhemr_blws"], "by": "report_name_fuzzy",
             "vocab": {"手术安全核查表": ["手术安全核查", "核查表"]},
             "exclude_vocab": ["知情同意书", "查房记录"],   // 负向词表：v_blws 误命中防护（A15）
             "template_field": "progress_template_name" },
  "severity": "medium",             // 映射：扣0.5分→low；1分→medium；过敏空项默认 medium（不走 High Gate，A13）
  "deduct_ref": 0.5,
  "enabled": true,                  // A2 规则治理字段组
  "version": "2026.08.27-qc-v1",    // 对应质控科签字版本
  "dept_codes": [],                 // 空=全院；科室差异化
  "exempt": {"scenes": ["自动出院", "姑息治疗", "日间手术"], "by": "pat_visit标志+配置"},
  "min_hours_after_event": 2,       // 时间窗：事件后 N 小时才检查，防“未出报告”误判（A2）
  "require_source_ready": true,     // 源水位前置：源未出报告不判缺
  "message": "缺《手术安全核查表》，归档前请补齐或确认"
}
```

四类判定器（引擎内置，规则只配参数）：
- `missing_doc`：trigger 谓词成立（患者有手术/输血/危急值等）→ expect 清单 ∪ 实有条目（词表模糊匹配）→ 缺失项即命中；
- `time_limit`：`文书完成时间(v_blws) - 事件时间(pat_visit入院/手术/HIS医嘱)` > 阈值（24h/8h/术后24h 等，卫生部书写规范 + 质控科口径）；
- `empty_field`：HIS 首页结构化字段 ∈ {NULL, ''} 黑名单值域（**'无' 不在黑名单**——临床「无过敏」为合法填写，A13；除非质控科对特定项明确口径）；
- `duplicate`：诊断/手术列表内规范化去重比对（名称归一：全半角/空格/序号剥离）。

### 3.3 规则生产流程

`t_mark_item` 全量（**实测 92 条且 FISENABLE=1 全启用**，P0-4 拉取，列名 FISENABLE 非 enabled）→ 逐条标注 A/B/C + 四类判定器映射 + 参数草案 → **质控科签字（版本号+日期）** → **签字完成后才允许编写规则配置文件（硬序，防凭经验固化）** → 生成规则配置文件入库（预检服务配置）→ 上线后按误报率迭代（调词表/阈值，不改代码）。**防猜测红线**：HIS 报告名编码字典、应备清单词表、时限阈值均以 P0 实测与质控科确认为准，不得凭经验假设。

---

## 4. JHEMR 强制提醒设计（D6：独立 DLL 一步到位）

### 4.1 首选A：外挂托盘助手（独立进程，失败域天然隔离）

- **机制**：每台工作站部署独立小托盘程序（嘉和官方同款先例：JHEMRInfoMonitor），常驻轮询预检服务 API（按本机登录医生）→ 检出问题时向 EMR 主窗口挂置顶对话框展示问题清单。**不加载进 EMR 进程、不碰嘉和任何文件**——助手崩溃/缺失/升级不协调时最多少弹窗，EMR 完全不受影响。
- **职责**：读配置（服务地址/开关）→ 轮询 → 置顶弹窗（owner=EMR 主窗句柄）→ 已知晓/去整改。
- **验证点**：弹窗线程编组（STA/Invoke，防卡死 UI）；主窗标题随版本变化的容错；360 白名单；取「当前登录医生工号」通道（客户端配置/登录脚本注入，P2-1 前置设计）。

### 4.2 候选B：AppDomainManager 独立 DLL（**待强命名复测，降级为候选**）

- **机制**：`JHEMRCentral.Win.exe.config` 追加 `<appDomainManagerType/appDomainManagerAssembly>` + 自签强命名 DLL。
- **round-1 实验结论（C:	empdm_test，证据见 review/round-1/证据.md）**：①config 通道对非强命名 DLL **静默忽略未生效**（本机无 sn.exe 未能测强命名）；②**环境变量通道真实生效且失败即崩溃**（TypeLoadException→进程 exit 127）——失败域为停诊级。
- **采用前置条件（全部满足才可试点）**：P0-5 强命名复测通过；**fail-open 设计强制**——任何部署残缺（DLL 缺失/损坏/版本不匹配）绝不允许阻断 EMR 启动（自愈脚本必须能删配置，而非只补）；「删 DLL 留 config」「DLL 损坏」两个专项验收通过。
- **DLL 内部职责**：同 4.1；另须全域 try-catch 自包裹 + 心跳自检，异常即自我禁用并写日志。

### 4.3 最后退化：最小 IL 注入（高运维等级，须信息科书面同意）

仅当 4.1/4.2 均不可行：一处注入 `Assembly.Load` + 独立业务 DLL。**升级覆盖 exe 需重打、360、合规责任与 4.2 相同且更重**——R7 的信息科书面同意范围必须显式覆盖本路线；措辞统一为「零修改程序集 IL」（exe.config 修改不属于零修改程序集）。

### 4.4 并行兜底：企微推送（P1 先行）

服务端完成即推（完成医生优先/管床兜底，独立实现），保证覆盖率；弹窗试点期双通道并存（同一 result_id 去重防双扰），稳定后企微降为夜间汇总。

---

## 5. 执行任务分解

### P0 只读核验（**技术项 3-5 天**；质控科签字与网络申请为并行外挂的人工依赖，不设死线、不阻塞技术项；全部 SELECT/副本实验，生产零接触）

| # | 任务 | 方法 | 验收标准 |
|---|---|---|---|
| P0-1 | **完成锚点延迟与完备性**：pat_visit.finished_date_time 在 177 副本是否及时/有值 | **主从比对优先（A20）**：申请 179:1521 只读，同患者 finished 值 177 vs 179 时间戳差即真实同步延迟；无纸化到达时间反推法仅作参考（混入病案室签收人工环节）；另核 NULL 率与索引存在性 | 延迟中位数/P95 量化成文；NULL 率<5% 或给出兜底锚点；反推法结果单独标注不确定性 |
| P0-2 | 四源连通矩阵（部署机视角） | 预检服务目标部署机（8.84 或新机）对 177/10.15/10.10.10.68/10.10.10.73 逐一连通+限量 SELECT；账号按 §1.4 边界申请（只读） | 矩阵表：源×连通×账号×驱动；不通项列网络申请单 |
| P0-3 | **值域与词表实测**（防猜测） | ①HIS REPORTNAME 0/1/2 编码字典（结合 FDESC 反推+信息科确认；0/1 条数相等疑成对生成，勿直接映射长/临时医嘱）；②手麻/LIS 报告名 DISTINCT 词表（近 90 天）；③v_blws.progress_status 值域与文书时间字段语义；④**HIS 首页表定位（升硬闸门 A5）**：177 有无首页同步副本实测，无且 179 不开通 → empty_field/duplicate/手术trigger 整族不上一期并成文；⑤JHEMR 文书名映射词表**含排除词表/模板名白名单（A15）**；⑥visit_id/visit_number/次数别名对齐核验（JHEMR↔V_QYBR↔无纸化 FBIHID/FBINCU，A18） | 六项产出成文，标注来源行数与置信度；④须出「上/不上」结论 |
| P0-4 | **规则映射表（关键闸门）** | 全量拉 t_mark_item（**FISENABLE=1，实测 92 条**）→ 逐条标注：A/B/C、判定器类型、数据源+字段、参数草案、严重度、豁免场景建议；产出《评分项-规则映射表 v1》 | 92 项 100% 覆盖标注；A 类配齐参数草案；**质控科签字**（版本号+日期）；签字前不得编写规则配置文件（硬序） |
| P0-5 | **提醒通道实验（关键闸门，B4 扩充）** | **前置：实验机装 Windows SDK 取 sn.exe**。在 `C:\jh_emr_run` 副本五组实验：①4.1 外挂助手原型（独立进程弹窗+EMR 主窗 owner）②AppDomainManager 强命名正测（config 通道）③**删 DLL 留 config** → 客户端必须仍能启动 ④**DLL 损坏/版本不匹配** → 同上 fail-open 验收 ⑤env 通道对照（已知崩溃，仅留证）；另验 CefSharp 子域与 Manager 继承冲突 | 五组结论+证据；确定首选路线（预期 4.1 胜出）；4.2 若采用必须全过③④ |
| P0-6 | **推送对象映射（A4/A20 重设计）** | 先测基线：first_finished_doctor_id 与 V_AI_ZKUSER 工号体系是否同源、近 30 天完成医生命中率分布；管床兜底链路（V_QYBR）命中率；再据此定阈值与顺序 | 基线分布成文；主/兜底两级链路命中率量化；阈值按基线设定（非先验 95%） |

### P1 独立预检服务（2-3 周）

| # | 任务 | 内容 | 验收标准 |
|---|---|---|---|
| P1-1 | 服务骨架 | **`prearchive_service/`（仓库根一级独立目录，A6）**：独立配置（加密凭据独立实现，不共享 SECRET_KEY）、调度循环（默认5min，锁防重入）、四源连接管理、健康端点；**零 import app.*** | 单元测试+fixture 源跑通；grep 断言无 `app.` 依赖通过 |
| P1-2 | 采集器 | 按锚点增量拉患者四源数据（限量/断路/超时），规范化为统一患者上下文 | 连续 3 天影子运行零异常 |
| P1-3 | 规则引擎 | 四类判定器 + 规则 DSL 加载/校验/版本化；命中产出问题清单（含评分项FID/严重度/整改话术） | 每条 A 类规则正反用例单测（含 026 TOP 高频项全覆盖） |
| P1-4 | 结果存储 | 独立表 `MED_PREARCHIVE_RESULT`：检查键 **(patient_id, visit_id, finished_date_time)**（A1 复检语义），每检一行留历史，最新行标记 current；推送状态/规则版本随行 | 表结构评审通过；复检语义单测；与六类质控表零耦合 |
| P1-5 | 企微推送 | HMAC 独立实现 + **契约测试向量（A8）**（与 relay_alert_service 对同一签名样例双实现比对一致）；接收人=完成医生优先/管床兜底（可配主任/病案室）；单患者合并一条 | 沙箱推送验证；接收人解析单测；契约测试通过留档 |
| P1-6 | 影子运行与调参（A12 两段式回测） | 生产只读跑 5-7 天不推送。回测两段式：(a) **归档后回测**——t_mark_main 已扣分病历（终末时点对齐）验证查全/查准；(b) **完成时刻影子**——抽样人工比对，不直接算 precision（终末≠完成时点）。**前置**：跨库 ID 对齐口径（FBIHID/FBINCU↔patient_id/visit_id）实测；PHI 不出无纸化库 | (a) 段 precision/recall 报告；(b) 段抽样一致性报告；误报率阈值质控科定 |
| P1-7 | 上线审批 | 按 023 §9.1 出批准单（环境/范围/数量/回滚点） | 批准单签核 |

### P2 强制弹窗 DLL（2-4 周，视 P0-5 与信息科沟通）

| # | 任务 | 内容 | 验收标准 |
|---|---|---|---|
| P2-1 | 提醒端开发 | 首选=4.1 外挂助手（或 4.2，视 P0-5）；置顶/主窗口 owner/问题清单渲染/自配置/**全域 try-catch 自禁用**；**服务端鉴权（A19）**：接口校验工号+科室+患者归属防冒用；**取当前登录工号通道**为开发前置；线程编组（STA/Invoke）与主窗标题变更稳定性专项测试 | 崩溃零容忍测试（服务断连/超时/异常数据/UI 编组/窗口找不到）；鉴权渗透用例 |
| P2-2 | 分发机制 | 登录脚本/域策略/信息科分发渠道 + exe.config 自愈 3 行 + 360 白名单清单 | 试点科室 100% 装机 |
| P2-3 | 试点 | 1-2 个科室 2 周：双通道（弹窗+企微）对照，收集医生接受度/打扰率/误报反馈 | 试点报告 → 全院推广决策 |
| P2-4 | 升级容忍演练 | 模拟嘉和客户端升级覆盖场景，验证自愈与 DLL 兼容性 | 演练记录 |

### P3 扩展（另行立项，不在本计划内）

全源接入（PACS/心电/病理/内镜/血透/电测听/气管镜/移动护理/输血）；B 类语义前置（接入 Dify 影子 V2 通道）；病案室签收视图列；金标准常态化回测。

---

## 6. 风险登记册

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | 177 副本对 finished 字段同步延迟/缺失（F2 两张完成日志表在副本为空是预警信号） | 高 | P0-1 量化；超阈值则申请 179:1521 只读账号（列网络申请） |
| R2 | 提醒端失败域：AppDomainManager env 通道失败=EMR 启动崩溃（round-1 实验证实停诊级） | **高**（round-1 升级） | 首选改 4.1 外挂助手（失败域隔离）；4.2 仅在强命名复测过+fail-open 双专项验收（删DLL留config/DLL损坏）全过后方可试点 |
| R3 | 嘉和客户端升级覆盖 exe.config/DLL | 中 | P2-2 自愈脚本；DLL 独立升级；升级容忍演练 P2-4 |
| R4 | HIS 报告名编码/词表与应备清单对不上（缺文书误报） | 中 | P0-3 实测词表 + 质控科签字 + P1-6 影子调参，误报率不达标不上线 |
| R5 | 提醒轰炸导致医生抵触 | 中 | 单患者单次合并；严重度降噪纪律（024/025 教训：默认 low/medium，红色仅安全类）；试点收集反馈 |
| R6 | 360/终端安全拦截 DLL | 中 | 白名单申请；试点先行 |
| R7 | 合规：在嘉和进程内运行自有代码 / IL 注入修改嘉和程序集 | 中 | 信息科书面同意为 P2 前置，**同意范围显式覆盖 4.1 外挂/4.2 AppDomainManager/4.3 IL 注入全部实际采用路线（A16）**；措辞统一「零修改程序集 IL」不作「零侵入」宣称 |
| R8 | 凭据扩散 | 低 | §1.4 边界：口令只进加密配置，不落仓库/文档 |
| R9 | 轮询给 177/HIS 源库加压 | 低 | 增量时间片+索引确认（P0-1）+限量；频率可配 |
| R10 | 预检结果含患者隐私 | 低 | 存 Med-Audit 应用库（与现六类结果同级）；弹窗/推送文案最小化（不带病历原文） |
| R11 | pyodbc 生产容器供应链：Linux 需 unixODBC + MS ODBC 驱动，现镜像不含（A7） | 中 | 独立镜像自行安装；或 LIS 采集改独立 sidecar 容器，主服务零新增原生依赖 |
| R12 | 多工作站/代签/夜班：完成医生≠本机登录医生≠主管医师，责任人错位（A10） | 中 | P0-6 基线定推送顺序；弹窗按患者维度而非仅登录医生；代签场景推送主管医师兜底 |
| R13 | 服务单点：预检服务宕机=全院静默失效，无人察觉（A10） | 中 | 自监控心跳：服务停跳即经 relay 通道反向告警病案室；DLL/助手端显示"服务不可达"状态 |
| R14 | 嘉和厂商升级清除/发现外挂或补丁（A10） | 中 | 4.1 外挂不碰嘉和文件，被清除面最小；与信息科建立升级通报机制；升级容忍演练 P2-4 |
| R15 | 与无纸化采集数据竞争：T_ITF 条目晚于完成时刻到达→系统性误判缺文书；四源跨库时钟偏差（A10/A2） | 中 | min_hours_after_event 时间窗+require_source_ready 水位前置；跨源时钟偏差实测入 P0-3 |
| R16 | 弹窗时机安全：抢救/危急值处置中被模态打断（A10） | 中 | 弹窗默认可延迟非阻塞全屏；夜班时段（可配）降级为企微；打断策略进试点评估 |

---

## 7. 与既有体系的关系

- 现有六类 Dify 质控：**零改动**（D5）；预检是新增独立轨道，互补关系（预检=归档前缺陷检查，六类=跨文书语义一致性）。
- **从属声明（A17）：本计划从属 `docs/ACTIVE/023`（唯一执行入口），023 获批前不得开工 P1/P2 的任何生产动作；本文件不是平行执行入口。**
- 023 §9.1：P1 上线（新服务、新表、推送开闸）与 P2 试点均需批准单。
- 026：规则来源与严重度映射依据；027：对接路径评估依据（本计划吸收其 R1/F1 通道结论并按用户 D6 决策收敛为 DLL 方案）。
- 嘉和工作区：P0-5 实验在其副本环境执行，遵守该仓库只读红线（实验产物放 C:\temp/jh_emr_run 约定目录）。

## 8. 交付物清单

P0：①延迟与完备性报告 ②四源连通矩阵 ③词表/字典四份 ④《评分项-规则映射表 v1》（质控科签字）⑤AppDomainManager 实验报告 ⑥推送映射核验记录。
P1：独立预检服务（代码+测试+规则配置 v1+影子运行报告+precision/recall 报告+批准单）。
P2：提醒 DLL+分发方案+试点报告+升级容忍演练记录。
全部变更登记 `开发起步包/01_统一修改记录.md`。

## 9. 复核 AI 核查清单（只读；逐项出结论）

1. **事实核验**：用 §1.1 给出的 sjzc live SQL 复跑 F1-F5（字段存在性/编码值域/量级），比对是否一致；抽查 F6-F12 在嘉和工作区 docs 的出处。
2. **决策一致性**：§0 六项决策与用户会话原话是否一致（用户提供接口清单、四轮 AskUserQuestion 答案、IL 补丁追问）。
3. **隔离完备性**：§2 架构是否真正做到零改动现有六类链路（对照 F13-F15 代码位置检查是否存在被遗漏的共享点，如日志器、DB 会话池、配置加载器）。
4. **规则设计合理性**：§3 四类判定器是否覆盖 026 §2 的 A 类全部模式；DSL 是否遗漏必要字段（如豁免机制/规则启停/科室差异化）；"防猜测"是否落实（P0-3 是否覆盖全部值域依赖）。
5. **强制提醒可行性**：§4.1 AppDomainManager 机制描述是否准确（Fx4.x 对强命名/GAC/全信任的要求，复核 AI 应给出独立技术判断）；退化方案是否完备。
6. **风险完备性**：§6 是否遗漏（复核 AI 至少评估：多院区/多工作站登录态、夜班完成场景、患者隐私在弹窗的暴露面、服务单点、嘉和厂商发现后的反应、与无纸化采集的数据竞争）。
7. **任务可执行性**：P0 各项验收标准是否可客观判定；工期估计是否合理。
8. **输出**：四张清单（同意/不同意/证据不足须人工/新问题），不执行任何写入。

---

## 10. 修订记录

| 版本 | 日期 | 修订人 | 内容 |
|---|---|---|---|
| v1 | 2026-08-27 | ZCode/GLM-5.3 | 初版（编制） |
| v2 | 2026-08-27 | ZCode/GLM-5.3 | 按 multi-review round-1（Kimi 21条/Grok 39条/Codex 5条，四方在场无缺席，产物 `review/round-1/`）的 24 项修订指令更新：A1 复检闭环（去重键含 finished_date_time）；A2 DSL 增治理五字段（enabled/version/dept_codes/exempt/min_hours_after_event/require_source_ready）；A3 一期覆盖重排（体温单/首页性别属性移出，首页族条件覆盖）；A4 触达对象收敛（完成医生优先/管床兜底）；A5 首页表硬闸门+整族降级；A6 隔离强化（独立目录/独立requirements/禁import app.*）；A7 R11 ODBC供应链；A8 HMAC契约测试；A9 P0工期外挂人工依赖；A10 R12-R16 入册；A11 目标句去拦截式宣称；A12 回测两段式+跨库ID对齐；A13 '无'剔除黑名单；A14 性别属性移出一期；A15 负向词表；A16 R7覆盖IL路线；A17 023从属声明；A18 visit别名核验；A19 DLL服务端鉴权；A20 P0-1/P0-6 方法重设计；B1 F3修正（LIS=FDESCNUM/dbo）；B2 F15措辞；B3 F14范围修正；B4 AppDomainManager降级候选+R2升高（本机实验：env通道崩溃证实）+4.1外挂恢复首选+P0-5五组实验。 |

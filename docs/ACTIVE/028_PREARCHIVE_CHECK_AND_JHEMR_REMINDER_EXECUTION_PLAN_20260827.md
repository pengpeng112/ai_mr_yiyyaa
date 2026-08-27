# 归档前病历预检与 JHEMR 强制提醒——执行计划（待独立复核）

> 文档编号：028
> 编制日期：2026-08-27
> 性质：**执行计划 + 待复核**；本文档不授权任何生产写入；P0 全部任务只读
> 编制者：ZCode/GLM-5.3（基于 026/027 分析与用户四轮决策确认）
> 复核对象：本计划的**事实基础、方案设计、任务分解、风险完备性**；复核 AI 按 §9 清单逐项核查并出四张清单（同意/不同意/证据不足须人工/新问题）
> 上游文档：`026_PAPERLESS_MANUAL_QC_TO_AI_FEASIBILITY_20260827.md`（规则来源与分类）、`027_JHEMR_SUBMISSION_REMINDER_INTEGRATION_20260827.md`（对接路径评估）
> 外部证据库：`D:\Users\Administrator\Desktop\嘉和`（嘉和系逆向分析工作区，只读引用其 docs 与 CHANGELOG）

---

## 0. 一页摘要（目标与已定决策）

**目标**：把质控从"病案室/医护事后打回"前置到**医生点击病历完成（待归档）时**——基于无纸化人工质控评分项（CDMS `t_mark_item`）的 A 类确定性规则，直读各系统提供给无纸化的同款 T_ITF_* 视图与 JHEMR 结构化表，发现缺文书/时限/空项/重复问题，强制提醒医生当场整改；现有六类 Dify 一致性质控**零改动**。

**用户已确认的六项决策**（2026-08-27 会话）：

| # | 决策 | 内容 |
|---|---|---|
| D1 | 提醒对象 | 默认主管医师；**可配置**扩展科主任与病案室 |
| D2 | 一期数据源 | 核心源先行：JHEMR 病历 + HIS 医嘱/首页 + 手麻 + LIS |
| D3 | 触发时点 | 病历完成即查即推（轮询触发锚点，分钟级） |
| D4 | 一期规则 | 仅 A 类确定性规则（纯代码，不调 Dify）；B 类语义维持每日批 |
| D5 | 部署隔离 | **独立服务隔离**：新模块+独立进程/容器、独立表、独立配置；零改动现有六类质控代码路径与 relay_alert_service |
| D6 | 强制提醒形态 | **独立 DLL 一步到位**（首选 AppDomainManager 机制，零修改嘉和程序集；IL 最小注入为退化方案；企微推送并行兜底）。不走 CDSS 通道 |

---

## 1. 事实基础（全部可独立复核；标注来源与复核方法）

### 1.1 已 live 只读实证（sjzc 技能，2026-08-27）

| # | 事实 | 来源 | 复核方法 |
|---|---|---|---|
| F1 | **触发锚点存在**：`jhemr.pat_visit` 含 `finished_date_time`、`first_finished_doctor_id`、`first_finished_date_time`、`first_page_submit_date/user_id`、`mr_submitnurse_record_*`（提交护士四字段） | `jhemr_vastbase_10_10_8_177` information_schema | `sjzc live jhemr_vastbase_10_10_8_177 --sql "SELECT column_name FROM information_schema.columns WHERE table_schema='jhemr' AND table_name='pat_visit' AND column_name ~ '(?i)(finish|submit)'"` |
| F2 | `mr_finished_index_callback`（18列，申请/审批流）与 `recordfinished_oper_log`（6列：patient_id/visit_id/operating_time/operating_name/operating_id/status）**存在但 177 副本上 0 行** | 同上 | 同款 SELECT COUNT(*) 两表 |
| F3 | T_ITF 条目层统一骨架（HIS/手麻/LIS 三源一致）：`FID/PATIENTID/FBIHID/FBINCU/报告名(REPORTNAME或FITEMNAME)/FDESC/PDFNAME/PDFPATH/FCKDATE/FUPDATE/FLOADDATE/FREPORTSTYLE/PAGECOUNT` | `his_source_10_10_10_15`（PAPERLESS.T_ITF_HIS，14列）、`docare_oracle_10_10_10_68`（MEDSURGERY.T_ITF_SM，13列）、`lis_sqlserver_10_10_10_73`（RMCLOUDLIS7.vw_hisinter_t_itf_lis，13列） | 各源 all_tab_columns / INFORMATION_SCHEMA.COLUMNS |
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
| F14 | Relay 企微已支持按患者定向主管医师（attending_doctor 规则，V_QYBR 兜底、ODS.V_AI_ZKUSER 反查 userid）——**D6 隔离要求下仅复制其 HMAC 协议实现，不改原服务** | `app/services/relay_alert_service.py:236-275,551-667` |
| F15 | 调度器支持 every_n_minutes（cron 化），但任务体固定为六类全链路——独立服务需自有调度循环（不动 scheduler.py） | `app/schemas.py:141`、`app/scheduler.py:209-229` |
| F16 | 缺文书判定有代码先例：`push_skip_policy.get_surgery_chain_skip_reason` 按来源类别计数（术前/手术/术后 <2 类跳过） | `app/services/push_skip_policy.py:121-159` |

### 1.4 凭据边界

用户已提供 14 系统接口清单（含库型/IP/账号/视图/FTP）。**凭据不落仓库**：计划文档与代码只登记"系统名/IP/库名/视图名"，口令由信息科以受控方式配置到预检服务的加密配置（沿用 Fernet 加密体系），复核 AI 不得要求在文档中复述口令。

---

## 2. 总体架构

```text
[触发] 预检服务每 N 分钟（默认5）轮询 jhemr.pat_visit
        WHERE finished_date_time > <检查点> AND (去重: 同 patient+visit 只检一次)
          ↓ 每个新完成 (patient_id, visit_id, first_finished_doctor_id)
[采集] 并行只读查询：
        ① JHEMR: pat_visit(入院/出院/完成) + v_blws(文书清单+progress_status+时间字段)
        ② HIS  : T_ITF_HIS(条目) + 病案首页结构化表(空项/重复，位置P0-3确认)
        ③ 手麻 : T_ITF_SM(条目)      ④ LIS : vw_hisinter_t_itf_lis(条目)
[判定] 规则引擎（纯代码四类判定器，规则=配置文件）
        missing_doc / time_limit / empty_field / duplicate
        → 每 (patient,visit) 产出一份"预检结果"（独立表，含问题清单+对应评分项）
[触达] ① 企微推送：完成医生（first_finished_doctor_id → userid 映射），
          可配置加主任/病案室；单患者单次合并为一条汇总（防轰炸）
        ② JHEMR 强制弹窗（P2）：客户端独立 DLL 轮询/监听 → 置顶模态弹窗
[留存] 预检结果独立表；病案室签收视图列（P3）
```

**隔离边界（D5）**：新代码全部在 `app/prearchive/`（或独立目录），自有：调度循环、DB 连接管理（cx_Oracle/psycopg2/pyodbc——pyodbc 为新增依赖且仅新模块引用）、结果表（前缀 `MED_PREARCHIVE_*`）、配置节（`prearchive`）、推送实现（HMAC relay 协议独立实现）。**禁止**：import 或修改现有六类链路模块、改 scheduler.py 注册、改 relay_alert_service.py、复用 push_log 表结构（新表）。

---

## 3. 规则固定化设计（无纸化规则 → 机器规则）

### 3.1 数据分层与可判范围

| 层 | 数据 | 支撑规则类型 | 一期覆盖的典型评分项（026 高频实证） |
|---|---|---|---|
| 条目层 | T_ITF_*（F3 骨架） | missing_doc | 无手术安全核查表(92)/无手术护理单(41)/无长期医嘱单(89)/无临时医嘱单(78)/无体温单(36)/无会诊单(34)/无入院记录(43)/无出院记录(33) |
| 结构化层 | pat_visit + v_blws + HIS 首页表 | time_limit / empty_field / duplicate | 入院记录超24h(51)/首页过敏药物未填(211+51)/入院记录出生地空项(52)/出院诊断重复(85)/首页性别等属性错 |
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
             "vocab": {"手术安全核查表": ["手术安全核查", "核查表"], "...": "…P0-3词表"} },
  "severity": "medium",             // 映射：扣0.5分→low；1分→medium；过敏/身份类→按High Gate
  "deduct_ref": 0.5,
  "message": "缺《手术安全核查表》，归档前请补齐或确认"
}
```

四类判定器（引擎内置，规则只配参数）：
- `missing_doc`：trigger 谓词成立（患者有手术/输血/危急值等）→ expect 清单 ∪ 实有条目（词表模糊匹配）→ 缺失项即命中；
- `time_limit`：`文书完成时间(v_blws) - 事件时间(pat_visit入院/手术/HIS医嘱)` > 阈值（24h/8h/术后24h 等，卫生部书写规范 + 质控科口径）；
- `empty_field`：HIS 首页结构化字段 ∈ {NULL, '', '无'} 黑名单值域；
- `duplicate`：诊断/手术列表内规范化去重比对（名称归一：全半角/空格/序号剥离）。

### 3.3 规则生产流程

`t_mark_item` 全量（~92项，P0-4 拉取）→ 逐条标注 A/B/C + 四类判定器映射 + 参数草案 → **质控科签字（版本号）** → 生成规则配置文件入库（预检服务配置）→ 上线后按误报率迭代（调词表/阈值，不改代码）。**防猜测红线**：HIS 报告名编码字典、应备清单词表、时限阈值均以 P0 实测与质控科确认为准，不得凭经验假设。

---

## 4. JHEMR 强制提醒设计（D6：独立 DLL 一步到位）

### 4.1 首选：AppDomainManager 独立 DLL（零修改嘉和程序集）

- **机制**：.NET Framework 支持在应用配置 `<runtime>` 节指定 `appDomainManagerType` + `appDomainManagerAssembly`——把自研强命名 DLL 放客户端目录、在 `JHEMRCentral.Win.exe.config` 追加 3 行，我们的代码即随客户端默认 AppDomain 启动。
- **DLL 内部职责**：读自身配置（服务地址/开关/医生映射）→ 后台线程轮询预检服务 API（按本机登录医生）或监听完成事件 → 检出问题时向 EMR 主窗口句柄挂**置顶模态对话框**（FindWindow 主窗体为 owner = 真强制）展示问题清单 + "去整改/已知晓"。
- **已知风险与验证点（P0-5）**：①AppDomainManager 在 Fx4.x 对程序集要求（强命名可自签；app-dir 全信任 vs GAC 需实测）；②exe.config 会被嘉和升级安装器覆盖（对策：分发脚本/登录脚本自愈 3 行；或机器级配置）；③360 白名单；④UI 挂钩稳定性（不用 UI 注入，只用窗口句柄弹窗，规避控件树脆弱性）。

### 4.2 退化：最小 IL 注入（若 4.1 实验失败）

仅在一处（如 JHEMRCentral.Win.exe 入口 Main 或 JHCommonLib 初始化点）注入 `Assembly.Load("JHPreCheckReminder")` + 反射调用——**业务全部在独立 DLL**，升级仅需重打 1 个注入点。嘉和无强名称（F6），技术上无障碍；维护成本高于 4.1，低于全量补丁。

### 4.3 并行兜底：企微推送（P1 先行）

服务端完成即推（F14 的定向逻辑独立实现），保证覆盖率；DLL 试点期双通道并存，稳定后企微降为夜间汇总。

---

## 5. 执行任务分解

### P0 只读核验（3-5 天；全部 SELECT/副本实验，生产零接触）

| # | 任务 | 方法 | 验收标准 |
|---|---|---|---|
| P0-1 | **完成锚点延迟与完备性**：pat_visit.finished_date_time 在 177 副本是否及时/有值 | 取近 30 天完成病历样本：177 值分布、NULL 率；与无纸化 T_MSS_ITFVIEW 到达时间/病案签收时间比对推出端到端延迟；确认 `finished_date_time` 有无索引（无则轮询 SQL 用 ROWNUM/时间片限流） | 延迟中位数/P95 量化成文；NULL 率<5% 或给出兜底锚点（first_finished_date_time） |
| P0-2 | 四源连通矩阵（部署机视角） | 预检服务目标部署机（8.84 或新机）对 177/10.15/10.10.10.68/10.10.10.73 逐一连通+限量 SELECT；账号按 §1.4 边界申请（只读） | 矩阵表：源×连通×账号×驱动；不通项列网络申请单 |
| P0-3 | **值域与词表实测**（防猜测） | ①HIS REPORTNAME 0/1/2 编码字典（结合 FDESC 文本反推+信息科确认）；②手麻/LIS 报告名 DISTINCT 词表（近 90 天）；③v_blws.progress_status 值域与文书时间字段语义；④HIS 首页结构化表定位（候选：V_HISshouye 族在 179 本机——177 是否有同步副本需实测，无则列 P0-2 网络申请）；⑤JHEMR 文书名与应备清单的映射词表 | 四份词表/字典成文，标注来源行数与置信度 |
| P0-4 | **规则映射表（关键闸门）** | 全量拉 t_mark_item（enabled=1）→ 逐条标注：A/B/C、判定器类型、数据源+字段、参数草案、严重度；产出《评分项-规则映射表 v1》 | 92 项 100% 覆盖标注；A 类（预计 40~60 项）配齐参数草案；**质控科签字**（版本号+日期） |
| P0-5 | **AppDomainManager 实验（关键闸门）** | 在 `C:\jh_emr_run` 副本：自签强命名测试 DLL（写日志文件+弹一个测试窗）→ exe.config 加 3 行 → 启动副本 → 验证加载与弹窗；失败则做最小 IL 注入实验 | 实验报告：可行/不可行+证据截图/日志；确定 4.1 或 4.2 路线 |
| P0-6 | 推送映射核验 | first_finished_doctor_id（嘉和工号）→ 企微 userid 映射链路核验（复用 V_AI_ZKUSER 思路只读验证覆盖率） | 映射命中率>95% 成文，否则列人工兜底 |

### P1 独立预检服务（2-3 周）

| # | 任务 | 内容 | 验收标准 |
|---|---|---|---|
| P1-1 | 服务骨架 | `app/prearchive/`：配置加载（加密凭据）、调度循环（默认5min，锁防重入）、四源连接管理（pyodbc 仅此模块）、健康端点 | 单元测试+本地 fixture 源跑通 |
| P1-2 | 采集器 | 按锚点增量拉患者四源数据（限量/断路/超时），规范化为统一患者上下文 | 连续 3 天影子运行零异常 |
| P1-3 | 规则引擎 | 四类判定器 + 规则 DSL 加载/校验/版本化；命中产出问题清单（含评分项FID/严重度/整改话术） | 每条 A 类规则正反用例单测（含 026 TOP 高频项全覆盖） |
| P1-4 | 结果存储 | 独立表 `MED_PREARCHIVE_RESULT`（患者/住院次/完成时间/问题JSON/推送状态/规则版本）；去重约束 patient+visit 唯一 | 表结构评审通过；与六类质控表零耦合 |
| P1-5 | 企微推送 | HMAC relay 协议独立实现；接收人=完成医生（可配主任/病案室）；单患者合并一条 | 沙箱推送验证；接收人解析单测 |
| P1-6 | 影子运行与调参 | 生产数据只读跑 5-7 天不推送，比对人工质控命中（用 t_mark_main 2026 已知扣分病历回测） | precision/recall 报告（026 §5 金标准回流落地）；误报率达标（目标：A类规则误报<10%，由质控科定阈值） |
| P1-7 | 上线审批 | 按 023 §9.1 出批准单（环境/范围/数量/回滚点） | 批准单签核 |

### P2 强制弹窗 DLL（2-4 周，视 P0-5 与信息科沟通）

| # | 任务 | 内容 | 验收标准 |
|---|---|---|---|
| P2-1 | DLL 开发 | 弹窗/置顶/主窗口 owner/问题清单渲染/自配置/静默失败（预检服务不可达绝不影响病历书写） | 崩溃零容忍测试（服务断连/超时/异常数据） |
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
| R2 | AppDomainManager 因全信任/强名称要求不通 | 中 | P0-5 副本实验先行闸门；退化路线 4.2 已备 |
| R3 | 嘉和客户端升级覆盖 exe.config/DLL | 中 | P2-2 自愈脚本；DLL 独立升级；升级容忍演练 P2-4 |
| R4 | HIS 报告名编码/词表与应备清单对不上（缺文书误报） | 中 | P0-3 实测词表 + 质控科签字 + P1-6 影子调参，误报率不达标不上线 |
| R5 | 提醒轰炸导致医生抵触 | 中 | 单患者单次合并；严重度降噪纪律（024/025 教训：默认 low/medium，红色仅安全类）；试点收集反馈 |
| R6 | 360/终端安全拦截 DLL | 中 | 白名单申请；试点先行 |
| R7 | 合规：在嘉和进程内运行自有代码 | 中 | 信息科书面同意为 P2 前置；侵入性论证（零修改程序集）随申请材料 |
| R8 | 凭据扩散 | 低 | §1.4 边界：口令只进加密配置，不落仓库/文档 |
| R9 | 轮询给 177/HIS 源库加压 | 低 | 增量时间片+索引确认（P0-1）+限量；频率可配 |
| R10 | 预检结果含患者隐私 | 低 | 存 Med-Audit 应用库（与现六类结果同级）；弹窗/推送文案最小化（不带病历原文） |

---

## 7. 与既有体系的关系

- 现有六类 Dify 质控：**零改动**（D5）；预检是新增独立轨道，互补关系（预检=归档前缺陷检查，六类=跨文书语义一致性）。
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

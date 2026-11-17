# 121 · 危急值系统推送对接与 JHEMR 临床引用双路赋能技术规范

> 建立日期：2026-11-14
> 状态：**现役接口与架构契约（方案已拍板，待危急值厂商联调与生产授权落地）**
> 关联专项：[062 病历时效质控执行指针](../ACTIVE/062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md)、[05 病历时效质控设计指针](../../开发起步包/05_病历时效质控设计指针.md)
> 安全红线：本文档为接口契约与工程实现规范，**不构成对 `10.10.8.177`（JHEMR/JHCDR）生产库的直接写入授权**；任何对 `jhcdr` 或 `jhemr` 表的 UPDATE/INSERT 及 DBA `GRANT` 操作，均须在联调前提交独立待审 SQL 经用户明确说“同意执行”后方可启用。严禁在文档、代码或配置中写入明文密码或真实患者隐私信息（PHI）。

---

## 一、总体架构拍板（「84 统一接数 + 双路赋能」）

### 1.1 背景与现网核查事实
1. 《住院病历时效节点信息化锁定管理规定（试行）》要求：**危急值病程记录须在“临床接收危急值时间”起算 6 小时内完成审签，超时触发锁定（对应 JHEMR 监控字典码 `JH04.03.016`）**。
2. 2026-11-14 现网只读核查确认：嘉和电子病历主库（`10.10.8.177:5432/jhemr`）自带的 `jhemr.jhcriticalvalues` 与 `jhemr.jhcriticalvalues_msg` 近 30 天均为 **0 行**（院内独立危急值管理平台未向 JHEMR 推送数据）。
3. 经对 JHEMR 客户端程序集（`JHEMR.JHCommon.UI.CriticalValues.dll`、`JHEMR.UI.UserControls.InPat.dll`）及数据同步配置（`DataSynchroTools` `TableColumnsConfig.XML`）静态反编译核实，嘉和内部存在两套成熟的危急值展示与写回病历机制。

### 1.2 三步闭环架构流向
用户已正式拍板采用 **「10.10.8.84（`ai_mrzk`）统一接数 + 双路赋能」** 架构，避免危急值厂商同时对接多套异构老系统：

```
┌──────────────────────┐
│  医院危急值管理平台   │ (或 LIS / PACS / 心电危急值源)
└──────────┬───────────┘
           │ 第一步：HTTP Webhook 实时推送标准 JSON（备选：只读视图每2分钟拉取）
           ▼
┌─────────────────────────────────────────────────────────────────┐
│             10.10.8.84 (ai_mrzk 病历质控中心)                    │
│  POST /api/timeliness/webhooks/critical-value                   │
│  1. 鉴权 + 幂等落库（按 crisis_id 维护事件状态机）               │
│  2. 触发时效引擎（CRISIS_VAL_6H）                                │
└───────────────┬─────────────────────────────────┬───────────────┘
                │ 第二步：6h 时效预警与病历锁定     │ 第三步：临床引用数据回填（经审批开启）
                ▼                                 ▼
┌───────────────────────────────┐ ┌────────────────────────────────────────────┐
│ 1. 企微提前预警（Relay 推送）  │ │ 通道一（首选）：更新 177 库 jhcdr 检验/检查表 │
│ 2. 超 6h 未签：外插 177 库     │ │   → 医生站右侧报告面板自动标红 + 右键写回病历 │
│    jhemr.jhpat_visit_doc_state│ │ 通道二（可选）：写入 jhemr.jhcriticalvalues_msg│
│    (monitor_code=JH04.03.016) │ │   → 「患者危急值管理」面板 + 一键创建病程草稿 │
│ 3. 医生审签病程后自动检测消锁  │ └────────────────────────────────────────────┘
└───────────────────────────────┘
```

---

## 二、对外联调规范：危急值系统推送接口（可直接发给危急值厂商）

> 以下 §2.1～§2.5 可原样复制发给危急值系统厂商作为联调技术规范。

### 2.1 对接目标与推送触发时机
请在危急值生命周期的以下 **3 个节点** 实时触发 HTTP 推送（同一条危急值全程使用同一个 `crisis_id`，质控中心按 `crisis_id` 幂等更新）：
1. **`REPORTED`（医技发布危急值时）**：推送危急值项目与结果，供电子病历右侧检验/检查面板实时标红展示；
2. **`RECEIVED`（临床护士/医生确认接收时，【必推核心节点】）**：推送临床接收时间与接收人，正式启动“临床接收后 6 小时内完成病程记录审签”倒计时；
3. **`CANCELLED`（医技撤销/误报召回时）**：推送撤销状态，质控中心自动终止倒计时并解除未消锁事件。
*(注：若贵方系统还有“临床处置完成 `HANDLED`”节点，也可一并推送更新 `deal_content`，非强制。)*

### 2.2 接口协议、鉴权与重试要求
- **请求地址**：`POST http://10.10.8.84:8000/api/timeliness/webhooks/critical-value`
- **请求头（Headers）**：
  - `Content-Type: application/json; charset=utf-8`
  - `X-Webhook-Token: <医院信息科分配的固定密钥 Token，存于 ai_mrzk Fernet 加密配置或环境变量，严禁明文入库>`
- **超时与重试要求**：
  - 连接/读取超时建议设为 `5 秒`；
  - 若返回 HTTP 状态码非 `200` 或响应 JSON 中 `code != 0`，请按 **1 分钟、5 分钟、15 分钟** 退避重试至少 3 次；
  - 接口严格按 `crisis_id` 幂等处理，重复推送不会产生重复锁记录。

### 2.3 请求 JSON 字段定义

#### （1）顶层字段（事件、患者与接收信息）
| 字段名 | 类型 | 必填 | 说明与取值规范 |
| :--- | :--- | :---: | :--- |
| `crisis_id` | string | **是** | 危急值记录全局唯一主键（幂等键，同一事件多次状态变更保持一致） |
| `event_status` | string | **是** | 事件状态枚举：`REPORTED`（已发布）/ `RECEIVED`（临床已接收）/ `HANDLED`（已处置）/ `CANCELLED`（已撤销） |
| `source_type` | string | **是** | 来源分类枚举：`LAB`（检验）/ `EXAM`（放射/超声/内镜等检查）/ `ECG`（心电）/ `PATHOLOGY`（病理）/ `OTHER` |
| `visit_type` | string | **是** | 就诊类型枚举：`INP`（住院）/ `OUTP`（门诊）/ `EMERG`（急诊）。*（病历时效锁定仅针对 `INP`）* |
| `patient_id` | string | **是** | HIS / 电子病历患者主索引 `PATIENT_ID`（必须与 HIS `PATS_IN_HOSPITAL.PATIENT_ID` 一致） |
| `visit_id` | int | **是** | 住院次数 `VISIT_ID`（必须与 HIS 住院次数一致，如 `1`）；若贵方系统仅存住院号，请至少保证 `inp_no` 准确 |
| `inp_no` | string | 条件必填 | 住院号（病案号），当无法提供 `visit_id` 时必填，用于质控中心反查在院记录 |
| `patient_name` | string | **是** | 患者姓名 |
| `sex` | string | 否 | 性别（`男` / `女`） |
| `bed_no` | string | 否 | 床号（如 `012`） |
| `dept_code` | string | **是** | 患者当前所在临床科室编码（与 HIS 科室字典一致） |
| `dept_name` | string | **是** | 患者当前所在临床科室名称 |
| `order_no` | string | 条件必填 | 对应 HIS 医嘱号（检验/检查申请关联的医嘱号，用于关联电子病历报告，有则必传） |
| `report_no` | string | **是** | 检验报告单号（LIS `report_no`）或检查报告单号（PACS `exam_no`），用于精准回填电子病历报告标红 |
| `sample_no` | string | 否 | 检验标本号（检验类建议传） |
| `sample_name` | string | 否 | 标本名称（如 `静脉血`、`动脉血`，检验类建议传） |
| `report_time` | string | **是** | 危急值发布/报告时间，格式严格为 `YYYY-MM-DD HH:mm:ss` |
| `report_dept_name` | string | 否 | 发布医技科室名称（如 `检验科`、`放射科`） |
| `report_doctor_name` | string | 否 | 发布/审核技师或医师姓名 |
| `receive_time` | string | **RECEIVED必填** | **临床确认接收时间**（`YYYY-MM-DD HH:mm:ss`），6 小时病历锁定的核心起算时间点 |
| `receive_user_code` | string | **RECEIVED必填** | 临床接收人工号（医院标准 6 位工号，如 `001234`） |
| `receive_user_name` | string | **RECEIVED必填** | 临床接收人姓名 |
| `target_doctor_code` | string | 否 | 通知/流转的临床责任医师工号（6 位工号，若危急值系统内护士已指定转交医生则传，用于精准企微提醒） |
| `target_doctor_name` | string | 否 | 通知/流转的临床责任医师姓名 |
| `deal_content` | string | 否 | 危急值系统内填写的临床初步处置说明 |
| `cancel_reason` | string | 否 | 当 `event_status = CANCELLED` 时的撤销原因 |
| `items` | array | **是** | 危急值具体项目明细数组（至少 1 项，见下表） |

#### （2）`items[]` 数组元素字段（支持单张报告含多个危急值指标）
| 字段名 | 类型 | 必填 | 说明与取值规范 |
| :--- | :--- | :---: | :--- |
| `exam_or_panel_name` | string | **是** | 检验组合名称或检查部位项目名（如 `急诊生化`、`血气分析`、`颅脑CT平扫`） |
| `item_code` | string | 条件必填 | 检验子项编码（对应 LIS 明细项目编码 `item_code`，检验类必传，用于精准点亮电子病历该行指标标红） |
| `item_name` | string | **是** | 危急值具体项目名称（如 `血清钾`、`白细胞计数`；检查类可填 `检查诊断结论`） |
| `result_value` | string | **是** | 危急值结果值或检查危急所见文本（如 `6.85` 或 `右侧大量气胸，肺压缩约80%`） |
| `unit` | string | 否 | 结果单位（如 `mmol/L`、`×10^9/L`，检查类可为空） |
| `ref_range` | string | 否 | 正常参考范围（如 `3.50-5.30`） |
| `abnormal_flag` | string | 否 | 异常标志（如 `↑↑`、`↓↓`、`危急过高`、`阳性`） |
| `alert_prompt` | string | 否 | 危急值提示语（如 `危急值高限(>6.20)`） |

### 2.4 标准请求与响应报文示例（脱敏合成样例）

- **请求报文示例**：
```json
{
  "crisis_id": "CV2026111500089",
  "event_status": "RECEIVED",
  "source_type": "LAB",
  "visit_type": "INP",
  "patient_id": "0009876543",
  "visit_id": 1,
  "inp_no": "26098765",
  "patient_name": "测试患者",
  "sex": "男",
  "bed_no": "015",
  "dept_code": "10102",
  "dept_name": "心血管内科一病区",
  "order_no": "2026111508812",
  "report_no": "LIS202611150331",
  "sample_no": "202611150092",
  "sample_name": "静脉血",
  "report_time": "2026-11-15 09:12:05",
  "report_dept_name": "医学检验科",
  "report_doctor_name": "测试技师",
  "receive_time": "2026-11-15 09:15:30",
  "receive_user_code": "002345",
  "receive_user_name": "测试护士",
  "target_doctor_code": "001122",
  "target_doctor_name": "测试医师",
  "deal_content": "已立即通知管床医师处理",
  "items": [
    {
      "exam_or_panel_name": "电解质测定(急)",
      "item_code": "K",
      "item_name": "血清钾",
      "result_value": "6.85",
      "unit": "mmol/L",
      "ref_range": "3.50-5.30",
      "abnormal_flag": "↑↑",
      "alert_prompt": "危急值上限(>6.20 mmol/L)"
    }
  ]
}
```

- **成功响应（HTTP 200）**：
```json
{
  "code": 0,
  "message": "ok",
  "crisis_id": "CV2026111500089",
  "received_at": "2026-11-15T09:15:31+08:00"
}
```

- **异常响应（HTTP 400 / 401 / 422）**：
```json
{
  "code": 4001,
  "message": "missing required field: receive_time when event_status=RECEIVED"
}
```

### 2.5 备选/对账补偿通道（数据库只读视图）
若危急值系统暂无法开发实时 Webhook，或作为防漏推补偿机制，由危急值厂商提供数据库只读账号及标准视图（含 §2.3 全部字段 + `update_time` 最后更新时间索引），由 `ai_mrzk` 定时任务每 2 分钟按 `update_time` 增量拉取并走同一套内部处理函数。

---

## 三、对内实现规范一：`ai_mrzk` 6 小时时效监控与锁定接线（第二步）

### 3.1 应用库接收台账表设计（`tl_critical_value` / Oracle `MED_TL_CRITICAL_VALUE`）
在 `app/timeliness/models.py` 与 `app/database.py` 中新增危急值原始事件表（遵循 ≤30 字符表名/索引名与 LOB 后置的 Oracle 兼容约束；生产建表 DDL 须人工审批执行）：
- **唯一键**：`crisis_id`（`VARCHAR(64)` UNIQUE）
- **核心列**：`event_status`、`source_type`、`visit_type`、`patient_id`、`visit_id`、`inp_no`、`dept_code`、`order_no`、`report_no`、`report_time`、`receive_time`、`receive_user_code`、`target_doctor_code`、`cdr_synced_flag`（通道一回填状态）、`jhemr_msg_synced_flag`（通道二回填状态）、`payload_json`（脱敏后结构化明细 CLOB/TEXT，日志输出禁止打印 `patient_name` 明文）。

### 3.2 时效规则与引擎映射（`CRISIS_VAL_6H`）
| 配置项 | 设定值 | 说明 |
| :--- | :--- | :--- |
| `rule_code` | `CRISIS_VAL_6H` | 危急值 6 小时病程记录时效规则 |
| `monitor_code` | `JH04.03.016` | 对应 `jhemr.jhinpat_mr_monitor_items` 既有危急值监控项（上线硬锁前须核查院内危急值病程模板 `templet_index.monitor_code` 绑码率） |
| `event_uid` | `CV-{crisis_id}` | 保证同一患者多次危急值各自独立计时、互不覆盖 |
| **起算时间 `T0`** | `receive_time` | 仅当 `visit_type == 'INP'` 且 `event_status in ('RECEIVED', 'HANDLED')` 且 `receive_time` 非空时激活计时；仅 `REPORTED` 态只做通道一标红回填，不启动 6h 倒计时 |
| **时限与预警** | `deadline_hours = 6`，`warn_before_minutes = 90`（可界面配置） | 提前 90 分钟企微预警，满 6 小时未审签转 `OVERDUE` / `LOCKED` |
| **达标文书判定** | `mr_class in ('BC', 'RCBC')`（病程记录类），审签时间 `>= report_time` | 匹配标题含 `危急值` 的专用病程记录，或 `receive_time`（放宽至 `report_time` 防护士晚点接收而医生已先写病程的倒挂误判！）至 `receive_time + 6h` 窗口内完成审签（`FIRST_SIGN`）的病程记录 |
| **责任医生路由** | `target_doctor_code` → `V_QYBR` 管床医师工号 → `receive_user_code` | 优先提醒危急值系统指定的流转临床医生，未传则自动回退该患者在院管床医生 |
| **撤销联动** | `event_status == 'CANCELLED'` | 若对应 `tl_event` 尚未完成，立即将状态置为 `EXEMPTED`（原因记 `SOURCE_CANCELLED`），不触发锁定 |

---

## 四、对内实现规范二：JHEMR（`10.10.8.177`）临床引用双通道（第三步）

> **安全门禁**：以下对 `10.10.8.177` Vastbase 库的写入必须封装在受控写入模块内，受独立配置开关（默认 `false`）与试点科室白名单控制，且仅在 DBA 对专用写账号授予目标表最小列级权限并经用户明确批准后启用。

### 4.1 通道一（推荐首选，零客户端改动）：回填 `jhcdr` 报告表实现右侧标红 + 右键引用入病历

#### （1）JHEMR 客户端消费原理（反编译实证）
医生在住院病历编辑界面打开右侧「检验报告 / 检查报告」辅助面板时，`JHEMR.UI.UserControls.InPat.dll` 直接查询 `10.10.8.177` 的 `jhcdr` schema：
- 检验明细表：`jhcdr.jhcdr_lab_report_items`（判断 `is_criticalvalues = '1'` 时整行红色高亮，展示 `criticalvalues_content`，支持勾选多行右键“写回病历”光标处）；
- 检查报告表：`jhcdr.jhcdr_exam_report`（判断 `is_criticalvalues = '1'` 时标红，支持右键复制/引用检查结论入病历）。

#### （2）检验类（`source_type == 'LAB'`）受控更新模板
- **匹配条件**：`patient_id = %s AND report_no = %s AND item_code = %s`（若 `jhcdr` 中 `visit_id` 非空则联合校验；执行前检查影响行数）。
- **更新字段**：
  - `is_criticalvalues = '1'`
  - `criticalvalues_content = %s`（拼装格式：`"{report_time} 危急值：{item_name} {result_value}{unit}（参考范围 {ref_range}），{receive_time} {receive_user_name}已接收"`）
- **注意**：若收到 `REPORTED` 时尚未同步进 `jhcdr`（LIS→CDR 存在数分钟同步延迟），标记 `cdr_synced_flag = 0`，在每轮 `timeliness_scan` 中对近 24 小时 `cdr_synced_flag = 0` 的记录自动补偿重试回填；若收到 `CANCELLED` 则回写 `is_criticalvalues = '0'`。

#### （3）检查/心电/病理类（`source_type in ('EXAM', 'ECG', 'PATHOLOGY')`）受控更新模板
- **目标表**：`jhcdr.jhcdr_exam_report`
- **匹配条件**：`patient_id = %s AND exam_no = %s`（对应推送报文的 `report_no`）
- **更新字段**：`is_criticalvalues = '1'`，`criticalvalues_content = %s`

---

### 4.2 通道二（可选进阶）：代写 `jhemr.jhcriticalvalues_msg` 启用「患者危急值管理」一键生成病程草稿

当临床进一步希望在嘉和菜单「患者危急值管理」弹窗（`FormCriticalValuesManage`）中查看全科室危急值台账，并点击「创建文书」按钮自动新建带危急值内容的病程草稿时，启用通道二。

#### （1）目标表 `jhemr.jhcriticalvalues_msg`（16 列实证结构）
| 列名 | 填充值来源 |
| :--- | :--- |
| `criticalvalues_id` | `crisis_id`（主键，幂等 `WHERE NOT EXISTS`） |
| `patient_id` | `patient_id` |
| `visit_id` | `visit_id` |
| `visit_type` | `'2'`（嘉和内部约定住院就诊标识，投产前与样本核对） |
| `patient_name` | `patient_name` |
| `dept_code` | `dept_code` |
| `send_time` | `report_time` |
| `sender` | `report_doctor_name` |
| `order_sn` | `order_no` |
| `lis_pk` | `report_no` |
| `criticalvalues_type` | `'LIS'`（当 `source_type == 'LAB'`）或 `'PACS'`（检查类） |
| `criticalvalues_class` | `items[0].exam_or_panel_name` |
| `message_content` | **严格按下方 10 段 `[*SP1*]` 协议拼装** |
| `dispose_status` | `'0'`（未在嘉和面板处置） |
| `dispose_doctor_id` / `dispose_time` | 初始 `NULL` |

#### （2）`message_content` 10 段 `[*SP1*]` / `[*SP2*]` 反编译格式规范
`JHEMR.JHCommon.UI.CriticalValues.dll` 解析 `message_content` 时按字面分隔符 `[*SP1*]` 切分为 10 段（`msgParts[0..9]`），多条子项在 `msgParts[9]` 内用 `[*SP2*]` 分隔：

```text
{0:patient_id}[*SP1*]{1:patient_name}[*SP1*]{2:sex}[*SP1*]{3:dept_name}[*SP1*]{4:bed_no}[*SP1*]{5:inp_no}[*SP1*]{6:sample_no}[*SP1*]{7:sample_name}[*SP1*]{8:report_time}[*SP1*]{9:子项1[*SP2*]子项2}
```
- 例如单子项拼装示例：
  `0009876543[*SP1*]测试患者[*SP1*]男[*SP1*]心血管内科一病区[*SP1*]015[*SP1*]26098765[*SP1*]202611150092[*SP1*]静脉血[*SP1*]2026-11-15 09:12:05[*SP1*]血清钾：6.85 mmol/L (参考值:3.50-5.30 ↑↑)`
- 临床在嘉和弹窗点击处置时，JHEMR 客户端会自动写入 `jhemr.jhcriticalvalues` 处置表并调起病程模板编辑器插入上述危急值文本。

---

## 五、联调验收与后期故障跟进排查 SOP

后续联调上线或临床反馈“危急值未提醒 / 未标红 / 误锁 / 写了病历未解锁”时，按以下 5 步逐层定位：

| 排查层级 | 检查位置 | 核查命令 / SQL / 判据 | 常见原因与处理 |
| :--- | :--- | :--- | :--- |
| **Step 1：查厂商是否推送到 84** | `10.10.8.84` 容器日志与 `tl_critical_value` 表 | 查 `/app/logs/app.log` 中 `webhooks/critical-value` 请求记录；按 `crisis_id` 或 `patient_id` 查 `tl_critical_value` | 1. 无日志：检查厂商到 `10.10.8.84:8000` 网络策略；<br>2. 返回 401：核对 `X-Webhook-Token`；<br>3. 返回 422：检查 `receive_time` 时间格式是否为 `YYYY-MM-DD HH:mm:ss` |
| **Step 2：查时效事件起算是否正确** | `ai_mrzk`「在院时效台账」页（`tl_event`） | 按患者或 `event_uid = CV-{crisis_id}` 查询：`trigger_time` 是否等于 `receive_time`，`deadline_at` 是否为 `+6h` | 1. 未生成事件：检查推送报文 `visit_type` 是否误传为 `OUTP`，或只推了 `REPORTED` 未推 `RECEIVED`；<br>2. 患者不在院：核对 `patient_id` + `visit_id` 与 HIS `PATS_IN_HOSPITAL` 是否一致（住院号 `inp_no` 与 `patient_id` 切勿传反） |
| **Step 3：查 JHEMR 右侧报告是否标红（通道一）** | `tl_critical_value.cdr_synced_flag` 与 `177` 库 `jhcdr` | 只读查询 `jhcdr.jhcdr_lab_report_items` 中对应 `report_no` + `item_code` 的 `is_criticalvalues` 是否为 `'1'` | 1. `cdr_synced_flag=0`：LIS/PACS 报告尚未同步至 `jhcdr`，或厂商传的 `report_no`/`item_code` 与 `jhcdr` 字段编码不一致（抓一条 `jhcdr` 真实行比对主键格式即可定位） |
| **Step 4：查医生写完病历为何未消锁** | `177` 库 `jhemr.mr_file_index` 与 `tl_event` | 核查该患者在 `report_time` 之后是否有 `mr_class in ('BC','RCBC')` 且已完成审签（`first_sign_time` 或审签状态非草稿） | 1. 医生只点“保存草稿”未点“审签”；<br>2. 若规则处于 `LOCK_EMR` 硬锁后补写，核查危急值病程所使用的模板 `templet_index.monitor_code` 是否已绑 `JH04.03.016`（未绑码会导致 JHEMR 原生不回填 `completed_date`） |
| **Step 5：查误报/撤回危急值解锁** | 危急值系统状态 & `ai_mrzk`「解锁审批与豁免」页 | 查厂商是否补推 `event_status = CANCELLED` | 厂商补推 `CANCELLED` 后系统自动置 `EXEMPTED`；紧急情况下医务部可在 `ai_mrzk`「解锁审批与豁免」页手工点击豁免立即解除 |

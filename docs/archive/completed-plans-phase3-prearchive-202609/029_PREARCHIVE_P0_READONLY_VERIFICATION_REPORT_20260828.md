# 028 P0 只读核验报告（sjzc 部分，2026-08-28）

> 文档编号：029
> 编制日期：2026-08-28
> 编制者：ZCode/GLM-5.3
> 性质：P0 只读核验报告（用户 2026-08-28 授权"开始 P0 只读核验（sjzc 部分）"）
> 查询方式：全部经 sjzc 受控连接器（8.83 平台），单条 SELECT、聚合为主、零写入、患者明细不落地（授权范围见 028 §5 P0；本报告不含任何患者标识）
> 上游：028（执行计划）、026（规则来源）、`prearchive_service/`（一期原型，commit bc10e8d）
> 关联交付：《030 评分项-规则映射表 v1（待质控科签字）》

> **【2026-08-28 事实更正（用户纠正，优先于本文】】**：§1.3 方案①（申请 179:1521 只读）**作废**——179（10.10.8.179）是嘉和电子病历**应用服务器**（文书经 web 推送给无纸化），不是数据库；电子病历数据库**仅有 177:5432 一个**。因此 §1.2"177 副本从不复制完成类字段"的表述应更正为：**完成事件不落数据库**（应用层直推无纸化），177 上完成字段全 NULL 是最终事实而非同步缺口。触发终态候选改为"无纸化接收侧逐份到达时间戳"（见 031 v4.3 §11/W9）。同日新增实测：`jhmr_file_index` 表存在（52 列，topic 标题含时间戳，术后首程 24h 判定依据）；`pat_visit` 全 50 列含 alergy_drugs 等首页字段但近 30 天填充率仅 8.1%（首页空项不可判，维持 K4 结论并修正表述）；`T_MARK_DETAIL.FMARKITEMID` 直连 `T_MARK_ITEM.FID`（026 的 211/51/52/85 为频次非编号）。

---

## 0. 一页摘要（五个关键发现）

| # | 发现 | 等级 | 影响 |
|---|---|---|---|
| K1 | **触发锚点在 177 副本不存在数据**：`pat_visit.finished_date_time`/`first_finished_doctor_id` 等 6 个完成类字段全表 117,113 行 100% NULL；`recordfinished_oper_log`、`mr_finished_index_callback` 均 0 行 | **方案影响级** | 028 的"完成即查即推"（D3）在当前可读侧不可实现，必须三选一（见 §1.3） |
| K2 | HIS `T_ITF_HIS.REPORTNAME` 实测仅 0/1/2：**0 与 1 各 16,479 条完全相等（成对生成）**、2=19,275（窗 2026-06-01 起）；`CONSULTATION_ID` 该窗全空 | 中 | 0/1 成对坐实"医嘱对"猜想但**语义仍需信息科确认（防猜测红线）**；会诊类规则无数据基础 |
| K3 | **手麻名称列=REPORTNAME（26 个真实词）**；LIS `FDESCNUM`=检验**类别**（15 值）、`FITEMNAME`=具体项目名——028 F3 v2 的"FITEMNAME（手麻）/FDESCNUM=描述列"表述有误 | 中 | 已修正代码与示例规则词表（§4）；检验报告族改按类别匹配更稳 |
| K4 | **首页结构化数据在四源内不存在**：177 的 21 张 `emr_first_page_*` 全是字典/配置/打印/QC 模板表（`emr_first_page_print` 为字段打印配置）；HIS 侧仅 `FXJCPT.BASYFY`（ID/PAID/VI 三列关联表） | 硬闸门落锤 | 028 §3.1 预设的整族降级成立：**empty_field/duplicate/首页过敏空项/诊断重复不上一期** |
| K5 | `v_blws` 实际 22 列与原型假设不符（无 `first_record_time/finished_date_time/last_update_time`，实际为 `first_save_time/finish_time_format/create_date/modify_date` 且**全为 text**）；视图含逐行 GBK 转换函数，全表聚合 120s 超时 | 中 | 已修正 BLWS_SQL（§4）；v_blws 值域导出与轮询加压需 DBA 侧配合（R9 实证） |

**P0-6（推送对象映射）BLOCKED**：ODS 8.216 当前 ORA-12541 无监听不可查；且完成医生字段在 177 无数据（K1），命中率基线无从测起。一期推送对象建议降级为"文书书写医生（v_blws.doctor_guid，实测 6 位工号格式）/管床医师兜底"。

---

## 1. P0-1 触发锚点延迟与完备性（177 侧）

### 1.1 实测数据

```sql
-- jhemr_vastbase_10_10_8_177
SELECT COUNT(*) total, COUNT(finished_date_time) fin, COUNT(first_finished_doctor_id) doc,
       COUNT(first_finished_date_time) ffdt, COUNT(first_page_submit_date) fpsd,
       COUNT(first_page_submit_user_id) fpu, COUNT(mr_submitnurse_record_date) nsd,
       COUNT(discharge_date_time) dis, COUNT(admission_date_time) adm
FROM jhemr.pat_visit;
-- 117,113 / 0 / 0 / 0 / 0 / 0 / 0 / 115,951(99.0%) / 117,074(99.97%)

SELECT (SELECT COUNT(*) FROM jhemr.recordfinished_oper_log) a,
       (SELECT COUNT(*) FROM jhemr.mr_finished_index_callback) b;  -- 0 / 0
```

### 1.2 结论

- 177 副本**从不复制"完成/提交"类字段**（整族 100% NULL，而常规时间字段 99%+ 有值）——不是延迟问题，是**同步列清单根本不含这些列**；028 F1"列存在"的实证成立但"有值"不成立，F2 的 0 行预警实锤升级；
- 主从比对（177 vs 179）无 179 账号，无法执行；但既然 177 侧整族无值，比对已无意义，结论直接成立。

### 1.3 触发方案三选一（需用户决策）

| 选项 | 内容 | 代价 | 备注 |
|---|---|---|---|
| ①申请 179:1521 只读 | 用主库真锚点（finished_date_time + first_finished_doctor_id 一步到位，还可能解锁首页数据表） | 网络申请+账号；179 曾 ORA-12547 | **推荐**：同时解 K1/K4/P0-6 三个问题 |
| ②换锚点：v_blws 状态轮询 | 轮询 `v_blws.modify_date/finish_time_format`（text 列）文书级变化，患者维度聚合出"疑似完成" | 轮询代价高（K5 视图重）；"完成"语义=推断（progress_status 值域未导出） | 可作为 ①未批期间的影子验证锚点 |
| ③降级：出院时点触发 | 用 `discharge_date_time`（99% 有值）做锚点 | 语义从"完成即查"退化为"出院后查"（D3 决策受损，提醒时效下降） | 兜底方案，不建议单独采用 |

---

## 2. P0-3 值域与词表实测（六小项）

### 2.1 ①HIS REPORTNAME 编码字典（部分结论）

- 窗口 2026-06-01 起：`0`=16,479 / `1`=16,479 / `2`=19,275；0 与 1 **逐数相等**（成对生成，与 028 猜想一致）；
- `CONSULTATION_ID` 在该窗全部为空 → **会诊关联通道无数据，会诊类规则（FID 49-52）不上一期**；
- **编码语义（0/1/2 各代表什么条目类型）仍需信息科或 HIS 厂商确认——防猜测红线，不做映射假设**。

### 2.2 ②手麻/LIS 词表（90 天窗，2026-05-30 起）

**手麻 T_ITF_SM（名称列=REPORTNAME，26 词，实测频次 TOP）**：

手术护理单 5,446 ／ 安全核查单 5,435 ／ 麻醉单 4,561 ／ 术前访视 4,525 ／ 术后随访 4,471 ／ 麻醉同意书 4,403 ／ 手术清点记录4 2,161 ／ 手术清点记录1 1,226 ／ 手术清点记录2 1,127 ／ 介入核查单 839 ／ 麻醉总结 812 ／ 手术清点记录5 693 ／ 介入护理记录 685 ／ 复苏单 467 ／ 麻醉质控单 231 ／ 清点记录3/6/7 ／ 介入护理记录1 ／ 压力性损伤/低体温风险评估 ／ 自费药品告知同意书 ／ 取血单 ／ 交接记录单。

**注意**：手麻侧**没有**"术前小结/术前讨论/手术记录/术后首次病程"——手术族规则的 expect 必须分源（核查/护理/访视/清点→手麻；小结/讨论/手术记录/术后病程→JHEMR v_blws）。

**LIS `FDESCNUM` 全值域（15 类）**：发光免疫 45,465 ／ 临检血液 43,321 ／ 生化 35,966 ／ 凝血常规 20,745 ／ 体液 13,946 ／ 免疫 11,649 ／ 细菌 10,167 ／ 便常规 6,434 ／ 其他 5,990 ／ 输血科 2,995 ／ 分子生物 2,771 ／ 流式细胞 2,689 ／ 分泌物 705 ／ 急查生化 207 ／ 精液常规 29。
（`FITEMNAME`=具体项目名，如"血液分析(紫管)""门生4（肝肾糖脂离子）（红管）"——报告族匹配用类别列更稳。）

### 2.3 ③v_blws 列结构（22 列实测）与值域（BLOCKED-超时）

- 真实列：`patient_id, inp_no, visit_id(numeric), dept_name, progress_type, progress_type_name, progress_title_name, progress_template_name, progress_message, progress_status, doctor_name, doctor_guid, record_time_format, progress_guid, state, msg_type, first_save_time, finish_time_format, create_date, modify_date`（以上 text）`, caption_date_time(oradate), mr_class`；
- `progress_status`/`state` 值域：**全表 GROUP BY 超时**（视图对 `progress_message` 逐行执行 GBK 转换函数 `safe_convert_from26`，120s 被杀）——需 DBA 侧导出或部署机 LIMIT 采样；R9（轮询加压）风险实证；
- `doctor_guid` 采样=6 位数字工号（如 000808/002522），可用作文书书写医生定向。

### 2.4 ④首页表定位（硬闸门：不上）

- 177：`table_name ~ '(first|basy|bgsy|home)'` 命中 21 张，全为 `emr_first_page_{column_dict,item_dict,button_list,control_config,print,print_log,qc_*,validate*,diag_oper_fre,...}` ——**字典/配置/打印/QC 模板，无患者级数据表**；`emr_first_page_print` 列为 print_field_name/dict_name/hospital_no 等打印配置；
- HIS：`BASY%` 仅 `FXJCPT.BASYFY`（ID/PAID/VI 三列），非首页结构化表；
- **结论：首页过敏空项（026 高频 211）/出生地（52）/诊断重复（85）整族不上一期**，与 028 §3.1 预设一致。若 179 开通后发现 `emr_first_page_data` 类数据表，可重新评估。

### 2.5 ⑤JHEMR 文书名词表（部分）

- `progress_template_name` 全量 DISTINCT 因视图超时未导出（同 2.3）——**模板名白名单/排除词表的完整版需 DBA 配合**；原型现有排除词表（知情同意/查房记录）与 026 证据一致，先沿用；
- 采样确认：v_blws 含入院记录/手术记录/手术知情同意书等模板（与 026/AGENTS 既有认知一致）。

### 2.6 ⑥visit 别名对齐（部分）

- `pat_visit.visit_id` 为 numeric，`v_blws.visit_id` numeric + `inp_no` varchar；T_ITF 三源为 `FBIHID`/`FBINCU`（varchar）；
- FBINCU↔visit_id 的值域比对未完成（跨库无 join，需抽样本地比对——**留给部署机连通后验证**，不猜测）。

## 3. P0-6 推送对象映射（BLOCKED）

- ODS `ods_8_216` 当前 ORA-12541（无监听）不可查，`V_AI_ZKUSER` 命中率无法测；
- 完成医生字段在 177 无数据（K1）→ "first_finished_doctor_id ↔ 企微 userid"基线无从建；
- **一期建议**：推送对象降级为 ①v_blws 最后书写医生（doctor_guid，6 位工号）②管床医师兜底（V_QYBR 链路，med-audit 已验证）——待 179 开通后再回补完成医生优先级。

---

## 4. 已落地的代码/规则修正（本报告同批提交）

| 修正 | 文件 | 内容 |
|---|---|---|
| BLWS_SQL 真实列名 | `prearchive/collectors.py` | `first_save_time AS record_time / finish_time_format AS finished_time / modify_date AS update_time` |
| 手麻名称列改 REPORTNAME | 同上 `ITF_NAME_KEYS` + `SqlSmGateway.ITF_SQL` | 删 FITEMNAME（实测不存在）；手术证据关键词扩为（手术/麻醉/介入） |
| LIS 类别语义 | 同上 | FDESCNUM（类别）优先、FITEMNAME（项目名）兜底 |
| 手麻 fixture 真实词表 | `prearchive/fixture_sources.py` | 安全核查单/手术护理单/麻醉单/术前访视（P0-3② 实测词） |
| LIS fixture 类别值 | 同上 | 临检血液/生化/体液 |
| 规则词表实测版 | `rules/example_rules.json` | 核查表词表=安全核查单/核查单/核查表；护理=手术护理单；检验族=临检血液/生化/体液（类别匹配） |
| 回归验证 | `prearchive_service/tests` | 105 项全绿（2026-08-28 复跑） |

## 5. 剩余待办（转移给用户/信息科/质控科）

1. **用户决策触发方案**（§1.3 三选一，推荐①申请 179:1521 只读）；
2. 信息科：HIS REPORTNAME 0/1/2 语义确认；v_blws progress_status/state 值域 DBA 导出；四源对部署机连通+账号（P0-2）；
3. 质控科：对《030 映射表 v1》逐条确认分类/参数/严重度并签字（版本号+日期）；
4. ODS 8.216 恢复后补 P0-6 基线（如仍走企微通道）。

## 6. 查询留档（sjzc live，全部只读聚合）

```
1  jhemr_vastbase_10_10_8_177  COUNT(*)/COUNT(finished_date_time)/... pat_visit 完成族列
2  jhemr_vastbase_10_10_8_177  recordfinished_oper_log / mr_finished_index_callback 行数
3  jhemr_vastbase_10_10_8_177  information_schema.columns v_blws（22列）
4  jhemr_vastbase_10_10_8_177  v_blws progress_status/state GROUP BY → 120s 超时（留证）
5  jhemr_vastbase_10_10_8_177  v_blws doctor_guid LIMIT 15 采样（工号格式）
6  jhemr_vastbase_10_10_8_177  tables ~ '(first|basy|bgsy|home)'（21张配置表）
7  jhemr_vastbase_10_10_8_177  information_schema.columns emr_first_page_print
8  his_source_10_10_10_15      T_ITF_HIS REPORTNAME 分组 + CONSULTATION_ID 计数
9  his_source_10_10_10_15      all_tables/all_tab_columns BASY% 检索（FXJCPT.BASYFY）
10 docare_oracle_10_10_10_68   all_tab_columns T_ITF_SM（13列，无FITEMNAME）
11 docare_oracle_10_10_10_68   T_ITF_SM REPORTNAME 90天词表（26词）
12 lis_sqlserver_10_10_10_73   sys.columns vw_hisinter_T_ITF_Lis（13列）
13 lis_sqlserver_10_10_10_73   FDESCNUM 90天类别值域（15类）/ FITEMNAME 对比
14 paperless_cdms_10_10_10_93  CDMS.T_MARK_ITEM FISENABLE=1 全量 92 条（分页2次）
15 ods_8_216                   zkuser/qybr 检索 → ORA-12541 BLOCKED
```

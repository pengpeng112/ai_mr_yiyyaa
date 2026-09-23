# 053 — 052 执行交付报告（JHEMR 客户端"病历完成"点击提醒：接线调查+待批实施包）

> 执行日期：2026-09-22（Asia/Shanghai）｜执行者：ZCode/GLM-5.3
> 作业书：`docs/ACTIVE/052_JHEMR_CLIENT_EVENT_REMINDER_ONESHOT_PLAN_20260921.md`（v1.1，round-7 修订版）
> 状态：**已定稿**（T0-T3+T6 完成；T4 生产实施/T5 AI 闭环=另批授权门，本批未执行）
> 证据目录：`review/jhemr-l2-20260921/`（本仓，gitignored）｜反编译产物：`C:\temp\jh050\`（既有七目录+本轮新增 8 目录）

---

## 0. 一句话结论

**T1 四分支判定=甲分支成立**：JHEMR 客户端「病历完成」按钮已接入库表驱动的个性化校验机制（`JHMR_FILE_CUM_FILEVERIFY` 表 CHECK_TYPE=4，**患者级重载**），且存在 **TIP_TYPE=1"提示不阻断"通道**——**纯库表 INSERT 配置即可实现点击病历完成时弹质控提醒、不改客户端、零 DLL 部署**。T2 演练通过，T3 就绪待批包已产出（`review/jhemr-l2-20260921/t3_ready_package_20260922.sql`）。

052 v1.1 的关键锚点"checkType 4/7 在已反编译范围内无调用点"被本轮证据**证伪**（利好修正，详见 §5 偏差说明）：4/7 的调用点都在制定者七目录未覆盖的宿主 `widgetdll/JHInPatMedical.dll` 中。

## 1. T1 四分支结论与证据（含重载判定+调用方消费方式）

### 1.1 结论=甲（宿主已调 VerifyConfig(4)→纯配置）

完整调用链（全部行号=反编译产物，版本绑定见 §2）：

```
医生点击「病历完成」（工具栏按钮 btnMRCom，Text="病历完成"）
└─ IPMWidgetPatientList.btnMRCom_Click（:6261）
   ├─ :6278 IPMUCDischargeFinish.IsRetuenFinshIsTx(pid, vid)（:75）
   │  ├─ :282 btnFinshedBLL(pid, vid, null) —— 既有完成校验链（设置号族，见 §1.4）
   │  └─ :315 returnFinishbyEmrFileConfig(pid, vid, ref)（IPMMedicalRecordOrSubSpecialBLL:1669）
   │     └─ :1673 IPMWidgetPatientInfoBLL.CustomEmrFileVerifyConfig(pid, vid, 4, ref tip)（:330）
   │        └─ 反射：Assembly.LoadFile("…\JHEMRPadEventCustom.dll")
   │           → JHEMR.JHEMRPadEventCustom.Logic.CustomEmrFileBusiness
   │           → 匹配 4 参数方法 = 患者级重载 CustomEmrFileBusiness.cs:436
   │              读 JHMR_FILE_CUM_FILEVERIFY WHERE CHECK_TYPE=4 AND ENABLE=1 AND (HOSPITAL_NO=本院 OR '*')
   │              逐行 string.Format(SETTING_SQL, 19 个占位符实参) → 执行 → 比对 → 按 TIP_TYPE 行为
   └─ :6291 returnFinishbyEmrFileConfig（第二次调用）
      └─ 全部校验通过后才 UPDATE PAT_VISIT SET MR_DOCTOR_PART_STATUS='2'（:6258-6262 提交完成）
```

### 1.2 重载判定（甲必答第一问）

**调的是患者级重载**（`CustomEmrFileVerifyConfig(string, string, int, ref string)`，CustomEmrFileBusiness.cs:436）。证据：宿主包装（IPMWidgetPatientInfoBLL.cs:351）反射匹配条件=`参数长度==4 && 方法名=="CustomEmrFileVerifyConfig"`——四参数签名即患者级。

**患者级占位符可用集**（:477-478 string.Format 实参顺序，与 052 §0.2 一致，已实测核对）：
`{1}`=PATIENT_ID、`{2}`=VISIT_ID、`{3}`=PAT_INP_NO、`{4}`=ID_NO、`{5}`=操作者当前科室码、`{6}`=入院时间、`{7}`=出院时间、`{12}`=RealUserId、`{13}`=hospitalCode、`{16}`=INPATIENT_NO、`{18}`=库服务器时间；**{8}{9}{10}{11}{14}{15}{17}=空串**（文书位不可用）。

**配置查询过滤**（JHDataDAL.cs:6760 患者级版）：`CHECK_TYPE=4 AND ENABLE=1 AND (HOSPITAL_NO='{本院}' OR HOSPITAL_NO='*')`，**无 MR_CLASS/MR_CODE 条件，CATALOG_CODE 仅显式传入才过滤（患者级调用时为空=不过滤）**——新规则行 CATALOG_CODE 填 0 即可，"单 MR_CLASS 窄域隔离"对患者级无效（与 052 §0.1 预判一致，隔离只能靠 SETTING_SQL 内部门控，T3 已按此设计科室门控）。

### 1.3 调用方消费方式（甲必答第二问）

| TIP_TYPE | 患者级函数内行为（:436-840） | 宿主消费（returnFinishbyEmrFileConfig:1675-1699 + 上游） | 实际效果 |
|---|---|---|---|
| 0 | 命中→RecordCustomLog（门=20240923HPJ001）→return false | flag=!false=true→ShowInformation+上游 return | **弹窗+阻断完成** |
| **1（推荐）** | 命中→收集静态 TIPMESSGE 到 text、return true；方法尾 `if(num>0) tipMessge=text` | flag=!true=false；tipMessge 非空→ShowInformation；上游继续完成链 | **弹窗（宿主弹）+不阻断** ✔=052 默认口径"提示不阻断"直接可用 |
| 2 | 函数内 ShowDialogBoxMessage(YesNo)；"否"→return false | 同 0 | 函数内弹窗；点"否"阻断 |
| 3 | 函数内 OKCancel；"取消"→return false | 同 0 | 函数内弹窗；点"取消"阻断 |

- 逐行执行：多条 CHECK_TYPE=4 规则**串行全部执行**，TIP_TYPE=1 收集多行文案拼接为一个 tipMessge。
- **fail-open**：SQL 异常 catch→return true（初始值）=静默无提醒不拦截（:429-433 同款，患者级 :836-839）。
- RESULT_TYPE=1 数值（CHECK_SYMBOL 1-6 全支持）；=2 字符仅 5/6；SQL 只读第一行第一列（第二列动态文案仅 TIP_TYPE=0/2/3 路径可见，TIP_TYPE=1 只有静态 TIPMESSGE）——与 052 §0.1 一致。
- **已知行为（本执行新发现，须入试点观察）**：btnMRCom 路径上 returnFinishbyEmrFileConfig 被调**两次**（IsRetuenFinshIsTx 内 :315 + btnMRCom_Click :6291），非聚合模式下 TIP_TYPE=1 命中会**连续弹两次相同提示**（各点一次确定，不阻断）；btnMrCommit 路径（:5080 单次调用）弹一次。不改客户端无法消除；聚合模式（20230713QC001=1）下 :6291 的 strreturn 被丢弃，提示可能只剩 IsRetuenFinshIsTx 内一次——两种模式试点时以实机为准记录。

### 1.4 完成按钮入口面（T1.4 设置号按钮面）

| 入口 | 控件/方法 | FILEVERIFY(4) 覆盖 |
|---|---|---|
| **工具栏「病历完成」btnMRCom**（Text=「病历完成」，:8367）——**用户原始需求「病历书写→病人列表→待归档→点击病历完成」的精确对应物** | IPMWidgetPatientList.btnMRCom_Click(:6261)；Visible 门=20170217LCE002（现无行=默认可见，:583-585） | **是**（两次调用） |
| 「提交病历」btnMrCommit | IPMWidgetPatientList.btnMrCommit_Click（:5080） | **是**（一次调用） |
| 出院患者列表（IPMUCDischargePatientList）右键菜单「提交病历完成/提交医疗文书」（:2683→:2747）与批量 TJBA_PL（:5692） | 调 btnFinshedBLL 校验链（IPMMedicalRecordOrSubSpecialBLL:68-846） | **否**（该链不含 FILEVERIFY；如需覆盖此路径，走同链设置号 20230427QC001/20230915QC001 通道，见 §6 可选扩展） |
| 提交终态 | UPDATE PAT_VISIT SET MR_DOCTOR_PART_STATUS='2'（IPMWidgetPatientList:6258-6262） | — |

btnFinshedBLL 链上的其他库表驱动通道（本轮新锚，记录备用）：`20230427QC001`（$ 分隔，表|非空列|提示语|数据源|PID列|VID列 的计数型校验，:197-242）、`20230915QC001`（Format 双 SQL 计数型，:283-306）、IJHInPatMedicalPatients 反射钩子（JHEmrInterFaceCommon:294，装载表=**JHMR_PAD_DEV_EVENT**，当前已装载 JHInPatMedicalCustom.IPatientCustom→20221028QC003 必填文书校验——部署型通道，本批不用）、`20240522QC002`+NEWAI_PAT_QUALITY（完成时 AI 质控非甲级提示，既有先例）。

## 2. 证据链与版本绑定

- `review/jhemr-l2-20260921/t0_dll_sha256.txt`：9 个 DLL 的 SHA-256。关键：宿主 `widgetdll/JHInPatMedical.dll`=b85caeee…（6.4MB，本轮新反编译→`C:/temp/jh050/InPatMedical/` 717 cs）；`JHEMRPadEventCustom.dll`=4f2d8941…（既有 PadEvent 产物）。
- `review/jhemr-l2-20260921/t1_wiring_evidence.md`：T1 全证据（调用链行号/重载判定/TIP_TYPE×完成链语义矩阵/checkType=7 次发现/同链其他通道/日志实证）。
- `review/jhemr-l2-20260921/t2_config_rehearsal.md`：T2 三表实证+设置号现值+演练结果+方言差异清单。
- `review/jhemr-l2-20260921/t3_ready_package_20260922.sql`：T3 就绪待批包（dry-run 打印稿）。
- 日志实证（T1.5）：本拷贝 JHLog/ErrorLog 中 FILEVERIFY 关键串（"个性化文书校验SQL/调用个性化文书配置/进入个性化文书服务配置"）0 命中——不能证生产未配置（仅本拷贝无触发痕迹），与 052 §0.1 记载一致；ErrorLog 中"个性化"命中=首页初始化方法日志，与本案无关。

## 3. T2 配置面核查与 SQL 演练结果（甲分支→已执行）

- **三表实证**（sjzc 只读=177 Vastbase 演练副本）：`JHMR_FILE_CUM_FILEVERIFY` 现存 **2 行**（CHECK_TYPE=1/2，均 ENABLE=0，本院 HOSPITAL_NO=49557032X 的历史停用配置，无 CHECK_TYPE=4 行=配置面干净）；`JHMR_FILE_CUM_SERVICE_CONFIG`=0 行；`JHMR_FILE_CUM_LOG`=0 行。
- **设置号现值**：20240923HPJ001（审计开关）无行、20170217LCE002（btnMRCom 显示开关）无行=按钮默认可见、20170217LCE001 值='JHInPatMedicl'≠"1"（btnMrCommit 不隐藏）、20230713QC001（聚合模式）无行、其余通道设置号均无行——**新增 FILEVERIFY(4) 行与现状零冲突**。
- **表结构更正**：FILEVERIFY 实为 20 列，含 052 未记载的 QUERY_FLAG/QUERY_REMARK/QUERY_DEFAULT_VALUES 三列（维护界面测试参数元数据，VerifyConfig 运行时不读）。
- **候选规则演练**（4 条，文案/阈值均标注"待质控科确认"；TIP_TYPE=1/RESULT_TYPE=1/CHECK_SYMBOL=1 大于 0 命中）：

| 规则 | 6212/1（09-22 出院，ST=0） | 2807/9（09-22 出院，ST=0） | 9614/3（09-17 出院 4.7 天，ST=0） | 6893/6（对照 ST=3） |
|---|---|---|---|---|
| R1 未首签文书存在 | **1 命中** | 0 | **1 命中** | 0 |
| R2 缺出院记录（TOPIC like） | 0（有"日间手术入出院记录"变体） | 0（有精确"出院记录"） | **1 命中** | — |
| R3 出院超 3 天未完成 | 0（当日） | 0（当日） | **1 命中** | 0（状态排除） |
| R4 手术缺记录关联（默认不激活） | 0 | 0 | 0 | 0 |

命中/不命中对照成立；查询全部秒级点查（patient_id+visit_id 等值），无锁风险。数据脏值如实记录：1 个 ST=0 样本出院年份=22025（R3 不触发=数据问题非 SQL 缺陷）。方言差异清单见 t2 文件 §5（177→179 全部兼容项+中文谓词通道限制说明）。

- **TIP_TYPE 选定=1**（有据）：T1 已证宿主成功路径弹 tipMessge（returnFinishbyEmrFileConfig 内 ShowInformation）且不阻断——满足 052 红线 4 的准入条件；TIP_TYPE=0 依红线禁入默认包；2/3 需用户拍板"点否=拦"不推荐。TIP_TYPE=1 代价=静态文案（无 SQL 第二列动态明细），文案已内嵌提示语设计。

## 4. T3 就绪待批包（位置与要素）

**位置**：`review/jhemr-l2-20260921/t3_ready_package_20260922.sql`（dry-run 打印稿，**未执行**）。

要素齐全度对照 052 §2 T3：
- ✔ 精确 schema（20 列全列 INSERT）/主键（ID varchar(75)）/目标行数（4 行）/预期影响行数（Part 2=4、Part 3=3）
- ✔ 改前快照（Part 1 SELECT 备份，当前预期 2 行）
- ✔ 幂等重跑（ID 固定语义锚 20260922AIQC01..04，重跑先 DELETE 同 ID）
- ✔ 事务边界（Part 2 四条同事务；Part 3 单事务）
- ✔ 回滚：首选 `UPDATE ENABLE=0`（**下次点击生效**，逐次查询已核；不撤销已发生提示/完成动作）+彻底版 DELETE 行（凭快照）；**设置号还原=无**（本包零 GOAL_SETTING_TABLE 变更）
- ✔ 隔离方式（按患者级重载设计）：R1-R3 的 SETTING_SQL 内嵌 `dept_discharge_from='{5}'` 试点科室门控（操作者科室+患者出院科室双门控，试点科室码 :PILOT_DEPT 由批准时指定）；R4 默认 ENABLE=0
- ✔ 试点范围字段：试点科室/人员（=试点科全用户，机制无人员维度）/时间窗（建议 ≥3 工作日观察）/推广梯度（单科→观察→质控科确认→逐批放开）
- ✔ 观察指标：客户端 JHLog 三行日志串（"病历完成调用个性化文书配置"/"个性化文书验证SQL：…CHECK_TYPE = 4"/"个性化文书校验SQL：…"）+点击总耗时（预期增量=4 条点查）+fail-open 预期（SQL 坏=静默无提醒不拦截）+§1.3 双弹窗已知行为记录
- ✔ 前置检查（Part 0）：179 本院代码核验/按钮实机确认/配置面现状核验/R2 中文谓词 179 复验
- ✔ 零阻断事故验收绑定实际配置语义（TIP_TYPE=1）：试点期任何"完成被拦截"即异常回滚信号

## 5. 偏差说明（事实锚点修正，业务裁定未变）

| # | 052 v1.1 锚点 | 本轮证据 | 处置 |
|---|---|---|---|
| 1 | "checkType 4/7 在已反编译范围内无调用点；当前证据倾向事件 4 未接线（丙/丁）" | **证伪（利好）**：4 与 7 均有调用点，位于制定者七目录未反编译的宿主 `widgetdll/JHInPatMedical.dll`（:1673 checkType=4；IPMWidgetPatientInfotxBLL.cs:25 checkType=7）。T1 候选清单所列 7 个 DLL（JHInPatMedicalCustom/Interface/JHEMRPadEvent/JHMRPatientCISInfoDef/JHMRWarningRemind/JHInterfaceAIQC/DataValidateByState）均非宿主——经二进制 grep `OnEmrPatientFinishBefore` 定位真宿主 | 按证据修正为甲分支；反编译产物补至 C:/temp/jh050/InPatMedical（717 cs） |
| 2 | "JHInPatMedicalPatients.OnEmrPatientFinishBefore/After 空实现"（PadEvent 产物） | 该锚点仅对 JHEMRPadEventCustom.dll 内的 JHInPatMedicalPatients 类成立；**JHInPatMedicalCustom.dll 的 IPatientCustom.OnEmrPatientFinishBefore 有真实现**（→20221028QC003+JHCON_MRFILESTATE_CONTROL 必填文书校验，经 JHMR_PAD_DEV_EVENT 装载） | 事实修正；该通道=部署型（需 DLL），本案不依赖，记录为 §6 可选扩展 |
| 3 | "TIP_TYPE=1 仅当 T1 证实目标宿主成功路径展示 tipMessge" | **已证实**：returnFinishbyEmrFileConfig:1675-1693 tipMessge 非空即 ShowInformation；患者级方法尾 num>0 时 ref 回写收集文本 | TIP_TYPE=1 准入成立，入默认包 |
| 4 | （052 未预见） | btnMRCom 路径 returnFinishbyEmrFileConfig 被调两次→非聚合模式 TIP_TYPE=1 命中弹两次相同提示；出院列表右键菜单/批量路径走 btnFinshedBLL 链不经 FILEVERIFY(4) | 已知行为记入 §1.3/§4 观察清单；右键路径覆盖=可选扩展 |
| 5 | T2 预设"HOSPITAL_NO 分布" | 本院代码=49557032X（演练副本 PAT_VISIT 全量+现存 2 行配置同源）；052 §0.1 称现存行为"设置号 20240923HPJ001"审计——实为开关，无行=关 | T3 行 HOSPITAL_NO 按 49557032X 精确匹配（优于通配 '*'），Part 0.1 留 179 复核 |
| 6 | FILEVERIFY 表结构（052 未列全列） | 20 列，含 QUERY_FLAG/QUERY_REMARK/QUERY_DEFAULT_VALUES（维护页测试参数，运行时不读） | T3 INSERT 全列显式赋值 |
| 7 | 演练库=177 Vastbase≠执行库 179 Oracle 方言风险 | 全部规则 SQL 用 NVL/TRUNC(SYSDATE)/LIKE 均双库兼容；**演练通道对中文 SQL 文本偶发编码异常**（0xe5 截断 3 次复现 2 次）→R2 改 TOPIC 列表本地判定，中文谓词实机执行不受影响 | Part 0.4 前置检查在 179 复验 R2 谓词 |

## 6. 未做清单与升级事项（待用户）

1. **T4 生产实施**（授权门）：T3 包逐条批准→179 执行 Part 0 前置检查→Part 1 快照→Part 2 INSERT（ENABLE=0）→批准激活 Part 3（试点科室+时间窗）→实机点击验证（弹窗+不阻断+JHLog）→观察→梯度推广。**本批零生产写入**。
2. **一期规则文案与阈值待质控科确认**（R1/R2/R3 文案、R3 阈值 3 天、R2"日间手术入出院记录"口径、R4 是否启用）——T3 包内已逐条标注。
3. 可选扩展（另批）：①出院列表右键菜单/批量路径的提示覆盖（走 20230427QC001/20230915QC001 通道，纯设置号配置，T3 附录未含、需要时补充设计）；②IL 补丁/AppDomainManager 方案不再需要（甲成立，方案优先级第一档达成）；③052 §2 T5 AI 质控闭环（免签端点/relay/回写表）维持另批状态，患者级 submission_id 契约修正建议（{1}_{2}_{18}）仍有效。
4. Git：本批零 commit/push（授权范围外）；工作区新增本报告与 052 状态行、INDEX/README/01 登记变更，归属清楚。

## 7. 生产/Git 状态

- **生产（179 Oracle/10.10.8.84 容器/E:\嘉和 客户端目录）：零写入零改动**（全程只读反编译+177 副本只读 SELECT；E:\嘉和 仅读文件与 grep，无任何修改）。
- 本仓改动（白名单内）：`docs/ACTIVE/053_*`（本报告，新）、`docs/ACTIVE/052_*`（状态行）、`docs/INDEX.md`（053 行+052 状态）、`开发起步包/{README.md,01_统一修改记录.md}`、`docs/ACTIVE/023_*.md`（§0.6 一行）、`review/jhemr-l2-20260921/**`（证据，gitignored）、`review/exec-log.md`（checkpoint）。
- Git：分支 `fix/ora-12609-p4-error-code`，起点 HEAD=7fc62e8；052 编制+round-7 修订的既有未提交文件（4 项）全部保留未动；本批未 commit/push（未授权）→**本地交付完成，未提交**。

## 8. 完成定义对照（052 §5）

- [x] T0+T1 全验收（调查线一次性完成；甲分支+重载判定+消费方式判定齐备）
- [x] 甲分支：T2（三表实证/演练命中对照/TIP_TYPE 选定有据）+T3（就绪包要素齐全）交付
- [x] 053 定稿+两仓登记+quick 门禁（结果见 §0 与登记行）；零生产写入、客户端零修改、E:\嘉和 零改动
- [ ] T4/T5：另批授权门，未执行（按 052 完成定义不计入本批）

# 052 — JHEMR 客户端"病历完成"点击提醒接入一次性计划（调查+待批实施包）

> 制定日期：2026-09-21（Asia/Shanghai）｜制定者：ZCode/GLM-5.3（受用户委托编制，交外部 AI 执行）
> 版本：**v1.1**（multi-review round-7 三方互查后修订，35 项裁决；v1.0 原文固化于 `review/round-7/方案.md` §2）
> **状态：已执行完毕，交付=053（2026-09-22）**——T1 判定=**甲分支**（宿主 `widgetdll/JHInPatMedical.dll` 已调患者级 VerifyConfig(4) 且 checkType=7 亦接线，v1.1"4/7 无调用点"锚点被证伪；TIP_TYPE=1 提示不阻断通道成立）；T2 演练通过；T3 就绪包=`review/jhemr-l2-20260921/t3_ready_package_20260922.sql`（dry-run，T4 另批）。偏差与证据链见 053 §5/§2。
> 用户原始需求（逐字）：「其中 jhemr 联调可以使用 E:\嘉和 请你分析下看看如何反编译，我需要在这个程序中 临床医疗 中的病历书写 病人列表 待归档 点击病历完成的时候进行提醒，请看看如何不影响很大情况下实现。E:\嘉和\JHEMR\JHEMR 是程序。请针对上述写个计划文件，让别的ai一次性按照计划完成」
> 上游定位：**028 强制提醒场景 / 027 五路径评估的补路径（R0）**；T5 可选阶段才对接 046 JHEMR 五接口（≠049/051 §9 的 L2 联调）
> 配套提示词：`开发起步包/PROMPT-20260921_JHEMR客户端病历完成提醒一次性执行.md`（v1.1）
> 交付报告预留：`docs/ACTIVE/053_052_EXECUTION_DELIVERY_REPORT_20260921.md`
> 边界：**客户端零修改**（不动 E:\嘉和\JHEMR\JHEMR 任何文件）｜E:\嘉和 材料只读｜jhemr 生产库默认只读，一切写=T4 授权门｜**本计划交付物=接线调查结论+条件性待批实施包，不是"提醒已接入"**

---

## 0.0 修订记录

- v1.1（2026-09-21，round-7）：①TIP_TYPE 四分法重写（1 不弹窗/2-3 可软阻断/0 阻断）；②补患者级重载（:436，不滤 MR_CLASS/MR_CODE、7 占位符为空）→"单 MR_CLASS 试点"仅适用文书级；③接线清单补全（checkType 2/8/文书级 1、服务事件 1；check_type=2 连带加载 8）；④checkType≠CALL_EVENT 编号系拆开；⑤PatMrStatus 降为对照（护理编辑锁）；⑥**新锚=JHInPatMedicalPatients.OnEmrPatientFinishBefore/After 空实现**（:37-45）——甲分支须宿主反编译证实；⑦T1 候选 DLL 重列（JHInPatMedicalCustom/Interface/JHEMRPadEvent 非 Custom/JHMRPatientCISInfoDef/JHMRWarningRemind/JHInterfaceAIQC/DataValidateByState；删不存在的 JHMRPatientCISInfo.dll）；⑧"293 类"更正=EmrButtonEvent_* 32+EmrPadCommit_* 57；⑨CATALOG_CODE 通配=0；⑩字符型仅运算符 5/6；⑪TIP_TYPE=1 丢 SQL 第二列；⑫审计仅 TIP_TYPE=0 分支→观察指标改客户端 JHLog；⑬医生完成显示字段=MR_DOCTOR_PART_STATUS（非 CATALOG_STATUS=编目链）；⑭演练库(177 Vastbase)≠执行库(179 Oracle)方言风险+fail-open 语义；⑮SETTING_SQL 只读锁死+禁执行存量未知 SQL；⑯T5 患者级 submission_id 双空→契约重设计；⑰"无自定义头"改"配置层不可达"；⑱5000ms 同步串行；⑲SQL 演练契约清单；⑳测试对象=出院待归档访次；㉑一期规则标注"候选待质控科确认"；㉒增丁=证据不足分支+完成定义按分支条件交付；㉓PROMPT 改"事实锚点允许按证据修正并记偏差"+T0 补 DLL 哈希与完整命令；㉔T4 批准包要素强制清单；㉕回滚措辞限定（下次点击生效/不撤销已发生影响）；㉖PHI 强化（JHLog 含完整标识禁抄）；㉗删 docs/73 悬空引用；㉘门禁档位写死 quick；㉙023 §0.6 行；㉚L2 标签改 028/027 口径+丙分支并列 027 R1 出口。
- v1.0（2026-09-21）：初版（含制定者侦察；其中接线清单不全、TIP_TYPE 语义有误、患者级重载遗漏——已被 round-7 证伪更正）。

## 0.1 反编译实证与语义（v1.1 修正版；执行 AI 可按证据再修正并记偏差）

**工具链**：`ilspycmd 8.2`，需 `DOTNET_ROLL_FORWARD=LatestMajor`（bash 语法；PowerShell 用 `$env:DOTNET_ROLL_FORWARD="LatestMajor"`）。既有产物 `C:\temp\jh050\{PadEvent,EditCommon,Central,CAUI,PatCIS,NIS,OutMr}`（材料只读）。反编译命令模板：`DOTNET_ROLL_FORWARD=LatestMajor ilspycmd <dll> -p -o C:/temp/jh050/<dir>`（cwd=E:\嘉和\JHEMR\JHEMR）。**T0 须对关键 DLL 记 SHA-256**（至少 JHEMRPadEventCustom/JHInPatMedicalCustom/JHEMRPadEvent/JHMRPatientCISInfoDef），绑定"产物↔材料版本"。

**机制 A=校验（两个重载，语义不同，先确认目标按钮调哪个）**：

1. **文书级** `CustomEmrFileVerifyConfig(PadEventArgs args, int checkType, ref string tipMessge)`（CustomEmrFileBusiness.cs:23）：配置查询按 CATALOG_CODE（指定或 **0**）/MR_CLASS（或 '*'）/MR_CODE（或 '*'）/CHECK_TYPE/ENABLE/HOSPITAL_NO（或 '*'）（JHDataDAL.cs:6744）；**checkType=2 时连带加载 CHECK_TYPE=8 的规则**（:6740-6742）。
2. **患者级** `CustomEmrFileVerifyConfig(string strPatientID, string strVisitID, int checkType, ref string tipMessge)`（:436）：查询**只滤 CHECK_TYPE/ENABLE/HOSPITAL_NO+可选 CATALOG_CODE 精确匹配**（:6760），**无 MR_CLASS/MR_CODE 条件**——"单 MR_CLASS 窄域试点"对患者级**无效**，隔离只能靠 SETTING_SQL 内部门控（科室/患者范围）。
3. 事件枚举（:838）：1=新建病历、2=病历签名、3=病历打印、**4=病历完成**、5=申请修改、6=病历删除、**7=患者列表（选择患者）**、8=保存病历。
4. **TIP_TYPE 四分法（v1.1 核心）**：

| TIP_TYPE | 函数内行为 | 阻断性 | 提醒可见性 |
| --- | --- | --- | --- |
| 0 | 条件命中→RecordCustomLog（若设置号开）→**return false** | 阻断 | 函数内不弹；调用方常把 tipMessge 自行弹出（Delete/Print/Modify 链） |
| 1 | 收集**原始 TIPMESSGE**（丢 SQL 第二列动态文案）→ref 返回，**return true** | 不阻断 | **函数内不弹窗**——完全取决于调用方成功路径是否展示（EmrPadSave.cs:2364-2384 会 ShowInformation；Delete/NewMultiple 只在 false 时弹） |
| 2 | 函数内 ShowDialogBoxMessage(YesNo)（"系统提醒"） | 点"否"→return false=**可软阻断** | 函数内弹 |
| 3 | 函数内 OKCancel | 点"取消"→可软阻断 | 函数内弹 |

5. RESULT_TYPE：1=数值（CHECK_SYMBOL 1-6 全支持）；**2=字符（仅 5=等于/6=不等于）**（:342-415）。SQL 结果只读**第一行第一列**；第二列动态文案仅 TIP_TYPE=2/3 可见。异常 catch→**return true（fail-open：SQL 坏=静默无提醒不拦截）**（:429-433）。
6. **审计：RecordCustomLog 仅在 TIP_TYPE=0 分支调用**——T4 观察指标用客户端 JHLog 的"个性化文书校验SQL"行为准，不能指望 JHMR_FILE_CUM_LOG 有 TIP_TYPE=1 记录。

**机制 B=外呼** `CustomServiceConfig(args, CallEventType)`（:895）：表 `JHMR_FILE_CUM_SERVICE_CONFIG`（CALL_EVENT/…/ORDER BY CREATE_DATE）。**CALL_EVENT 与 checkType 非同一编号系**（实证：B-1=签名后[EmrPadAfterSign:259]、B-2=删除[:111]、B-3=保存[EmrPadSave:2410]；A-2=签名、A-3=打印）——**B-4=病历完成无任何实证**。SERVICE_TYPE 1=WCF/2=WebApi（REQUEST_TYPE 1=POST/2=GET）；PostHelper.HttpPost **有** HeaderPram 参数但**配置路径未使用**→签名能力"配置层不可达"；**超时 5000ms 同步执行、多配置行串行累积延迟**；可选 SETTING_SQL 门控。**依赖 args.m_xdsFile——患者级事件无当前文书对象时机制 B 接不上**。

**接线现状（v1.1 补全；含 .Logic 目录）**：A-1 文书级=EmrPadSaveFile:726、患者级=EmrPadNewMultiple:22；A-2=EmrPadBeforeSign:474；A-3=EmrPadPrint:95/372；A-5=EmrAllowApplyModify:88、EmrAllowModify:56；A-6=EmrPadDeleteFile:48；A-8=EmrPadSaveFile:876；B-1/2/3 同上。**checkType 4/7 在已反编译范围内无调用点**（"已检索范围内未发现"，不证完整客户端/生产配置没有）。

**患者级完成钩子（round-7 新锚）**：`JHInPatMedicalPatients` 实现 `IJHInPatMedicalPatients`——`OnEmrPatientFinishBefore/After`（:37-45）**空实现（return string.Empty）**，同文件 Commit/CelFinish/Click 亦空；唯一有逻辑=`OpenOnePatientAfter`（双击患者→CustomAutoEmrFiles(Event_Type=1)，走 `JHMR_FILE_CUM_AUTOFILE_CONFIG`，与 FILEVERIFY 的 checkType 4 **不是同一套枚举**）。**当前证据倾向：事件 4 未接线（分支丙/丁），除非宿主 DLL（JHInPatMedicalCustom/Interface 等）内有调用。**

**其他更正**：医生"病历完成"显示字段=`MR_DOCTOR_PART_STATUS`（本院映射 2=病历完成，PCICUCMRViewDAL.cs:113-123）；`CATALOG_STATUS=1`=病案室**编目**完成（docs/78:67，编目链，勿混）。`JHNIS.JHNISCommonLib.PatManage.PatMrStatus`=护理编辑权限锁（角色=NURSE、MR_NURSE_PART_STATUS），**仅作对照不作主锚**。按医院设置号装载的类：EmrButtonEvent_* 32 个+EmrPadCommit_* 57 个（带设置号后缀文件≈283）。本客户端拷贝日志（E:\嘉和\JHEMR\JHEMR\JHLog\ 8 份+ErrorLog\）**0 命中"个性化"**（不能证生产未接线，仅本拷贝无痕迹）。客户端业务库=179 **Oracle 主库**；sjzc 演练=177 Vastbase 副本（方言差异风险）。

## 0.2 占位符模板（两套，勿混用）

**文书级（19 位全可用）**：`{0}`空｜`{1}`PATIENT_ID｜`{2}`VISIT_ID｜`{3}`PAT_INP_NO｜`{4}`ID_NO｜`{5}`当前科室码｜`{6}`入院时间｜`{7}`出院时间｜`{8}`文书创建时间｜`{9}`FILE_UNIQUE_ID｜`{10}`MR_CLASS｜`{11}`MR_CODE｜`{12}`RealUserId｜`{13}`hospitalCode｜`{14}`CAPTION_DATE_TIME｜`{15}`TOPIC｜`{16}`INPATIENT_NO｜`{17}`opeartion_no（原文拼写）｜`{18}`库服务器时间。

**患者级（7 位为空）**：同序，但 **{8}{9}{10}{11}{14}{15}{17}=空串**（:480）——患者级 SQL 只能用 {1}-{7)、{12}{13}{16}{18}。

## 0.3 红线（违反=交付作废）

1. E:\嘉和 材料目录只读；产物只进 C:\temp\jh050\ 或本仓 review/；在 E:\嘉和 产出文档须按其 AGENTS 登记+verify_repo.py。
2. **客户端零修改**；IL 补丁/AppDomainManager 仅设计稿，单独批准才可实施。
3. jhemr 库默认只读；写操作=T4 授权门内用户当次逐项批准（一次只管一次）。
4. 提醒默认口径=提示不阻断：**TIP_TYPE=0 禁入默认包**；TIP_TYPE=1 仅当 T1 证实目标宿主成功路径展示 tipMessge；否则用 2 并向用户明示"点否=拦"须拍板。
5. **SETTING_SQL 演练仅限本次自写的纯 SELECT；存量配置行的 SETTING_SQL 只做文本审查禁止执行**（其内容为任意可执行串）。
6. PHI：JHLog/日志含完整患者标识——**禁止抄原始日志进产物**，只留计数/耗时/patient_id 末 4 位；演练患者选出院待归档访次由质控科口径或最小必要。
7. T5（含免签端点/relay/回写表）另批；本批零 git 写、零生产服务器写操作。
8. 本仓文件白名单（允许修改）：`docs/ACTIVE/052_*.md`（状态行）、`docs/ACTIVE/053_*.md`（新）、`docs/ACTIVE/023_*.md`（仅 §0.6 一行）、`docs/INDEX.md`、`开发起步包/{README.md,01_统一修改记录.md}`、`review/jhemr-l2-20260921/**`、`review/exec-log.md`、C:\temp\jh050\ 反编译产物。其余（含 app/、prearchive_service/、E:\嘉和 任何文件）禁改。

## 1. 目标与交付物定位

在医生「病历书写→病人列表→待归档→点击病历完成」路径上弹出质控提醒（一期=库内候选规则；内容待质控科确认），影响最小化。**本计划交付=①接线调查结论（甲/乙/丙/丁分支）②条件性待批实施包（仅甲/乙成立时）③丙/丁时的替代方案设计**——不是"提醒已接入"；实机接入在 T4 获批后。方案优先级（调查序）：纯库表配置＞IL 补丁＞AppDomainManager；**丙分支时并列呈报 027 R1（库轮询+企微，零客户端改动）供用户选择**。

## 2. 任务包（T0–T6）

### T0 启动与现场（~20min）
双仓规程（ai_mrzk AGENTS；E:\嘉和 CHANGELOG→START_HERE→AGENTS）；工具链核验；七目录在否+关键 DLL SHA-256 记录（§0.1 清单）；053 滚动骨架；`review/jhemr-l2-20260921/` 证据目录。

### T1 接线定位（核心，~120min；从真实按钮向下追，勿从枚举反推）
1. **反编译补全（按优先序）**：`JHInPatMedicalCustom.dll`、`JHInPatMedicalInterface.dll`（病人列表宿主，验证是否调 `CustomEmrFileVerifyConfig(…,4)` 或 `OnEmrPatientFinishBefore` 非空）、`JHEMRPadEvent.dll`（非 Custom 分发器）、`JHMRPatientCISInfoDef.dll`（病人列表本体；注意与 Custom 后缀区分）、`JHMRWarningRemind.dll`、`JHInterfaceAIQC.dll`、`DataValidateByState.dll`。全目录 grep `CustomEmrFileVerifyConfig|CustomServiceConfig|JHEMRPadEventCustom|IJHInPatMedicalPatients|OnEmrPatientFinish`（含反射字串）。
2. **完成按钮链读穿**：从待归档列表 UI 按钮→`MR_DOCTOR_PART_STATUS` 提交链（勿走 CATALOG_STATUS 编目链、PatMrStatus 护理锁仅对照），记录可插入点。
3. **设置号按钮面**：从装载/菜单配置现查按钮设置号与绑定事件类名（**不引用 docs/73**——该引证已废，表名现场反查）。
4. **日志实证**：grep `E:\嘉和\JHEMR\JHEMR\JHLog\` 与 `ErrorLog\` 的"个性化文书校验SQL/进入个性化文书服务配置功能"（现成路径，0 命中亦如实记录）。
5. **四分支结论**：**甲**=宿主已调 VerifyConfig(4)→纯配置；**乙**=找到现成会调 4 的可装载类（32 按钮类内实证，找不到即不成立）→配置+装载评估；**丙**=均否→IL 补丁/AppDomainManager 设计稿+**并列 027 R1 替代**；**丁**=证据不足（DLL 缺失/混淆等）→证据+未决清单。甲/乙须同时回答：**调用的是哪个重载（决定参数表与试点隔离方式）+ 调用方如何消费返回值与 tipMessge（决定 TIP_TYPE 选择）**。

### T2 配置面核查与 SQL 演练（只读；仅甲/乙分支执行，丙/丁跳过改出设计稿，~60min）
1. sjzc 只读：三表 DESCRIBE+现存行+HOSPITAL_NO 分布+设置号 20240923HPJ001 现值（注意 177 副本）。
2. 一期**候选**规则（≤5 条，标注"待质控科确认"）：未签名文书数/缺必需文书（030 A 类）/超时限（029 词表）；按**目标重载的占位符表**（患者级禁用文书位）写 SETTING_SQL；**CATALOG_CODE 用 0**。
3. 演练契约：**自写纯 SELECT**；Oracle 方言为目标（177 通过≠点击可用，记方言差异清单）；单行首列返回；数值型整数范围；字符型仅等/不等；日期/引号/花括号字面量转义按 C# string.Format 契约验证；**3 个出院待归档访次**+命中/不命中对照；结果只落计数/耗时/末四位。
4. 文案定稿（TIP_TYPE 按 T1 结论选定；患者级+类型 1 时动态明细不可用=仅静态文案，文案内嵌提示语）。

### T3 试点实施包（仅甲/乙；丙/丁改产替代设计，~40min）
INSERT 脚本包（dry-run 打印）：精确 schema/主键/目标行数/改前快照（SELECT 备份）/幂等重跑/预期影响行数/事务边界/回滚条件；**隔离方式按重载**（患者级=SETTING_SQL 内科室门控，无 MR_CLASS 可用）；回滚=ENABLE=0（**下次点击生效**，逐次查询已核；不撤销已发生业务影响/日志）+DELETE 行（凭快照）+设置号还原；试点范围字段：客户端/人员/科室/时间窗/推广梯度（试点批准≠全院推广）。观察=客户端 JHLog"个性化文书校验SQL"行+点击总耗时（含 fail-open 预期：SQL 坏=静默无提醒）。

### T4 生产实施【授权门——用户当次逐项批准】
批准对象= T3 完整脚本包（每条 INSERT/回滚/试点范围单列）；试点→实机点击验证弹窗与不阻断→观察→梯度推广。零阻断事故验收绑定"实际配置的 TIP_TYPE 语义"。

### T5 AI 质控闭环（可选另批；**前置契约修正**）
患者级 submission_id 不能用 {9}_{17}（双空）→改 {1}_{2}_{18}（或含 nonce）且幂等查询须带患者访次校验；机制 B 患者级无 m_xdsFile→PARAMETER 模板适配或经 relay 组装；闭环需 check_id 关联与结果版本策略；免签端点/relay 需身份/重放/密钥设计；回写表=生产写另批。

### T6 交付登记
053 定稿（分支结论/证据链/演练/就绪包或替代设计）；INDEX/README/01+**023 §0.6 行**；E:\嘉和 侧若产出→CHANGELOG+verify_repo.py；**门禁=quick（本任务零代码改动，文档档位；不跑 full）**。

## 3. 验收标准

| 包 | 验收 |
| --- | --- |
| T0 | 规程已读；工具链 PASS；DLL SHA-256；053 骨架 |
| T1 | 四分支其一+证据链（反编译行号/按钮链/日志）；**甲/乙必须含重载判定+调用方消费方式判定** |
| T2 | 三表实证；SQL 按契约演练通过（出院访次）；TIP_TYPE 选定有据 |
| T3 | 就绪包要素齐全（快照/幂等/事务/回滚条件/试点范围）**或**丙/丁替代设计稿 |
| T4 | （获批后）试点弹窗+无意外阻断+JHLog 证据 |
| T5 | （另批）闭环证据 |
| T6 | 053+两仓登记+quick PASS |

## 4. 升级出口

1. T1=丙/丁→停配置路线，呈设计稿+027 R1 对比，待用户选型。
2. jhemr 连接失败/权限不足→记录报告不绕行。
3. 演练锁等待/性能风险→重写或降条目。
4. 任何生产写/客户端改/Git 写在其批准落地前→停在该门。

## 5. 完成定义（按分支条件交付）

- [ ] T0+T1 全验收（调查线一次性完成）
- [ ] 甲/乙：T2+T3 就绪包交付；丙/丁：替代方案设计+证据+未决清单交付（**=调查完成，不算实施就绪，不得冒充**）
- [ ] 053 定稿+两仓登记+quick PASS；零生产写入（T4 获批前）、客户端零修改、E:\嘉和 零改动

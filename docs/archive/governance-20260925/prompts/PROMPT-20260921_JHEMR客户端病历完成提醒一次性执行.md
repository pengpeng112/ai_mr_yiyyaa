# 交给执行 AI 的提示词

请在 `F:\python\前后端代码\ai_mrzk` 仓库执行 `docs/ACTIVE/052_JHEMR_CLIENT_EVENT_REMINDER_ONESHOT_PLAN_20260921.md` **v1.1**（multi-review round-7 三方互查修订版），完成 T0–T1（调查线）及分支条件下的 T2–T3，把生产实施做成"就绪待批包"，结果写入预留的 `docs/ACTIVE/053_052_EXECUTION_DELIVERY_REPORT_20260921.md`。

任务一句话：查明嘉和 JHEMR 客户端「病人列表→待归档→点击病历完成」是否已接入库表驱动的校验/外呼机制（checkType=4），成立则产出配置实施就绪包，不成立则产出替代方案设计（IL 补丁/AppDomainManager/027 R1 库轮询对比）。制定者侦察锚点已固化在 052 §0.1/§0.2（v1.1 已按 round-7 三方互查修正患者级重载/TIP_TYPE 四分法/接线全清单/空 Finish 钩子等）——**业务方向不再重开争论，但事实锚点允许你按反编译证据再修正，并在 053 偏差说明中记录**；勿盲目照抄，也勿重做已完成的七目录反编译。

先按 ai_mrzk AGENTS 启动顺序读文件；涉 E:\嘉和 时按其 CHANGELOG→START_HERE→AGENTS 规程执行（材料只读、服务器默认只读）。使用 med-audit-oneshot-delivery Skill；门禁按 052 §2 T6=quick（文档档位，勿跑 full）。

本执行请求允许：只读反编译（ilspycmd 需 DOTNET_ROLL_FORWARD=LatestMajor；新 DLL 按 052 T1 清单补反编译到 C:\temp\jh050\）、经 sjzc 对 jhemr 库只读查询（DESCRIBE/SELECT；**仅限本次自写纯 SELECT，存量配置行 SETTING_SQL 只做文本审查禁止执行**）、052 §0.3 白名单文件的本地产出、quick 门禁。

本请求不授权：jhemr 生产库任何写入（T4 脚本只 dry-run 打印，执行须用户当次逐项批准）、对 E:\嘉和\JHEMR\JHEMR 任何文件的修改（IL 补丁/AppDomainManager 仅输出设计稿）、T5 生产改造（另批）、git commit/push、登生产服务器写操作、把含患者标识的原始日志抄入产物。

若上下文耗尽，在 053 滚动稿写准确剩余包、失败命令、证据与续跑点。最终回复给出：T1 四分支结论与证据（含重载判定+调用方消费方式）、T2 演练结果（如适用）、T3 就绪包或替代设计位置、偏差与升级事项、生产/Git 状态。

# 047 — 046 统一修复与无纸化/JHEMR 闭环执行交付报告

> 日期：2026-09-10 至 2026-09-11（两段执行完毕）；执行：ZCode/GLM-5.3；作业书=046 v1.2。
> 状态：**本地开发与合成验证全部完成（T0-T10 全包闭合，终版门禁全绿）**；两段执行
> （第一段 2026-09-10 T0→T5；第二段 2026-09-11 T6→T10）。JHEMR=L1 已验收，
> **L2 真实联调/L3 生产试点未开始**；生产迁移/部署/外发未执行。
> checkpoint=review/exec-log.md `[046:*]` 区块；终版门禁=§10。
> 红线：零生产、零真实患者、未 commit；真实 JHEMR 联调与生产试点未完成前不宣称对接成功。

## 1. 逐包结果（滚动）

| 包 | 状态 | 结果摘要 | 证据 |
| --- | --- | --- | --- |
| T0 | DONE | 基线 HEAD=58ea350；ST-004 两测试核验接纳（19 passed）；9 新表/5 新权限/白名单迁移/测试 ID 锁定 | exec-log [046:v1.2:T0] |
| T9a | DONE | D1 双轮耗时累加/D2 杀树幂等清理/D3 头注释/ST-001 Oracle LENGTH/ST-002 预览端口身份核验+备选端口/ST-003 时钟注入/ST-005 兼容/OBS-1/044 §11 追加/01 补记 D8+ST-004 | exec-log [046:v1.2:T9a]；quick 4/4 |
| T1a | DONE（T1b PLANNED→已闭合） | 92 条账本（92/23/7/62 与 030 一致，123 条款）；AI 匹配服务（stub+确定性校验+任务生命周期）；闭环 API；BFF 白名单+权限矩阵；权限迁移脚本（dry-run 默认） | exec-log [046:v1.2:T1a] |
| T2 | DONE | F05 修复（五态引擎）/F06 修复（评估全量入库）/RUN+RULE_EVAL 持久化/T7.1 汇总模型（算术守恒）/断言迁移表 §3 | 本节下文 + §3 |
| T3 | DONE | 11 FID 逐子句（FID57 拆分/FID38 落地/FID14 变体词表）；多手术事件关联（_pair_docs_to_events+SM 聚类 6h）；规则 v2026.09.10-046-t3（16 条，旧版备份 .bak） | exec-log [046:v1.2:T3] |
| T1b | DONE（T1 整包 DONE） | trial 执行/观察/反馈 API+服务；隔离实证（RESULT/Outbox 零行、指针零变化） | exec-log [046:v1.2:T1b] |
| T4 | DONE | publish_atomic/rollback_atomic（故障注入无半发布）；RefreshableRuleSet TTL 60s+force_refresh；compare 全量差异+jsonl 持久化；字段依赖发布门；两套前端新建/编辑/复制+非法 JSON 拒绝 | exec-log [046:v1.2:T4] |
| T5 | DONE | IssueService 生命周期（稳定 issue_key/复检收敛/复现重开/乐观锁）；checks/issues API+BFF（白名单→40）；科室范围隔离；两套前端工作台；demo seed 5 新权限；**真机 E2E 2 passed（匹配→trial→观察真 API 链）** | exec-log [046:v1.2:T5] |
| T6 | DONE（2026-09-11 第二段） | delivery_wiring 全链接线：materialize_for_run 返回 resolved_issue_keys；PrecheckProcessor 接 delivery_emitter（finish_run→materialize→emit，trial 跳过）；build_stack 构造 emitter+治理注入；delivery worker 每轮 reconcile 补偿（治理过滤不越权）；test_pa_delivery_wiring 11 用例（合成触发端到端/治理矩阵/复检新事件+resolutions/崩溃幂等/目标停用） | exec-log [046:v1.2:T6] |
| T7 | DONE（2026-09-11 第二段；L1 已验收，L2/L3 未开始） | 预检侧 integration_api（五接口：幂等 submission-checks/T7.1 完整汇总 GET/一次性票据/反馈不改判/同锚点复检）+ 主服务签名路由（HMAC 四件套+nonce 重放+时钟偏差）；BFF 白名单 40→46+权限矩阵；联调包 integration/jhemr/（openapi/schema/纯 TEST 样例/mock_client/签名向量/错误码/字段对照）；测试 12+13+7 | exec-log [046:v1.2:T7]；L1 证据=review/jhemr-l1-20260911.log |
| T8 | DONE（2026-09-11 第二段） | backtest v2（人工扣分=参照：未评范围=unknown 不计 FP；对齐窗口排除整改后回测；五态不计 FN unknown；分母 0=null 不写 100%；FID/子句/科室三级+FP 原因聚合）+ 院内运行脚本（合成基准默认）+ test_pa_backtest_v2 12 | exec-log [046:v1.2:T8]；合成产物=review/backtest-synthetic-20260911.md |
| T9b | DONE（2026-09-11 第二段；T9 整包闭合=T9a+T9b） | diagnostics 模块（引擎版本/最后成功采集/源故障/任务与 Outbox 积压/死信/连续失败/compare 差异；零 PHI）；/healthz additive 块 + /api/admin/diagnostics；故障隔离验收（任务 failed/源 partial 结果仍落库/目标 dead 不回压）；test_pa_ops_diag 7 | exec-log [046:v1.2:T9b] |
| T10 | DONE（2026-09-11 第二段） | Oracle DDL 生成（10 表+PK/UNIQUE/INDEX+RESULT 4 列 ALTER，ORM 奇偶校验 PASS，未执行）；**终版全量门禁 11/11 PASS 含 legacy 双轮实跑，锚全部不低于**（main 1376/prearchive 438+1skip/unit 62/e2e 52+17skip）；专项=L1 真机+T6/T8/T9b 包测试；登记闭环（045 核销/INDEX/023/README/01） | exec-log [046:v1.2:T10]；review/gate_full_stage2b.log |

## 2. 运行链路（T2 后的当前形态）

**终版全链（T6/T7/T1b 已全部接入）**：

`合成 FinishedVisit（fixture/paperless_rpa 或 JHEMR emr_submit/rechecks）→
TriggerPoller / integration_api（BackgroundTasks）→ PatientContextBuilder →
RuleEngine（五态 evaluations）→ EvalRunStore（RUN+RULE_EVAL）→ RESULT upsert（含
evaluations/notices/source_health/summary）→ IssueService 物化（稳定 issue/复检收敛/
resolved_issue_keys）→ ResultEventEmitter（治理过滤→Outbox 确定性事件）→
DeliveryWorker dispatch（每轮 bounded reconcile 补偿）→ Mock/真实接收端 ACK →
运行诊断面（healthz/admin diagnostics）`；旁路：trial 轨道（隔离执行/观察/反馈）、
compare 影子（diff_count）、WeComPusher（既有）、JHEMR 五外部接口（主服务签名路由→
BFF 白名单→integration_api）。

fixtures 冒烟（--once，2026-09-10）：3 例 processed；张某 fail（手术族缺文书 8 项，
含真实缺陷）、李某 fail 5（含新判定的出院记录缺失）、王某全负例 13 pass 0 fail。

## 3. F05 断言迁移表（046 §T2 义务）

| 原 test_id / 旧语义 | 新 test_id / 新语义 | 依据 | 理由 | 边界新增 | 实际结果 |
| --- | --- | --- | --- | --- | --- |
| `test_pa_engine_time_limit.py::test_time_limit_doc_missing_no_problem`（缺文书→problems==[]，notice pass/doc_not_found） | `test_time_limit_doc_missing_past_deadline_is_defect`（必需+源完整+过期限→1 problem fail，eval fail/required_doc_missing） | 046 §1.2 F05、§7 场景1、§3.3 | 旧契约把缺文书当合格=误判通过；time_limit 规则自身声明文书必需 | +`test_time_limit_doc_missing_within_deadline_pending`（期限内→pending+复查时间）、+`test_time_limit_doc_missing_with_source_error_unknown`（源故障→unknown） | passed |
| 同文件 `test_time_limit_doc_time_unknown_no_problem`（时间不可靠→pass） | `test_time_limit_doc_time_unknown_is_unknown_eval`（→unknown 不当合格）；新增 `test_time_limit_event_time_unknown_is_unknown_eval` | 046 §3.3 unknown 定义、§7 场景2 | 时间无法可靠取值不得当合格 | 负例（doc 存在且时限内仍 pass）由既有 within_limit 用例保留 | passed |
| `test_pa_rules_t24.py::test_file_index_topic_unknown_and_missing_cases`（file_index 无匹配行→problems==[]） | 同名用例内迁移：无匹配行+过期限→1 problem（details.missing=True）+notice fail；标题无时间→unknown | 046 F05 | 同上（file_index_topic 时间源同语义） | event_time_unknown 分支补 eval=unknown 断言 | passed |
| `test_pa_engine_missing_doc.py` 全文件（trigger_not_met/within_time_window/source_not_ready 旧 status=pass/skip） | reason 断言全部保持（负例场景保留）；语义升级：trigger_not_met→not_applicable（源健康）或 unknown（源故障）、within_time_window→pending+deadline、source_not_ready→unknown | 046 §3.3 | 状态值升级不改场景覆盖；负例（不误报缺陷）仍是 problems==[] | 新增 eval 断言在 test_pa_eval_states.py 矩阵 | passed |
| `test_pa_e2e.py::test_end_to_end_full_chain`（李某预期 4 问题集） | 预期集+`R-TIME-DISCHARGE-RECORD-24H`（fixture 无出院记录，出院 08-27 08:00，check 08-28→过期限缺陷） | 046 F05 | fixture 真实缺出院记录，旧引擎掩盖 | 王某全负例保持（fixture 补首程/出院/有创操作记录三类文书后 0 问题） | passed |
| `test_pa_anchor_modes.py::test_blws_status_mode_aggregates_and_enriches`（王某锚点/水位=11:05） | 迁移为 15:05（fixture 补出院记录 update 15:05 成为最新文书） | 046 T2 fixture 补全 | 锚点=最新 update_time 语义不变，数值随 fixture 更新 | — | passed |
| `test_pa_engine_empty_duplicate.py`（首页不可用→skip） | 首页不可用→unknown（reason 不变） | 046 §3.3 | 源故障不当合格；负例（无问题不推送）保留 | — | passed |

未削弱任何负例：所有"不误报缺陷"场景（时间窗内/源故障/触发不满足）仍断言 problems==[]，
仅从 pass/skip 升级为 pending/unknown/not_applicable。

## 4. T7.1 汇总 schema（T2 实现，T7 复用）

`SUMMARY_SCHEMA_VERSION="2.0.0"`；字段=046 §T7.1 终态表全集；算术约束测试：
applicable=pass+fail+unknown+pending；evaluated=pass+fail；
rule_instance=applicable+excluded（not_applicable/disabled/dept_excluded/exempt_scene
全部计入 excluded 并按 reason 计数）；覆盖率分母 0→null（不显示 100%）；
required/ready_source_checks 按适用实例×引用源对计数。queued/running 未定计数由
GET 层以 null+provisional=true 表达（T7 落地）。

## 5. 迁移与回滚（终版）

- 主服务权限：`scripts/migrate_qc_permissions_20260910.py`（dry-run 默认；--apply/--rollback 白名单内；5 新权限=match_run/trial_manage/check_view/issue_review/issue_feedback；**未执行**，生产按 023 §9.1 批准单）。
- 预检 SQLite：`scripts/migrate_prearchive_schema_20260910.py`（RESULT 四新列 additive ALTER + 闭环 10 表 create；默认 dry-run）。
- Oracle：`prearchive_service/sql/create_prearchive_closed_loop_oracle_20260910.sql`（T10 生成：10 表 CREATE + 10 PK + 7 UNIQUE + 18 INDEX + RESULT 4 列 ALTER；列集合与 ORM 奇偶校验 PASS；**未执行**，由 DBA 按 023 §9.1 批准单手工执行；空串语义=字符串列不设 DEFAULT ''，应用层提供值）。
- 回滚：SQLite 演示库可重建；Oracle 不 DROP 新增表/审计数据（046 §8.2）；代码回滚=整工作区未提交，直接丢弃即回第一段前状态；已部署场景先关 result_delivery/JHEMR_INTEGRATION 开关再回退规则版本/镜像。
- 本地演示库 data/prearchive_result.db 已应用迁移并清理演示数据。

## 5.1 启动方法

- 预检服务（fixtures 合成）：`cd prearchive_service && python run_service.py --fixtures`（:8600；真实模式 `--config config.json`）。
- JHEMR 集成 L1 栈：预检侧起后，主服务带 `PREARCHIVE_ADMIN_ENABLED/BASE_URL/TOKEN/SECRET` + `JHEMR_INTEGRATION_ENABLED/CLIENT_ID/HMAC_SECRET` 环境变量启动；联调包 `prearchive_service/integration/jhemr/README.md` §5 有逐步命令与 mock_client 演示。
- 结果投递（T6）：`result_delivery.enabled=true` 后 delivery worker 自动启动（每轮 dispatch + bounded reconcile 补偿）；治理在 `rule_registry.governance` + `result_delivery` 配置节。

## 5.2 外部未完成项（本地不可闭合）

1. JHEMR L2/L3：需 JHEMR 开发方按联调包接入测试环境（046 §2 Q3 用户已确认分工）。
2. 真实 AI 匹配：需院内模型通道凭据（PREARCHIVE_MATCH_BASE_URL/API_KEY）。
3. 真实回测（T8 院内模式）：需授权后的聚合脱敏样本 JSON（患者级资料不出批准环境）。
4. W10 系统推送类规则清单（033 ③，仍待用户逐系统提供）。
5. 生产部署/迁移执行：全部按 023 §9.1 批准单。

## 6. 契约/断言变更登记（滚动）

- BFF 白名单 20→32 目标（T7.1 精确集合+权限矩阵，test 迁移见 test_prearchive_admin_bff.py）。
- BFF 白名单 32→40（T5 核查工作台 +8）；**40→46（T7 JHEMR 集成 +6**：submission-checks POST/GET、view-tickets、redeem、feedback、rechecks；集成目标=服务账号最小权限 check_view/issue_feedback）。
- AUDIT_ACTIONS append-only 扩展 13 个闭环动作；**T7 再 +3**（jhemr_submission_check/view_ticket_redeem/jhemr_issue_feedback）。
- PrearchiveResult 新增 4 列（历史行空=未保存评估明细，不补造）。
- 引擎 notice.status 值域从 pass/skip 扩为五态+excluded（reason 字符串兼容）。
- **T7 新增外部契约**：`/api/integrations/jhemr/*` 五接口（JHEMR HMAC 签名四件套，默认 503 零网络）；`check.result` GET 汇总 schema v2.0.0（queued/running 未定计数 null+provisional=true）；环境变量 JHEMR_INTEGRATION_ENABLED/CLIENT_ID/HMAC_SECRET。

## 7. JHEMR 能力级别（滚动）

- **L1 本地 Mock：已验收（2026-09-11）**——真实双服务栈（prearchive fixtures:18601
  + 主服务:18602）+ mock_client 真实 HTTP 全链：create 202→T7.1 汇总（16 实例
  算术守恒/6 issues/provisional=false）→幂等 200 reused→票据→反馈 viewed→
  复检 revision 3 manual_recheck→未签名 401。证据=review/jhemr-l1-20260911.log；
  自动化=prearchive test_pa_jhemr_check 12 + 主侧 test_jhemr_integration 13 +
  包契约 test_pa_integration_package 7；联调包=prearchive_service/integration/jhemr/。
- L2 真实测试 JHEMR 显示并可打开正确就诊：**未开始**（需 JHEMR 开发方接入测试
  环境后联合验收，046 §2 Q3 分工）。
- L3 生产试点真实医生整改复检：**未开始**（按 046 §8.2 部署阶段与批准单执行）。

## 8. 模型 stub 与真实运行区别

stub=StubMatchModel（账本确定性生成候选，可控故障注入，零网络）；
真实通道=HttpMatchModel（院内 OpenAI 兼容；PREARCHIVE_MATCH_BASE_URL/API_KEY/model
配置，未配置时 503 不冒称）。本报告所有匹配证据均为 stub；真实模型匹配未运行。

## 9. 第一段交接（2026-09-10，按 046 §6.3 分界=T5 完成后）

**状态：第一段完成，总体未完成。** T0/T9a/T1a/T2/T3/T1b/T4/T5 已闭包；T6 进行中（见上表）；T7/T8/T9b/T10 未开始。第二段从 checkpoint `review/exec-log.md [046:v1.2:T6:IN_PROGRESS]` 的第一个未闭合门继续，同一 047 追加，不新建 048。

### 9.1 第一段交接门禁

- 第一段完整门禁：`run_gates --full --anchor-file docs/reference/gate_anchors.json`，产物 `review/gate-runs/<stage1 时间戳>/`（结果见 exec-log 交接块）。
- 专项真机 E2E（demo wb046 + sidecar，全部真 API）：workbench.spec 2 passed（覆盖导入→匹配→候选接受→trial 执行→观察入页）；rule-center 正向 16 条；legacy-pages 5。
- 必测项无 SKIPPED 充完成：legacy 双轮均实跑（sidecar 由 run_gates 自起自灭）。

### 9.2 当前测试基线（第一段末）

- prearchive：389 passed + 1 skip（046 起点 283+1 → +106 新增）。
- 主服务聚焦（BFF/权限迁移/前端静态契约）：36 passed；主全量以第一段门禁产物为准。
- 前端：typecheck 0 err；unit 62 passed（起点 57 → +5）。
- quick 门禁 4/4 PASS（isolation 79 文件零 import app）。

### 9.3 关键契约/断言变更汇总（第一段）

1. F05 断言迁移表=§3（7 组，负例全保留）。
2. BFF 白名单 20→40（T1a +12、T5 +8、trial 执行/观察/反馈 +3 含在 T5 内），TARGET_PERMISSIONS 逐条矩阵；测试为精确集合比较（非数量下限）。
3. 引擎 notice.status 值域 pass/skip→五态+excluded（reason 字符串兼容）；evaluations 逐实例记录。
4. example_rules v2026.09.10-046-t3（16 条）；旧版 example_rules_v2026.08.29-qc-authorized-v1.json.bak 保留。
5. RESULT 表 +4 列；闭环 10 新表（含 TRIAL_FEEDBACK）；AUDIT_ACTIONS +13。
6. envelope v1 additive：resolutions/shadow/run_revision/ruleset_revision（schema json 同步；旧接收端可忽略）。
7. 生命周期测试草稿体 empty_field→time_limit（empty_field 被 046 字段依赖发布门正确拦截=预期）。
8. E2E 计数 14→16（规则数）；demo dry-run PHI 哨兵 '10.' 字面→IPv4 正则。

### 9.4 环境与进程

- demo 栈：run-id=wb046（demo serve 18080；sidecar 已停由 run_gates 自管）；数据目录 data/demo/wb046 与 config/demo/wb046。
- 直跑 prearchive 网络类测试需 `NO_PROXY=127.0.0.1,localhost`（系统代理劫持回环，run_gates 已内置注入）。
- 迁移已应用：本地演示库 data/prearchive_result.db 与 data/demo/wb046 侧（scripts/migrate_prearchive_schema_20260910.py --apply；含 TRIAL_FEEDBACK）。

### 9.5 第二段执行结果（2026-09-11，终版）

T6/T7/T8/T9b/T10 全部闭合（见 §1 对应行）；本 047 即最终交付报告，不新建 048。
第二段测试增量：prearchive 389+1→438+1（+49），主服务 1363→1376（+13）。

## 10. 终版门禁（T10，2026-09-11 09:12，run_gates --full --anchor-file）

| 门禁 | 结果 | 计数 | 备注 |
| --- | --- | --- | --- |
| compileall / naming / isolation / sidecar_check | PASS | - | isolation 94 文件零 import app |
| main_pytest | PASS | **1376 passed** | 锚 1327（046 起点+49；第一段 1363+13） |
| prearchive_pytest | PASS | **438 passed+1 skip** | 锚 283（第一段 389+49） |
| typecheck / build | PASS | - | ui-next 镜像无漂移 |
| frontend_unit | PASS | **62 passed** | 锚 57 |
| frontend_e2e | PASS | **52+17 expected skip** | =锚 |
| legacy_rule_center_e2e | **PASS 双轮实跑** | 正向 1+降级 1 | demo wb046 serve；sidecar 自起自灭；无 SKIPPED 充完成 |
| 锚比较 | **全部不低于** | - | gate_anchors.json 未上调 |

产物=review/gate_full_stage2b.log 与 review/gate-runs/（09:12 时间戳目录），exit 0。
首跑（09:06 无 demo）legacy 双轮 SKIPPED(no-demo) 不算完成，起 demo 后复跑闭合；
两跑产物均保留。

## 11. 完成定义对照（046 §9 本地开发清单）

- [x] 92 项覆盖账本完整（rules/paperless_coverage_v1.json，123 条款行；11 FID 发布锚 full/partial 如实标注，blocked 不伪装通过）。
- [x] AI 匹配→候选→批量 trial→观察/反馈→确认发布全流程可操作（第一段 T5 真机 E2E 2 passed；真实模型与 stub 区别见 §8）。
- [x] F01-F12 已修复或有验证过的能力边界（F03/F04/F05/F06/F07/F08/F09/F10 第一段；F01/F02 账本+流程 T1；F11 T7 可信上下文+签名；F12 T3 事件关联；F13=ST-001 T9a）。
- [x] 自动运行入口真正串到 Outbox 和合成接收端（T6：poll_once 正常入口自动入队，禁手工 enqueue 证据；含整改复检 resolutions 更新）。
- [x] 两套前端维护+核查、权限/未知状态/故障降级（T4/T5+第一段门禁双前端套件）。
- [x] JHEMR 五接口+联调包完成（T7；客户端分工=046 §2 Q3 用户确认）。
- [x] 旧 AI 质控/双调度/日志/导出/人工标记/Relay/H5 回归（终版门禁 main 1376+legacy 双轮）。
- [x] 全量门禁+专项通过；版本/证据/回滚/未完成已交接（§5/§5.1/§5.2/§10）。
- [x] 047/INDEX/023 阶段行/启动包/01 登记；045 F0-F5/D1-D8/ST/OBS 全核销（044 §11+各包证据）；无「已裁定仍待用户」残留。
- [x] 白名单 46 精确集合/权限矩阵、F05 断言迁移（§3）、GET v2 schema（§4）、无新增启动 seed（T1a 守卫测试）验证通过。

业务终态三项（真实接收方/真实试点/新目录运维交接）=L2/L3/生产范围，未完成（§7/§5.2）。

## 12. 92 项覆盖与真实接线证据指针

- 覆盖账本：`prearchive_service/rules/paperless_coverage_v1.json`（§3 断言迁移表另见）。
- 真实接线（合成链全程真 API）：第一段=workbench.spec 2 passed（导入→匹配→候选→trial→观察）；
  第二段=T6 test_pa_delivery_wiring 11（触发→自动事件→dispatch→ACK→sent）+T7 L1
  review/jhemr-l1-20260911.log（真实双服务栈五接口全链）。
- 模型 stub 与真实区别：§8；JHEMR 能力级别：§7。

## 13. 048 执行批次追加更正（2026-09-15；append-only，不改写上文）

048（系统可靠性与工作台完善）执行 AI 对本报告两处事实性更正，原文数字与建议保留如下说明：

1. **§5 回退建议更正**：「代码回滚=整工作区未提交，直接丢弃即回第一段前状态」的建议**失效**——2026-09-15 时工作区已混合 043–048 多批次未提交改动，整区丢弃会损毁其他会话成果。正确回退口径见 049 §9：以 048 批次 before 副本（`review/system-hardening-20260915/before/`+SHA256）与该批 diff 为单位逐文件回退，禁止 `git reset/clean/stash` 整工作区。
2. **§10 门禁表「锚」数字口径更正**：§10 所写「锚 1327」系误标——1327 是 2026-09-07 权威跑（gate-runs/20260907-215610）的实际通过数，并非机器锚；机器锚单一来源=`docs/reference/gate_anchors.json`（main_pytest=1295，2026-09-07 定格 042 基线）。2026-09-11 实跑 1376 为实际数，远高于锚。三类数字（机器锚/历史实跑/报告引用）自此区分，锚文件未改动。

（证据：049 §4 Q3/D1；`review/system-hardening-20260915/baseline.txt`。）

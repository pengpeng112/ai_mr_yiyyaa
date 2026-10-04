# 050 — D-J1 修复与历史批次分批提交一次性计划

> 制定日期：2026-09-21（Asia/Shanghai）｜制定者：ZCode/GLM-5.3（受用户委托编制，交外部 AI 执行）
> 版本：**v1.1**（multi-review round-6 三方互查后修订；v1.0 原文固化于 `review/round-6/方案.md` §2）
> 状态：**已执行完毕，交付=051（2026-09-21，T0–T5 全包：B1–B4 四批 140 文件落库+D-J1 A 案修复+L1 修复与强化+全量门禁 11/11+锚更新+B5 提交；零生产、未 push）**
> 上游依据：D-J1=049 §4/§10；**Git 分批提交=用户 2026-09-21 委托（"详细的执行计划…交给别的 AI 一次性开发完成"），属本计划新立事项，049 §10 无此条目**
> 配套提示词：`开发起步包/PROMPT-20260921_DJ1修复与历史批次提交一次性执行.md`（v1.1）
> 交付报告预留路径：`docs/ACTIVE/051_050_EXECUTION_DELIVERY_REPORT_20260921.md`
> 边界：零生产、零真实患者、零真实模型外呼、**不 push / 不 tag / 不 PR / 不切分支**；Git 写操作仅限本地 commit，且以 §0.1-7 条件生效

---

## 0.0 修订记录

- v1.1（2026-09-21，round-6）：①commit 授权改条件生效（v1.0"已批准"表述不成立，三方一致）；②修 B2 `run_service.py` 路径（实为顶层 `prearchive_service/run_service.py`）；③B5 补 PROMPT-20260921 并加动态清单规则；④T0 端口命令改有效参数（脚本无 `--dry-run`，默认即 dry-run）；⑤计数改"以 T0 实测为准"（编制时=134：61M+73??）；⑥T3 补 demo 栈起停前置（否则 legacy 门 SKIPPED）；⑦D-J1 契约细化（物化失败→partial 降级+重试+故障注入；"齐"判据=本次 run fail 去重 keys ⊆ GET keys；L1 判据=期望 key 集合；T2.4 注明仅防回归）；⑧B 案加前置条件默认不采用；⑨锚预期改 049 实测下限口径；⑩T4/T5 拆分（051 骨架进 B5、终稿允许残留）；⑪checkpoint 每包即写；⑫逐文件 add+4 目录白名单例外；⑬§2 拆三清单+全路径；⑭删 RP1（git 96891f6 已记复核通过）；⑮L1 钉死 APP_DB_TYPE=sqlite+输出目录参数；⑯reset --mixed 限定最后一批；⑰T0 记录初始 staged；⑱101 移 B1；⑲杂项（四步流程/估时/口径/023 §0.6 行/前缀注记）。完整裁决见 `review/round-6/分歧表.md`。
- v1.0（2026-09-21）：初版。
- v1.1 补记（2026-09-21 同日）：用户完成 round-6 人工终审，**裁定选项 A=批准 PROMPT 提交条款（五批本地 commit、不 push）**；§0.1-7/§7 授权状态更新为已生效，PROMPT 提交条款改确定性表述。计划文本其余不变。

## 0.1 已裁定事实（禁止再争论，直接执行）

1. **D-J1 修复=A 案物化前移**（三方独立代码核验 `materialize_for_run` 不读 run 终态字段，可行）：把物化块（含 trial 跳过、try/except、resolutions 计算）整体移到 `finish_run` 之前；**只搬物化块，emit 留在 finish 之后**（`trigger.py:289` 注释"用 finish 后的最新 run"，envelope `checked_at` 依赖之，前移会使 checked_at 变 `now()` 回退值）。验收契约：**run 状态首次变为 completed 起，JHEMR GET 返回 issues 必须满足"本次 run fail evals 按 rule+event 去重 keys ⊆ GET 返回 keys"**（GET 返回的是就诊全部非 trial issues、含历史状态，"齐"只针对本次新增部分）。**物化失败语义**：内联重试一次→仍失败则 run 状态降级 `partial` 并在 health/summary 附 `issues_materialization=failed` 诊断——物化失败时不得发布 completed；故障注入用例固化该行为。**B 案（GET 稳定读）默认不采用**，仅当 A 案被测试证实不可行时启用，且启用前置条件=已物化标记短路、并发互斥、重复调用不改 version、`UQ_PREARCHIVE_ISSUE_KEY` 冲突捕获重读（`materialize_for_run` 非幂等：fail 命中路径每次 version+1）。
2. **提交粒度**：commits 是主题检查点非历史重演——工作区文件为 043–049 未提交累积终态，按 §3 T1 归属表整文件归批；**仅完整批次集合保证可构建，单个 hash 不是可部署/可独立回退版本**（B2 引用的 closed_loop_api 等在 B3 才提交）；编年权威=`开发起步包/01_统一修改记录.md`。
3. **分支**：留在 `fix/ora-12609-p4-error-code` 继续 commit；不合并 master、不新建分支。
4. **锚更新**：全量门禁全绿后用 `scripts/update_gate_anchor_20260906.py <result.json> --anchor-file docs/reference/gate_anchors.json`；**锚是 passed 计数下限，旧锚低于新基线=更宽松而非更严格**；执行前确认 result.json 各计数≥旧锚（脚本为整体替换语义）；旧值→新值记 051；脚本异常则不手改锚（错过抬锚，无破坏），记偏差。
5. **扣留项**：`.v2c/`、`.video_agent/`——round-6 已核为 ZCode CLI 官方插件缓存指针文件（video2code 0.6.0 / video-agent-kit 0.4.3），**非本仓资产**：不提交、不删除，051 报告用户裁定（是否加 .gitignore）。
6. **外部事项**（与 049 §10 的 D-J1 之外各项一致）：JHEMR L2/L3、真实 AI 匹配通道、真实回测、W10 清单、生产 DBA 迁移、UI Next canary。~~RP1 双发复核~~ 已于 commit 96891f6（2026-09-01）记录复核通过，不再列为待办。
7. **commit 授权（round-6 人工终审已裁定）**：**2026-09-21 用户明示批准 PROMPT 提交条款（选项 A：五批本地 commit B1–B5、不 push）——授权已生效，无需逐批再确认**；范围=本地 commit，不含 push/tag/PR。演练模式条款（T1 降级为"归属核对演练"、零 commit）保留作未批准情形的历史文本，不再适用。

## 0.2 红线（违反=交付作废）

1. **add 规则**：仅允许 `git add <显式完整路径>`，**一律逐文件**；仅 4 个未跟踪目录允许整目录 add（`.agents/skills/med-audit-demo-stack/`、`.agents/skills/med-audit-gates/`、`.agents/skills/med-audit-oneshot-delivery/`、`prearchive_service/integration/`、`frontend/src/features/governance/components/`——共 5 目录，add 前后清点文件数一致）；**禁止** `git add -A` / `git add .` / `git add -u`，禁止对 `prearchive_service/prearchive/`、`prearchive_service/tests/`、`tests/`、`frontend/src/`、`static/` 等父目录整目录 add（会把 B3 文件打进 B2）。每批 add 后 `git status --porcelain` 核对 staged 集合=清单∩现存，多 stage 即 `git restore --staged <多余路径>` 修正（仅限本轮误加项）。
2. **撤销规则**：禁止 `git reset --hard` / `git clean` / `git stash` / rebase / cherry-pick；`git reset --mixed` 仅允许撤销**当前最后一批**且 HEAD 与 commits.md 记录一致时使用（会移走该批及其后全部提交），中间批次问题走 §6 升级出口；每次撤销在 01/051 登记。
3. 提交信息=`类型(范围): 中文摘要`（§3 T1 建议文本可微调不改语义）；commit 后新增 01 关联登记行补记全部 hash。
4. 路径书写：**禁用花括号展开写法**（`{README,01}.md` 在 pwsh 不展开且 `01.md` 不存在），全部写完整路径。
5. PHI 不进产物；`review/` 与 `docs/attachments/` 不入 git（gitignored，add 清单核对零混入）。
6. 未知归属统一处置：保留现场、不提交、不删除，051 列清单待用户裁定；"拒绝生产/push 等请求"仅指当前范围，用户后续明示授权后按新授权重新核对范围执行。
7. 未尽事项走 §6 升级出口，不擅自扩大授权。

## 1. 背景与目标

048 批次（2026-09-15，交付=049）后，本地仅剩两个可做事项：

1. **D-J1**（049 §4）：`trigger.py::process` 先 `finish_run`（:286）后 `materialize_for_run`（:294），JHEMR 轮询方在 completed 后毫秒级内可能读到 issues 空/不齐（L1 实测 first observed=0、稳定态=4）。修复需 `trigger.py`/`integration_api.py` 白名单扩展——本计划即授权载体。
2. **Git 分批提交**（用户 2026-09-21 委托新立）：工作区编制时 134 项未提交（61 M + 73 ??，**以 T0 实测为准**；含 050/PROMPT 自身后为 136）= 043–049 未提交累积终态。**提交保护的是纳入版本控制的代码与文档；`review/` 证据目录不入 git，其备份属独立事项，不由本计划解决**。

目标：一个连续主线完成 D-J1 修复+竞态/故障注入测试+L1 断言强化+全量门禁（demo 栈编排）+锚更新+五批本地 commit（条件生效）+051 交付登记。

## 2. 三清单（源文件白名单 / 允许生成产物 / 提交清单）

**A. 源文件修改白名单**（仅此可改内容）：

| 文件（完整路径） | 用途 |
| --- | --- |
| `prearchive_service/prearchive/trigger.py` | D-J1 A 案物化前移+失败降级 |
| `prearchive_service/prearchive/issue_service.py` | 仅当物化前移需调整内部契约 |
| `prearchive_service/prearchive/eval_store.py` | 仅当 finish_run 需原子选项（预期不需要） |
| `prearchive_service/prearchive/integration_api.py` | 仅 B 案启用时（默认不动） |
| `prearchive_service/tests/test_pa_jhemr_check.py` 或新文件 `prearchive_service/tests/test_pa_terminal_consistency.py` | 竞态/故障注入测试 |
| `scripts/run_jhemr_l1_20260915.py` | 判据强化（期望 key 集）+APP_DB_TYPE=sqlite+输出目录参数 |
| `scripts/seed_workbench_demo_20260915.py` | 仅当 T3 demo 造数需要微调（预期不动） |
| `docs/reference/gate_anchors.json` | 仅经 update 脚本（T3），禁手改 |
| `docs/ACTIVE/050_DJ1_FIX_AND_BATCHED_COMMIT_ONESHOT_PLAN_20260921.md`（状态行）、`docs/ACTIVE/051_050_EXECUTION_DELIVERY_REPORT_20260921.md`（新）、`docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md`（仅 §0.6 追加一行）、`docs/INDEX.md`、`开发起步包/README.md`、`开发起步包/01_统一修改记录.md`、`review/exec-log.md` | 交付登记 |

**B. 允许生成的运行产物**（不提交，`review/` gitignored）：`review/dj1-commit-20260921/`（baseline.txt、before/ 副本+sha256、commits.md）、`review/gate-runs/<ts>/`（门禁产物）、L1 新日志（输出到 `review/dj1-commit-20260921/`，旧日志 `review/system-hardening-20260915/jhemr-l1.log` 先备份再动）、前端 build 中间产物。

**C. 提交清单**=T1 归属表（B1–B4）+ B5（§3 T4：显式清单+动态规则——T2 实际修改过的 A 清单文件全部入 B5，逐一核对）。

白名单外文件**只允许 git add，不允许内容修改**；B1–B4 批内文件发现内容疑误→保留现场+偏差登记，不顺手改。

## 3. 任务包（T0–T5，按序执行）

### T0 现场冻结与基线（~10min）

1. 记录 `git rev-parse HEAD`、`git branch --show-current`（预期 `fix/ora-12609-p4-error-code`）、**当前 staged 状态**（`git diff --cached --name-only`；若非空，逐项核对归属并记录——非本轮误加的既有 staged 不自动撤销，报告处理）。
2. `git status --porcelain` 全清单落 `review/dj1-commit-20260921/baseline.txt`；与 §3 T1 归属表逐项对照：多出的文件→按归属规则归类或扣留（记偏差）；少了→记偏差不臆造。**计数以实测为准**（编制时参考=134：61 M+73 ??；v1.1 编制后含 050/PROMPT 自身=136：61 M+75 ??，其中 050 与 PROMPT-20260921 归 B5）。
3. 端口检查（只读；脚本**无 `--dry-run` 参数，默认即 dry-run 只打印计划**，4173 恒只报不杀）：`python scripts/clean_demo_ports_20260906.py --ports 18080,18081,18082,18600,18601,18602`；预期全部空闲；未知进程占用→记录并评估受影响步骤，不擅自清空。
4. `python scripts/run_gates_20260906.py --quick` 必须 4/4 PASS（快速冒烟；全量基线证据=049 §6，本轮全量在 T3 重取）。
5. before 副本：`trigger.py`、`issue_service.py`、`run_jhemr_l1_20260915.py` 复制到 `review/dj1-commit-20260921/before/`（+sha256）。
6. **开工即建滚动 051 骨架**（含当前 HEAD、已完成步骤、失败命令、证据、下一步——每包完成即更新，不等 T5）。

### T1 历史批次分批提交 B1–B4（~60min；条件生效见 §0.1-7）

**每批四步**：①`git add <该批显式路径清单>`（逐文件；5 个白名单目录例外）；②`git status --porcelain` 核对 staged=清单∩现存；③`git commit -m "<该批信息>"`；④hash 即时记 `review/dj1-commit-20260921/commits.md`+exec-log checkpoint。

**归属表**（round-6 逐文件核定，执行时只需核对；同文件多批次→归语义主体批次并记 051 备注）：

**B1 `chore(efficiency): 043/044跨会话效率治理+门禁基建+045计划与指令治理产物`**
- `.agents/skills/med-audit-demo-stack/`、`.agents/skills/med-audit-gates/`、`.agents/skills/med-audit-oneshot-delivery/`（目录；含 09-12 指令治理修订累积态）
- `scripts/run_gates_20260906.py`（043 创建，含 048 双 spec 扩展累积态）、`scripts/clean_demo_ports_20260906.py`、`scripts/update_gate_anchor_20260906.py`、`scripts/export_zcode_conversations_20260906.py`
- `docs/reference/gate_anchors.json`（043 首版；T3 更新后 B5 再提交新值）
- `docs/reference/101_FEATURE_BASELINE.md`（**round-6 自 B2 移入**：唯一改动=043 门禁锚指针节，diff 注释明示"2026-09-07，043"）
- `tests/conftest.py`、`tests/test_gate_scripts_20260906.py`、`tests/test_agent_efficiency_skills.py`、`tests/test_env_guard_conftest.py`、`tests/test_instruction_governance_20260907.py`
- `docs/ACTIVE/043_AGENT_EFFICIENCY_REVIEW_AND_AUTOMATION_PLAN_20260906.md`、`docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`、`docs/ACTIVE/045_044_VERIFICATION_REMEDIATION_PLAN_20260908.md`
- `开发起步包/PROMPT-20260906_会话全量获取与跨AI分析.md`、`开发起步包/PROMPT-20260906_跨会话效率治理一次性执行.md`、`开发起步包/PROMPT-20260908_044核查修复一次性执行.md`

**B2 `feat(prearchive): 046/047无纸化规则中心闭环+JHEMR五接口+覆盖账本/AI匹配/trial/Outbox`**
- `prearchive_service/prearchive/` 下 M 集（**逐文件**）：`admin_api.py`、`api.py`、`backtest.py`、`collectors.py`、`engine.py`、`field_registry.py`、`fixture_sources.py`、`models.py`、`outbox.py`、`result_contract.py`、`rule_models.py`、`rule_repository.py`、`rule_service.py`、`store.py`、`trigger.py`（新集）：`closed_loop_models.py`、`coverage.py`、`delivery_wiring.py`、`diagnostics.py`、`eval_store.py`、`integration_api.py`、`rules_provider.py`、`trial_service.py`（closed_loop_api/issue_service/match_service→B3）
- `prearchive_service/run_service.py`（**顶层路径，v1.1 修正；非 prearchive/ 子目录**）
- `prearchive_service/config.example.json`、`prearchive_service/rules/example_rules.json`、`prearchive_service/schemas/qc-result-v1.schema.json`
- `prearchive_service/rules/paperless_coverage_v1.json`、`prearchive_service/rules/example_rules_v2026.08.29-qc-authorized-v1.json.bak`
- `prearchive_service/sql/create_prearchive_closed_loop_oracle_20260910.sql`
- `prearchive_service/integration/`（目录）
- `prearchive_service/tests/` 下（**逐文件**）M 集：`test_pa_admin_api.py`、`test_pa_anchor_modes.py`、`test_pa_delivery_outbox.py`、`test_pa_demo_lifecycle_http.py`、`test_pa_e2e.py`、`test_pa_engine_time_limit.py`、`test_pa_rule_center_lifecycle.py`、`test_pa_rule_registry_modes.py`、`test_pa_rules.py`、`test_pa_rules_t24.py`、`test_pa_system_push_channel.py`；新集：`test_pa_backtest_v2.py`、`test_pa_closed_loop_api.py`、`test_pa_coverage_ledger.py`、`test_pa_delivery_clock.py`、`test_pa_delivery_wiring.py`、`test_pa_engine_events.py`、`test_pa_eval_states.py`、`test_pa_integration_package.py`、`test_pa_jhemr_check.py`、`test_pa_match_service.py`、`test_pa_ops_diag.py`、`test_pa_publish_atomic.py`、`test_pa_rules_fid11.py`、`test_pa_trial_run.py`、`test_pa_workbench.py`（checks_pagination/match_recovery→B3）
- `app/main.py`、`app/routers/jhemr_integration.py`、`app/routers/menu.py`、`app/services/feedback_stats.py`、`app/services/prearchive_admin_client.py`、`app/demo_support/seed.py`（prearchive_admin.py→B3）
- `frontend/playwright.config.ts`（046 ST-002）、`frontend/src/components.d.ts`、`frontend/src/features/governance/AuditTypesPage.vue`、`frontend/src/features/governance/components/`（目录）、`frontend/src/router/route-manifest.ts`、`frontend/tests/e2e-legacy/legacy-pages.spec.ts`、`frontend/tests/e2e-legacy/rule-center.spec.ts`、`frontend/tests/unit/prc-rule-edit-drawer.test.ts`（prearchiveAdmin.ts/types.ts/WorkbenchPage.vue→B3）
- `tests/test_jhemr_integration.py`、`tests/test_qc_permission_migration_20260910.py`、`tests/test_t9a_tool_oracle_fixes_20260910.py`、`tests/test_menu_api.py`（046 T5 menu 18）、`tests/test_prearchive_rules_display.py`（test_prearchive_admin_bff.py→B3）
- `scripts/migrate_qc_permissions_20260910.py`、`scripts/migrate_prearchive_schema_20260910.py`、`scripts/run_prearchive_backtest_20260911.py`
- `docs/ACTIVE/046_PAPERLESS_RULES_JHEMR_CLOSED_LOOP_PLAN_20260910.md`、`docs/ACTIVE/047_046_EXECUTION_DELIVERY_REPORT_20260910.md`
- `开发起步包/PROMPT-20260910_046统一修复与无纸化JHEMR闭环执行.md`

**B3 `feat(prearchive): 048/049工作台分页有界聚合+匹配事务+BFF any-of+双前端硬化`**
- `prearchive_service/prearchive/closed_loop_api.py`、`prearchive_service/prearchive/issue_service.py`、`prearchive_service/prearchive/match_service.py`
- `app/routers/prearchive_admin.py`
- `frontend/src/api/endpoints/prearchiveAdmin.ts`、`frontend/src/api/types.ts`、`frontend/src/features/governance/WorkbenchPage.vue`
- `static/scripts/app.js`、`static/scripts/modules/prearchive_rule_center.js`、`static/templates/pages/audit_types.html`（`static/ui-next/` 若出现在 status 一并归本批）
- `frontend/tests/e2e-legacy/workbench.spec.ts`、`frontend/tests/e2e/workbench-real.spec.ts`
- `prearchive_service/tests/test_pa_checks_pagination.py`、`prearchive_service/tests/test_pa_match_recovery.py`、`tests/test_prearchive_admin_bff.py`
- `scripts/seed_workbench_demo_20260915.py`、`scripts/run_jhemr_l1_20260915.py`（T2 将再改，B5 提交增量）
- `docs/ACTIVE/048_SYSTEM_HARDENING_ONESHOT_PLAN_20260915.md`、`docs/ACTIVE/049_048_EXECUTION_DELIVERY_REPORT_20260915.md`
- `开发起步包/PROMPT-20260915_系统可靠性与工作台完善一次性执行.md`

**B4 `docs(governance): 协作规则/总索引收口(09-08与09-12指令修订+023阶段行)`**
- `AGENTS.md`、`CLAUDE.md`、`docs/skills/med-audit-codex.md`、`.agents/skills/med-audit-history-remediation/SKILL.md`
- `docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md`、`docs/INDEX.md`
- `开发起步包/00_AI协作规则.md`、`开发起步包/README.md`、`开发起步包/01_统一修改记录.md`、`开发起步包/PROMPT-20260919_历史会话供外部AI分析使用说明.md`

**扣留（不提交不删除）**：`.v2c/`、`.video_agent/`

B4 后核对：`git status --porcelain` 应仅剩扣留目录+`docs/ACTIVE/050_*.md`+`开发起步包/PROMPT-20260921_*.md`（两者归 B5）+本轮 T2 起的新改动。跑一次 `--quick`（4/4）确认提交未破坏现场。

### T2 D-J1 修复（~60min）

1. **复现先行**：新文件 `prearchive_service/tests/test_pa_terminal_consistency.py`（stack 构造同 `test_pa_jhemr_check.py`）——spy `EvalRunStore.finish_run`，在真实 finish_run 执行**前**断言该 run 的 IssueRow 物化行已存在（编码 A 案顺序）；旧代码必 FAIL=复现证据落 051。**若最终采用 B 案，此测试改写为 GET 侧断言**（终态首查 issues 齐）。
2. **A 案实现**（`trigger.py`）：物化块（trial 跳过+try/except+resolutions 计算）整体移到 `finish_run` 前；**emit 不动**（§0.1-1）。物化失败路径：内联重试一次→仍败则 `run_status` 降级 `partial`+`issues_materialization=failed` 诊断。
3. **契约测试**（同文件）：①顺序断言（上）；②**HTTP 首查**：process 完成后 GET `/api/integration/jhemr/submission-checks/{check_id}`（**预检内部前缀为单数 integration；主服务 BFF 为复数 integrations——两套前缀是既有架构，勿"顺手统一"**）断言 completed 且"本次 run fail 去重 keys ⊆ GET keys"。**注（round-6）**：TestClient 同步执行，旧代码下该测试同样通过——**仅作防回归，不作 D-J1 复现证据**；复现证据只认步骤 1 spy 测试与 L1。③**故障注入**：物化抛异常 ⇒ run≠completed（=partial）+诊断标记存在。
4. **L1 强化**（`scripts/run_jhemr_l1_20260915.py`）：①期望 key 集合断言（合成 fixture 的预期 rule+event keys；first 与 stable 均须=期望集，"非空即稳"旧判据废弃）；②子进程 env 显式 `APP_DB_TYPE=sqlite`（`app/database.py` 按 env 选库，防条件性继承 Oracle）；③输出目录参数（本轮写 `review/dj1-commit-20260921/`，旧日志先备份）。
5. 定向回归：`python -m pytest prearchive_service/tests/test_pa_terminal_consistency.py prearchive_service/tests/test_pa_jhemr_check.py prearchive_service/tests/test_pa_workbench.py prearchive_service/tests/test_pa_delivery_wiring.py -q` 全绿；`python scripts/run_jhemr_l1_20260915.py`（新输出目录）ALL PASS。

### T3 全量门禁 + 锚更新（~数十分钟；049 实测无失败复跑约 6-7 分钟）

1. **demo 栈前置（round-6 补，必需）**：`run_gates` 不启动 18080 主服务，端口未听时 legacy 门直接 SKIPPED（`run_gates:313`）→ 不算 11/11。编排（用 med-audit-demo-stack Skill）：`python scripts/demo_env.py create+serve`（run-id 自定，18080-18082）→ 健康检查 → sidecar 18600 由门禁自管自回收，workbench 造数由 spec 内幂等 seed 自带 → `python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json` 必须 11/11 PASS、锚全部不低于、exit 0 → **finally 停 demo**（`demo_env.py stop --run-id`）并核验端口零残留。
2. 锚更新：确认 result.json 各计数≥旧锚 → `python scripts/update_gate_anchor_20260906.py review/gate-runs/<本轮ts>/result.json --anchor-file docs/reference/gate_anchors.json`；旧→新记 051。**预期口径：以 049 实测（main 1379 / prearchive 452+1skip / unit 62 / e2e 52）为下限参考；本轮新增用例计入 prearchive（不进 main），以当次 result.json 实数为准**。脚本异常→不改锚记偏差（§0.1-4）。

### T4 B5 提交（~10min；条件同 T1）

`fix(prearchive): D-J1终态物化顺序修复+竞态故障注入测试+门禁锚更新+051交付`
- 显式清单：`prearchive_service/prearchive/trigger.py`（+实际动过的 `issue_service.py`/`eval_store.py`/`integration_api.py`）、`prearchive_service/tests/test_pa_terminal_consistency.py`（或实际动过的 `test_pa_jhemr_check.py`）、`scripts/run_jhemr_l1_20260915.py`、`scripts/seed_workbench_demo_20260915.py`（若动）、`docs/reference/gate_anchors.json`、`docs/ACTIVE/050_*.md`（状态行）、`docs/ACTIVE/051_*.md`（**骨架**，含 B1–B4 hash）、`docs/ACTIVE/023_*.md`（§0.6 追加 050/051 行）、`docs/INDEX.md`、`开发起步包/PROMPT-20260921_DJ1修复与历史批次提交一次性执行.md`（**v1.1 补**）、`开发起步包/README.md`、`开发起步包/01_统一修改记录.md`
- **动态规则**：逐一核对 T2 实际修改集⊆清单 A，白名单内修改而未列出的文件必须补入 B5。
- B5 自身 hash 无法预写入 051——终稿处理见 T5。

### T5 收尾核验与登记（~15min）

1. 051 终稿（含 B5 hash 与五批全表）：结构=逐包勾选/五批 commit 表/门禁表含锚旧新/D-J1 证据（spy 复现 FAIL→修复 PASS、故障注入、L1 期望集比对）/偏差说明/扣留清单/回退（逐批 reset --mixed 仅限最后一批+before 副本）。**051 终稿与 INDEX/01 的 B5-hash 补记按 00 §6 惯例允许留在工作区并在交付时说明**；如需工作区干净，可追加一次 `docs(delivery): 051终稿与登记补记` commit（§0.1-7 授权范围内，须在 051 声明"六次提交"）。
2. 01 追加登记行（执行批+全部 hash 补记，字段含批数与文件数）。
3. INDEX：050 标已执行、051 行补状态、盘点行前缀、文首更新时间同步。
4. 最终核验：`git status --porcelain` 仅预期残留（扣留目录+01 尾行/051 终稿等，逐项列出）；`git log --oneline -6`（或 -7）显示各批；端口零残留。
5. exec-log checkpoint `[050:T0..T5]` 逐包一行（**每包完成即写，此处仅为收尾核对**）。

## 4. 顺序与依赖

T0 → T1（B1→B2→B3→B4 严格按序）→ T2 → T3 → T4 → T5。T1 先于 T2（D-J1 diff 干净落 B5）；T3 先于 T4（锚新值与全绿证据进 B5）；T2 失败不阻塞已完成的 T1；T3 失败阻塞 T4；**T1 未获 commit 授权时降级为核对演练，不阻塞 T2 起后续**。

## 5. 验收标准

| 包 | 验收 |
| --- | --- |
| T0 | baseline.txt+初始 staged 记录落盘；quick 4/4；端口空闲；滚动 051 已建 |
| T1 | 四步流程×4 批全过；每批 staged=清单；4 hash 记录；批后 quick 4/4（或演练模式=归属表+预演记录+零 commit） |
| T2 | spy 测试先 FAIL 后 PASS；故障注入（物化异常⇒非 completed）；HTTP 契约 keys 断言过；定向回归+L1（期望集）ALL PASS |
| T3 | demo 栈起停完整；full 11/11 PASS 锚全不低于（无 SKIPPED 充数）；锚更新成功（或偏差登记） |
| T4 | B5 hash 记录；staged=清单+动态核对 |
| T5 | 051 终稿含五 hash；01/INDEX/README 登记；最终 status 仅预期残留 |

## 6. 升级出口（停下问用户）

1. T0 归属核对发现归属表外仓库文件（非扣留项）→ 扣留不提交，继续其余，051 列清单。
2. A 案破坏 materialize/emit 既有测试语义且 B 案前置条件不满足 → 停 T2，保留 T1 成果，报告两案证据。
3. 全量门禁失败且定位超 30 分钟（估时口径：全量门禁本身数十分钟属正常，30 分钟指"失败后定位"）→ 记失败命令与续跑点（滚动 051），停止后续提交。
4. commit 后发现批次混入错误文件 → 仅当该批=当前最后一批且 HEAD 与记录一致时 `git reset --mixed` 撤销重做（01/051 登记）；否则停后续批次报告。
5. `.v2c/`、`.video_agent/` 归属与 `.gitignore` 处置 → 用户裁定（本计划默认扣留）。
6. 任何 push/tag/PR/生产动作请求 → 当前范围一律拒绝并报告；用户后续明示授权按新授权执行。

## 7. 完成定义

- [ ] T0–T5 全部验收通过
- [ ] **模式一（已获批 2026-09-21，本轮适用）**：5 个本地 commit（B1–B5）落库，hash 已登记，未 push
- [ ] **模式二（未获批）**：T1 演练产物完整（归属表+staged 预演+扣留清单），B5 仅提交 T2/T3 成果或全部不提交（按用户指示），零 commit 或仅代码批
- [ ] D-J1 契约有 spy+故障注入+L1 期望集三重固化回归
- [ ] 051 定稿 + INDEX/README/01/exec-log 登记
- [ ] 零生产、零真实患者、零外呼、扣留目录未动

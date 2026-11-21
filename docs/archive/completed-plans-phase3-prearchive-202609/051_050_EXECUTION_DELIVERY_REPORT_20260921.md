# 051 — 050 D-J1 修复与历史批次分批提交执行交付报告

> 版本：v1.0（执行交付，B5 提交版；B5 hash 补记见 §2 脚注与 01 台账补记行）
> 执行日期：2026-09-21｜执行者：ZCode/GLM-5.3
> 作业书：`docs/ACTIVE/050_DJ1_FIX_AND_BATCHED_COMMIT_ONESHOT_PLAN_20260921.md` v1.1（round-6 三方互查修订版）
> 执行请求：`开发起步包/PROMPT-20260921_DJ1修复与历史批次提交一次性执行.md`（commit 条款已获用户 2026-09-21 选项 A 批准：五批本地 commit、不 push）
> 边界遵守：零生产、零真实患者、零真实模型外呼、未 push/tag/PR、未切分支、扣留目录未动

## 1. 执行摘要

T0–T5 六包全部完成。核心成果：

- **T1 五批中的前四批提交落库**（B1–B4，共 140 文件），043–049 六轮未提交累积终态全部纳入版本控制；每批四步流程（逐文件显式路径 add→staged 核对→commit→hash 即记）零偏差。
- **T2 D-J1 修复（A 案）**：`trigger.py` 物化块前移至 `finish_run` 之前——run 一旦置 completed/partial，JHEMR GET 的 issues 必已含本次 run 物化结果；物化失败内联重试一次→仍败降级 `partial` 并留 `issues_materialization` 诊断（不得发布 completed）。复现证据=spy 测试旧代码 FAIL（finish_run→completed 时物化数=0）+故障注入旧代码 FAIL（物化失败仍 completed）；修复后 3/3 PASS、定向回归 32/32、**L1 真双栈 ALL PASS 且 first==stable==expected=6**（D-J1 窗口消除的跨进程实证）。
- **附带发现并修复 L1 预检栈隐患**：`:memory:`+StaticPool 单连接在 uvicorn（BackgroundTasks 走 threadpool 线程）下被 event-loop 线程读事务交叉回滚，实测 issues=0 而 evals=6（TestClient 单线程不复现）——改临时文件 sqlite（与 run_service 生产形态一致）后归真。**更正 049 事实**：其"稳定态 4 条"系该共享连接损坏伪影（6 条 fail eval 受 UQ(run,rule,event) 约束，去重后仍 6 条）。
- **T3 全量门禁 11/11 PASS、锚全部不低于、exit 0**（demo 栈编排前置；4173 占用自动 fallback 4273=046 ST-002 机制生效）；锚更新 main 1295→1379 / prearchive 283→455(+1skip) / unit 57→62 / e2e 52(+23skip)（均≥旧值，仅经脚本）。
- **T4 B5 提交**=本批 D-J1+测试+锚+交付文档。

## 2. 五批 commit 表

| 批 | 信息 | hash | 文件数 | 变更量 |
| --- | --- | --- | --- | --- |
| B1 | chore(efficiency): 043/044跨会话效率治理+门禁基建+045计划与指令治理产物 | `8774f69` | 20 | +2594 |
| B2 | feat(prearchive): 046/047无纸化规则中心闭环+JHEMR五接口+覆盖账本/AI匹配/trial/Outbox | `9050446` | 90 | +16778/-325 |
| B3 | feat(prearchive): 048/049工作台分页有界聚合+匹配事务+BFF any-of+双前端硬化 | `509024a` | 20 | +5007/-14 |
| B4 | docs(governance): 协作规则/总索引收口(09-08与09-12指令修订+023阶段行) | `8d2efcc` | 10 | +175/-50 |
| B5 | fix(prearchive): D-J1终态物化顺序修复+竞态故障注入测试+门禁锚更新+051交付 | （本提交，hash 见 01 补记行） | 11 | 见 git show |

分支=`fix/ora-12609-p4-error-code`（未切）；**未 push/tag/PR**。注：按 00 §6 惯例，B5 hash 与 051 终稿尾注、INDEX/01 补记行留在工作区（见 §7 残留清单）。

## 3. 逐包勾选表

| 包 | 状态 | 证据 |
| --- | --- | --- |
| T0 现场冻结与基线 | ✅ | HEAD=58ea350/分支正确/staged=0/porcelain=136(61M+75??，与 v1.1 预期一致)/端口空/quick 4/4；`review/dj1-commit-20260921/{baseline.txt,baseline-porcelain.txt,before/,before-sha256.txt}` |
| T1 B1–B4 分批提交 | ✅ | `commits.md`；每批 staged=清单；B2 integration/ 目录 find=10 vs staged=9 差异=1 个 gitignored `__pycache__` pyc（已核）；B4 后残留=扣留 2 目录+050/051/PROMPT-20260921（全归 B5），与 v1.1 预期逐项吻合；批后 quick 4/4 |
| T2 D-J1 修复 | ✅ | `prearchive_service/tests/test_pa_terminal_consistency.py`（spy/HTTP/故障注入 3 用例，旧代码 2 FAIL 复现→修复后 3/3）；`trigger.py` A 案；定向回归 32/32（+jhemr_check/workbench/delivery_wiring）；L1 ALL PASS |
| T3 全量门禁+锚更新 | ✅ | demo 栈 create/serve sh050（health 200）→`--full --anchor-file` 11/11 PASS 锚全不低于 exit 0（gate-runs/20260921-201330）→stop 端口零残留；`update_gate_anchor` 旧 5 项→新 5 项（§1 数字） |
| T4 B5 提交 | ✅ | staged=11 文件=清单 A 实改集（trigger/新测试/L1 脚本/锚/050 状态行/051/023 §0.6/INDEX/PROMPT/README/01），动态核对零遗漏 |
| T5 收尾登记 | ✅ | 本 051+023 §0.6 行+INDEX/README/01+exec-log `[050:T0..T5]`；最终核验见 §7 |

## 4. 门禁表（T3 全量，2026-09-21 20:18）

| 门禁 | 结果 | 计数 | 耗时(s) | 备注 |
| --- | --- | --- | --- | --- |
| compileall | PASS | - | 0 | |
| naming | PASS | - | 0 | |
| isolation | PASS | - | 0 | 零 `import app.*` |
| sidecar_check | PASS | - | 4 | |
| main_pytest | PASS | passed=1379 | 71 | 锚 1295→**1379** |
| prearchive_pytest | PASS | passed=455 skipped=1 | 39 | 锚 283→**455**（452+3 terminal_consistency）；1skip=cx_Oracle 驱动冒烟延续 |
| typecheck | PASS | - | 25 | |
| frontend_unit | PASS | passed=62 | 37 | 锚 57→**62** |
| build | PASS | - | 29 | 含 ui-next 同步 |
| frontend_e2e | PASS | passed=52 skipped=23 | 39 | 锚 52/17skip→52/**23skip**（23=环境门跳过：17 既有+6 workbench-real；与 049 同口径） |
| legacy_rule_center_e2e | PASS | - | 31 | 正向 3 passed+降级 2 passed，双 spec 双轮实跑无 SKIPPED |

专项（full 之外）：L1 `python scripts/run_jhemr_l1_20260915.py --out-dir review/dj1-commit-20260921` → ALL PASS（证据=`review/dj1-commit-20260921/jhemr-l1.log`；048 旧日志未覆盖）。

## 5. D-J1 证据链（049 §10 第 3 行核销）

1. **复现（旧代码）**：`test_materialize_precedes_finish_run` FAIL——`finish_run(…→completed) 时已物化 issue 数=0，终态先于物化`；`test_materialize_failure_downgrades_run` FAIL——`物化失败后 run=completed`（契约违反）。
2. **修复（A 案）**：物化块（trial 跳过+重试+降级 partial+诊断）前移；emit 留 finish 后（envelope checked_at 依赖，trigger.py:289 注释口径）。
3. **修复后**：3/3 PASS；故障注入断言"materialize 抛异常 ⇒ run=partial+source_health 含 issues_materialization"；HTTP 契约（GET keys=DB 物化 keys）。
4. **跨进程实证**：L1 first==stable==expected=6 ✓（期望集=fail evals 按 issue_key_for 口径）。
5. **B 案未启用**（A 案一次通过）；其前置条件（已物化短路/并发互斥/重复不改 version）仍记录在 050 §0.1-1 备查。

## 6. 偏差与更正说明

1. **049 事实更正**：§4/§10 中"L1 稳定态=4 条（去重）"实为 L1 预检栈 `:memory:` 共享连接在 uvicorn 双线程下的损坏伪影；6 条 fail eval 因 UQ(run,rule,event) 约束去重后仍为 6 条。本轮文件库修正后实测 6/6。049 历史数字不回写，以本节为准。
2. **L1 判据升级**：旧"非空即稳"重试循环废弃，改期望 key 集断言（round-6 分歧表 #7 落实）。
3. **T2 未动 issue_service.py/eval_store.py/integration_api.py**：A 案在 trigger.py 内闭合，白名单"仅当"文件零修改（B5 动态核对依据）。
4. **e2e skipped 17→23 记入锚**：均为环境运行门（SYNTHETIC_DEMO_E2E/WORKBENCH_E2E 未注入时自动跳过），与 049 §3 口径一致；比较器只约束 passed 不低于。
5. 4173 端口被已知 Playwright preview（pid 11088）占用，门禁按 046 ST-002 自动 fallback 4273，只报不杀。

## 7. 最终核验（T5）

- `git status --porcelain` 残留：`.v2c/`、`.video_agent/`（扣留，非本仓资产——round-6 已核为 ZCode 插件缓存指针，处置待用户裁定）+ 01 补记行/051 尾注等 T5 后追加的登记增量（按 00 §6 留工作区）。
- `git log --oneline -6` 显示 B1–B5 五批（见 §2）。
- 端口 18080-18082/18600/18601-18602 零残留（dry-run 核验）；4173 恒只报不杀。
- exec-log checkpoint `[050:T0..T5]` 逐包落盘。

## 8. 回退步骤

1. 本批代码回退：`review/dj1-commit-20260921/before/` 副本（trigger.py/issue_service.py/run_jhemr_l1）逐文件覆盖+`git diff` 核对；新文件（test_pa_terminal_consistency.py）删除即回退。
2. 提交回退（**仅限最后一批 B5**，且 HEAD 与 commits.md 一致时）：`git reset --mixed 8d2efcc`；更早批次问题走升级出口报告用户，不自行撤销（050 §0.2-2）。
3. 锚回退：旧值见 §4 括号内（1295/283/57/52/17skip），手改仅限用户批准后。

## 9. 外部未完成（不变，049 §10 其余各项）

JHEMR L2 联调 / L3 现场验收、真实 AI 匹配通道、真实回测、W10 清单、生产 DBA 迁移、UI Next canary；另有本轮待用户裁定：`.v2c/`、`.video_agent/` 是否加 .gitignore。

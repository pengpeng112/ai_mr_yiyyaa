# 058 — 057 启动治理与数据库只读探索执行交付报告

> 交付日期：2026-09-28。执行者：ZCode/GLM-5.3。授权=用户当轮指令执行 `docs/ACTIVE/057_STARTUP_GOVERNANCE_AND_DATABASE_READONLY_PLAN_20260925.md` 剩余任务（N0 已完成不重做）。
> 边界遵守：**零生产写入、零数据库写入、零外发、零 Git 写操作**；全部数据库访问为只读事务（各源 guards 证据落盘）；不启用 disabled 源、不改无关业务模块、不降断言/锚。

## 1. 完成定义对照（057 §1 两级）

- **第一级（本地治理和调查报告完成）：达成。** G1–G4、D0–D6、R1 全部执行并验收。
- **第二级（全源现时复核）：未达成，差额如下**——13 个逻辑源 BLOCKED（预检 12 源生产占位禁用+本仓无凭据）+ FILEVERIFY 现时对账子分支 BLOCKED（178:22 拒连）。按计划如实列差额，不宣称全源。

## 2. 逐任务状态

| 任务 | 状态 | 关键产出/证据 |
| --- | --- | --- |
| N0 导航（前置） | DONE（不重做） | 057 §2/§N0 |
| G1 状态矩阵与勘误 | DONE | `review/governance-20260925/status-matrix.csv`（23 行，5 对核销）；056 首部 2026-09-28 勘误（§6.6 无 01 登记仅记冲突）；`g1-repo-docs-diff.md`（ARCHITECTURE/DEPLOY/CLAUDE 差异清单，未改四文件） |
| G2 全目录清单 | DONE | `asset-inventory.csv`（905 文件/类型/跟踪/入站引用）；`archive-manifest.json`（16 PROMPT 候选，哈希） |
| G3 小批迁移 | DONE | 16 个已交付 PROMPT 分两批（8+8）迁至 `docs/archive/governance-20260925/prompts/`（逐文件 SHA-256 双验、无覆盖断言）；INDEX 6 处路径+归档清单行同批更新；oneshot 技能 2 处现役引用同步；历史引用（ACTIVE 报告/01）保留并登记 |
| G4 维护规则与欠账 | DONE | `g4-maintenance-notes.md`：E2E 47 skips=环境类三开关+轮条件（覆盖到=52 mock）；编号/配对/归档入口核对；文档校验器建议（另包）；未完成项六类分账 |
| D0 工具与保护 | DONE | `scripts/explore_databases_readonly_20260925.py`（白名单模板 27、分方言保护链、84 转运、脱敏、预算闸）；`tests/test_database_readonly_explorer_20260925.py` **26/26 PASS**；--help/--dry-run 先行 |
| D1 源台账 | DONE | `review/db-discovery-20260925/source-registry.json`（20 源；2 生产物理实例+本地）；84 只读配置探测（d1_probe_prod_config.py，脱敏） |
| D2 核心链 | DONE（1 子分支 BLOCKED） | 216 应用库（11.2.0.4/355 对象/全部 MED_* 表在场）；ODS（V_QYBR 40 列=V_ZYBR∪V_CYBR、PAT_VISIT 100 列、HIS 域可见）；177 EMR（v_blws 22 列全等、aizk_user 权限面=2 对象）；FILEVERIFY 现时对账 BLOCKED（178:22 拒连） |
| D3 预检/无纸化 | DONE | result_store=216 实测；18 表在位 0 行；RESULT 27 列；anchor=finished+13 源禁用=空转链；CDMS BLOCKED；92 条快照未导入 registry=登记 |
| D4 辅助源 | DONE（全 BLOCKED 待资源） | 五源历史结构留 README §8.3 对照；资源申请入台账 |
| D5 未知/阻塞源 | DONE | PACS/ES/XD/postgres_generic/local_dev_sqlite 状态齐；XD=057 §6 人工输入 |
| D6 契约与建议 | DONE | `d6-findings.md`：9 条问题六类分账+资源申请清单+102 契约无需更新结论 |
| R1 本报告 | DONE | 见下 |

## 3. 修改文件清单

- 代码/测试（新增）：`scripts/explore_databases_readonly_20260925.py`、`tests/test_database_readonly_explorer_20260925.py`。
- 文档：`docs/ACTIVE/056_*.md`（首部勘误）、`docs/INDEX.md`（6 处 PROMPT 路径+归档清单行+057/058 行+导航时间）、`docs/ACTIVE/058_*.md`（本报告，新）、`docs/archive/governance-20260925/README.md`（新）；`.agents/skills/med-audit-oneshot-delivery/SKILL.md`（2 处位置说明）。
- 迁移：`开发起步包/PROMPT-*.md` 16 个 → `docs/archive/governance-20260925/prompts/`。
- review 过程产物（gitignored）：`governance-20260925/`（status-matrix/g1-baseline/asset-inventory/archive-manifest/g3 批次 spec+链接检查/g4 笔记/exec-log）、`db-discovery-20260925/`（source-registry/四源证据 JSON/d1、d2c 脚本/d6-findings/exec-log）。
- 登记：`开发起步包/01_统一修改记录.md` 追加 1 行（append-only）。

## 4. 验证证据

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| D0 离线测试 | 26/26 PASS | `python -m pytest tests/test_database_readonly_explorer_20260925.py -q` |
| 各批次 quick 门禁 | G1/G3/G4/终态 4/4 PASS exit 0 | `review/gate-runs/20260928-{182130,183023,183330,1900xx}/summary.md` |
| 终态 full+锚 | 见交付时附记（§9） | `run_gates --full --anchor-file docs/reference/gate_anchors.json` |
| 链接检查 | 断链仅 2 预期（058 预留→本报告成立后消除；README_CN 对已删除文件的说明性提及） | `g3_link_check.py` |
| 迁移完整性 | 16/16 哈希前后一致、源消失、无覆盖 | `archive-manifest.json`+g3 批次输出 |
| 只读事务证据 | 每源输出 JSON guards 字段（read_only 回验/超时/rollback+close） | `db-discovery-20260925/<source>/*.json` |

## 5. 数据库只读范围与覆盖

- 覆盖：216/orcl（JHEMR 身份/355 对象/V_QYBR/PAT_VISIT/MED_PUSH_LOG/MED_PREARCHIVE_RESULT 列）；177:5432/jhemr（身份/v_blws 22 列/jhmr_file_index 可见性/pg_class 估计）；本地 data/med_audit.db（ro）。
- 未做：任何患者级明细采样（本轮纯结构与聚合，PHI 零读取）；全表 count；被拒源连接尝试。
- 阻塞差额：13 源 BLOCKED + FILEVERIFY jhemr 账号分支（详见 source-registry 与 d6-findings §资源申请）。

## 6. 阻塞项与恢复第一步

| 阻塞 | 缺什么（责任方） | 恢复第一步 |
| --- | --- | --- |
| CDMS 无纸化源 | DSN+只读账号（信息科） | 配置入受控 prearchive 配置后走 D3b 流程 |
| 五源+HIS/SM/LIS/PACS/ES | 各自账号/实例确认（平台/信息科） | 先 his_base 一源试点再批量 |
| XD 心电 | 库型/实例/表名（用户，057 §6） | 用户提供后建独立分支 |
| FILEVERIFY 现时对账 | 178:22 通道（网络/运维）或 jhemr 只读凭据（管理员） | 核 178 sshd/防火墙；`d2c_fileverify_jhdb.py` 就绪 |
| 177 第一批 INSERT | 用户明确批准（056 §6.3） | 本轮零推进，维持待批 |

## 7. 风险与残留

- 056 §6.6 归属：01 无独立登记行（冲突已记勘误，内容与 review 检查点互证）；按 00 规则留用户裁定，未代写。
- 台账级"B 级现时未复核"行（002/011/012/024/025 等，见 status-matrix）待各自轨道现时证据。
- 仓库级说明四文件（ARCHITECTURE/DEPLOY/CLAUDE）补正为后续小批，本报告仅登记差异。
- 探索期对工具的 9 次有证据修正（11.2 方言/保留字绑定/pyformat/锁超时方言/sqlite3 参数等）均以现场实测为据，已固化在工具内并有离线测试回归。

## 8. 审查重点（给复核者）

1. G3 迁移：`git status` 中 16 个 D + 新归档目录逐文件哈希（archive-manifest）；INDEX 引用一致性。
2. 只读保护：`db-discovery-20260925/*/` JSON 的 guards 与 queries 计数；确认无 >20 条/轮、无患者明细。
3. aizk_user 权限面结论（=v_blws+jhmr_file_index）与 056 §6.1 一致性。
4. D6-1（anchor=finished 配置漂移）与 D6-2（账号权限）是否需进入业务变更轨道。

## 9. 终态验证附记

- 终态 full 门禁+锚已执行（2026-09-28 19:08）：**11 项全 PASS + 锚比较全部不低于，exit 0**——compileall/naming/isolation/sidecar PASS；main_pytest **1405 passed/0 fail**（锚 1379，新增 D0 离线 26 项等抬升且不低于）；prearchive 455+1skip（锚一致）；typecheck/build PASS；frontend_unit **69**（锚 62）；frontend_e2e 52+47skip（锚一致，47 skip=环境类三开关，见 G4 §2）；legacy_rule_center_e2e SKIPPED no-demo（本批未起 demo 栈，不冒充实跑）。证据 `review/gate-runs/20260928-190437/summary.md`。
- 回退/恢复：G3 按 archive-manifest 反向映射+哈希核对；本 AI 全部修改文件清单见 §3；数据库侧无任何需回退对象（只读）。
- 回退/恢复：G3 按 archive-manifest 反向映射+哈希核对；本 AI 全部修改文件清单见 §3；数据库侧无任何需回退对象（只读）。

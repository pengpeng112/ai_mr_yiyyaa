# 高危严重度整改与复核交接（契约校验器抬升 + 语义假高危）

> 文档编号：024
> 编制日期：2026-08-17（Asia/Shanghai）
> 性质：交接 + 待独立复核；本文档本身不授权新的生产写入
> 适用系统：Med-Audit 后端（生产 10.10.8.84:8000，容器 med-audit，Oracle 应用库）；历史 Dify 影子工作流已于 2026-08-19 收敛为 `3一致性核查正式版-质控门禁影子V2.yml`
> 交接目的：另一 AI 对 2026-08-17 全天的高危严重度整改做独立复核，验证结论、数字与残留风险
> 后续复核：121 人新表与分质控可行性的独立复核见 `docs/ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md`；025 不回溯授权新的生产写入

---

## 0. 一页摘要

2026-08-17 处理了两个层面的高危（severity=high/red）数据质量问题，全部改动已热部署生产：

1. **机械层 bug（后端）**：`result_contract_validator.py` 曾把工作流合法输出的 `(fail, medium, yellow)` 强制"修复"为 `(fail, high, red)`，且发生在高危守卫之后，导致大量中风险问题被抬成高危落库。已修复为"只降不升"。
2. **语义层假高危（AI 输出）**：内网 AI 把 omission（单方未写/新增诊断）、数据质量（BMI=0）自我标注为 contradiction/severe，机械门槛无法识别。已通过开启并扩展语义降级规则处理。
3. **三轮存量整改**共降级 **1,356 条假高危维度**（546 + 694 + 116），同步 594 条汇总级记录；7/14 以来高危维度 3,042 → **1,686**，患者质控总览高危分组 1,389 → **819**。所有降级带审计标记并有 JSON 备份。
4. **影子 YML 增量修正**：7 条支路插入"确定性修正"代码节点（围栏清理/枚举标准化/summary 代码汇总）+ 3 个可选 start 患者字段；**14/14 提示词、5/5 原有代码节点逐字节未变**；原版已备份。**Dify 生产应用未被触碰**，需人工导入验证后才生效。

剩余 1,686 条高危已全量逐条验证：机械门槛不合格 0、语义规则残留 0、log↔维度双向一致 0 异常；抽样摘要均为真实双侧矛盾（错侧手术、过敏史冲突、生命体征矛盾等）。

---

## 1. 背景与触发时间线（均为 2026-08-17 当日，Asia/Shanghai）

| 时间 | 事件 |
|---|---|
| 上午 | 用户报告 `/api/patient-qc/patients?severity=high&date_from=2026-04-01&date_to=2026-07-01` 返回空，认为"实际有数值" |
| 下午 | 诊断完成：4/1~7/1 范围内全库无 high 维度；high 仅从 7/14 13:12 起存在；6月告警页的高危是发送时点快照，底层数据此前已被历史整改降级 |
| ~19:00 | 修复契约校验器并部署；第一轮存量降级 546 条 |
| 19:20 | admin 导出 patient_visit Excel（189 患者，筛选 severity=high）——外部 AI 复核的就是这份 |
| ~19:57 | 用户提供外部 AI 复核文档；逐条验证：统计类论断多为口径产物，医学类论断（遗漏被判矛盾）属实 |
| ~20:05 | 部署 text_quality 黑名单 + 语义降级配置开关（生产开启）；第二轮降级 694 条 |
| ~20:30 | 新增两条语义规则（超集诊断、不可能数值）并部署；第三轮降级 116 条 |
| ~20:35 | 影子 YML 增量修正完成并本地验证；全量终态复核通过 |

---

## 2. 问题链与根因

### 2.1 问题一：patient-qc 高危查询为空（非 bug，数据使然）

- 该接口按 `PushLog.push_time` 过滤日期、按 `AuditDimensionResult.severity` 过滤严重度。
- 生产事实：2026-04/05/06 全库（log 级/结论级/维度级）**无任何 high**；最早 high 维度 `push_time=2026-07-14 13:12:40`。
- 前置机告警日志（QCRecordAlertLog）5月 3 条 / 6月 1,402 条 high 是**发送时点快照**：当时旧口径下确为 high，其后历史数据被批量重写降级（5~6月维度连一条 `fail` 状态都没有，原始 response 已被清理为"[已清理]"）。
- 结论：查空正确；把开始日期设到 7/14 之后可查出数据。同日验证 7/14~8/17 + severity=high 返回 1,389 个患者分组（整改前口径）。

### 2.2 根因一：契约校验器"抬升"缺陷（机械层，已修复）

位置：`app/services/result_contract_validator.py` `normalize_dimension_combo()`。

- 原 `VALID_COMBOS` 只允许 5 种组合，`fail` 只配 `high/red`。工作流按提示词契约输出 `general → medium/yellow`（status=fail）时被判"非法组合"，第 117 行 `severity = STATUS_TO_SEVERITY[status]`（fail→high）强制抬成 `high/red`。
- 该校验运行在高危守卫（`_downgrade_unqualified_high_risk`，8/13 部署）**之后**，守卫看到的是 medium/yellow 便正确跳过——抬升发生在守卫眼皮底下。生产 7/14 以来 0 条守卫降级标记佐证守卫形同虚设。
- 证据链（均可在容器内复现）：守卫合成测试正常降级；真实 raw response 重解析，进入 `_post_process_result` 前 medium/yellow、出来 high/red；前后快照二分锁定唯一写入者是契约校验器。
- **修复**：`VALID_COMBOS` 增加 `(fail, medium, yellow)`、`(fail, low, blue)`；非法组合修复改为**只降不升**（按 status 重推仅当推导结果更低）。

### 2.3 根因二：AI 语义性假高危（外部复核文档证实）

内网 AI（Qwen3-30B，影子 YML 0.4.0）在 issue 结构上自证"合格"（level=severe、issue_mode=contradiction、双侧证据非空、confidence 0.92~0.95、受控 safety_category），但语义上是 omission/数据质量：

- **翟林泰 c0957613**：双侧证据完全相同（初步诊断一致），摘要自己写"诊断一致"却判 contradiction——假。
- **王剑辉 01001084**：首次病程新增诊断（上颌窦囊肿）被判矛盾，实为入院后检查新发现（evolution）——假。
- **张定宇 c0467915**：BMI=0 属数据/模板错误，且 `text_quality` 维度判 red 直接违反 YML 契约——假。
- **高庆贵 c1089051**：两条 high 都是"新增 7 项诊断"超集模式且跨维度重复——假。
- **王魁军 c1083906**：一条新增诊断（假）+ 一条"声带囊肿 vs 声带息肉"文字冲突（真）——需逐 issue 判断。
- **王金强 c1075448**：左鼓膜穿孔 vs 鼓膜完整（wrong_site_or_side）——**真阳性，必须保留**。
- **孙合松 c1084580**：双下肢放射痛 vs 无（真矛盾，severity 裁量属临床）——保留。

对应处理：`text_quality` 进入硬门槛黑名单（无条件）；语义降级开关化并开启；新增超集诊断/不可能数值两条规则。

---

## 3. 外部复核文档验证结论（19:20 导出的 189 患者 Excel）

导出审计（MED_EXPORT_AUDIT_LOG #126）：`patient_visit`，189 条，`filter_criteria={"severity":"high"}`。

| 外部论断 | 验证结果 |
|---|---|
| 189/189 患者全部高危，失去区分度 | **口径产物**：导出本身按 severity=high 筛选。全量 7/14 以来 17,932 住院次中高危 1,557（当时口径 8.7%） |
| 入院vs首病程 89.3% severe | raw AI 输出口径属实；落库后 high 1655 / medium 197 / low 129 |
| JSON 不稳定（20 失败 / 140 围栏） | raw 属实（实测围栏 674/4661≈14.5%）；后端容错解析兜住，落库 parse 失败 18/4661≈0.4% |
| patient_summary 427 次丢失 | raw 属实；但 PushLog.patient_id 由请求上下文回填，**落库空值=0**。根因：YML start 节点只有 mr_txt/mr_type，无患者字段输入 |
| severity 枚举混乱（severe/general 混入最终值） | **落库干净**：dim severity 仅 low/medium/high。其统计基于 raw 输出 |
| summary 与 dimension 打架 15+ | **落库 0**（双向核查）；后端 `_reconcile` 已自动汇总 |
| 必须 High Gate 代码化 | 后端 8/13 已上线（外部文档不知道）；机械门槛下当时 2,496 条 high 100% 合格 |
| 遗漏被当矛盾、text_quality 判红等医学论断 | **属实**（见 2.3），已按语义规则处理 |

---

## 4. 代码变更清单（本地仓库 `fix/ora-12609-p4-error-code` 分支，**均未 git 提交**）

| 文件 | 变更 | 部署 md5（本地=容器一致） |
|---|---|---|
| `app/services/result_contract_validator.py` | VALID_COMBOS +2 组合；非法组合修复只降不升 | `ef860c4f45c96874f320fef14855d0ac` |
| `app/services/dify_schema_parser.py` | 硬门槛维度黑名单 `{other, text_quality}`（`_HIGH_RISK_FORBIDDEN_DIMENSIONS`）+ 拒绝原因码 | `137796402a47e55031511fc608ec9fe4` |
| `app/services/high_risk_semantic_shadow.py` | ①`semantic_enforce_enabled()` 由硬编码 False 改为 env `HIGH_RISK_SEMANTIC_ENFORCE` / config `high_risk_semantic_enforce` 开关（默认关）；②新增规则 `text_quality_forbid_high`、`diagnosis_superset_not_contradiction`（一侧诊断列表为另一侧严格超集→非矛盾）、`impossible_vital_value_data_quality`（BMI=0/W 0kg/H 0cm） | `074d1454d9bd419ce6b951d86d828ec4` |
| `tests/test_008_remediation.py` | +3 测试：fail+medium 不抬升、fail+low 不抬升、修复只降不升（warn+high→medium，fail+high 保留） | — |
| `tests/test_003_fbcde_remediation.py` | 原"临床批准前 env 不可降级"测试改为"env 授权后可降级+审计标记"；+6 测试：text_quality 门槛、text_quality 影子规则、超集命中/真矛盾保护/非诊断保护、不可能数值命中/正常生命体征保护 | — |
| `scripts/remediate_contract_elevation_20260817.py` | 第一轮存量整改脚本（dry-run/--apply/--verify，写前备份） | — |
| `scripts/remediate_semantic_downgrade_20260817.py` | 第二/三轮存量整改脚本（复用 evaluate_semantic_high_risk_dim，与解析时同源） | — |
| `scripts/build_admission_fact_gate_shadow_yml_20260819.py` | 当前唯一门禁影子 DSL 的幂等构建/校验脚本；替代 2026-08-17 增量脚本 | — |
| `docs/3一致性核查正式版-质控门禁影子V2.yml` | 2026-08-19 唯一保留的可导入影子 DSL；全分支只降不升，入院分支含事实门禁 | 见文件 SHA-256 |

测试状态：`test_003`（17）、`test_008`（28）、`test_dify_pusher` 全过；全量套件仅 3 个**存量失败**（导出审计相关，stash 对照确认与本次无关）。

---

## 5. 数据整改三轮明细（生产 Oracle，均有 JSON 备份与审计标记）

| 轮次 | 依据 | 降级维度 | 汇总同步 | 备份文件（docs/remediation/） |
|---|---|---|---|---|
| 1（19:0x） | 契约抬升回滚（`_qualified_high_risk_issue` 不合格） | 546（544→medium，2→low） | 45 条 push_log+conclusion | `contract_elevation_apply_20260817.json` |
| 2（20:0x） | 语义规则 r1（identical 93 / short 625 / text_quality 5） | 694 | 484 条 | `semantic_downgrade_apply_20260817.json` |
| 3（20:3x） | 语义规则 r2（superset 108 / impossible 8） | 116 | 65 条 | `semantic_downgrade_apply2_20260817.json` |
| **合计** | | **1,356** | **594** | |

- 范围统一：`push_time >= 2026-07-14` 且 `status='success'` 且 `superseded_by IS NULL` 的当前有效记录。
- 只改 `severity/alert_level/risk_score`（维度另追加 `extra.semantic_enforced_demote` 审计标记）；**不动**维度 status、response_json、QCRecordAlertLog 快照、QCFeedback。
- 终态：7/14 起 high 维度 **1,686**；患者质控总览分组（7/14~8/17）**819**；机械门槛不合格 0；语义残留 0；log↔维度双向不一致 0。
- 具名病例终态（当前有效记录）：翟林泰/王剑辉/张定宇/高庆贵 = 0 条 high；**王金强 = 1 条保留（真错侧）**；孙合松 = 1 条保留（真矛盾）。王魁军未做终态单独核验（其"囊肿vs息肉"文字冲突预计保留）。

---

## 6. 影子 YML 增量修正（历史事实与当前收敛状态）

**修改方式：原地修改；原版备份在同目录 `.orig-20260817.yml`；Dify 生产应用未触碰，导入验证后才生效。**

结构对比证据（脚本逐节点比对）：

- 节点 31 → 38：新增 7 个 `确定性修正-1..7` code 节点（id 1783000000101~07），**无删除**。
- **14/14 LLM 提示词逐字节相同；5/5 原有代码节点代码逐字节相同。**
- 仅有变化的原有节点：start（+3 个**非必填**变量 patient_id/patient_name/visit_number）与 7 个 End（输出 value_selector 改指修正节点）。
- 边 31 → 38：8 条原边改道经修正节点（保留 sourceHandle，含 if-else 双分支汇聚场景），7 条修正→End 新边。
- 路由失败输出（fail-closed 支路）未处理。

修正节点逻辑（Node 实测通过）：去 markdown 围栏 + 容错截取 JSON（失败**原样透传**）；patient_summary 患者字段直传（仅当 start 提供时）；维度 status/severity/alert 枚举标准化；audit_summary 按维度最高级代码重算（消除 summary/dimension 矛盾）。

**注意**：patient 直传要真正生效，还需后端推送请求携带患者字段（Dify 拒绝未声明输入，须与 YML 导入同步上线；后端尚未实现该发送逻辑）。

2026-08-19 收敛说明：上述 `.orig-20260817.yml` 和中间 `3一致性核查正式版.yml` 已按项目负责人要求清理；历史节点数、字节数和差异结论保留在本文。唯一导入资产现为 `docs/3一致性核查正式版-质控门禁影子V2.yml`，增加全分支只降不升形式门禁，以及入院事实/证据闭环、CDB 临床确认和事件去重。该收敛不代表已导入生产 Dify。

---

## 7. 生产部署状态（10.10.8.84:8000，容器 med-audit）

- 三个 py 文件热更新进容器（md5 与本地一致，见 §4 表），各自清理 `__pycache__` 后 `docker restart`，`/api/health/live` 正常。
- 镜像 `med-audit:latest` 三次 `docker commit`：19:01 `f3148355…`（校验器修复）、`feat: 高危门槛text_quality黑名单+语义降级配置开关`、`feat: 语义规则扩展-超集诊断/不可能数值`。
- 配置：`/opt/med-audit-docker/config/config.json` 新增 `"high_risk_semantic_enforce": true`（改前备份 `config.json.bak-20260817-semantic`）。**语义降级对新数据实时生效**。
- 当日调度正常（全天 622 条推送，最后一条 12:30）。
- 应用库 APP_DB_TYPE=oracle；表名前缀 `MED_`。

---

## 8. 独立复核 AI 的核查清单（建议逐项执行）

> 访问方式：`ssh -i ~/.ssh/id_ed25519_med_audit -p 40022 root@10.10.8.84`，容器内执行 `docker exec -w /app -e PYTHONPATH=/app med-audit python …`。请勿在生产执行任何写操作。

1. **复现"查空非 bug"**：查询 4/1~7/1 范围 `MED_AUDIT_DIMENSION_RESULT.severity='high'` 计数（应为 0），及最早 high 维度 push_time（2026-07-14 13:12:40）。
2. **校验器修复有效性**：容器内 `normalize_dimension_combo({'status':'fail','severity':'medium','alert_level':'yellow','confidence':0.9})` 应返回 medium/yellow 且无 invalid_combo 错误；`warn+high` 应降为 medium；`fail+high` 应保留。
3. **硬门槛黑名单**：`_qualified_high_risk_issue` 对 `dimension_code='text_quality'` 的合格结构 issue 应返回 None。
4. **语义规则**：`evaluate_semantic_high_risk_dim` 对超集诊断 / BMI=0 样例应命中对应 reason；对"左右侧冲突""诊断项有差异""正常生命体征"样例**不得**命中（防误杀）。
5. **存量残留**：重跑 `scripts/remediate_contract_elevation_20260817.py --verify` 与 `scripts/remediate_semantic_downgrade_20260817.py --verify`（均应返回 0）。
6. **数字对账**：7/14 起 high 维度总数（1,686）；患者质控分组 7/14~8/17（819）；与备份 JSON 的条目数互相印证。
7. **真阳性保护**：患者 c1075448（王金强）当前应有 1 条 high（physical_examination / wrong_site_or_side）；c1084580（孙合松）1 条。
8. **一致性**：log=high 无 high 维度 = 0；log!=high 有 high 维度 = 0（SQL 见下）。
   ```sql
   SELECT count(*) FROM MED_PUSH_LOG p WHERE p.severity='high'
     AND p.push_time >= DATE'2026-07-14' AND p.status='success' AND p.superseded_by IS NULL
     AND NOT EXISTS (SELECT 1 FROM MED_AUDIT_DIMENSION_RESULT d
                     WHERE d.push_log_id=p.id AND d.severity='high');
   ```
9. **审计标记抽查**：随机抽降级维度看 `extra.semantic_enforced_demote` 与备份 JSON 的 reasons 一致。
10. **YML 完整性**：运行 `scripts/build_admission_fact_gate_shadow_yml_20260819.py --check`，并核对 38 节点/38 边、双输出键与七个门禁节点。
11. **测试**：本地 `python -m pytest tests/test_003_fbcde_remediation.py tests/test_008_remediation.py -q` 全过；全量套件仅 3 个存量失败（导出审计，与本次无关，可 stash 验证）。
12. **配置**：`load_config().get("high_risk_semantic_enforce")` 应为 True；备份文件存在。

---

## 9. 已知残留与风险（如实申报）

1. **语义降级自动生效**：新数据命中规则即降级（带审计标记）。规则配有防误杀测试，但**未做临床背书**；临床接手后应复核，必要时把配置改回 `false`。
2. **severity 裁量类未动**：孙合松类"真矛盾但可能只值 medium"的记录保留 high——属临床裁量，规则不宜自动降。
3. **外部文档提到的深层问题未全部处理**：同日不同时间生命体征变化、术前/术中诊断演变判断、危急值响应时间窗等语义规则未实现（见 003/023 与外部复核文档 §14 的 18 条回归用例）。
4. **YML 未导入 Dify**：唯一门禁影子 V2 尚未在 Dify 应用中运行过；patient 直传依赖后端补发患者字段（未实现）。
5. **4~6 月无高危的范围性结论**：基于当前库内数据（原始 response 已被历史清理为"[已清理]"），无法从 raw 复核当时的判定。
6. **王魁军终态未单独核验**；3 个存量测试失败（导出审计）与本次无关但一直未修。
7. **本地改动未 git 提交**（文件清单见 §4），存在丢失风险。

---

## 10. 回滚方案

- **语义降级开关**：config `high_risk_semantic_enforce` 改 `false`（即时生效，无需重启）。
- **数据**：按三轮备份 JSON 中的 dim_id 列表 `UPDATE … SET severity='high', alert_level='red'`（汇总级同理，备份含 from/to 与 risk_score 原值）；或直接以备份 JSON 为准整体还原。
- **代码**：git 未提交，回滚=还原工作区文件；生产代码回滚不得再依赖已清理的本地 YML 备份。
- **YML**：Dify 试运行必须新建影子应用；回滚方式为删除/停用该影子应用，不覆盖现有生产 Workflow。旧本地 DSL 已按 2026-08-19 清理要求移除。

---

## 11. 附件清单

- `docs/remediation/contract_elevation_dryrun_20260817.json` / `contract_elevation_apply_20260817.json`（第一轮）
- `docs/remediation/semantic_downgrade_apply_20260817.json`（第二轮）/ `semantic_downgrade_apply2_20260817.json`（第三轮）
- `docs/remediation/STAGE1_REPORT.md`、`stage1_5_shadow_results.json`（8/13 历史高危复核背景）
- `docs/3一致性核查正式版-质控门禁影子V2.yml`（2026-08-19 唯一保留的影子导入资产）
- 外部复核文档原文：用户 19:57 提供的《多源病历一致性质控 YML 与实际输出复核整改交接说明》（未落盘，关键论断已转录于本文 §3）
- 关键代码位置：`app/services/dify_schema_parser.py`（`_qualified_high_risk_issue`/`_downgrade_unqualified_high_risk`/`_post_process_result`）、`app/services/result_contract_validator.py`、`app/services/high_risk_semantic_shadow.py`

# 分质控可行性与 121 人高危表独立复核交接

> 文档编号：025
> 编制日期：2026-08-17（Asia/Shanghai）
> 性质：交接 + 待第三 AI 独立复核；本文档本身不授权任何生产写入、不授权改 Dify、不授权再降级
> 适用系统：Med-Audit 后端（生产 10.10.8.84:8000，容器 med-audit，Oracle 应用库）
> 交接目的：把 024 当日整改、另一 AI 对 121 人 Excel 的完整分析、以及本轮独立复核结论放在同一份文档里，供下一任 AI 只读复核
> 上游文档：`docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md`
> 证据表：`D:\Users\Administrator\Desktop\patient_visit_summary_20260817_204230.xlsx`（含患者标识与病历原文，外发前必须脱敏）

---

## 0. 给下一任复核 AI 的一页入口

请按这个顺序读，不要从 `docs/archive/` 开始：

1. `AGENTS.md`
2. `docs/INDEX.md`
3. `docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md`（当日机械层/语义层整改与三轮降级）
4. **本文 025**（含另一 AI 原文 + 本轮独立复核）

**红线（与 024 相同，必须遵守）：**

- 生产只允许只读。禁止 `UPDATE`/`DELETE`/`INSERT`、禁止 `docker commit`、禁止改 `config.json`、禁止触发 Dify/Relay/调度/补跑。
- 外部 AI 不得接收姓名、患者号、住院号、身份证、手机号、完整 `mr_text`/`request_json`/`response_json`。本仓库这份 Excel 含完整病历，**不要整表外发**。
- 本文与 024 都不授权新的降级或 Prompt 上线。任何写入仍服从 023 §9.1。
- 不要把六路分质控重新合并成一个大模型。

**本轮已经形成的综合判断（供你证伪，不要先当成结论）：**

1. **分质控可行，而且应该继续。** 问题不是“拆错了”，而是拆开后入院模块仍在错误产高危，汇总层缺少二次裁决。
2. **024 的机械整改成立**：契约校验器只降不升、`text_quality` 黑名单、三轮降级 1,356 条、当前 high 维度 1,686、患者质控分组 819、log↔维度双向一致 0，生产文件 md5 与文档一致。
3. **024 的“剩余 1,686 条抽样都是真双侧矛盾”过满。** 规则层残留可以是 0；临床假高危仍大量存在。
4. **另一 AI 对 121 人新表的核心定位成立**：主因是 `admission_vs_first_progress`，最大逃生通道是 `critical_diagnosis_basis`。
5. **当前剩余高危不能直接作为临床高危推送依据。**

---

## 1. 本轮做了什么、没做什么

2026-08-17 夜间（024 三轮降级与影子 YML 补丁之后），运营方提供 121 人 `patient_visit` 新表，并粘贴另一 AI 的完整分析（见本文附录 A）。本轮 AI 做了：

- 独立复算该 Excel 的 raw `质控N_返回JSON`（不是只信另一 AI 的数字）。
- 对照现行 `_qualified_high_risk_issue` 与 `evaluate_semantic_high_risk_dim`。
- 按 024 清单对生产做**只读**核查（SSH 密钥、容器 exec、SELECT / 配置 / md5）。
- 核对本地三文件 md5、三轮备份 JSON 条数、影子 YML 结构、相关单测。

**没有做：** 生产写入、新语义规则、YML 导入 Dify、改 audit_type code、git 提交。

生产探测时间约 2026-08-17 21:04（容器当时 Up 33 minutes, healthy）。

---

## 2. 与 024 的关系（先分清两张表）

| 材料 | 时间 | 内容 | 角色 |
| --- | --- | --- | --- |
| 024 | 2026-08-17 下午至 20:35 | 契约抬升修复 + 三轮存量降级 + 影子 YML 增量 | 已执行交接；生产写入当日已获运营方授权 |
| 189 人 Excel | 19:20 导出，`severity=high` | 整改中途的高危切片；外部 AI 分析未落盘，024 §3 已转录 | 口径产物：导出本身按高危筛选 |
| 121 人 Excel | 20:42 导出 | 三轮降级之后的新高危切片 | 附录 A 的分析对象；本轮复算对象 |
| 本文 025 | 20:42 之后 | 独立复核 024 + 复算 121 人表 + 收录附录 A | 待第三 AI 再核 |

121 人表文件名：`patient_visit_summary_20260817_204230.xlsx`  
工作表：`患者就诊数据汇总`，122 行（含表头）× 202 列。  
质控结果在 `质控1`～`质控5` 的推送时间 / 审计类型 / 推送 JSON / 返回 JSON；患者级列是 `严重程度`、`问题维度明细`、`高危问题说明`、`整改建议`。

**必须先分清两层数据：**

- Excel 里的 `质控N_返回JSON` 是 **当时 Dify 原文**。024 改的是库内 `severity` / `alert_level` / `risk_score`，**不动 `response_json`**。所以表里的红灯比库里更“脏”。
- 导出列 `严重程度=高危` 对 121/121 成立，首先是因为这张表就是按高危导的；其次，抽查到的具名病例在库里也确实还是 high。

入院日期：2026-08 有 98 人，2026-07 有 22 人，2026-06 有 1 人。这是近期高危切片，不是 819 人全量。

---

## 3. 024 数字与代码：本轮核实结果

访问方式（只读）：

```text
ssh -i ~/.ssh/id_ed25519_med_audit -p 40022 root@10.10.8.84
docker exec -w /app -e PYTHONPATH=/app med-audit python …
```

生产当时：`APP_DB_TYPE=oracle`，容器 `med-audit` healthy，单 worker 环境变量未见多 worker。配置备份在容器内 `/app/config/config.json.bak-20260817-semantic`（024 写的是宿主机 `/opt/med-audit-docker/config/…`，挂载后容器路径是 `/app/config/`）。

| 024 主张 | 本轮结果 |
| --- | --- |
| 2026-04-01～07-01 无 high 维度 | 成立（0） |
| `normalize_dimension_combo`：fail+medium 保持；warn+high 降 medium；fail+high 保留 | 成立 |
| 三文件 md5 与生产一致 | 成立：`result_contract_validator.py`=`ef860c4f45c96874f320fef14855d0ac`；`dify_schema_parser.py`=`137796402a47e55031511fc608ec9fe4`；`high_risk_semantic_shadow.py`=`074d1454d9bd419ce6b951d86d828ec4` |
| `high_risk_semantic_enforce=true` | 成立 |
| 备份条数 546 / 694 / 116，汇总 45+484+65=594 | 成立（见 `docs/remediation/*apply*20260817.json`） |
| 7/14 起当前 high 维度 1,686 | 成立 |
| 患者质控 7/14～8/17 高危分组 819 | 成立。必须加 `contract_valid IS NULL OR =1`，否则会数成 1,046 |
| log=high 无 high 维度、log≠high 有 high 维度 | 均为 0 |
| 机械门槛残留 0、当前语义规则残留 0 | 对**当前规则**成立（重建 dim 时脚本把 status 固定为 fail，与 024 脚本口径相同） |
| 王金强 1 条 high（查体 / 错侧）；孙合松 1 条 | 成立 |
| 影子 YML：31→38 节点，14/14 提示词、5/5 原代码未改；start 增加 3 个非必填患者字段；7 个 End 改指修正节点 | 2026-08-17 核查时成立。2026-08-19 已进一步收敛为唯一门禁影子 V2，旧文件清理；历史结论保留。 |
| 相关单测 | `tests/test_003_fbcde_remediation.py` + `tests/test_008_remediation.py` 共 45 passed |
| 最早 high 仍是 2026-07-14 13:12:40 | **当前库不成立**。7/14 当天已无剩余 high；剩余最早是 2026-07-15 10:20:31 |
| 容器内可直接跑两份 `--verify` 脚本 | **不成立**。脚本不在生产镜像里 |

生产剩余 high 的结构（024 摘要未写清，本轮补上）：

```text
high 维度 1,686
  admission_vs_first_progress  1,684
  surgery_chain                    2

剩余 safety_category（issue 标签计数）：
  critical_diagnosis_basis      1,372
  wrong_site_or_side              183
  patient_identity                103
  allergy_medication               99
  wrong_procedure_or_implant        2
```

维度分布（剩余 high）：查体 305、诊断一致性 250、现病史 214、初步诊断 206、时间线 205、既往史 156、辅助检查 142、主诉 117、治疗计划 89、手术一致性 2。

这直接支持附录 A 的判断：剩余问题几乎全部在入院模块，且 `critical_diagnosis_basis` 是主通道。

---

## 4. 121 人表：另一 AI 的数字 vs 本轮复算

解析对象：每名患者最多 5 路 `质控N_返回JSON`。外层常为 `{"hcjg": "..."}`，内层是工作流 JSON；部分带 Markdown 围栏。

| 项目 | 附录 A | 本轮 | 裁定 |
| --- | ---: | ---: | --- |
| 患者 | 121 | 121 | 一致 |
| 子质控调用 | 448 | 448 | 一致 |
| 可解析 JSON | 436 | 436 | 一致 |
| 解析失败 | 12 | 12 | 一致 |
| 仍带 Markdown 围栏 | 84 | 82 | 口径差 2，可忽略 |
| patient_id 空 | 268/436 | 268/436 | 一致（raw 输出空；024 说落库由请求上下文回填） |
| visit_number 空 | 268/436 | 268/436 | 同上 |
| summary 与 dimension 冲突 | 至少 6 | **正好 6**，全是入院模块 `summary=low` 但维度有 high | 成立 |
| 红色/严重 dimension | 332 | high 维度 332 | 一致 |
| 不满足当前 High Gate | 至少 32 | high 中 45 条不过门（issue 不合格 32，status 非 fail 11，禁维度 2） | 成立 |
| 导出列 121/121 高危 | 失去区分度 | 数字对；**首先是导出筛选口径** | 解释需补 024 对 189 人表的同一纠正 |
| 同一 issue 跨维度复制 | 102 次结果 / 至少 279 次重复 | 宽松口径（explanation 或证据对）**102 / 280**；严口径 61 / 85 | 成立 |

按模块：

| 模块 | 调用 | 可解析 | 附录 A 的 summary | 本轮维度 |
| --- | ---: | ---: | --- | --- |
| `admission_vs_first_progress` | 169 | 164 | severe 150 / medium 2 / low 12（91.5%） | high 321 / medium 41 / low 1,278 |
| `progress_vs_nursing` | 87 | 87 | 基本全部 low | 全部 low |
| `jyjc_vs_bcnursing` | 81 | 74 | 无 red | 无 high；medium 253 / low 191 |
| `discharge_vs_frontpage` | 81 | 81 | 1 次 red | high 维度 2 |
| `surgery_chain` | 23 | 23 | 5 次 red | high 8 / medium 15 |
| `syssvsscbc` | 7 | 7 | 1 次 red | high 1 |

入院红色 issue：附录 A 写 317 个红 issue、234 个 CDB；本轮 318 / **235**。约 74%。

围手术期重叠：跑 `syssvsscbc` 的 7 人全部同时跑了 `surgery_chain`。成立。

形式门槛通过后，当前语义规则在这张 raw 表的 gate-pass high 上只能再打下约 31 条（短证据 23、证据相同 5、诊断超集 4）。也就是说：**024 已上线的语义规则几乎吃不掉这张表里的剩余红灯。** 生产 1,686 条剩余 high 用同一规则重跑，命中数是 0。

---

## 5. 具名病例（附录 A 的医学判断 vs 本轮结构核对）

下列患者在 20:42 这张高危导出里，且 **2026-08-17 21:04 生产当前有效记录仍为 high**。复核时只核结构，不要把病历原文写进新文档。

| 患者 | 当前库 high | 附录 A 判断 | 本轮结构核对 |
| --- | --- | --- | --- |
| 刘德水 `c0752043` | 入院 `past_history` + `diagnosis_consistency` | 假矛盾；两边证据都是同一初步诊断，却用“否认外伤手术输血”推肺脓肿史 | **同意。** issue 双侧 evidence 相同；explanation 与 evidence 对不上；形式门槛仍通过。当前 `identical_evidence` 比的是维度级 evidence，不是 issue 的 `evidence_a/b`，所以漏了 |
| 昝淑霞 `00764518` | 入院 `chief_complaint` | 性别模板错误被打成主诉高危；证据却是两边一致的主诉 | **同意。** `safety_category=patient_identity`，但 evidence 不含性别值。更合理是 `text_quality` / 患者信息，默认低或中 |
| 张淑香 `c0021536` | 入院 `initial_diagnosis` + `diagnosis_consistency` | 遗漏被包装成矛盾；颈椎病/椎间盘、咽炎/胃炎不该直接红 | **同意。** `issue_mode=contradiction` + CDB，explanation 却是“首次病程未提及”。超集规则因名称交叉而打不中 |
| 杨广阳 `c1091720` | 入院 `history_of_present_illness` + `timeline_consistency` | 真矛盾，但高危应慎重；同一事复制到多个维度 | **同意是真 contradiction。** 主诉那条短证据已被现规则降掉。是否 red：急性脑梗死发病时间可能有时效含义，**不宜写成“凡时间差一律中危”**；应去重，CDB 仍过宽 |
| 王金强 `c1075448` | 入院 `physical_examination` / `wrong_site_or_side` | 真错侧；surgery 与 syssvsscbc 重复报同一事件 | **同意真阳性。** 库里只剩入院查体 1 条。raw 里 surgery `status=high`、syssvsscbc `status=issue`/`surgical`，是枚举不合法被门禁误降，**不是事件合并**。模型一旦改成合法 `fail`+`wrong_site_or_side`，重复红灯会回来 |
| 孙合松 `c1084580` | 入院 `physical_examination` 1 条 | 024 作真矛盾保留 | 与 024 一致。是否只值 medium 属临床裁量，本轮不自动降 |
| 王魁军 `c1083906` | 入院 `diagnosis_consistency` 1 条 | 024 称未单独核终态 | 仍有 1 条 high。本轮未做临床定性 |

---

## 6. 对附录 A 架构建议的取舍

| 附录 A 建议 | 本轮裁定 |
| --- | --- |
| 分质控继续，不要并回一个大模型 | **同意。** 生产剩余 1,684/1,686 都在入院模块，拆开才定位得这么准 |
| 收紧 `critical_diagnosis_basis`：默认 medium，只有再叠加“影响当前关键诊疗决策”才允许 high | **同意，应排第一。** 不要删除该分类。错侧/过敏/身份已有独立分类，收紧 CDB 不会误伤王金强 |
| High Gate 代码化 | 后端 8/13 已有形式门槛；缺的是“证据是否在证明声称的那个事实” |
| 每个 issue 强制 `fact_key/value_a/value_b/relation` | **同意。** 刘德水、昝淑霞离开这一层无解 |
| 证据必须包含对应 value，再进 High Gate | **同意，必须写进代码** |
| 同一 issue 先去重再挂维度 | **同意。** 宽松口径 102 次 / 280 次重复 |
| summary / patient_summary 由代码出 | **同意。** 唯一门禁影子 V2 已由代码汇总，并保留患者字段直传入口，但 **未导入 Dify**；患者字段后端也还没传 |
| 统一 high/medium/low 枚举 | **同意。** 入院 150 次 summary 仍在用 `severe` |
| 围手术期多模块合成一个事件 | **同意做展示/汇总层合并**，不要停跑 `syssvsscbc` |
| 把生产 code `discharge_vs_frontpage` 改成 `first_progress_vs_discharge` | **显示名必须改清楚，生产 code 现在不能改。** 111 号文档已冻结该 code。真正的“出院 vs 首页”应另立类型 |
| 六路再整理成入院基线 / 过程动态 / 检验响应 / 围手术期 / 诊断演变 / 首页终末 | 方向对，作为下一阶段产品设计；**不作为立刻改生产配置的授权** |
| 先不要继续堆 Prompt | **同意** |

建议叠在 024 已完成工作上的顺序：

1. 收紧 `critical_diagnosis_basis`
2. issue 增加 `fact_key / value_a / value_b`，High Gate 校验互斥与证据包含
3. 按 fact_key / 证据对去重
4. summary 继续由代码汇总；YML 修正节点先影子验证再导入
5. 围手术期在展示层合并为手术安全事件
6. `discharge_vs_frontpage` 只改显示名
7. 最后再改入院模块 Prompt

---

## 7. 定性（供第三 AI 打分）

- 架构方向：对。
- 拆分方式：基本可行，应继续。
- YML 规则思想：基本合理。
- 024 机械层与三轮存量降级：该做，也做实了。
- 当前剩余高危和 121 人表 raw 输出：**暂时不能直接作为临床高危推送依据。**
- 024 已声明且仍然有效的残留：语义开关无临床背书、YML 未进 Dify、本地改动未 git 提交、4～6 月原始 response 已被清理。

---

## 8. 第三 AI 核查清单（只读）

生产访问与 024 §8 相同。禁止写。`--verify` 脚本不在镜像内，不要为了跑脚本而把未批准文件写进镜像；可用 stdin 灌只读 Python。

1. 复读 024 §0～§3 与本文 §3，核三文件 md5、`high_risk_semantic_enforce`、三轮备份条数。
2. 复算：7/14 起当前 success + `superseded_by IS NULL` 的 high 维度是否仍为 1,686；其中入院模块是否仍约占 1,684。
3. 复算患者质控分组：7/14～8/17、`contract_valid IS NULL OR =1`、按 `patient_id+visit_number+dept`，是否仍为 819。
4. 复算剩余 high 的 `safety_category`，CDB 是否仍是最大头。
5. 打开 121 人 Excel（本地，勿外发），独立复算附录 A 的表：121 / 448 / 436 / 12 / 入院 150/164 severe。
6. 只核结构、不抄病历原文：刘德水证据是否相同且与 explanation 错位；昝淑霞 evidence 是否不含性别；张淑香是否 omission 被标 contradiction；杨广阳是否真时间/症状矛盾且跨维度复制；王金强是否仍为 1 条查体错侧。
7. 确认 `discharge_vs_frontpage` 的 YML/111 文档语义是“首次病程 vs 出院”，生产 code 未改名。
8. 确认 `3一致性核查正式版-质控门禁影子V2.yml` 只导入新影子应用，未覆盖 Dify 生产应用。
9. 对附录 A 与本文的**分歧点**单独表态：121/121 是否只是导出口径；杨广阳是否允许因脑梗死时效保留偏高；生产 code 能否重命名。
10. 输出四张清单：同意 / 不同意 / 证据不足须人工 / 发现的新问题。不要提出并执行写入。

可用只读 SQL（与 024 一致）：

```sql
SELECT count(*) FROM MED_AUDIT_DIMENSION_RESULT d
JOIN MED_PUSH_LOG p ON p.id = d.push_log_id
WHERE d.severity='high'
  AND p.push_time >= DATE '2026-07-14'
  AND p.status='success' AND p.superseded_by IS NULL;

SELECT p.audit_type_code, count(*)
FROM MED_AUDIT_DIMENSION_RESULT d
JOIN MED_PUSH_LOG p ON p.id = d.push_log_id
WHERE d.severity='high'
  AND p.push_time >= DATE '2026-07-14'
  AND p.status='success' AND p.superseded_by IS NULL
GROUP BY p.audit_type_code;
```

本地测试（不改生产）：

```text
python -m pytest tests/test_003_fbcde_remediation.py tests/test_008_remediation.py -q
python scripts/build_admission_fact_gate_shadow_yml_20260819.py --check
```

注意：旧原版/中间版已于 2026-08-19 清理。当前用上述 `--check` 校验唯一门禁影子 V2；历史结构对比结论见 024 §6 与本文 §3。

---

## 9. 明确不授权

- 不授权对剩余 1,686 条再降级。
- 不授权收紧 CDB 的代码/配置上线。
- 不授权导入影子 YML 到 Dify。
- 不授权重命名 `discharge_vs_frontpage`。
- 不授权合并或停用任一现网 audit_type。
- 不授权把这份 Excel 或 raw JSON 交给公网模型。

若第三 AI 复核通过且运营方要进入下一阶段，必须另开批准单：环境、规则、数量、before hash、回滚点。执行入口仍是 023。

---

## 10. 附件

- 024：`docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md`
- 三轮备份：`docs/remediation/contract_elevation_apply_20260817.json`、`semantic_downgrade_apply_20260817.json`、`semantic_downgrade_apply2_20260817.json`
- 影子 YML：`docs/3一致性核查正式版-质控门禁影子V2.yml`（唯一保留）
- 121 人表：`D:\Users\Administrator\Desktop\patient_visit_summary_20260817_204230.xlsx`
- 另一 AI 对 189 人表的分析：未落盘，见 024 §3
- 另一 AI 对 121 人表的分析：**全文见附录 A**（按用户 2026-08-17 粘贴原文收录，未改写）

---

# 附录 A — 另一 AI《121 人新表与分质控复核》原文

> 收录说明：以下为用户 2026-08-17 提供的另一 AI 分析原文。本轮未改写其表述。文中的国家卫健委链接是原作者所引，本轮未逐条打开核验。具名病例与具体病历描述来自其对 Excel 的阅读；第三 AI 复核时应回表核结构，不要把更多原文扩散到新文件。

我重新核了你刚上传的这份 **121 名患者的新表**，并再次对照前面的 YML。结论比较明确：

**前面交接文档的总体判断是准确的；“分质控”这个方向也是可行的，而且我认为应该继续采用。**
但现在需要进一步明确：**问题已经不主要是“要不要拆分”，而是拆分后的某些子质控仍然在错误地产生高危，最终汇总层又缺少可靠的二次裁决。**

## 一、这份新表再次证明：当前结果还不够准确

我重新统计了新表：

| 项目 | 新表实际情况 | 判断 |
| --- | ---: | --- |
| 患者 | 121 人 | — |
| 子质控调用 | 448 次 | 平均约 3.7 次/患者 |
| 可正常解析 JSON | 436 次 | 97.3% |
| JSON 解析失败 | 12 次 | 仍需处理 |
| 返回仍带 Markdown ``` | 84 次 | 不符合 YML |
| patient_id 为空 | 268/436 | 明显异常 |
| visit_number 为空 | 268/436 | 明显异常 |
| summary 与 dimension 严重度冲突 | 至少 6 次 | 明确程序问题 |
| 红色/严重 dimension | 332 个 | 偏多 |
| 不满足当前 High Gate 硬条件 | 至少 32 个 | 明确违规 |
| 最终患者级“高危” | **121/121** | 明显失去区分能力 |

所以之前说：

> **“高危泛化仍然存在”**

这个判断没有问题。

而且这批数据进一步把问题定位得更清楚了。

## 二、真正的问题集中在“入院记录 vs 首次病程”

新表各模块的表现差异非常大。

其中：

**入院记录 vs 首次病程**

169 次调用，164 次能够正常解析，其中：

* severe/red：**150 次**
* medium/yellow：2 次
* low：12 次

也就是说：

> **91.5% 的可解析结果都被这个模块判成红色严重问题。**

而其他模块远没有这么夸张。

例如：

* 病程 vs 护理：87 次，基本全部 low；
* 检验检查 vs 病程护理：主要是 low/yellow，没有 red；
* 首次病程 vs 出院：81 次，仅 1 次 red；
* 围手术期：23 次，5 次 red；
* 首页手术 vs 术后首次病程：7 次，1 次 red。

所以现在已经能很明确地说：

> **不是“分质控”导致所有患者高危，而是 admission_vs_first_progress 这个子质控把大量一般问题升级成了高危。**

## 三、我发现了一个非常关键的漏洞：`critical_diagnosis_basis`

在“入院记录 vs 首次病程”的红色 issue 中，我统计到 **317 个红色 issue 对象**。

其中：

> **234 个使用 `critical_diagnosis_basis` 作为 high 的安全分类，占约 74%。**

这基本就是当前最大的“高危逃生通道”。

YML 原意可能是：

> 如果矛盾涉及关键诊断依据，可以 high。

但是模型已经把这个概念扩展成：

> 只要觉得“可能影响诊断”，就可以叫 critical_diagnosis_basis。

于是：

* 发病时间不同；
* 一个诊断没写；
* 既往史没写；
* 两份文书详略不同；
* 一个辅助检查没有引用；
* 诊断名称存在差异；

都可能被包装成：

> “影响关键诊断依据 → critical_diagnosis_basis → severe → high/red”。

这就是为什么 YML 明明写了很多：

> “遗漏不得 high”

最后仍然会出现大量 red。

### 我建议

**不要直接删除 `critical_diagnosis_basis`，但必须大幅收紧。**

默认应该：

> `critical_diagnosis_basis` → medium/yellow

只有再满足一个更硬的条件，例如：

> `immediate_clinical_safety_impact = true`

而且能证明这个矛盾会直接影响当前的重要诊疗决策，才允许进入 high。

否则这个分类会一直成为模型的“万能高危理由”。

## 四、几个病例说明现在的判定确实还不准

### 刘德水：很典型的假矛盾

模型说：

> 首次病程记录写“既往有肺脓肿病史”，入院记录没有写，因此严重矛盾。

甚至给 severe/high。

但它引用的入院记录证据竟然是：

> “初步诊断：肺部感染、咯血、肺结节”

首次病程引用的也是：

> “初步诊断：肺部感染、咯血、肺结节”

**两段所谓“矛盾证据”实际上完全一致。**

而模型在 explanation 里又自己引申：

> 入院记录“否认重大外伤、手术、输血史”，所以与肺脓肿史矛盾。

这个医学逻辑也不成立：

> **“否认外伤、手术、输血史”不等于“否认肺脓肿病史”。**

这就是非常典型的：

> **证据和模型解释没有对上。**

因此，仅判断：

```text
evidence_a 非空
evidence_b 非空
```

还远远不够。

### 昝淑霞：问题存在，但维度和证据错位

患者实际为女性。

首次病程的病例特点里出现：

> “患者中年男性”

这个确实应该提示。

但是当前模型将它放进：

> `[高危][主诉]`

其 high issue 中提供的 evidence_a/evidence_b 却分别是：

> “腹胀1周，双下肢红疹1天”

和：

> “患者因腹胀1周，双下肢红疹1天入院”

两条主诉实际上完全一致。

然后 explanation 才突然说：

> “女性 vs 中年男性”。

因此这个 high 连**证据闭环**都没有建立。

更合理的是：

> `text_quality / template_error`

或者：

> `patient_info_consistency`

通常先低/中危。

如果同时出现姓名、住院号、性别等多个患者身份字段属于另一患者，才应该考虑：

> patient_identity → high。

### 张淑香：典型“遗漏被包装成矛盾”

当前说：

> 入院记录有“心律失常（窦性心动过缓）”，首次病程没有，所以属于严重诊断矛盾。

这不符合 YML 自己的基本原则：

> **一边有、一边没有 = omission，不等于 contradiction。**

另外：

> 颈椎病 vs 颈椎间盘突出

也不能仅因为名称不同就 high。

> 慢性咽炎 vs 慢性胃炎

如果确认确实写错，是一个值得整改的诊断文本问题，但一般也不应该直接上升到“患者安全红色”。

### 杨广阳：这是“真矛盾”，但高危仍应慎重

一份记录：

> 言语不清 3 天

另一份：

> 1 周前出现头晕，并明确“无言语不清”。

这个确实属于比较标准的：

> **contradiction**

应该提示医生核实。

但是是否直接成为 red/high，还要看这个发病时间矛盾是不是直接影响了当前时效性诊疗决策。

因此我更建议：

> 默认中危；

只有满足“明确影响当前关键诊疗决策”的硬规则才升高危。

这样红色才真正有临床价值。

## 五、所以，“分质控”到底可不可行？

**可行，而且我赞成。**

从医院业务场景看，这种拆法实际上比“大一统质控 Prompt”更合理。

因为不同文书之间的医学关系完全不同。

例如入院记录与首次病程，本质上是在比较：

> **入院基线事实的一致性。**

病程与护理是在比较：

> **同一时间段病情、生命体征、护理级别、治疗措施的一致性。**

检验检查与病程是在比较：

> **异常结果有没有被识别、评价和处置。**

围手术期则不是简单两份文书比较，而是：

> **术前 → 麻醉 → 术中 → 术后**

事件链。

国家卫健委的医疗质量安全核心制度本身也强调病历要客观、真实、准确、及时、完整、规范，同时危急值、手术安全核查等都有各自独立的管理逻辑。

因此：

> **按临床场景拆分，是正确的。**

## 六、但我建议把现在的“六路质控”再稍微调整一下

我更推荐下面这个结构：

1. **入院基线一致性**
   * 入院记录 ↔ 首次病程
   * 身份、主诉、现病史、既往史、体征、初步诊断
   * 重点抓真正 contradiction
   * omission 默认不 high

2. **诊疗过程动态一致性**
   * 病程 ↔ 护理
   * 必须带时间窗
   * 避免不同时间状态误判

3. **检验检查响应质控**
   * LIS/PACS ↔ 病程/护理
   * 普通异常、中危
   * 真正危急值由医院规则表判断，不让 LLM 自己猜
   * 危急值管理本身应有清晰的报告、接收、确认及追溯机制。

4. **围手术期事件链**
   * 术前 → 手术 → 麻醉 → 术后
   * 真正重点是患者、部位、侧别、术式等安全要素
   * 手术安全核查制度本身也把患者身份、手术部位、手术方式列为重要核查内容。

5. **诊断演变与出院完整性**
   * 首次病程 ↔ 出院记录
   * 允许合理诊断演变
   * 重点检查“最终诊断有没有依据”“重大诊疗经过有没有漏写”

6. **病案首页最终一致性**
   * 出院记录 / 手术记录 ↔ 首页
   * 这是最终编码、诊断、手术信息的终末核查。

这里有一个特别需要改的地方：

当前 YML 的：

> `discharge_vs_frontpage`

名字叫“discharge vs frontpage”，

但是实际 YML 中写的是：

> **首次病程记录与出院记录核查。**

也就是：

**code 和实际业务含义不一致。**

建议直接改名：

```text
first_progress_vs_discharge
```

否则以后维护的人看到 `discharge_vs_frontpage` 会以为它在比较：

> 出院记录 ↔ 病案首页。

这个一定要整理。

## 七、围手术期两个模块我建议不要完全独立重复跑

现在有：

> `surgery_chain`

以及：

> `syssvsscbc`
> 首页手术与术后首次病程

我查了这批数据：

**7 个运行 syssvsscbc 的患者，全部同时运行了 surgery_chain。**

例如王金强：

`surgery_chain` 已经抓到了：

> 左侧 vs 右侧。

`syssvsscbc` 又再次抓：

> 首页左侧 vs 术后病程右侧。

这个病例确实是真高危，但是前端最后不应该显示成两个、三个不同“高危”。

应该把它们合并成一个：

> **手术侧别不一致事件**

下面列证据：

* 术前记录：左
* 手术记录：左
* 首页：左
* 术后首次病程：右

这样临床一眼就知道：

> **是术后病程写错的概率极高。**

这反而比两个模型分别报警更有价值。

## 八、我现在最建议你增加的不是 Prompt，而是一个“事实结构层”

现在 high gate 最大的问题是只验证：

> 两边都有 evidence。

但不验证：

> **这两段 evidence 到底是不是在证明模型声称的那个矛盾。**

建议每个 issue 强制输出：

```json
{
  "fact_key": "sex",
  "fact_name": "患者性别",
  "value_a": "女",
  "value_b": "男",
  "time_a": "",
  "time_b": "",
  "source_a": "admission_record",
  "source_b": "first_progress_record",
  "evidence_a": "性别：女",
  "evidence_b": "患者中年男性",
  "relation": "contradiction"
}
```

然后程序判断：

```text
fact_key 是否一样
        ↓
是否同一时间/可比较时间
        ↓
value_a/value_b 是否真正互斥
        ↓
证据是否真的包含对应 value
        ↓
再进入 High Gate
```

这样刘德水那种：

> evidence 两边都是“肺部感染、咯血、肺结节”

却突然判断“肺脓肿病史矛盾”

就直接过不了。

## 九、还有一个比之前更明确的新发现

我发现这批可解析结果中：

> **102 个质控结果存在同一个 issue 被复制到多个 dimensions 的情况，累计至少重复 279 次。**

比如：

一个“发病时间 3 天 vs 1 周”的问题，

可能同时出现在：

* 主诉；
* 现病史；
* 时间线一致性。

临床最后看到了三个红色，其实是：

> **同一件事。**

因此后续应该增加：

> `issue_id / fact_key / event_key`

先去重，再映射 dimension。

一个问题可以打多个标签，但：

> **只形成一个质控事件。**

这样页面也会干净很多。

## 十、这版我会怎么定性

我现在会把整个方案评价为：

**架构方向：对。**
**拆分方式：基本可行。**
**YML规则思想：基本合理。**
**当前实际结果：暂时不能直接作为临床高危推送依据。**

最关键的整改顺序应该是：

1. **收紧 `critical_diagnosis_basis`**
2. **High Gate 代码化**
3. **增加 fact_key/value_a/value_b 结构**
4. **证据与事实一致性校验**
5. **同一 issue 去重**
6. **summary 由代码自动汇总**
7. **patient_summary 由代码直接传递**
8. **统一 high/medium/low 枚举**
9. **围手术期多个模块结果合并成事件**
10. 最后才继续优化 Prompt。

特别是这一点我建议坚持：

> **不要把分质控重新合并成一个大模型。**

现在已经能看到，拆开以后我们很容易定位：

> admission 模块有问题，
> lab 模块总体比较克制，
> nursing 模块可能需要评估是否过于保守，
> surgery 模块则需要重点解决重复报警和合理诊断演变。

这反而证明了**分质控本身是有价值的**。

最终理想状态不是“每个模型给一个高危/中危”，而是：

> **多个子质控负责发现证据 → 一个统一规则引擎负责去重、裁级 → 最终向临床形成一个患者级问题清单。**

这样我认为是最适合你这个多源病历一致性质控系统继续往生产级发展的路线。

原作者引用：

- https://www.nhc.gov.cn/yzygj/c100068/201804/42ab2552298047679cd6ec733f233862.shtml
- https://www.nhc.gov.cn/yzygj/c100068/201906/454f50c1b2c545518284248646bb0f2c/files/1732873391043_84969.docx

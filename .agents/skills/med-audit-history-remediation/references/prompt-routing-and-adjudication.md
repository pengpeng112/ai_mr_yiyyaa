# 六类提示词路由与高危复核

## 1. 固定路由

按数据库中的 `audit_type_code` 精确选择提示词，禁止模糊匹配或按中文名称猜测：

| audit_type_code | 临床语义 | 技能内完整提示词 |
| --- | --- | --- |
| `admission_vs_first_progress` | 入院记录 vs 首次病程记录 | `prompts/admission_vs_first_progress.md` |
| `discharge_vs_frontpage` | 首次病程记录 vs 出院记录 | `prompts/discharge_vs_frontpage.md` |
| `surgery_chain` | 术前/手术/术后首次病程连贯性 | `prompts/surgery_chain.md` |
| `progress_vs_nursing` | 病程记录 vs 护理记录 | `prompts/progress_vs_nursing.md` |
| `jyjc_vs_bcnursing` | 检验检查 vs 病程/护理 | `prompts/jyjc_vs_bcnursing.md` |
| `syssvsscbc` | 病案首页手术/诊断 vs 术后首次病程 | `prompts/syssvsscbc.md` |

`discharge_vs_frontpage` 是生产兼容 code，虽然临床语义是“首次病程 vs 出院记录”，不得重命名为 `discharge_vs_first_progress`。

## 2. 快照来源与完整性

快照日期：2026-07-16。来源为仓库现役 `docs/reference/110–115`，复制时内容哈希一致：

| 文件 | SHA-256 |
| --- | --- |
| `admission_vs_first_progress.md` | `36B0AA80EED38EF85E693F1F773DFA6CE264BEA4573CE9A87004639D0CDB63D2` |
| `discharge_vs_frontpage.md` | `3E7E357070894B20215201E5F01430013749DCC6D23F507B46AD6843AD3BD633` |
| `surgery_chain.md` | `88289A6AEC7A93448B155F9890D5E6B25C42E73DD62655C033D338C5DE900075` |
| `progress_vs_nursing.md` | `A6093CAC4109228EAFE9D6BA78F2511CBF52F631443AEC42FC7A9B7E889A05D1` |
| `jyjc_vs_bcnursing.md` | `812BCCB27D3F57F59EC388DA463416641367A420595996B72CAFB7B8B4596032` |
| `syssvsscbc.md` | `69D5ADB40B854F895243F3053DE649415C2168B6FA4635623A1C04F26C465023` |

若源文档发生变化，技能快照不会自动变化。执行者必须比较哈希；不一致时停止并提交“是否同步新版本”的确认，不得自行合并临床规则。

## 3. 单条高危复核顺序

对每条历史 high/red 维度执行：

1. 读取 `audit_type_code`，只加载对应完整提示词。
2. 校验 `dimension_code` 属于该提示词白名单；`other` 或白名单外 code 标记 `manual_review/code_out_of_scope`（`other` 不得 keep_high）。
3. 校验所需文书 source 是否存在。任一必需来源整体缺失时不得 high；按提示词输出 unknown/gray/manual_review，不伪造 pass。
4. **取证**：优先 `extra.issues[]` 的 evidence_a/b；否则 content 列；最后才是 evidence 数组列。库内 evidence 数组为 `[]` 时不得直接认定无证据。
5. 使用提示词“节点一”规则，仅基于脱敏后的双方原始证据片段重新识别 issue。不得把数据库当前 high 作为先验结论。
6. 使用提示词“节点二”规则检查等级映射、source 名称、证据字段、置信度和维度完整性。
7. 再执行后端确定性门槛：维度必须 fail、confidence>=0.8、双方证据有意义，并且同一 `extra.issues` issue 满足 severe、high_eligible、contradiction、双方真实证据、置信度阈值和受控 safety category。
8. **临床过宽检查（即使后端门槛通过也要做）**：`safety_category` 是否与事实匹配；是否仅为时间详略/措辞差异/合理演变。通过形式门槛但临床过宽 → 不得 keep_high，应 `downgrade_medium` 或 `manual_review`。
9. 只有提示词临床规则和后端门槛同时通过，才输出 `keep_high` 候选。否则只能输出降级建议或 `manual_review`，不得直接写库。

## 4. 六类特别限制

- `admission_vs_first_progress`：只允许 patient_identity、allergy_medication、wrong_site_or_side、critical_diagnosis_basis 等清单内**直接患者安全冲突**进入 high。生产高危高度集中在此类型：主诉时间差、查体措辞差、详略不同被标 `critical_diagnosis_basis` 的，默认倾向降级/人工，不得仅因模型 high_eligible 就 keep。
- `discharge_vs_frontpage`：合理诊断演变、一般遗漏、倒填待核、单侧证据不得 high。
- `surgery_chain`：必须使用真实的 preop/operation/postop source；任一必需文书缺失、普通术后记录不全或伪 source 不得 high。
- `progress_vs_nursing`：必须是同一事项、可比较时间窗的直接相反证据；同日状态变化和护理级别时间差不得 high。
- `jyjc_vs_bcnursing`：当前所有 omission，包括“危急结果未响应”，最高 medium/manual_review，不得 high；普通 contradiction 只有影响 critical_diagnosis_basis 才可能 high。
- `syssvsscbc`：仅 wrong_site_or_side 或 wrong_procedure_or_implant 的双侧直接冲突可能 high；外部医学推断不得 high。

## 5. AI 输出格式

外部 AI 每条只返回：

```json
{
  "review_token": "opaque-token",
  "audit_type_code": "one-of-six-codes",
  "dimension_code": "prompt-whitelisted-code",
  "decision": "keep_high|downgrade_medium|downgrade_low|manual_review",
  "target_mapping": "high_red|warn_medium_yellow|pass_low_blue|unknown_low_gray",
  "reason_code": "controlled-code",
  "prompt_sha256": "sha256-of-selected-prompt",
  "high_gate": {
    "required_sources_present": false,
    "direct_bilateral_contradiction": false,
    "same_comparable_fact_and_time": false,
    "confidence_at_least_0_8": false,
    "severe": false,
    "high_eligible": false,
    "allowed_safety_category": false,
    "backend_compound_gate_passed": false
  },
  "brief_rationale": "不含患者标识的简短理由",
  "clinical_confirmation_required": true
}
```

`target_mapping=pass_low_blue` 仅适用于已有充分一致性证据；文书缺失、单侧证据或资料不足必须使用 `unknown_low_gray`。AI 不能将 `clinical_confirmation_required` 改为 false。

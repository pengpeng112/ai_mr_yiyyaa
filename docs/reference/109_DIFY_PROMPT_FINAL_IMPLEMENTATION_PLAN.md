# 六类 Dify 病历质控提示词最终实施计划

> 状态：后端高危兜底已实施并完成自动化验证；六类生产 Dify 提示词仍待人工更新与灰度
> 建立日期：2026-07-13
> 核心目标：消除“某类文书缺失或单侧未提及被判为高危”的误报，同时尽量保持原有工作流、JSON 字段、落库和告警功能不变。

## 1. 适用范围

| 编号 | audit_type_code | 质控类型 | 最终提示词 |
| --- | --- | --- | --- |
| 110 | `admission_vs_first_progress` | 入院记录 vs 首次病程 | `110_DIFY_PROMPT_ADMISSION_VS_FIRST_PROGRESS.md` |
| 111 | `discharge_vs_frontpage` | 首次病程 vs 出院记录 | `111_DIFY_PROMPT_DISCHARGE_VS_FIRST_PROGRESS.md` |
| 112 | `surgery_chain` | 围手术期 | `112_DIFY_PROMPT_SURGERY_CHAIN.md` |
| 113 | `progress_vs_nursing` | 病程 vs 护理 | `113_DIFY_PROMPT_PROGRESS_VS_NURSING.md` |
| 114 | `jyjc_vs_bcnursing` | 检验检查 vs 病程/护理 | `114_DIFY_PROMPT_JYJC_VS_BCNURSING.md` |
| 115 | `syssvsscbc` | 首页手术 vs 术后首次病程 | `115_DIFY_PROMPT_SYSSVSSCBC.md` |

每类均保留“节点一临床事实提取 + 节点二 JSON 结构转换”两节点拓扑。

## 2. 不可回退规则

1. 任一必需文书整体缺失：不得输出明确问题或 high；节点一输出 `manual_review`，节点二输出 `unknown/low/gray/review_only`。
2. 一方未提及、另一方有记录：不得作为直接矛盾，不得 high。
3. high 必须来自同一个 issue，并同时满足 `severe + high_eligible + confidence>=0.8 + 不同真实来源的双方直接证据 + 受控患者安全类别`。
4. 明确问题不够 high 时保留 `warn/medium`，不得错误抹成 unknown。
5. 仅证据不足或无法确认时才使用 `unknown/gray/manual_review`。
6. 模板、错字、重复和格式问题通常只能 low；若内容实际造成错患者、错侧、错药、错术式，应归入相应安全维度再判断。
7. 当前生产 payload 和解析链路尚不能验证本院危急规则与完整时间窗，因此检验检查“危急结果未响应”本阶段最高为 medium/manual_review，不允许单侧 omission high；完成规则字段接入及后端验证后方可另行启用例外。

## 3. 兼容性策略

- 最终 JSON 继续使用现有 `version/audit_type/patient_summary/audit_summary/dimensions` 结构。
- 继续输出 `medical_evidence`、`nursing_evidence`、`extra.issues`、`extra.manual_review`，避免改变当前解析与落库主字段。
- 维度 code 首轮保持各类型现有白名单，不一次性扩容，避免影响历史统计和页面展示。
- `progress_vs_nursing` 仍按 legacy 证据列落库，但新版提示词本身执行与其他类型相同的高危规则。
- 首次病程 vs 出院记录继续使用生产现有 code `discharge_vs_frontpage`，本轮不得重命名，避免影响历史日志、调度、配置和统计。
- `surgery_chain` 必须确认 payload 中三类文书均可区分，才可部署其提示词。

## 4. 实施顺序

1. 在 Dify 复制现有工作流为新版本，不覆盖旧版本。
2. 分别替换六类节点一、节点二提示词；保持 Start、条件分支、End 输出变量和 API key 不变。
3. 使用匿名固定样本离线回放：双方存在冲突、单侧文书缺失、单侧未提及、同义表达、一般问题、真实高危。
4. 新工作流先影子运行，结果不发送企业微信告警。
5. 临床抽检确认后，先灰度一个活配置类型；`surgery_chain` 因三来源识别前置条件不得作为首个灰度类型。
6. 确认无缺失文书 high、无单侧证据 high、无 warn→high 后，再逐类切换。

## 5. 必测用例

- source_a 缺失、source_b 存在；source_b 缺失、source_a 存在；双方均缺失。
- 双方都有文书，但一方未提及目标事项。
- 双方同义、上下位、合理诊断演变或不同时间状态变化。
- 双方明确相反但仅一般文书问题。
- 双方明确相反且涉及身份、过敏、侧别、关键术式或当前生命支持。
- 节点一输出 severe 但缺任一证据、confidence<0.8 或 high_eligible=false。
- 节点二必须把上述不合格 high 降为 medium 或 unknown，不能保留 red。
- jyjc 危急规则：已响应、未响应、响应窗未结束、无机构规则四类；当前阶段四类均验证不会因单侧 omission 形成 high。
- JSON 代码块、尾随文字、截断、空输出；任何解析异常都不得形成 high 告警。

## 6. 灰度与回滚

灰度期间每日统计：high 总量、单侧/无证据 high、missing source 数、manual review 数、JSON 失败数和企业微信告警数。以下任一情况立即切回旧工作流并关闭新告警：

- 文书缺失或单侧未提及仍产生 high；
- high 无两侧可追溯证据；
- 一般问题被大批转为 unknown 或 pass；
- 解析失败仍触发结论级告警；
- 原有成功推送、落库、页面展示或反馈链路异常。

回滚只切换 Dify 工作流版本和告警开关，不删除新旧结果，便于追溯。

## 7. 上线前业务确认

1. 本院危急检验/影像规则及响应时间窗。
2. 确认首次病程 vs 出院记录继续使用生产 code `discharge_vs_frontpage`（已确认，本轮不改 code）。
3. `surgery_chain` 的术前、手术、术后文书真实 source 字段。
4. high 的临床响应时间与行政闭环时间。

## 8. 后端实施状态（2026-07-13）

已完成：

- 六类审计统一执行 high 硬门槛；单侧、无证据、低置信度、warn→high 和缺少结构化高危 issue 均不能触发红色告警。
- 双侧明确问题但不满足 high 全部条件时保留为 `warn/medium/yellow`；证据不足时转为 `unknown/low/gray/manual_review`。
- 非结构化 JSON 解析回退最多判为 medium，解析异常不得形成 high。
- admission 维度编码归一化保持专属，不扩散到其他类型。
- 批量兼容回退不得丢失 `audit_type_code`；审计类型测试和日志重推路径均传递该 code。
- 首页手术生产响应路径统一为 `$.audit_summary.has_inconsistency`。

仍待人工执行：六类 Dify 两节点提示词更新、匿名样本回放、影子运行和临床抽检。

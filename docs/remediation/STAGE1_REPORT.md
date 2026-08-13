# Stage 1 历史高危复核脱敏包生成报告

> 文档编号：023-WP7-S1
> 生成日期：2026-08-13（Asia/Shanghai）
> 执行者：Codex 主代理
> 依据：`docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` §11.4
> Skill：`med-audit-history-remediation` Stage 1
> 停止点：用户批准该复核包可交给外部 AI

---

## 1. 执行摘要

| 项 | 值 |
|---|---|
| **范围** | 023 §11.4 formally_unqualified high/red 维度 |
| **数据库** | 生产 Oracle 应用库（容器内只读） |
| **发现 high/red 维度** | 3331 条 |
| **formally_qualified（排除）** | 2864 条（过后端复合门槛，不在本次范围） |
| **formally_unqualified（纳入）** | **467 条** |
| **生产写入** | **无**（Stage 1 只生成脱敏包，不写库） |
| **患者标识泄露** | **无**（自动安全审查通过） |

## 2. 类型分布（精确匹配 §11.4）

| audit_type_code | 候选数 |
|---|---|
| admission_vs_first_progress | 239 |
| jyjc_vs_bcnursing | 123 |
| discharge_vs_frontpage | 91 |
| surgery_chain | 14 |
| **合计** | **467** |

## 3. 证据可用性

| 类别 | 数量 | 说明 |
|---|---|---|
| 双方证据均存在 | 357 | 可交外部 AI 复核 |
| 仅单侧证据 | 104（81+23） | 需评估是否足以判断矛盾 |
| 双方证据均为空 | 6 | **转内网人工复核**，不外发 |

## 4. 输出文件

| 文件 | 位置 | SHA-256 | 说明 |
|---|---|---|---|
| `stage1_review_package.json` | `docs/remediation/` + 容器 `/tmp/stage1_review/` | `1D11362A85B31AB0A61D5EE70C6C3B1EB799E3BDBB79C0B8AA21A7E7B877AEF4` | 467 条脱敏记录，可交外部 AI |
| `stage1_internal_mapping.json` | **仅容器内** `/tmp/stage1_review/` | `EA0204A3D0A942ECD865FC18F74159114C2CAB3D981E911264089A835682E5CB` | token→真实ID映射，**不得外发** |
| `stage1_report.json` | `docs/remediation/` + 容器 | — | 元数据摘要 |

## 5. 脱敏规则

| 处理 | 说明 |
|---|---|
| 患者标识移除 | patient_id/姓名/住院号/次数/科室均不在包内 |
| 数字脱敏 | 6 位以上数字串 → `[NUMBER]` |
| 日期脱敏 | 日期格式 → `[DATE]`/`[DATETIME]` |
| 科室脱敏 | 科室名模式 → `[DEPT]` |
| 证据截断 | 单侧最大 200 字符（467 条中无截断） |
| Token 映射 | 每条记录用 `secrets.token_hex(16)` 生成不可逆 token |

## 6. 安全审查结果

- ✅ 自动扫描：无 PHI 标识字段、无长数字残留
- ✅ 全部必填字段完整（review_token/audit_type_code/dimension_code/severity/confidence/evidence/prompt_sha256）
- ✅ 每条记录附带对应类型提示词快照 SHA-256
- ⚠️ **人工抽检待完成**：证据文本本身是临床医学信息（症状/诊断），发送前需人工确认无直接可识别信息
- ⚠️ 6 条双方证据为空的记录应转内网人工复核

## 7. 科室回填候选

023 §11.3 只读基线确认：7019 条 PushLog 科室为空，经 V_QYBR 精确匹配**只有 1 条**可唯一回填，其余 7018 条无匹配（禁止猜测）。

该 1 条候选将在 Stage 5 科室回填阶段单独处理，本次不涉及。

## 8. 下一步所需批准

### 8.1 交外部 AI 前需确认

1. **人工抽检**：临床/质控人员抽样检查脱敏证据，确认无可识别患者信息。
2. **6 条空证据记录**：决定是内网人工复核还是排除。
3. **外部 AI 模型和隔离方案**：确认使用的 AI 模型、隔离环境、返回格式。

### 8.2 交外部 AI 后的流程（Stage 2）

1. 外部 AI 返回 `keep_high/downgrade_medium/downgrade_low/manual_review` + `reason_code`。
2. 本地二次裁决：重新跑后端门槛 + 语义 shadow + 提示词临床规则。
3. 生成"可批准 keep_high / 可批准降级 / 必须人工 / 拒绝"四张清单。
4. **停止点**：临床质控负责人批准精确 token/等级/理由后才可进入 Stage 3 dry-run。

---

## 9. 未触碰的生产资源

- 未修改任何数据库表、行或配置
- 未调用 Dify
- 未触发调度
- 未发送 Relay/企业微信
- `internal_mapping.json` 保留在容器 `/tmp/stage1_review/`，未下载到本地工作目录

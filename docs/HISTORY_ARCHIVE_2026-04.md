# 2026-04 阶段历史归档

本文件用于替代以下阶段性、临时性说明文档，作为当前仓库保留的统一历史修改记录：

- `docs/frontend-improvement-plan.md`
- `docs/FRONTEND_PHASE4_SKIP_CLOSEOUT_2026-04-06.md`
- `docs/SESSION_RECAP_2026-04-07.md`
- `docs/bug.md`
- `.sisyphus/plans/code-review-fixes.md`

## 1. 前端阶段收口

- 前端改造已完成 `Phase 1 ~ Phase 3`。
- `Phase 4` 的 `Vite + Vue3 SFC` 迁移本轮明确跳过，不纳入当前交付。
- 当前正式前端交付形态仍为 `static/`：
  - `static/scripts/app.js` 已拆分为 `modules/` 与 `utils/`
  - `static/styles/app.css` 已拆分为 `components/` 与 `pages/`
  - 已接入 `dayjs`
- 原先误建或试验性质的前端脚手架方案不再保留。

## 2. 本阶段核心改造

### 2.1 数据推送

- 手工推送支持单日与日期范围推送。
- 支持多日期维度：查询日期、病历创建日期、入院日期、出院日期。
- 支持并行 workers、多 Dify 目标、轮询/加权分发、空结果自动重试。
- 返回结果增加目标级统计、有效 workers、空结果重试次数等字段。
- 去重逻辑调整为优先按 `MRID/mrid` 处理，适配 `b.mrid||c.form_id` 唯一键方案。

### 2.2 质控反馈与导出

- 反馈病例列表、查看详情、CSV/Excel 导出补充住院与诊疗信息字段：
  - 入院日期、出院日期、所在科室名称、入院诊断、是否出院
  - 入院科室名称、出院科室名称、出院主诊断、手术
- Excel 导出支持按维度拆分病程记录与护理记录对照列。
- 导出链路校正为真实 `.xlsx`，不再返回伪 Excel 文件。

### 2.3 隐私脱敏

- 脱敏策略收口为：
  - 数据库存储保留原值
  - 列表与详情接口返回原值
  - 仅 Excel 导出按配置对姓名、身份证号、住址、联系电话脱敏
- 身份证短长度场景脱敏边界已修复。

### 2.4 权限与管理

- 角色、权限、菜单、科室分配链路补齐。
- 反馈确认时的科室映射权限边界收紧。
- `reviewed_by / reviewed_at` 改为使用日志实际复核字段，不再误用反馈创建信息。

## 3. 本阶段处理过的重点问题

- 修复反馈与导出字段缺失。
- 修复导出格式错误与 Excel 回退风险。
- 修复推送链路、去重逻辑、空结果重试和目标统计问题。
- 修复权限分配、菜单分配、科室分配相关缺口。
- 修复多处列表/详情/导出联动与前端调用问题。

## 4. 当前保留文档原则

- 长期入口与规范文档保留：
  - `README_CN.md`
  - `开发文档.md`
  - `DEPLOY.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/FEATURE_BASELINE_2026-04.md`
  - `PROJECT_REFACTOR_BLUEPRINT.md`
  - `docs/医疗审计系统_代码改造与UI优化计划.md`
- 阶段性会话总结、收口说明、临时修复计划、一次性执行清单不再单独保留。

## 5. 后续约定

- 后续新增阶段总结时，优先更新：
  - `docs/FEATURE_BASELINE_2026-04.md`
  - `docs/HISTORY_ARCHIVE_2026-04.md`
- 不再新增新的 `SESSION_RECAP`、`CLOSEOUT`、`bug.md`、临时修复计划类文档，避免文档堆积。

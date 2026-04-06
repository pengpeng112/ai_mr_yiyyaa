# Oracle 稳定性整改与功能改造计划

## TL;DR
> **Quick Summary**: 先止血（logs 500、调度不执行），再做能力改造（调度可配置、推送标记/复核跳过、全链路可观测）。
>
> **Deliverables**:
> - `/api/logs` NULL 兼容修复
> - 前端可配置调度（10分钟/30分钟/每天/自定义）并可靠生效
> - 推送标记 + 人工复核 + 下次跳过规则
> - Docker 完整 SQL/参数/耗时/行数日志
> - “查询14条 vs 实际推送N条”漏斗对账能力
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: T1 → T3 → T7 → T11 → T13 → FINAL

---

## Context
### Original Request
1) 定时任务表达式可在前端修改（10分钟、30分钟、每天等）；
2) 前端可查看每次推送记录与推送标识，并支持手动修改；已推送但未复核下次跳过；
3) Docker 日志完整记录执行 SQL；
4) 定时任务设置成功但到期未自动执行需核查；
5) `/api/logs` 报错（error_msg 为 None 导致 Pydantic 校验失败）；
6) 查询14条但文书/推送条目更少，需解释并增强排障能力。

### Interview Summary
- 已有运行日志证明：Dify 调用耗时长（70-90s）、调度状态轮询频繁、logs 接口确有 NULL 导致 500。
- 内部排查证据：调度链路、分组/去重/跳过链路、Oracle NULL 语义与事务风险均已定位。

### Metis Review
- 已补齐护栏：避免范围膨胀到前端重构/消息系统重构。
- 已补齐验收维度：scheduler 生效、NULL 兼容、漏斗对账、SQL 审计日志完整性。

---

## Work Objectives
### Core Objective
在 Oracle 约束下，交付“稳定可运行 + 可观测 + 可运维回放”的推送与调度体系。

### Concrete Deliverables
- logs API 在历史 NULL 脏数据下稳定返回 200。
- 调度表达式可配置，且 5 秒内可在状态接口看到 next_run_time 更新。
- 推送标记/复核标记可查询和手动修改，并影响下一次推送。
- SQL 审计日志可开关，输出 SQL、params、elapsed、rows。
- 每次推送输出漏斗计数，能够解释数量收缩原因。

### Definition of Done
- [ ] `/api/logs?page=1&limit=20` 在 NULL 数据场景返回 200
- [ ] 调度修改后自动执行正常
- [ ] “已推送未复核跳过”生效
- [ ] SQL 日志完整且可检索
- [ ] 漏斗统计可对账

### Must Have
- Oracle 兼容（NULL 语义、事务安全、单 worker）。

### Must NOT Have
- 不做前端全面重构；不做消息系统重构；不引入分布式调度平台。

---

## Verification Strategy
- **Infrastructure exists**: YES（脚本 + API 集成验证）
- **Automated tests**: Tests-after
- **Framework**: `python scripts/*.py` + `curl` + Docker logs 证据

QA政策：每个任务必须包含 1 个 happy-path + 1 个 error/edge 场景，证据落地到 `.sisyphus/evidence/`。

---

## Execution Strategy
### Parallel Execution Waves
Wave 1（止血+观测基础）: T1 T2 T3 T4 T5
Wave 2（调度可配置与可靠性）: T6 T7 T8
Wave 3（推送标记与业务规则）: T9 T10 T11 T12
Wave 4（对账与运维）: T13 T14
Wave FINAL: F1 F2 F3 F4

### Dependency Matrix
- T1 → T13
- T2 → T13
- T3 → T7,T8,T14
- T4 → T13,T14
- T5 → T13
- T6 → T7
- T7 → T8
- T8 → T14
- T9 → T10,T11
- T10 → T11,T12
- T11 → T12,T13
- T12 → T13
- T13 → FINAL
- T14 → FINAL

### Agent Dispatch Summary
- T1/T2/T4/T5/T6: `quick`
- T3/T7/T8/T9/T10: `unspecified-high`
- T11/T12/T13: `deep`
- T14: `writing`

---

## TODOs

- [ ] 1. `/api/logs` NULL 兼容止血
  - **What to do**: logs 列表/详情响应前统一字符串字段 `None -> ""`；修复 `error_msg` 首发报错。
  - **Must NOT do**: 不改变业务语义值。
  - **Parallelization**: YES, Wave1, Blocks T13
  - **References**: `app/routers/logs.py`, `app/schemas.py`, `app/models.py`
  - **Acceptance**: `/api/logs` 返回 200，无 ValidationError。
  - **QA Scenarios**:
    - Happy: curl `/api/logs?page=1&limit=20` => 200，items 可解析；Evidence: `task-1-logs-ok.json`
    - Error: 数据含 NULL `error_msg` 仍返回 200；Evidence: `task-1-null-safe.json`

- [ ] 2. logs schema 全字段 nullable 对齐扫描
  - **What to do**: 扫描 `PushLogItem/PushLogDetail` 全字段并修复 mismatch。
  - **Must NOT do**: 不无评估地大面积改 Optional。
  - **Parallelization**: YES, Wave1, Blocks T13
  - **References**: `app/schemas.py`, `app/models.py`, `app/routers/logs.py`
  - **Acceptance**: logs 相关响应字段在历史脏数据下稳定。
  - **QA Scenarios**:
    - Happy: `/api/logs/{id}` 200；Evidence: `task-2-detail-ok.json`
    - Edge: 跨分页 page=1/2 均 200；Evidence: `task-2-paging-ok.json`

- [ ] 3. 调度状态诊断增强
  - **What to do**: 状态接口增加 enabled/cron/job_id/next_run_time/last_error。
  - **Must NOT do**: 不新增第二 scheduler 实例。
  - **Parallelization**: YES, Wave1, Blocks T7/T8/T14
  - **References**: `app/scheduler.py`, `app/routers/scheduler.py`, `app/main.py`
  - **Acceptance**: 可区分“未建job/未触发/执行失败”。
  - **QA Scenarios**:
    - Happy: status 含 next_run_time；Evidence: `task-3-status.json`
    - Error: disabled 场景清晰呈现；Evidence: `task-3-disabled.json`

- [ ] 4. SQL 审计日志（完整SQL+参数+耗时+行数）
  - **What to do**: Oracle 查询链路统一审计日志前缀，支持开关。
  - **Must NOT do**: 默认模式不泄露敏感明文。
  - **Parallelization**: YES, Wave1, Blocks T13/T14
  - **References**: `app/oracle_client.py`, `app/routers/config.py`, `app/main.py`
  - **Acceptance**: Docker logs 可检索 SQL/params/elapsed/rows。
  - **QA Scenarios**:
    - Happy: 触发查询后日志字段完整；Evidence: `task-4-sql-audit.log`
    - Edge: 关闭开关后不打印明细；Evidence: `task-4-toggle.log`

- [ ] 5. 推送漏斗埋点
  - **What to do**: 输出 raw_rows/dept_filtered/group_count/skipped/success/failed/dedup_drop。
  - **Must NOT do**: 不改现有过滤语义。
  - **Parallelization**: YES, Wave1, Blocks T13
  - **References**: `app/routers/push.py`, `app/oracle_client.py`, `app/services/payload_builder.py`, `app/services/push_executor.py`
  - **Acceptance**: 单次推送漏斗可完整对账。
  - **QA Scenarios**:
    - Happy: summary 日志存在且守恒；Evidence: `task-5-funnel.log`
    - Edge: 重复数据有 dedup 统计；Evidence: `task-5-dedup.log`

- [ ] 6. 调度表达式策略模型（预设+自定义）
  - **What to do**: 提供 10min/30min/daily 预设与 cron 自定义入口。
  - **Must NOT do**: 不支持秒级 cron。
  - **Parallelization**: YES, Wave2, Blocks T7
  - **References**: `app/schemas.py`, `app/routers/config.py`
  - **Acceptance**: 预设可保存；非法 cron 拒绝。
  - **QA Scenarios**:
    - Happy: 设置 10min 成功；Evidence: `task-6-10m.json`
    - Error: 非法 cron 返回 4xx；Evidence: `task-6-invalid.json`

- [ ] 7. scheduler 保存与热更新一致性
  - **What to do**: 保证“配置持久化 + 内存 job 更新”一致事务语义。
  - **Must NOT do**: 不允许 file 与内存配置分叉。
  - **Parallelization**: NO, Wave2, BlockedBy T3/T6, Blocks T8
  - **References**: `app/routers/config.py`, `app/scheduler.py`
  - **Acceptance**: 更新后 5 秒内 next_run_time 对齐。
  - **QA Scenarios**:
    - Happy: daily 切 */10 后立即反映；Evidence: `task-7-reschedule.json`
    - Error: 更新失败时保持旧配置可运行；Evidence: `task-7-rollback.json`

- [ ] 8. 调度可靠性参数（misfire/coalesce/max_instances）
  - **What to do**: 明确错过触发点行为与并发行为。
  - **Must NOT do**: 不启用多 worker。
  - **Parallelization**: NO, Wave2, BlockedBy T7, Blocks T14
  - **References**: `app/scheduler.py`, `app/main.py`
  - **Acceptance**: 重启后不再出现“到点未执行且无解释”。
  - **QA Scenarios**:
    - Happy: 到点生成 history 记录；Evidence: `task-8-auto.json`
    - Edge: 重启后仍按新配置执行；Evidence: `task-8-restart.log`

- [ ] 9. 推送标记/复核字段与迁移
  - **What to do**: 新增 pushed/reviewed/manual_override 等字段及迁移函数。
  - **Must NOT do**: 不破坏旧数据读取。
  - **Parallelization**: YES, Wave3, Blocks T10/T11
  - **References**: `app/models.py`, `app/database.py`
  - **Acceptance**: 字段存在、默认值正确。
  - **QA Scenarios**:
    - Happy: 迁移后字段可读写；Evidence: `task-9-migration.json`
    - Edge: 历史记录读取不异常；Evidence: `task-9-compat.json`

- [ ] 10. 标记查询/手动更新 API + RBAC
  - **What to do**: 提供标记读写 API，记录操作者与时间。
  - **Must NOT do**: 不新建角色体系。
  - **Parallelization**: YES, Wave3, BlockedBy T9, Blocks T11/T12
  - **References**: `app/routers/logs.py`, `app/routers/permissions.py`
  - **Acceptance**: 授权成功、未授权 403。
  - **QA Scenarios**:
    - Happy: 管理员更新标记后可查；Evidence: `task-10-auth-ok.json`
    - Error: 非授权用户被拒绝；Evidence: `task-10-rbac-deny.json`

- [ ] 11. 接入“已推送未复核 -> 下次跳过”规则
  - **What to do**: 在 manual/async/scheduler 路径统一判定与优先级。
  - **Must NOT do**: 不与现有 rectified/suppress 规则冲突。
  - **Parallelization**: NO, Wave3, BlockedBy T9/T10, Blocks T12/T13
  - **References**: `app/services/push_executor.py`, `app/routers/push.py`
  - **Acceptance**: 满足条件时不调用 Dify；override 可强制推送。
  - **QA Scenarios**:
    - Happy: 未复核对象被跳过；Evidence: `task-11-skip.log`
    - Edge: override 后强制推送；Evidence: `task-11-override.log`

- [ ] 12. 手动/重推/定时计数口径统一
  - **What to do**: 将 skipped 从 failed 中拆分，状态接口返回独立 skipped。
  - **Must NOT do**: 不改历史状态枚举。
  - **Parallelization**: NO, Wave3, BlockedBy T10/T11, Blocks T13
  - **References**: `app/routers/push.py`, `app/services/task_manager.py`
  - **Acceptance**: progress 与结果明细可对齐。
  - **QA Scenarios**:
    - Happy: success+failed+skipped 与明细一致；Evidence: `task-12-progress.json`
    - Edge: manual/retry/auto 口径一致；Evidence: `task-12-paths.json`

- [ ] 13. 对账输出能力（解释数量差异）
  - **What to do**: 在结果响应/日志中输出可读“收缩原因摘要”。
  - **Must NOT do**: 不暴露敏感原文。
  - **Parallelization**: NO, Wave4, BlockedBy T1/T2/T4/T5/T11/T12, Blocks FINAL
  - **References**: `app/routers/push.py`, `app/services/payload_builder.py`, `app/services/push_executor.py`
  - **Acceptance**: 任一批次可解释“为什么少于查询行数”。
  - **QA Scenarios**:
    - Happy: 摘要含 grouped/skipped/dedup；Evidence: `task-13-summary.json`
    - Edge: 人造异常批次可完整回放；Evidence: `task-13-replay.log`

- [ ] 14. 运维排障手册与回滚预案
  - **What to do**: 输出调度检查、日志对账、回滚步骤文档。
  - **Must NOT do**: 不写泛化空文档。
  - **Parallelization**: YES, Wave4, BlockedBy T3/T4/T8, Blocks FINAL
  - **References**: `Dockerfile`, `app/scheduler.py`, `app/main.py`, `app/oracle_client.py`
  - **Acceptance**: 手册可按步骤复现检查与回滚。
  - **QA Scenarios**:
    - Happy: 按手册完成调度生效检查；Evidence: `task-14-runbook.log`
    - Edge: 按手册完成一次配置回滚；Evidence: `task-14-rollback.log`

---

## Final Verification Wave
- [ ] F1. **Plan Compliance Audit** — `oracle`
- [ ] F2. **Code Quality Review** — `unspecified-high`
- [ ] F3. **Real QA Replay** — `unspecified-high`
- [ ] F4. **Scope Fidelity Check** — `deep`

---

## Commit Strategy
- Commit A: logs 500 + scheduler 诊断/状态
- Commit B: scheduler 可配置与热更新可靠性
- Commit C: 推送标记/复核跳过规则
- Commit D: SQL 审计日志 + 漏斗对账 + 运维文档

---

## Success Criteria
### Verification Commands
```bash
curl "http://localhost:8000/api/logs?page=1&limit=20"
curl "http://localhost:8000/api/scheduler/status"
curl "http://localhost:8000/api/health"
python scripts/test_api.py
```

### Final Checklist
- [ ] Logs API NULL 兼容稳定
- [ ] 调度可配、可生效、可自动执行
- [ ] 推送标记/复核跳过规则生效
- [ ] SQL 与漏斗日志可用于复盘

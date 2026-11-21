# 执行任务书 `PROMPT-WP10-S7`：064 生产上线 3 日只读观察与最终验收报告（**严格只读**）

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（WP-10 收口步骤 S7）  
> **建议执行时间**：2026-11-25 或 2026-11-26（距 2026-11-21 上线满 3 个工作日）  
> **前置事实**：WP-01 ~ WP-09 本地开发与走查修复、以及 **WP-10 S0 ~ S6 全部生产发布、Oracle 索引 DDL、历史回填与 `med-prearchive` 影子激活均已于 2026-11-21 执行完毕并验收通过**——**严禁重复执行 S0 ~ S6 任何发布或 DDL 动作！**  
> **授权边界**：本任务书**仅授权对 `10.10.8.84` / `10.10.8.216` / `10.10.8.177` 执行严格只读巡检，以及本地编写验收报告与更新台账文档**；**严禁任何生产写入/重启/改配置/DDL/DML，严禁任何 Git 写操作**。

---

## 一、2026-11-21 上线基线快照（供 3 日后逐项对照）

| 项目 | 2026-11-21 S0~S6 实测基线 | 备注 / 回滚点 |
| --- | --- | --- |
| `med-audit:latest` | `sha256:a94f65b5e845...` | 回滚：`med-audit:backup-pre-064-20261121` + `/root/backup_pre_064_20261121.tar.gz` |
| `med-prearchive:latest` | `sha256:ab4905310aa3...` | 回滚：`med-prearchive:backup-pre-064-20261121` + `/opt/med-audit-docker/config/prearchive.prod.json.bak-20261121` + `/root/backup_prearchive_pre_064_20261121.tar.gz` |
| 主服务四道写闸 | `jhemr_write=False` / `insert_monitor=None` / `notify_mode=LOG_ONLY` / `JHEMR_INTEGRATION_ENABLED=None` | 必须全程零漂移 |
| 预检对外投递闸门 | `push.enabled=false` / `result_delivery.enabled=false` / `staging_table.enabled=false` / `require_manual_confirm=true` | `OUTBOX=0` / `DELIVERY_LOG=0` |
| `timeliness_scan` | 常规更新 `4~15` 行（每 30 分钟阈值更新 ~1,343 行）、`persist` `750~930 ms`、总耗时 `62~69 s` | 上线前为 `7,715` 行 / `94~102 s` |
| 核心统计接口耗时 | `workbench-overview` 冷 `313.9 ms`/热 `18.7 ms`；`/stats/severity` `107.3 ms`；`/stats/anomaly-top` `139.6 ms` | 上线前 `severity` 841 ms |
| Oracle 3 条索引 | `IDX_PUSH_LOG_CURR_TIME`、`IDX_PUSH_LOG_CURR_SEV_DEPT`、`IDX_PUSH_LOG_DISCHARGE_DEPT` 全部 `VALID` | `MED_PUSH_LOG` 初始 249,671 行，回填 `DISCHARGE_DEPT` 1,870 行 |
| `med-prearchive` 首轮影子 | `RULE_VERSION=16`、`RESULT=100`、`RULE_EVAL=1,600`、`ISSUE=121`（96 人）、`OUTBOX=0`、`DELIVERY_LOG=0` | 仅接 `177 JHEMR`（`anchor_mode=discharge`，`rule_registry.mode=registry`），`his`/`sm` 暂关 |

---

## 二、7 项严格只读巡检清单（通过 `10.10.8.84:40022`，口令仅从 `MED_AUDIT_SSH_PASSWORD` 环境变量读取）

> 注意：数据库只读探查严禁导入 `app.main` 或调用 `init_db()`；仅用 `from app.database import engine` 执行 `SELECT`；输出中严禁出现患者姓名、完整住院号、口令或密文。

1. **容器运行态与异常日志检查**：
   - `docker ps` 核对 `med-audit` 与 `med-prearchive` 持续 `Up` 且 `healthy`（无意外重启 / OOMKilled）。
   - 统计 `2026-11-21T08:48:19Z` 以来两容器日志中的 `Traceback` 与 `ERROR` 数量；若有报错，摘录脱敏类型与频次并评估是否需跟进。
2. **写闸与零外发红线核验**：
   - 读取 `med-audit` 写闸四值与 `med-prearchive` `prearchive.prod.json` 的 `push`/`result_delivery`/`staging_table` 开关，确认全部未漂移。
   - 查询 Oracle `SELECT COUNT(*) FROM MED_PREARCHIVE_OUTBOX` 与 `MED_PREARCHIVE_DELIVERY_LOG`，必须均为 **`0`**。
3. **定时调度（09:00 每日增量 & 11:44 出院终末）3 日执行核查**：
   - 按天（`>= 2026-11-22`）统计 `MED_PUSH_LOG` 的 `audit_run_mode` / `status` / `COUNT(*)` 及 `DISCHARGE_DEPT IS NOT NULL` 新增行数，确认每日 `09:00` 与 `11:44` 调度稳定触发且新出院记录正常落 `DISCHARGE_DEPT`。
   - 核查 `med-audit` 日志中近 3 天调度器是否触发 `ORA-12609` 瞬时重试以及重试后是否成功。
4. **时效扫描（`MED_TL_SCAN_RUN`）3 日稳定性**：
   - 查询 `2026-11-21 15:00` 以来的扫描总轮次、成功/失败轮次、平均耗时、中位 `EVENTS_UPDATED`（预期常规轮次维持个位数~数十、单轮平均耗时 < 75s、失败率为 0 或偶发瞬时恢复）。
5. **总览/统计接口响应 & Oracle 索引状态 & 双端口复核**：
   - 核对 3 条新增索引在 `USER_INDEXES` 中全部 `VALID`。
   - 复测 `GET /api/stats/workbench-overview`（冷/热，预期冷 < 1.5s / 热 < 200ms）、`GET /api/stats/severity`（< 200ms）、`GET /api/stats/anomaly-top`（< 200ms）；注：签发测试 JWT 时须带 `auth_method="password"`。
   - 复测 `:8000/ui-next/`（200）、`:3000/ui-next/`（200）、`:3000/mobile/timeliness`（200）、`:3000/mobile/qc/1?token=invalid`（401）。
6. **`med-prearchive` 影子 3 日产出与病案室核查情况**：
   - 查询 `MED_PREARCHIVE_RUN`（按 `STATUS` 分组）、`MED_PREARCHIVE_RESULT`（总量、有缺陷人数、`SUM(PROBLEM_COUNT)`）、`MED_PREARCHIVE_RULE_EVAL`（按 `STATUS` 分组）、`MED_PREARCHIVE_ISSUE`（按 `RULE_ID`、`STATUS` 分组）、`MED_PREARCHIVE_ISSUE_ACTION`（病案室人工确认/误报/整改动作计数与原因分布）。
   - 核对 `GET /api/prearchive-admin/checks` 返回 `200` 且与库内计数一致。
7. **宿主机磁盘与 Oracle 表空间余量**：
   - `df -h /` 核对根分区可用空间（基线 37G，确认日志未异常膨胀）。
   - `USER_FREE_SPACE` 核对 `JHEMR`（基线 5.2 GB）与 `UNDOTBS1`（基线 78 GB）余量健康。

---

## 三、验收产物与收口动作

1. 新建验收报告 `review/064-wp10/RELEASE_REPORT.md`，包含：
   - 结论（`PASS` / `PASS WITH FOLLOW-UPS` / `ATTN`）；
   - S0 ~ S6 上线与回滚点总表（直接沿用上方基线并核验镜像 ID 未变）；
   - S7 3 日 7 项巡检实测表（与 11-21 基线逐项对比）；
   - 已知遗留事项与下一阶段建议清单（明确标注不在 064 范围内、需业务/信息科配合推进）：
     1. 无纸化 CDMS（`10.10.10.93`）只读账号到位后跑 `analyze_paperless_rejections_ro.py` 与 `paperless_gold_backtest_ro.py` 金标准回测；
     2. `PAPERLESS.T_ITF_HIS` / `MEDSURGERY.T_ITF_SM` 接口源地址与凭据确认后接入，补齐手术/检验类预检规则；
     3. 嘉和客户端对接路线 B `GET /api/integrations/jhemr/ai-reminders`；
     4. 清理 2026-11-21 16:41 首轮未修复 `current_flag` 前遗留的 100 条 `MED_PREARCHIVE_RUN` `status='running'` 占位行（仅记录建议，**严禁未经批准执行 `DELETE`**）。
2. 台账收口：
   - 在 `开发起步包/01_统一修改记录.md` 末尾追加 1 行（append-only，禁改历史行）；
   - 更新 `开发起步包/02_协作任务板.md` 将 `20261121-064-wp10-prod-release` 标为 `DONE`；
   - 更新 `docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md` 状态行与 `docs/INDEX.md` 对应状态为「全量上线并完成 3 日验收」；
   - 执行 `.\.venv\Scripts\python.exe scripts/check_documentation_20261002.py` 与 `git diff --check` 均通过。
3. **停止并向用户汇报**（不执行 `git commit`/`push`，不执行任何生产写操作）。

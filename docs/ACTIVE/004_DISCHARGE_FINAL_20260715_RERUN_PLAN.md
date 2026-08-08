# 2026-07-15 discharge_final 六类定向补跑执行计划

> 状态：**仅计划，禁止未批准执行**  
> 编制：2026-07-16  
> 前置：应用 Oracle（`APP_DB_TYPE=oracle`）监听可达；业务 Oracle/Vastbase 只读验证通过  
> 关联：`003_PRODUCTION_QC_REMEDIATION_PLAN`、调度锁历史可见性修复、Oracle 连接池恢复修复  

## 1. 目标

在**书面批准**后，仅补跑：

| 参数 | 值 |
| --- | --- |
| query_date | `2026-07-15` |
| audit_run_mode | `discharge_final` |
| audit_type_codes | 六类全部：`admission_vs_first_progress`, `discharge_vs_frontpage`, `surgery_chain`, `progress_vs_nursing`, `jyjc_vs_bcnursing`, `syssvsscbc` |
| 触发方式 | 管理接口/容器内受控手动触发（非改生产 cron） |

**本文件不是上线授权。** 未完成下方门禁与批准前禁止执行。

## 2. 禁止事项

- 禁止连公网 AI、禁止用真实患者测企微/H5。
- 禁止扩大日期或 run_mode。
- 禁止在应用库 `ORA-12541` / listener 不可用时强行补跑。
- 禁止跳过 dry-run 对账与备份。
- 禁止删除历史告警或覆盖原始 `response_json`。
- 002 幂等未落地时：仅单 worker、独占 `discharge_push` 锁、停用并行手工大批量；不得多实例并发补跑。

## 3. 执行前门禁（全部勾选）

1. [ ] `curl -fsS http://127.0.0.1:8000/api/health/live` → alive  
2. [ ] 应用库：`docker exec med-audit python -c "from app.database import test_app_db_connection; print(test_app_db_connection())"` → `status=up`  
3. [ ] 业务 Oracle/Vastbase：配置测试接口或只读 `SELECT 1` 成功（不打印连接串）  
4. [ ] `docker top med-audit` 确认 **单 uvicorn worker**  
5. [ ] `/api/scheduler/status`：`discharge_push` 锁 **idle**  
6. [ ] 镜像/配置备份完成：`docker commit` 或记录 digest；`config/`、应用库 export 按院内规程  
7. [ ] 只读基线已导出：2026-07-15 六类 SchedulerHistory / PushLog 计数（见第 5 节）  
8. [ ] 书面批准单号：____________ 批准人：____________  

## 4. 推荐执行步骤（人工或其它 AI）

### 4.1 补跑前只读快照

在容器内运行只读聚合（勿输出病历正文/密钥），至少记录：

- 六类各自：history 条数与 status、PushLog total/success/skipped/failed、parse_status 分层、qc_usable  
- 告警：pending/success/failed/dept_filtered  

保存到宿主机：`/opt/med-audit-docker/backups/rerun_20260715_discharge_<timestamp>/baseline.json`

### 4.2 触发方式（择一，批准后）

**方式 A（推荐）：管理 API**

```text
POST /api/scheduler/trigger
  ?query_date=2026-07-15
  &audit_run_mode=discharge_final
  &audit_type_codes=admission_vs_first_progress,discharge_vs_frontpage,surgery_chain,progress_vs_nursing,jyjc_vs_bcnursing,syssvsscbc
```

需 `manage_scheduler` 权限；Bearer token 不写进脚本仓库。

**方式 B：容器内受控调用**

仅在批准窗口内，用现有 `trigger_now(..., _audit_run_mode="discharge_final", audit_type_codes=[...])` 路径；禁止改 `scheduler_discharge` 的 cron 为临时补跑。

### 4.3 补跑中观察

- 日志：`docker logs --tail 200 med-audit`（脱敏查看）  
- 若再次出现 `ORA-12541`：立即停止，勿重试轰炸；先恢复 listener  
- 锁：确认 `discharge_push` 为 running → 结束后 idle  
- 锁失败时应出现 `SchedulerHistory.audit_type_code=__scheduler_lock__` 且 status=failed  

### 4.4 补跑后对账

对比 baseline：

| 检查 | 通过标准 |
| --- | --- |
| 六类均有 history 终态 | 无「配置了却完全无 history」静默漏跑 |
| jyjc 等类型级失败 | 若仍 failed，记录错误码，不得改阈值硬过 |
| parse_failed | 不计入 qc_usable；不因补跑伪造 success |
| 重复告警 | 同维度不重复 success 外发；dept_filtered 可解释 |
| supersede | 仅 parse_success 的 discharge 可覆盖 daily（见 003 语义） |

输出 `after.json` 与差异表；差异原因必须逐类写清。

## 5. 回滚

- 应用：回滚镜像 digest + 原 compose/env（**注意 SECRET_KEY 变更会导致配置密文不可解密**）  
- 数据：仅能用补跑前库备份恢复；禁止“再跑一遍反向”当回滚  
- 告警：已发送记录不删除  

## 6. 交付物清单

- [ ] 批准单  
- [ ] baseline/after 聚合 JSON（无 PHI）  
- [ ] 触发参数与操作者、起止时间  
- [ ] 六类对账表与残留问题  
- [ ] 是否需要进入历史高危整改技能阶段 1  

## 7. 与代码修复的关系

本计划假设已部署：

1. 业务 Oracle 池：瞬时 TNS 错误重建池、ping 陈旧连接、不把 ORA-12541 永久记入 pool_failed  
2. 应用库：`pool_pre_ping` + recycle + dispose 重试  
3. 调度锁未获取 → `SchedulerHistory(__scheduler_lock__, failed)`  

**listener 本身 down 仍须 DBA 恢复**；应用修复只提升恢复后自动可用与可观测性，不能替代数据库服务。

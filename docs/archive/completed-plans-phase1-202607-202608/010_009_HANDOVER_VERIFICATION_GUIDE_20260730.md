# 009 二次整改交接文档

> 日期：2026-07-30  
> 编写：整改实施 AI  
> 复核修订：2026-07-30（核查 AI：修正文档编码损坏、生产状态失真、`contract_valid=0` 当前可见漏洞、批量脚本 `not_found` 死循环）  
> 用途：供后续核查 AI 或开发人员接手验证和收尾  

## 1. 已完成工作摘要

### 代码修复（本地测试通过）

| 编号 | 修复内容 | 关键文件 |
|------|----------|----------|
| P0-1 | 契约维度集合修正为权威提示词（progress 6维、jyjc 6维、surgery 10维、discharge 9维、syss 4维）；admission 改为配置注入；新增 warn/low/blue 合法组合 | `app/services/result_contract_validator.py` |
| P0-2 | 新增 `contract_valid`/`contract_errors` 字段；SQLite 迁移 + Oracle DDL；supersede 入口检查契约；**默认当前结果过滤排除 contract_valid=0** | `app/models.py`, `app/database.py`, `app/dify_pusher.py`, `app/services/push_log_writer.py`, `app/services/push_log_supersede.py`, `app/services/current_result_filter.py`, `app/routers/patient_qc.py` |
| P0-3 | preview 输出 `manifest_complete`/`load_failed_count`；`create_batch_from_preview` 在 `load_failed>0` 时拒绝创建 | `app/services/historical_rerun_service.py` |
| P0-4 | 消除 `superseded_by = log.id` 自环；改用 `status="discarded"`；current_result_filter 排除 discarded | `app/services/historical_rerun_service.py`, `app/services/current_result_filter.py` |
| P1-1 | SchedulerHistory 传入 audit_run_mode 和 error_msg | `app/services/scheduler_audit_runner.py` |
| P1-2 | 新增 `_LeaseHeartbeat` 后台线程，Dify 调用期间续约 | `app/services/historical_rerun_service.py` |
| P1-3 | in_flight/claim_exception 回退为 pending 等待重试，不伪装为业务 skipped | `app/services/historical_rerun_service.py` |
| P2-1 | start_batch_async 原子预留 token | `app/services/historical_rerun_service.py` |
| P2-2 | lease 释放失败记录结构化错误日志 | `app/services/historical_rerun_service.py` |
| P2-3 | retry 新日志持久化 contract 状态；supersede 仅对仍为当前的旧日志执行；告警默认 suppress | `app/services/push_executor.py` |
| P2-4 | 对账输出 total_items/empty_key_count/qc_usable_count/dual_current_count；含正式业务身份 | `app/services/historical_rerun_service.py` |

### 测试

| 文件 | 状态 |
|------|------|
| `tests/test_009_remediation.py` | 通过（含 contract 当前可见门禁用例） |
| `tests/test_008_remediation.py` | 通过 |
| `python -m compileall app` | 通过 |

### 生产服务器操作（2026-07-30）

1. Oracle DDL：`CONTRACT_VALID` / `CONTRACT_ERRORS` 已存在  
2. 代码热更新 + 容器重启：Schema 自检通过，health alive  
3. **复核发现并已修**：
   - 默认当前结果过滤未排除 `contract_valid=0`（现已排除；存量无效结果已标记 `discarded`）
   - 6 月历史重跑 preview **ABORT**（`load_failed=4`，Oracle TNS 超时），**未创建批次**
   - 1～6 月 host 脚本在容器重启后 task `not_found` 无限轮询（脚本已改，断点续跑）

## 2. 当前生产状态（复核后）

- 服务器：`10.10.8.84:40022`，用户 `root`；密码从本地密钥库或 `MED_AUDIT_SSH_PASSWORD` 获取（**禁止写入文档**）
- 容器：`med-audit`，compose：`/opt/med-audit-docker/`
- 服务：`http://10.10.8.84:8000`
- Dify 节点池：5 节点 `qc-node-1`～`5`，策略 `round_robin`（与定时共用）
- 6 月批次（`/tmp/run_june_full.py`）：
  - 日志：`docker exec med-audit cat /tmp/june_full.log`
  - 结果文件 **不存在**（因 ABORT 未写 final）
  - 末状态：`Preview candidates=6719 load_failed=4` → **`ABORT: load_failed > 0`**
- 1～6 月 host 覆盖重推：`/tmp/h1_replace_push.sh`；断点约 **2026-02-13** 起续跑

## 3. 核查 AI 需要验证的事项

### 高优先级

1. **6 月批次状态**
   ```bash
   docker exec med-audit cat /tmp/june_full.log
   ```
   - 当前预期：`ABORT: load_failed > 0`（非 BATCH_STARTED）
   - 重试：缩小日期范围或错峰加载后再 preview

2. **批次 API（仅当成功 create 后）**
   ```bash
   curl -s -X POST http://localhost:8000/api/users/login -H "Content-Type: application/json" \
     -d '{"username":"<ADMIN_USER>","password":"<ADMIN_PASSWORD>"}'
   curl -s http://localhost:8000/api/push/historical-rerun/batches/<ID> -H "Authorization: Bearer <TOKEN>"
   curl -s http://localhost:8000/api/push/historical-rerun/batches/<ID>/reconciliation -H "Authorization: Bearer <TOKEN>"
   ```

3. **contract_valid 当前可见门禁**
   ```sql
   -- 业务当前不应出现 contract 失败且 success
   SELECT COUNT(*) FROM MED_PUSH_LOG
   WHERE CONTRACT_VALID = 0 AND SUPERSEDED_BY IS NULL AND STATUS = 'success';
   -- 预期：0（存量应已 discarded；新代码过滤器也排除）
   ```

4. **self-supersede**
   ```sql
   SELECT COUNT(*) FROM MED_PUSH_LOG WHERE SUPERSEDED_BY = ID;
   -- 预期：0
   ```

5. **discarded 状态**
   ```sql
   SELECT COUNT(*) FROM MED_PUSH_LOG WHERE STATUS = 'discarded';
   ```
   默认列表/统计应不可见。

### 中优先级

6. **Dify 契约错误抽检**  
   查 `CONTRACT_ERRORS`：`missing_dimensions` / `admission_dimensions_not_configured` 等。

7. **admission 维度配置**  
   仍依赖运行时 `expected_dimensions_override`；配置 UI 未必暴露 `dimension_codes`。

8. **Oracle Instant Client 11.2**  
   无连接池/call timeout；忙时 `ORA-12609` 仍是 P0 运维风险。

### 低优先级

9. 浏览器验收、preview 持久化分片、双 Session 并发压测。

## 4. 关键约束

- 不得修改 `SECRET_KEY` / `JWT_SECRET_KEY`
- uvicorn 单 worker
- 历史重跑默认 `alert_policy=suppress`
- discharge_final SQL 转换仅 3/6 类型有完整支持
- Oracle 空串 = NULL

## 5. 文件清单

```
app/services/result_contract_validator.py
app/models.py
app/database.py
app/dify_pusher.py
app/services/push_log_writer.py
app/services/push_log_supersede.py
app/services/historical_rerun_service.py
app/services/current_result_filter.py
app/services/scheduler_audit_runner.py
app/services/push_executor.py
app/routers/patient_qc.py
tests/test_009_remediation.py
tests/test_008_remediation.py
docs/ACTIVE/010_009_HANDOVER_VERIFICATION_GUIDE_20260730.md
docs/INDEX.md
```

## 6. 回滚

```bash
# 使用热更新前的镜像 tag 回滚（若已保留）
docker tag med-audit:<old_tag> med-audit:latest
cd /opt/med-audit-docker && docker-compose up -d
```

`CONTRACT_VALID`/`CONTRACT_ERRORS` 为 NULL 时按历史兼容处理。

## 7. 安全声明

- 文档/仓库 **禁止** 写入 SSH/管理员明文密码  
- 批量重跑默认 suppress 告警  
- 不得轮换生产 `SECRET_KEY`

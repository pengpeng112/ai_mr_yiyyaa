# 016 交接文档：015 完成后的状态与后续工作

> 文档编号：016  
> 日期：2026-08-08（Asia/Shanghai）  
> 性质：**交接与状态事实**，供后续 AI / 人工接手；本身不自动授权生产写操作、Dify 推送或历史补跑  
> 前置：015 整合整改已完成并热部署；011/P4 错误码已部署；轨 A 源失败标注已在本地落地  
> 分支：`fix/ora-12609-p4-error-code`（**大量未提交本地改动**，不仅是轨 A）

---

## 0. 一句话结论

| 问题 | 答案 |
| --- | --- |
| 015 开发计划做完了吗？ | **是**（A1–A4 / B1–B3 / C1 + 部署热修） |
| 病程护理 ORA-12609 解决了吗？ | **否**。011/P5 = **FAIL**；根治在 **012** |
| 交接 AI 该先干什么？ | 读 INDEX → 015 → 013 → 011 → 012 → 本文件；**不要重做 015**；问用户选轨 B/E 等 |
| 本地 git 干净吗？ | **否**。工作区相对 `51bb6d5` 有大量未提交修改；生产靠 docker 热更 + `docker commit`，与 git HEAD 不必一致 |

---

## 1. 对「别的 AI 交接提示词」的复核意见

整体质量：**可用，建议作为交接提示词底座**。下列为**必须修正**，否则交接 AI 会踩坑。

| # | 原提示词说法 | 复核结论 | 交接时应改为 |
| --- | --- | --- | --- |
| 1 | 分支「含未提交的轨 A 改动」 | **不完整**。未提交范围远大于轨 A，含 015 全套、C1 热修、`attach_success_push_log_as_current`、留存 L3、relay/scheduler 等 | 写清：「相对 `51bb6d5` 有大规模未提交改动；生产已热更部分代码，git 未 commit」 |
| 2 | 轨 A 在 `data_source_loader.py L827` | **行号略偏**。`_fetch_source_records` 调用约 L828；`[source=…]` 标注在约 **L838–L848** | 写「约 L838–L848 / 搜 `[source=`」，勿死钉 L827 |
| 3 | 011 force=True「后续应更新 011 文档」 | **文档已在 015/B1 订正**（S-08/A.7 已是 force=False + 禁止改回） | 改为「文档已改；代码 force=False；禁止再改回 True」 |
| 4 | 014 的 G4「PushLog 无唯一约束」/ 轨 D 仍写 S1 | **已过时**。C1 已建 **success 当前**唯一索引（生产 VALID） | 写「已有 success-only 唯一索引；014 G4 过时」 |
| 5 | 007 三处缺口 M1/M2/M3 | **015/B2 已改文档** | 写「007 文档已按 002 落地与 source_version 语义修订」 |
| 6 | 生产镜像 `82f2583cc2ed` | **本会话最后 commit 记录为** `5f7212ab8748`（及更早 `63cf83a9376c`）；ID 会变 | 写「以现场 `docker images med-audit:latest` 为准」 |
| 7 | 全量 906 passed | 可能随轨 A 增加；**会变** | 接手后重新 `pytest tests/ -q` 记数，勿写死 |
| 8 | 日产量异常「已诊断清楚无需大改」 | **本会话结论倾向**：多为 `unreviewed_pending` skip，**合理**；仍建议接手 AI 用生产 skip 分布**再确认一次**再关单 | 标「暂定结论，可只读复核」 |
| 9 | 生产日志打印 INSERT 含患者信息 | **可信为旧镜像/SQLAlchemy echo 或异常堆栈参数**；本地 `database.py` 默认 `echo=False` | 轨 E 重建镜像前，容器内核对 `echo`/异常日志路径；**勿在本地乱改 payload** |

**提示词中正确且必须保留的要点：**

- 015 禁止重做 A1–C1  
- C1 **success-only** + `attach_success_push_log_as_current`  
- 红线文件列表（payload / mr_txt / record_identity / fanout 关联）  
- 011/P5 = FAIL，根因指向 V_HLJL / 012  
- 011 `force=False` 不得改回 True  
- 轨 B 门禁：P0/P1 前禁止 P2 切换  
- 轨 D 强门禁  
- SSH 密码只用环境变量  

---

## 2. 已完成工作清单（按主题）

### 2.1 015 整合整改（本地 + 生产热部署 2026-08-08）

| ID | 内容 | 证据位置 |
| --- | --- | --- |
| A1 | fanout 复用 `_apply_query_timeout` | `data_source_loader.py`；`tests/test_data_source_loader_fanout.py` |
| A2 | 删除 `_daily_push_job` | `scheduler.py` 仅保留 v2 |
| A3 | historical_rerun `public_error_message` | `app/routers/historical_rerun.py` |
| A4 | relay 静默 except → warning | `relay_alert_service.py` `_log_swallowed` |
| B1 | 011 force=False 文档 | `docs/ACTIVE/011_*.md` S-08 / §6.2.7 |
| B2 | 007 文档与 002/source_version 对齐 | `docs/ACTIVE/007_*.md` |
| B3 | 116 high 复合门槛表述 | `docs/reference/116_*.md` |
| C1 | 多当前清理 + 唯一索引 | 生产 `MED_PUSH_LOG`；`scripts/remediate_pushlog_multi_current.py`；`database._ensure_push_log_current_identity_unique_index` |
| C1 热修 | 索引仅 `status=success`；`attach_success_push_log_as_current` | `push_log_supersede.py`；`bulk_push_executor` / `push_executor` |
| 额外 | 留存 L3 Oracle CLOB | `retention_service._sql_not_equal_text` |

### 2.2 011/P4 错误码（git HEAD `51bb6d5` 及后续热更）

- `classify_oracle_error` + 稳定错误码  
- `SchedulerHistory.error_code` 迁移与写入  
- 行为测试：12609 有限重试、非瞬态不重试  
- 生产曾见 `error_code=ORA_TNS_RECEIVE_TIMEOUT`

### 2.3 轨 A（诊断加固，本地已有代码）

- 源加载失败消息加 `[source={source_name}]`（`data_source_loader.py` 约 L838–L848）  
- `tests/test_oracle_error_code.py::TestSourceLoadFailureAnnotation`  
- **是否已打进当前生产镜像**：以容器内文件是否含 `[source=` 为准（热更后需再确认）

### 2.4 生产只读观察结论（2026-08-08）

| 项 | 结论 |
| --- | --- |
| 服务 | `med-audit` 可 healthy；`/api/health` up；调度器 running |
| C1 数据 | success 多当前组曾为 0；索引 VALID |
| 011/P5 | **FAIL**：`discharge_final` + `progress_vs_nursing` 连续 ORA-12609 |
| 其他出院类型 | 多数仍可 completed |
| daily progress tot 小 | 倾向正常 skip，非整类挂死 |
| 部署日 | 曾 `docker restart` 打断进行中的日调度 |

### 2.5 生产只读观察复核（2026-08-08 22:36，轨「观察」，脚本 `scripts/p5_readonly_observe.py`）

| 项 | 实测证据 |
| --- | --- |
| 生产镜像 | `5f7212ab8748`（2026-08-08 09:32 CST 构建），容器 Up 13h healthy，与 §1 #6 修正一致 |
| 轨 A `[source=` 是否进容器 | **是**（2026-08-08 22:50 热更：`docker cp` + 语法校验 + `docker commit`，新镜像 `20d1ba100ad6`；容器内备份 `data_source_loader.py.bak_20260808`）；**2026-08-09 13:23 已 `docker restart` 生效**：进程内确认 `NEW_CODE`，容器 healthy，调度器 running（当日 09:00 调度在重启前已完成，未被打断） |
| 72h ORA-12609 日志计数 | **16 次** |
| 调度器 | running；下次运行 2026-08-09 09:00 +08:00 |
| `progress_vs_nursing` daily_increment | 116 条 completed（最近 2026-08-08 09:00:02），日增量正常 |
| `progress_vs_nursing` discharge_final | 3 条 failed / `error_code=ORA_TNS_RECEIVE_TIMEOUT`（最近 2026-08-08 11:45）→ **P5 仍 FAIL**，根治仍依赖 012 |

---

## 3. 未完成 / 需继续做的工作

### 3.1 立即决策项（给用户）

1. **是否 git commit** 当前分支全部/分批本地改动（默认禁止 push，除非另授）  
2. **是否确认轨 A 已在生产容器**（若未，是否再热更一次）  
3. **下一轨选择**：B / E / 继续只读观察 / 其他  

### 3.2 轨 B — 012 双源（主根治，门禁严）

| 阶段 | 状态 | 交接 AI 可做 |
| --- | --- | --- |
| P0 配置冻结/乱码/键核查 | NOT_RUN | 只读方案与检查清单 |
| P1 DBA 15/16/17 执行计划 | NOT_RUN | 整理 SQL、验收指标；**推动 DBA** |
| P2 Adapter/flag | 本地草案已实现（2026-08-08，flag 默认 off） | — |
| P2 双源 Builder/切换码 | **已实现（2026-08-09，经用户批准）**：`progress_nursing_multi_source_builder` + `dual_source_loader` + loader 顶部增量分发；19 单测全绿 | **生产 flag/anchor SQL 未写入**，受 P1+P4 门禁约束 |
| P3–P7 | 未开始 | 禁止抢跑 |

冻结口径（不得重新开放）：三 `mr_class`、`caption_date_time`、572/709、护理双时间、原关联键。

### 3.3 轨 C — 日产量

- 状态：**暂定已解释**（unreviewed_pending）  
- 可选：生产只读 skip 分布复核后正式关单  

### 3.4 轨 D — 历史补跑

- **禁止**在 011/P5 未过、012 未评估前全量补跑  
- 需：日期/类型/科室/`alert_policy`/书面批准 + preview  

### 3.5 轨 E — 部署工程化与镜像

- 热更脚本模板化  
- **重建镜像**（减少 docker commit 漂移；处理日志是否泄露患者字段）  
- 升级冒烟清单  

### 3.6 011/P5 持续观察

- 目标：连续 ≥3 次同类型调度无 12609  
- 当前：**FAIL**  
- 根治不依赖再加超时，而依赖 **012 窄查询 / 数据源**  

---

## 4. 红线与不变量（交接必须遵守）

**禁止修改：**

- `payload_composer.py` / `payload_builder.py` 全部  
- `dify_pusher.py` 的 `mr_txt` 映射  
- `record_identity.py` 全部  
- `data_source_loader` 关联/分组/`_build_fanout_params`/fanout `setdefault` 文书字段（轨 A 仅允许失败消息标注）  
- 未批准的 `text_template` / 审计 SQL join  

**禁止操作：**

- 未批准 git push、生产全量补跑、危险 DDL、真实企微告警验证  
- 将密码/病历/患者标识写入 git 或现役文档  
- 把 `pool.close(force=False)` 改回 `force=True`  
- 回退 C1 success-only 唯一索引  

**命名：** builder 只用 `mr_text`。

---

## 5. 建议执行顺序（给下一任 AI）

```text
1) 读 docs/INDEX.md + 本 016 + 015/013/011/012 + AGENTS.md
2) git status / 关键文件 grep 自证，勿盲信旧报告行号
3) 问用户：提交 git？下一轨 B/E/观察？
4) 未指定时：只做只读盘点 + 011/P5 证据表更新
5) 用户批准后：轨 B 本地草案（flag 默认 off）或轨 E 镜像重建
6) 禁止在 12609 未根治前做轨 D 全量历史补跑
```

---

## 6. 011/P5 只读判定（可复制）

SSH：`10.10.8.84:40022` root；密码仅从环境变量 `MED_AUDIT_SSH_PASSWORD`。

容器内应用库（表名 Oracle 前缀）：

```sql
-- 近况：progress_vs_nursing
SELECT audit_run_mode, status, error_code, COUNT(*) AS cnt, MAX(run_time) AS last_rt
FROM MED_SCHEDULER_HISTORY
WHERE audit_type_code = 'progress_vs_nursing'
GROUP BY audit_run_mode, status, error_code
ORDER BY MAX(run_time) DESC;
```

```text
docker logs --since 72h med-audit 2>&1 | grep -c "ORA-12609" || true
```

**PASS 条件：** 连续 ≥3 次同类型（尤其 `discharge_final` + `progress_vs_nursing`）无 ORA-12609 / TNS 接收超时 / 整类 0 秒假成功掩盖。  
**当前：** FAIL（2026-08-08 22:36 复核：`discharge_final` 3 条 failed / `ORA_TNS_RECEIVE_TIMEOUT`，最近 2026-08-08 11:45；72h 日志 ORA-12609 共 16 次）。

若轨 A 已部署，失败消息可含 `[source=nursing]` 等标注。

---

## 7. 给下一任 AI 的精简提示词（修正版，可整段复制）

```text
你是 Med-Audit 交接执行 AI。工作目录：F:\python\前后端代码\ai_mrzk
分支：fix/ora-12609-p4-error-code（相对 51bb6d5 有大规模未提交改动；生产曾热更+docker commit，与 git 不一定一致）

必读顺序：
docs/INDEX.md
docs/ACTIVE/016_HANDOVER_AFTER_015_AND_NEXT_TRACKS_20260808.md   ← 本交接事实源
docs/ACTIVE/015_CONSOLIDATED_REMEDIATION_EXECUTION_PLAN_20260807.md  （已完成，禁止重做 A1–C1）
docs/ACTIVE/013_ACTIVE_PLAN_INVENTORY_AND_MANUAL_HANDOVER_20260806.md
docs/ACTIVE/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md
docs/ACTIVE/012_PROGRESS_NURSING_DUAL_VIEW_REVIEW_20260804.md
AGENTS.md

已完成：015 全套+部署；C1 success-only 唯一索引 + attach_success_push_log_as_current；
留存 L3 DBMS_LOB；011/P4 错误码；轨A [source=] 标注（本地；生产以容器文件为准）。
011 文档 force=False 已订正；代码 pool.close(force=False)，禁止改回 True。

未完成：011/P5=FAIL（discharge progress ORA-12609，根治靠012）；
012 P0–P7；历史补跑；镜像正规重建；git 提交整理。

红线：禁止改 payload_composer/payload_builder/dify_pusher 的 mr_txt 映射/record_identity/
data_source_loader 关联与 fanout 字段逻辑/text_template；builder 只用 mr_text。
禁止未批准生产补跑/危险DDL/git push；密码只用 MED_AUDIT_SSH_PASSWORD。

默认：先只读盘点并问用户选轨：
B=012本地草案(flag默认off，需批准才写切换码) /
E=部署脚本与镜像重建 /
观察=011/P5 只读证据表 /
提交=整理并 git commit（勿 push除非另授）。
未回答前不写业务代码。交付含：变更说明、文件清单、pytest、红线grep、不确定即停。
```

---

## 8. 文档维护

- 本文件为现役交接；完成后结论并入 011/012/INDEX，再归档  
- 新增/移动 `docs/**/*.md` 须同步更新 `docs/INDEX.md`

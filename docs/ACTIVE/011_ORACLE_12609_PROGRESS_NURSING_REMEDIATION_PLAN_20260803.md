# ORA-12609 病程与护理记录链路整改计划

> 文档编号：011  
> 编制日期：2026-08-03  
> 适用范围：生产 Med-Audit、Oracle 病程/护理查询、`progress_vs_nursing` 日常与 `discharge_final` 调度  
> 文档性质：分阶段执行计划，不等同于生产补跑授权  
> 当前状态：Oracle Instant Client 19c 与 P4 可靠性补丁已部署生产；等待日常和出院任务连续观察  

> 2026-08-03 生产升级记录：修复查询超时配置回退、ping/直连/科室查询超时保护、连接池非强制退役、`ORA-12609` 应用库瞬态分类、SchedulerHistory 运行模式与脱敏错误信息、运行总览模式归属及 SQLite/Oracle 索引迁移。容器已由新镜像 `sha256:82f2583cc2ed1e0a9ce38b51c32591798ac8942ff2ce099f2f75e1196175f7ca` 重建并验证 healthy、单 worker、Oracle Client 19.25；未触发历史补跑、手工推送、Dify 或真实告警。备份目录：`/opt/med-audit-docker/backups/20260803_204249_oracle_scheduler_fix`。O-01、O-03～O-07 仍保持开放，必须等待正常调度连续观察。

## 1. 目标、结论与边界

### 1.1 整改目标

1. 确认生产实际加载的是 Oracle Instant Client 19c，而不是宿主机或镜像内残留的 11.2 库。
2. 确认 `call_timeout`、连接池、陈旧连接重建和一次性查询重试真正作用于病程/护理查询。
3. 定位 `ORA-12609: TNS: receive timeout` 是网络/监听瞬断、连接池陈旧连接、单条 SQL 执行过慢，还是查询结果/CLOB 读取过慢。
4. 让病程/护理类型在查询超时、部分批失败或结果为空时明确记为失败或不可用，禁止被展示为“已完成”。
5. 在不产生重复 Dify 推送、重复告警和错误当前结果的前提下，恢复日常和出院任务；历史补推必须在观察门通过后另行执行。

### 1.2 对“是否需要升级驱动”的明确回答

需要升级，但升级不是完整解决方案。

- 生产原客户端为 11.2.0.4，`cx_Oracle` 在该版本下不支持连接池和可用的 `call_timeout`；应用配置的查询超时因此不能作为可靠保护。
- 已切换到 19c 后，运行时探针确认 `cx_Oracle.clientversion() = 19.25.0.0.0`，连接可以设置 `call_timeout=5000`，`SELECT 1 FROM DUAL` 成功。这一步是必要基础设施修复。
- `ORA-12609` 的含义是 TNS 接收超时，仍可能由慢 SQL、数据库服务器等待、监听/防火墙、CLOB 返回过大或连接池并发耗尽引起。不能因为版本显示为 19c 就认定业务已经恢复。
- 只有在 19c 下连续观察通过，并且 SQL 执行计划/耗时没有异常，才可以关闭本问题；否则必须继续 SQL、网络或连接池专项整改。

### 1.3 明确不做

- 观察期内不启动 2026 年 6 月历史补推、不执行全量重跑、不调用真实企微/H5 测试。
- 不修改患者、病历、护理原始数据，不删除历史 `PushLog`、告警或 Dify 响应。
- 不在日志、导出文件或外部复核包中记录患者 ID、住院号、姓名、病历正文或完整 CLOB；只记录脱敏哈希、数量、批次号和错误码。
- 不通过无条件增大超时、无限重试、提高连接池上限来掩盖 SQL 或网络问题。
- 不把部分成功的 bundle 当作完整成功；任一批最终失败时，`progress_vs_nursing` 本次运行必须 fail-closed。

## 2. 已知生产基线

| 项目 | 已知事实 | 证据/要求 |
| --- | --- | --- |
| 服务器 | `10.10.8.84:40022`，容器 `med-audit` | 只允许通过受控 SSH 访问，密码不得写入文档 |
| 应用库 | Oracle | `APP_DB_TYPE` 和运行时配置只读核对 |
| 原客户端 | Instant Client 11.2.0.4 | 升级前日志和镜像备份 |
| 当前客户端 | Instant Client 19c，19.25 | 容器内 `clientversion()` 探针 |
| Python 驱动 | `cx_Oracle==8.3.0` | 记录包版本和加载库路径 |
| 当前健康状态 | 容器 healthy，`/api/health` 正常 | 每个阶段都需复核 |
| worker | 必须保持单 worker | `docker inspect`/启动参数核对 |
| 错误 | `progress_vs_nursing` 出院任务曾出现 `ORA-12609` | SchedulerHistory 与容器日志交叉核对 |
| 已有代码保护 | 瞬态 Oracle 错误一次性完整重试、连接池重建、失败事务回滚 | `app/oracle_client.py` 和测试 |
| 当前待证实 | 查询级超时是否在所有 Oracle 路径生效、19c 后是否仍复现 | 本计划 P0-P5 |

### 2.1 本轮已经解决的问题

下表记录截至 2026-08-03 已执行并取得证据的整改。这里的“已解决”只表示对应技术缺陷已经修复，不代表 `ORA-12609` 整体问题已经关闭；另一位 AI 必须按“复核方法”重新查证。

| 编号 | 原问题 | 已落实的解决措施 | 当前证据 | 复核方法 |
| --- | --- | --- | --- | --- |
| S-01 | 生产实际加载 Oracle Instant Client 11.2，缺少可用的连接池和调用超时能力 | 将 `/opt/oracle` 与 `/opt/oracle/lib` 的 `libclntsh.so`、`libocci.so` 链接切换到 19c | 容器内 `cx_Oracle.clientversion()` 返回 `(19, 25, 0, 0, 0)` | 重启容器后检查 `clientversion`、`readlink -f` 和 `ldd`，确认未加载 11.2 |
| S-02 | 应用配置的查询超时在 11.2 客户端上实际不生效 | 19c 下启用连接对象 `call_timeout`；目前只在 `fetch_records()` 主查询路径的 `cursor.execute()` 前调用 `_apply_query_timeout()` | 生产探针可写入并读回 `call_timeout=5000`，`SELECT 1 FROM DUAL` 成功；**仅证明主病程/护理查询路径** | 使用应用同一连接配置重复探针，并同时记录 `config.json` 实际 `query_timeout_ms`/`statement_timeout_ms`；核对日志无 DPI-1050；其他 Oracle 调用点须按 O-02 复核 |
| S-03 | 旧客户端不支持应用设计的 Oracle SessionPool，连接可靠性保护无法落地 | 19c 客户端允许初始化 `cx_Oracle.SessionPool`；现有代码具备 acquire、ping、陈旧连接 drop 和重建逻辑 | `app/oracle_client.py::get_oracle_connection()` 已实现；19c 满足客户端版本门槛 | 在不打印密钥的前提下检查“连接池初始化成功”日志，并注入陈旧连接测试 |
| S-04 | `ORA-12609` 发生后单次主查询直接失败，瞬态故障没有有限恢复机会 | 将 `ORA-12609` 纳入瞬态错误分类；目前只在 `fetch_records()` 主查询和 `get_oracle_connection()` acquire 阶段关闭资源、重建连接池并完整重试一次 | `is_transient_oracle_error()`、`fetch_records()` 和 `test_fetch_records_retries_ora_12609_once`；**尚无“第二次仍失败、不递归重试”和“非瞬态错误不重试”行为测试** | 当前只能判 `PARTIAL`；P4 必须新增上述测试，并评估 V_QYBR 科室补全、census、relay 等其他 Oracle 路径是否需要统一重试封装 |
| S-05 | 后续重新构建 Docker 镜像可能再次把动态链接退回 11.2 | `Dockerfile` 默认创建指向 `libclntsh.so.19.1`、`libocci.so.19.1` 的链接，同时保留 11.2 文件供受控回滚 | 本地 `Dockerfile` 已修改 | 构建新镜像后在新容器重复 S-01，不以宿主机热链接作为验收 |
| S-06 | 升级过程缺少明确回滚点 | 升级前保留生产备份目录，并提交切换后的容器镜像 | 备份：`/opt/med-audit-docker/backups/20260803_084422_oracle19_switch`；新镜像：`sha256:a58254ede02dd26847cf819dce4f90f4943d604c7fdf801926663f0ab2462556` | 只读核对备份目录、镜像 ID 和创建时间；不得实际回滚健康生产 |
| S-07 | 升级后可能因重启方式产生重复调度 | 容器继续使用单 worker，重启后健康检查正常 | 容器为 healthy，`/api/health` 正常，Oracle 探针约 208ms | 核对启动参数只有 `--workers 1`，并检查同一调度不存在重复 SchedulerHistory |
| S-08 | 查询异常可能污染连接/事务并继续复用坏池 | 异常路径先 rollback，关闭 cursor/connection，再 `reset_oracle_pool()`；只允许一次内部重试 | `app/oracle_client.py::fetch_records()` 已实现 | 单元测试断言 close/rollback/reset 次数，生产日志核对没有连续重试风暴；`reset_oracle_pool()` 使用 `pool.close(force=False)`（见 A.7），不得改为 force=True |

### 2.2 与本问题相关、此前已经落实的保护

以下保护不是 19c 切换本身，但会直接影响病程护理恢复和补推安全，复核 AI 不应重复建设或回退：

1. 历史批次遇到 Oracle/Vastbase 加载失败时 `load_failed > 0`，preview 必须 ABORT，不能创建不完整批次。
2. Oracle 历史批次已修复 CLOB 绑定顺序和 `FOR UPDATE` claim 兼容问题；复核时以当前代码和 Oracle 行为测试为准。
3. 历史/终末新结果只有 `status=success + parse_status=success + contract_valid!=0` 才能成为当前结果或 supersede 旧结果。
4. `contract_valid=0`、fallback、parse_failed、discarded 结果保留审计，但不得当前可见、不得覆盖有效结果、不得生成新告警。
5. 日常和出院调度保留独立数据库 run lock，不能恢复为单一共享锁。
6. 历史补跑默认 `alert_policy=suppress`，不得通过真实企微/H5 告警验证驱动问题。
7. 病程/护理加载错误必须落 SchedulerHistory/批次错误，不得把查询异常解释为“当天 0 条数据”。

### 2.3 尚未解决或尚未证明解决的问题

以下事项仍保持开放状态，任何复核报告不得写成“已完成”：

| 编号 | 开放事项 | 当前状态 | 关闭标准 |
| --- | --- | --- | --- |
| O-01 | 19c 升级后 `progress_vs_nursing` 是否还会出现 `ORA-12609` | 待日常、出院及后续任务连续观察 | 连续 3 次同类型调度无 ORA-12609/查询超时/整类失败 |
| O-02 | `call_timeout` 是否覆盖所有 Oracle 查询调用点 | 目前只证明 `fetch_records()` 主路径和生产探针可用；`fetch_department_list`、`data_source_loader`、`patient_census_service`、`patient_dept_query`、`relay_alert_service`、`patient_visit_export_service` 等路径尚未统一设置 | 完成 P2 全调用点审计并补测试；无 `ping` 属性时的 `_ping_oracle_connection()` `SELECT 1` 兜底也必须在超时保护下执行 |
| O-03 | 病程/护理 SQL 是否因 `TO_CHAR`、视图展开、CLOB、排序或 JOIN 产生慢查询 | 尚未取得实际执行计划和分层耗时 | DBA 提供实际计划，分层实验和 p95 达标 |
| O-04 | 网络、监听、防火墙或 Oracle 服务端等待是否参与 ORA-12609 | 尚无同期服务端证据 | 应用错误时间线与 listener/alert/session wait 对齐并形成结论 |
| O-05 | 连接池在真实调度并发下是否耗尽或长期等待 | 代码已具备，生产负载尚未连续验证 | acquire 等待、池重建和超时指标在连续观察中正常 |
| O-06 | 2026 年 6 月病程/护理历史任务是否可以恢复 | 明确禁止执行，原批次因 `load_failed` ABORT | P5 通过后重新 preview，且 `load_failed_count=0`、manifest 完整并获书面批准 |
| O-07 | 09:00 日常和约 11:44 出院观察结果 | 尚待以 `/api/scheduler/status` 的实际 next_run 为准核查 | SchedulerHistory、PushLog、业务库计数和错误日志四方对账通过 |
| O-08 | 19c 热切换镜像、Dockerfile、compose 配置是否一致 | 生产热提交和本地 Dockerfile 已分别存在；尚未证明 `docker-compose.yml` 重建不会拉回旧镜像 | 复核 `docker inspect` 的 image ID/digest、compose `image`/build 配置、Dockerfile 和容器内库路径四方一致；否则 S-06/S-07 不得判 PASS |

### 2.4 独立复核判定规则

复核 AI 必须对 S-01～S-08、O-01～O-08 逐项给出以下四种判定之一：

- `PASS`：命令、代码和生产证据一致；
- `PARTIAL`：代码已具备但生产未验证，或生产已热修但新镜像重建未验证；
- `FAIL`：证据与声明矛盾、行为回归或仍复现；
- `NOT_RUN`：因权限、时间窗或安全边界未执行，必须写明原因。

不得仅根据 `/api/health`、一次 `SELECT 1`、存在 PushLog 或“当前日志无 ORA-12609”判定整体通过。复核报告至少附：镜像 ID、客户端/驱动版本、动态库路径、调度时间窗、聚合数量、错误关键词计数、测试命令和未执行项。

特别规定：仅进行本地代码/文件复核而未连接生产时，S-06、S-07 以及 O-08 中涉及生产镜像、容器健康和 compose 重建的结论必须标记为 `NOT_RUN`，不能用本地 Dockerfile 或历史文字记录替代 `docker inspect`、容器启动参数和生产运行时证据。

## 3. 执行总原则和停止点

每次只推进一个阶段，阶段末提交报告并停止。下阶段必须由系统负责人书面确认，或在同一条指令中明确批准多个阶段。

| 阶段 | 内容 | 是否写生产 | 停止条件 |
| --- | --- | --- | --- |
| P0 | 只读基线与任务冻结 | 否 | 基线不可复现、容器不健康或存在并发重跑时停止 |
| P1 | 19c/驱动/超时运行时验收 | 否 | 版本、库路径或超时探针失败时停止 |
| P2 | Oracle 连接池和查询调用路径审计 | 仅配置变更需批准 | 发现未设置超时、连接泄漏或重试风暴时停止 |
| P3 | SQL、执行计划、网络分层定位 | 否 | 无 SQL 计划或无法区分错误层级时停止 |
| P4 | 本地代码加固和回归 | 否 | 任何基线回归、全量测试失败时停止 |
| P5 | 生产 canary 与连续观察 | 仅正常调度产生业务结果 | 任一硬门不通过立即停止历史补跑 |
| P6 | 定向恢复/历史补跑 | 是，需单独批准 | preview、幂等、告警抑制或对账失败时禁止执行 |
| P7 | 验收、回滚演练和关闭问题 | 只读为主 | 对账不一致时保持问题开放 |

## 4. P0：生产只读基线与冻结

### 4.1 执行前检查

在本地和服务器分别记录 `git status`、镜像 ID、容器 ID、配置文件 SHA-256；不得清理他人修改。确认：

1. `med-audit` 为 healthy，应用仅一个 uvicorn worker。
2. `/api/health/live`、`/api/health/ready` 和深度 `/api/health` 的结果及延迟。
3. `scheduler_daily`、`scheduler_discharge` 的 enabled、audit types、`next_run`、`last_error`、诊断字段。
4. `daily_increment` 和 `discharge_final` 的数据库锁均为 idle；没有历史批次 consumer 正在运行。
5. 观察期间暂停手工补推和历史重跑脚本；保留现有日志，不轮换密钥。

### 4.2 推荐只读命令

以下命令仅示意，执行者必须隐藏密码和 token；所有输出只保留聚合信息。

```bash
ssh -p 40022 root@10.10.8.84
docker ps --filter name=med-audit --format '{{.Names}} {{.Status}} {{.Image}}'
docker inspect med-audit --format '{{json .Config.Cmd}} {{json .Config.Healthcheck}}'
curl -fsS http://127.0.0.1:8000/api/health/ready
curl -fsS http://127.0.0.1:8000/api/scheduler/status
docker logs --since 2h med-audit 2>&1 | \
  grep -Ei 'ORA-12609|TNS: receive timeout|推送漏斗|fanout_bundle_error|SchedulerHistory|progress_vs_nursing'
```

应用库只读统计必须包含：

- 每次运行、每个 `audit_type_code`、每种 `audit_run_mode` 的候选数、PushLog 数、`status`、`parse_status`、`contract_valid`、`skip_reason`；
- SchedulerHistory 的 started/finished/status/error_code/error_summary；
- `progress_vs_nursing` 日常和出院的运行时间、耗时、最慢批次（不含患者键）；
- 同期 Oracle 业务视图的去重 bundle 数，用于判断“0 条”是真无数据还是查询失败。

### 4.3 P0 交付物

生成 `run_id`、只读 JSON/CSV 聚合、命令清单和 SHA-256。报告必须写明：查询时间窗、是否有并发任务、失败错误码、未执行的操作。任何 `ORA-12609` 都记为 `load_failed` 或 `query_failed`，绝不能解释为候选数为 0。

## 5. P1：Oracle 19c 与驱动运行时验收

### 5.1 客户端加载核验

在容器内执行并保存不含密钥的输出：

```bash
docker exec med-audit python - <<'PY'
import cx_Oracle, os
print('clientversion=', cx_Oracle.clientversion())
print('module=', cx_Oracle.__file__)
print('ORACLE_HOME=', os.getenv('ORACLE_HOME'))
print('LD_LIBRARY_PATH=', os.getenv('LD_LIBRARY_PATH'))
PY
docker exec med-audit sh -lc 'readlink -f /opt/oracle/libclntsh.so; readlink -f /opt/oracle/lib/libclntsh.so; ldd $(python -c "import cx_Oracle,os; print(cx_Oracle.__file__)") | grep -i clntsh'
```

验收必须同时满足：

- `clientversion` 为 19.x（当前预期 19.25）；
- `/opt/oracle` 和 `/opt/oracle/lib` 的 `libclntsh.so`、`libocci.so` 均指向 19.x；
- `ldd` 没有加载 11.2 路径；
- 容器重启后结果一致，不能只在热切换后的单个进程中成立。

### 5.2 `call_timeout` 探针

用应用同一配置创建连接，在执行任何业务 SQL 前设置 5000ms，输出“属性是否存在、赋值是否成功、读取值、`SELECT 1` 延迟”。报告必须同时记录 `config/config.json` 中该数据源的实际 `query_timeout_ms`；若未配置，则记录 `_apply_query_timeout()` 回退使用的 `statement_timeout_ms` 或默认 60000ms。5 秒探针只是能力验证，不得被解释为生产查询的实际超时口径。不得打印连接串、用户名密码或患者数据。

如 DBA 允许且不会影响生产，可用最小的 `DBMS_LOCK.SLEEP(8)` 做一次受控超时探针；没有 `EXECUTE` 权限时不要修改权限，改在测试库完成。探针失败不代表业务 SQL 失败，但必须标为 P1 未通过。

### 5.3 驱动升级结论门

- 19c、`call_timeout`、连接探针全部通过：进入 P2/P3，不能直接宣布问题关闭。
- 仍是 11.2、出现 DPI-1047/DPI-1050 或超时属性赋值失败：停止业务观察，回滚到备份镜像或修复库链接。
- 19c 已加载但仍有 ORA-12609：保留升级成果，转 SQL/网络/连接池定位，不再重复升级驱动。

## 6. P2：连接池、超时和调用路径审计

### 6.1 代码路径盘点

逐一搜索 `get_oracle_connection` 的调用点，确认以下路径都在 `cursor.execute` 前调用 `_apply_query_timeout`：

- `progress_vs_nursing` 的 `fetch_records`；
- 患者枚举、科室查询、V_QYBR 科室补全、统计和健康探针；
- 调度锁、SchedulerHistory 和日志统计所用应用库连接（若为同一 Oracle）；
- 任何后台线程新建的 `SessionLocal` 或直连。

发现某条路径没有超时设置时，先补测试，再按 P4 修改；不能用“主查询已设置”替代全路径审计。

### 6.2 连接池参数审计

只依据实际并发和 Oracle DBA 限额确定 `pool_min/pool_max/pool_increment/pool_timeout_seconds/acquire_timeout_seconds`。初始建议是小池、单 worker、有限 Dify 并发，避免把数据库连接数打满；具体数值必须由连接数观测批准。

必须验证：

1. 每次 acquire 都 ping；陈旧连接 drop 后重新 acquire。
2. acquire 超时有明确错误码，不无限等待。
3. `ORA-12609`、`ORA-03113` 等瞬态错误最多完整重试一次；重试前关闭 cursor/connection 并重建池。
4. SQL 语法、权限、列不存在、绑定错误不得重试。
5. 递归 retry 配置只能由内部标记控制，不能被外部请求注入；日志记录 attempt、耗时和稳定错误码，不记录 SQL 参数中的患者信息。
6. 连接、cursor、事务在成功和异常路径均释放；单条失败不能污染批量 Session。
7. `reset_oracle_pool()` **实际调用** `pool.close(force=False)`（`app/oracle_client.py`，守护测试 `test_reset_oracle_pool_does_not_force_close`）。含义：仅使旧池退出全局使用，**不强制中断**其他线程已借出的在飞连接；旧连接在各自线程 `close` 后自行释放。若 close 因仍有在飞连接抛错，代码捕获后记 warning 并继续。**禁止**将此处“修复”为 `force=True`——那会中断 bulk push / census / relay / export 等并发在飞查询，引入新风险。
8. `_ping_oracle_connection()` 在连接对象没有 `ping` 属性时会执行 `SELECT 1 FROM DUAL`；该兜底查询本身必须继承 `call_timeout` 或具有独立超时保护，避免陈旧连接探测反而长时间挂起。

### 6.3 连接池观测指标

至少记录：活跃/空闲连接数、acquire 等待、连接重建次数、query timeout 次数、ORA-12609 次数、重试成功/失败次数、查询 p50/p95/p99。若当前驱动无法提供池指标，增加仅聚合计数的应用指标，不记录连接凭据。

## 7. P3：病程/护理 SQL 与网络分层定位

### 7.1 先确认实际数据源

`progress_vs_nursing` 可能走 Oracle legacy SQL，也可能走 Vastbase 多源配置。执行者必须从运行日志、审计类型配置快照和 loader 入口确认本次错误发生在哪个数据源；不能把 Vastbase `statement_timeout` 与 Oracle `ORA-12609` 混为一谈。

### 7.2 Oracle SQL 分层实验

在只读窗口、脱敏日期和小科室范围下，依次测量：

1. 仅查询患者键/日期的基表计数；
2. 加入病程表但不取 CLOB；
3. 加入护理表但不取 CLOB；
4. 完整双方 JOIN 和字段列表；
5. 完整查询的 fetch/逐行读取耗时。

每步记录 SQL hash、绑定参数类型、返回行数、执行耗时和 Oracle 错误码，不记录原始文本。用 `DBMS_XPLAN.DISPLAY_CURSOR` 或 DBA 批准的 `EXPLAIN PLAN` 获取实际计划，重点检查：

- `TO_CHAR(日期列, 'yyyy-mm-dd') = :query_date` 是否导致索引失效；
- 患者 ID+次数 JOIN 是否发生隐式类型转换；
- 视图展开后是否全表扫描；
- CLOB 列是否在数据库端排序、重复 JOIN 或一次性返回过大；
- 日期/科室过滤是否在最早节点生效。

### 7.3 SQL 优化候选（仅测试，不直接上线）

按以下顺序对比，保持结果语义和字段映射不变：

1. 将日期等值函数改为半开区间绑定：`>= :date_from AND < :date_to`，避免对日期列套 `TO_CHAR`；
2. 先取得双方文书的患者键和时间，再按键回取有限字段；
3. 对病程、护理拆成两条受控查询，在应用层按 `patient_id + visit_number + date` 合并；
4. 评估 CLOB 分段读取或最大字符数，但任何截断必须在 payload 中标注，且须经临床确认；
5. 只有 DBA 根据计划和写入窗口批准后，才可创建或调整索引。

禁止仅把 60 秒改成 300 秒来“解决”问题。若 SQL 在 60 秒内无法稳定完成，应保留失败状态并继续优化。

### 7.4 网络/监听分层

由 DBA/网络人员在同一时间窗提供 listener、数据库 alert、会话等待和防火墙空闲连接策略。应用侧只做 TCP/Oracle 连接延迟探针和错误时间线对齐，不修改服务器网络参数。若只有高并发时出现错误，优先检查连接数、进程数和中间设备 idle timeout。

## 8. P4：应用可靠性整改

### 8.1 查询与任务状态

1. 统一使用稳定错误码：`ORA_TNS_RECEIVE_TIMEOUT`、`ORACLE_QUERY_TIMEOUT`、`ORACLE_CONNECTION_RESET`、`ORACLE_SQL_OR_SCHEMA` 等。
2. `SchedulerHistory` 必须记录 `audit_run_mode`、错误码和脱敏短摘要；类型在生成 PushLog 前失败也必须可见。
3. 一批失败时丢弃内存中的部分结果，禁止生成当前可用的部分 PushLog；preview/历史批次 `load_failed > 0` 必须 fail-closed。
4. 日常与出院使用独立 run lock；不得因一次重试重新获取另一任务的锁。
5. 健康检查优先使用 `/api/health/live`；深度 Oracle 检查增加最小间隔或仅由 readiness/运维触发，避免监控制造连接压力。

### 8.2 测试要求

必须新增或补齐行为测试，而不是只检查源码字符串：

- `ORA-12609` 首次失败、重建连接池、第二次成功；
- 第二次仍失败时只产生一次明确失败，不递归重试；
- SQL/权限/列错误不重试；
- `call_timeout` 可赋值和旧客户端赋值失败的兼容行为；
- 连接/cursor 在异常、超时、CLOB 读取异常后关闭；
- 多批查询第二批失败时无部分结果提交；
- SchedulerHistory 在类型级失败时为 failed/partial，不出现伪成功；
- 既有 `pushed_flag/reviewed_flag/manual_override/skip_reason`、contract 门禁、supersede 和告警抑制回归。

本地验证至少执行：

```powershell
python -m pytest tests/test_oracle_client.py tests/test_oracle_pool_recovery.py -q
python -m pytest tests/test_008_remediation.py tests/test_009_remediation.py -q
python -m pytest
python -m compileall app tests scripts
python scripts/check_naming_convention.py
```

## 9. P5：生产 canary 与连续观察

### 9.1 观察前门禁

只有 P0-P4 报告通过，且容器 healthy、单 worker、19c 探针通过、没有历史批次运行时，才进入 canary。观察期间禁止六月补推和任意手工全量推送。

### 9.2 观察批次

以 `/api/scheduler/status` 的真实 `next_run` 为准。当前记录的观察点为：

1. 09:00 左右的 `daily_increment / progress_vs_nursing`；
2. 11:44 左右的 `discharge_final / progress_vs_nursing`；
3. 后续至少再观察两次同类型正常调度，覆盖不同业务量。

每个观察点分别在任务结束后立即、+30 分钟、+120 分钟读取：SchedulerHistory、PushLog 聚合、容器日志和 Oracle 错误计数。不要只看“有 PushLog”。

### 9.3 通过标准

推荐硬门：

- 连续 3 次同类型调度无 `ORA-12609`、`ORACLE_QUERY_TIMEOUT`、`fanout_bundle_error`；
- 任何类型级失败均在 SchedulerHistory 可见，不能出现“失败但总览成功”；
- 实际候选数与业务库只读计数一致；若为 0，必须有业务库计数证据；
- 无部分结果、无重复当前结果、无 self-supersede、无重复告警；
- query p95 小于配置超时，并且连接池没有持续 acquire 等待或耗尽；
- `parse_success`、`contract_valid` 和 `qc_usable` 口径对账一致；
- 日常和出院锁互不误伤，两个任务不会互相静默跳过。

任一硬门失败，停止后续 canary 和历史补跑，回到 P2/P3；不得通过延长等待或手工删除失败记录来“达标”。

## 10. P6：定向恢复与历史补跑

### 10.1 进入条件

仅当 P5 连续观察通过，且医院负责人书面批准具体日期、类型、批次和告警策略后执行。优先恢复未完成的单日/单类型任务，再考虑 1–6 月历史补跑。

### 10.2 执行顺序

1. 只读 preview：按日期、`progress_vs_nursing`、run mode 生成 manifest；校验 `load_failed_count=0`、候选哈希和完整性。
2. 小批 canary：建议 20–50 条 bundle，`alert_policy=suppress`，确认 Dify 不产生真实企微/H5 外发。
3. 批次扩容：每批不超过已压测安全上限；每批结束回查成功、解析、契约、跳过和失败原因。
4. 日期扩展：前一日期完整对账通过后，才进入下一日期；不得跨日并发抢占同一锁。
5. 终末优先：`discharge_final` 只有 `qc_usable` 结果才可 supersede daily；fallback/parse_failed/contract_invalid 只保留审计，不覆盖当前结果。

### 10.3 回滚准备

执行前保存旧镜像、配置和数据库 schema/批次快照；每批记录 run_id、manifest hash、before/after 计数。任何数量不一致、重复当前或告警异常立即停止，不执行宽范围 UPDATE。

## 11. P7：最终验收和问题关闭

最终报告必须包含：

1. 19c 客户端版本、动态库真实路径、驱动版本和 `call_timeout` 探针结果；
2. ORA-12609 按日期、任务、错误层级的发生次数和重试结果；
3. SQL 版本/SQL hash、执行计划摘要、p50/p95/p99、返回行数和最慢批次；
4. 候选、PushLog、解析、契约、质控可用、告警六层对账；
5. 失败、跳过、部分成功和业务库无数据的区分；
6. 未修改表、未发送告警、未外发患者数据的声明；
7. 回滚演练结果和剩余风险。

问题关闭条件：P5 硬门全部通过、P6（如执行）批次对账通过、连续 3 次正常调度无 ORA-12609，且 DBA 对 SQL/网络结论签字。否则状态保持“观察中”或“需 SQL/网络专项整改”。

## 12. 回滚方案

### 12.1 客户端回滚

仅在 19c 导致启动失败、DPI 错误或兼容性回归时执行。先停止调度并确认无查询，再恢复备份目录中的库链接/旧镜像，重启后复核健康和 `clientversion`。不得在线替换正在使用的动态库。

### 12.2 代码/配置回滚

使用升级前镜像 tag 和配置备份恢复；保留 `PushLog`、SchedulerHistory、错误日志，不删除失败事实。回滚后仍需跑一次只读探针和单次 canary，不能直接恢复历史补推。

### 12.3 数据回滚

本计划默认不修改业务原始数据。若后续批准了历史结果写入，必须使用批次 before 快照按 ID 精确反向恢复；禁止按日期或严重度宽范围回滚。

## 13. 交付报告模板

每个阶段都按以下格式交付：

```text
阶段/P编号：
run_id：
执行时间（含时区）：
服务器/容器/镜像：
实际执行命令（已脱敏）：
查询范围：
候选/批次/返回行数：
成功/失败/跳过/解析/契约/告警聚合：
ORA-12609 次数及错误层级：
修改文件或配置：无/列明路径与原因
数据库写入：无/列明批准批次
备份与 SHA-256：
测试证据：
停止点结论：
下一阶段所需批准：
```

## 14. 交给其他 AI 的执行提示词

```text
你是 Med-Audit 生产整改实施 AI。工作目录：F:\python\前后端代码\ai_mrzk。
请先阅读 AGENTS.md、docs/INDEX.md、docs/reference/101_FEATURE_BASELINE.md、
docs/skills/med-audit-codex.md、docs/ACTIVE/008_PROGRESS_NURSING_HISTORICAL_RERUN_AND_LOG_DETAIL_REMEDIATION_PLAN_20260729.md、
docs/ACTIVE/009_008_IMPLEMENTATION_INDEPENDENT_REVIEW_AND_REMEDIATION_PLAN_20260729.md、
docs/ACTIVE/010_009_HANDOVER_VERIFICATION_GUIDE_20260730.md 和本文件。

目标：处理 Oracle ORA-12609 对 progress_vs_nursing 病程/护理查询的影响。

硬性边界：
1. 先做 P0 只读基线；一次只推进一个阶段，到停止点必须汇报并等待批准。
2. 生产服务器是 10.10.8.84:40022，容器 med-audit；不在文档、日志、输出中写入密码、token、患者 ID、姓名、住院号或病历正文。
3. Oracle Instant Client 19c 已切换且探针显示 19.25；不要重复升级，先验证重启后动态库路径和 call_timeout。
4. 观察期间禁止六月历史补推、全量重跑、真实企微/H5 测试和宽范围数据库 UPDATE。
5. ORA-12609 只能有限重试一次；SQL/权限/字段错误不得重试；任一批最终失败必须 fail-closed，不能提交部分结果。
6. 必须区分 Oracle ORA-12609 与 Vastbase statement_timeout，先确认实际数据源和调用入口。
7. 任何 SQL 优化先取得执行计划/耗时证据；不要仅提高 timeout。涉及索引、网络参数或生产 DDL 必须交 DBA/负责人批准。
8. 保持单 worker、独立 daily/discharge run lock、Dify 输入 mr_txt 字符串、contract_valid 门禁、skip_reason 和告警历史不变。

执行顺序：P0 -> P1 -> P2 -> P3 -> P4 -> P5；P6 历史补跑需新的书面批准。
每阶段按本文第 13 节模板报告，附命令、聚合指标、错误码、SHA-256、测试结果和下一步批准事项。

开始执行前，先按本文 2.1～2.4 对 S-01～S-08 和 O-01～O-08 逐项输出 PASS/PARTIAL/FAIL/NOT_RUN；发现任何声明与实际不一致时，以生产只读证据和当前可执行代码为准，并停止进入下一阶段。
```

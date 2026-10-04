# 056 — JHEMR FILEVERIFY 目标库勘误与接手续办说明

> 日期：2026-09-24（Asia/Shanghai）  
> 状态：**旧 179 Oracle 执行方案冻结；177 Vastbase 只读复核待做；生产零写入**  
> 接续入口：055 §0.5；本文件给下一位 AI 解释误判来源和当前边界。
>
> **现状勘误（2026-09-28，057/G1 追加；不改写下述历史正文）**：上行"177 Vastbase 只读复核待做"是本文件 2026-09-24 编制时状态。现时以 §6.5（2026-09-24 晚 ZCode/GLM-5.3 接手复核，v3/v4 哈希、方言断言、执行器安全闸、SQLite 演练、177 只读 P0 现时重跑全绿零漂移）与 §6.6（2026-09-25 Codex 执行器提交前校验补强）为准：**只读复核已完成**；第一批 177 写入仍待用户明确批准，第二批激活未批；`SECRET_KEY` 漂移已由 055 §0.4-5 记录的 2026-09-27 修复收口。归属说明：§6.5 会话在《开发起步包/01_统一修改记录.md》2026-09-24 行登记；§6.6 未见 01 独立登记行，其内容与 `review/jhemr-fileverify-056/exec-log.md` 相互印证，按文档自述保留，本勘误不代前任补写登记。

## 1. 结论

`10.10.8.179` 是嘉和 Web/接口应用服务器，**不是 EMR 客户端使用的主数据库**。其本机 Oracle 连接属于 S4 JHWebInterface 接口库。客户端经 `10.10.8.178` 中间件读取的 EMR 主库是 `10.10.8.177:5432/jhemr` Vastbase/openGauss。`ODS`（既有资料指向 `10.10.8.216` 的 Oracle 视图族）是另一业务查询域，不能替代 `jhemr.jhmr_file_cum_fileverify` 目标表。

因此 054/055 以“179 Oracle 主库”为前提的 P0、v3 SQL 包和执行驱动器均**不可继续执行**。旧第一批批准的目标写明 179 Oracle，不能自动视为已批准在 177 Vastbase 插入。四行第一批、第二批激活、J09–J12 均未执行。

## 2. 误判从哪里来

| 时间与材料 | 当时说法或更正 | 本次判定 |
| --- | --- | --- |
| 嘉和工作区旧 `docs/S4-嘉和通用接口/24-嘉和通用接口分析.md` | 从 179 本机 `web.config` 的 Oracle 连接串推断“EMR 主库在 179” | 该连接实际属于 S4 接口服务，不能代表 EMR 客户端主链 |
| 本仓 027（2026-08-27） | 引用旧 docs/24，把 179 称主库、177 称只读副本 | 本仓错误源头 |
| 本仓 029 文件头（2026-08-28） | **用户已纠正**：179 是应用服务器，EMR 数据库只有 177:5432，申请 179:1521 的方案作废 | 优先于 027 的旧假设；后续文档漏读 |
| 嘉和工作区 `docs/通用-环境与连接/26-系统与数据库映射.md` §5（2026-08-31）与 `31-178中间件机登录与授权.md` §7 | 178 活跃服务配置均指向 177:5432/jhemr；177 `pg_is_in_recovery()=False`，可写非流复制；179 Oracle 是 S4 接口库 | 独立实证再次否定“179 EMR 主库” |
| 本仓 052 round-7、053、054、055（2026-09-21 起） | 又把 177 称演练副本、179 称生产 Oracle 主库 | 已作废事实被层层复制，是本次执行阻塞的真正原因 |

053/T2 曾在 177 查到 `jhemr.jhmr_file_cum_fileverify` 20 列、当时 2 条停用历史行和无 `CHECK_TYPE=4`；那是**旧时点只读证据**，不得推断现值。仓库 `config/config.json` 的 `emr_vastbase` 段也指向 177:5432、`jhemr.v_blws`。用户提供的账号口令不写入本报告。

## 3. 本次操作与状态

- 8.84→179 ping 和 8080 可达，所测数据库端口拒绝连接；这只描述 179 网络状态，**现在不再作为本任务数据库阻塞条件**。
- 已在 027、031、052、053、054 末尾追加事实勘误；055 顶部和 §0.5 标明冻结，`docs/INDEX.md` 更新状态。历史正文不改写。
- `review/jhemr-fileverify-055/execute_t0_t1.py`（gitignored）在线阶段 `p0/snapshot/insert` 已加拒绝执行闸；`insert --commit` 离线调用验证为 `FATAL`，未连接数据库。v3 包原始字节和 SHA-256 保留，仅作历史证据，不修改原包。
- **零生产写入、零 Git 写入、零 177 数据库会话**。本次没有使用用户给出的口令登录 177，也没有修改 ODS/179/178。
- 2026-09-24 两次 full 门禁随会话切换中断，目录 `review/gate-runs/20260924-213455/` 和 `20260924-214237/` 无完整 `summary.md`；**不能宣称 full 通过**。本次终态 quick 4/4 PASS（`review/gate-runs/20260924-215411/summary.md`）；由于旧执行器加了安全闸，接手后仍须按 `med-audit-gates` 重跑终态 full。
- 生产 compose `SECRET_KEY` 漂移是独立事故，055 §0.4 已记录；本次未修复，仍需独立生产配置写授权。

## 4. 下一位 AI 的安全续跑顺序

1. 按仓库启动顺序和 `med-audit-oneshot-delivery` 技能接管，保留全部未提交改动；先读 029 文件头、嘉和工作区 026 §5/031 §7、055 §0.5 和本文件。
2. 只读确认 177:5432 数据库身份、`jhemr.jhmr_file_cum_fileverify` 表当前四目标 ID、历史行、20 列、长度语义、医院码及中文往返；用 PostgreSQL/Vastbase 客户端，不运行旧 Oracle P0。必要时只读核对 178 客户端服务确实读取同一库。ODS 只作为另一路业务查询源核对。
3. 在本地将 v3 候选 SQL/事务脚本改为 Vastbase 方言，核对函数、日期、转义、列元数据、字节长度、客户端模板占位符和中文谓词；先在隔离环境做完整回滚演练。原 v3 哈希冻结，不原地改写。
4. 形成新的审批包：明确 **177:5432/jhemr**、四个固定 ID、预计四行且全部 `ENABLE=0`、写前快照/哈希、提交前逐字符读回、异常回滚和 J09 验收方式。取得覆盖 177 目标的明确批准后才写入。第二批 R1–R3 激活、R4、DELETE、客户端改动均不在该批准内。
5. 完成终态门禁、`docs/INDEX.md` 与统一修改记录，准确区分第一批/第二批/J09/三工作日观察结果。

## 5. 交接红线

不要再申请“打通 84→179:1521”作为 FILEVERIFY 前置，也不要将 ODS 或 216 应用库当作 EMR 配置表。不要把 053 的旧时点 2 行当作当前生产现状。不要执行 `review/jhemr-l2-20260921/t4_v3_executable_package_20260923.sql` 或旧 `execute_t0_t1.py` 的在线阶段。**177 的写入须重新审批。**

## 6. 2026-09-24 续跑进展与新目标审批材料（Codex）

### 6.1 177 现时只读 P0

通过 178 `jhdbservice/config/dataservice.yaml` 的**活跃**连接配置在内存中取得连接参数，实际查询经 84 容器只读会话到达 177；未把口令写入脚本、文档或输出。Med-Audit 的 `aizk_user` 可以连接 177，但对目标表和 `pat_visit` 无 SELECT 权限，因此不能作为本任务 P0 账号；以下结果来自客户端实际使用的 `jhemr` 账号。会话设置 `default_transaction_read_only=on`，只执行 SELECT、无 ANALYZE 的 EXPLAIN 及事务内 SAVEPOINT，最后 ROLLBACK。

| 门禁 | 2026-09-24 现时结果 |
| --- | --- |
| 身份 | `current_database=jhemr`、`session_user=jhemr`、服务器 `10.10.8.177:5432`、`pg_is_in_recovery()=false`、PG 兼容报版 9.2.4 |
| 本院码 | `jhemr.pat_visit` 仅 `49557032X`，计 121552 行 |
| 四个固定 ID | `20260922AIQC01`–`04` 均不存在，合计 0 行 |
| 现存配置 | `CHECK_TYPE=1, ENABLE=0` 一行；`CHECK_TYPE=2, ENABLE=0` 一行；无 `CHECK_TYPE=4` |
| 目标 schema | 恰 20 列；`id varchar(75)`、`setting_sql varchar(1500)`、`tipmessge varchar(150)`、`catalog_code varchar(15)`、`hospital_no varchar(45)`；另两日期列为 `oradate`，其余列名/类型见只读脚本输出。Vastbase 实际物理列顺序与旧 Oracle 包不同，INSERT 明列不受顺序影响 |
| 中文/方言 | “质控提醒、出院记录、入出院记录”往返逐字一致；`coalesce`、`current_date` 日期差及 `CURRENT_TIMESTAMP::oradate` 探针通过 |

证据复现：`review/jhemr-fileverify-056/read_only_p0.py`（gitignored）；脚本不打印患者行或凭据。现时 P0 只说明**查询时点**，真正写入前必须在同一账号/目标重跑并比对。

### 6.2 v4 候选包与验证

- 原 v3 保持冻结，原始字节 SHA-256=`2c0f8a3e43671c2f97d802d29178fbad9ee7e0b5b0e50271f60a5914c0b18a7c`。新候选由 `review/jhemr-fileverify-056/build_v4_candidate.py` 从该哈希锚自动生成，结果 `review/jhemr-fileverify-056/v4_vastbase_candidate.json`，原始字节 SHA-256=`0cccc27361002aa3ae7b180e69ad002ae81579ef7ebd0a7fb6377d8bb209e84f`。保留四 ID、全部 `CHECK_TYPE=4/TIP_TYPE=1/ENABLE=0/HOSPITAL_NO=49557032X`、原提示语与 `PILOT-PENDING` 门控；R4 恒停用。
- 方言变更：数字列 `delete_flag` 与 `mr_doctor_part_status` 使用数字比较；`nvl` 改 `coalesce`；R3 `trunc(sysdate)-trunc(oradate)` 改 `current_date - discharge_date_time::date`；`operation_type` 实测为 varchar，R4 改与 `'0'` 比较；外层两个 `SYSDATE` 改 `CURRENT_TIMESTAMP::oradate`。四条规则 `SETTING_SQL` 字符数为 269/342/258/350，均小于 1500；提示语长度 33/33/30/32，均小于 150。其余业务谓词沿用 v3。
- 177 的只读 `EXPLAIN`：四条规则及四条 INSERT 均 4/4 PASS（**没有执行 INSERT**）；`review/jhemr-fileverify-056/rehearse_in_memory.py` 在隔离 SQLite 内存表完成 4/4 INSERT、读回比较与 ROLLBACK 后 0 行。该内存演练验证事务/读回机制，不能等同 Vastbase 实际写入验证；Vastbase 语法由只读 EXPLAIN 覆盖。
- 受控执行器 `review/jhemr-fileverify-056/execute_v4.py` 已备：目标硬锁定 177:5432/jhemr、候选 SHA 锚、写前 P0 与全表快照 SHA、同事务 4 行 rowcount=1、提交前逐字段读回、异常 ROLLBACK、提交后新只读会话复核。`insert` 入口要求 `--commit` 和明确批准引用；脚本当前**未运行在线写阶段**。不含 DELETE、激活或 R4 启用路径。

### 6.3 待用户审阅的第一批批准范围

拟议动作：在 `10.10.8.177:5432/jhemr` 的 `jhemr.jhmr_file_cum_fileverify` **仅插入** `20260922AIQC01`–`04` 四行，全部 `ENABLE=0`，使用上列 v4 候选 SHA。执行前复跑 §6.1 六项 P0，导出全表快照并记录行数/SHA；单连接单事务插入，四次 rowcount 均须为 1，提交前逐字段读回和总行数 `原值+4` 必须一致，否则 ROLLBACK；提交后新只读连接复核。已提交后的删除不在范围，发生异常停机报告。第一批不包括 R1–R3 激活、R4 激活、试点科室配置、客户端改动或生产密钥修复；第二批仍须独立授权和预检。

**截至本节写入：第一批仍未获 177 目标写入批准，也没有任何 177 INSERT/UPDATE/DELETE；J09–J12 与连续三个工作日观察均未开始。** Git 未写。门禁终态见 §6.4 与统一修改记录。

### 6.4 交接待办

1. 本地复核候选 JSON、执行器及 §6.3 精确范围；取得用户覆盖 177 目标与四 ID 的明确批准后，才可在具备 psycopg2 的现场通道用运行时环境变量执行 `execute_v4.py`。凭据不写文件。
2. 写入前重跑 P0、快照/哈希，写后读回并登记；J09 现场验收与第二批各自按新目标重新核准，不能沿用旧 179 批准。
3. `SECRET_KEY` 漂移按 055 §0.4 独立处置，FILEVERIFY 查询通过不代表调度/推送恢复。

### 6.5 接手复核完成（2026-09-24 晚，ZCode/GLM-5.3；零生产写、零 Git 写）

§6.4-1 的本地复核已全部完成：v3/v4 原始字节哈希复核 MATCH；v4 四条 INSERT 的头/中/尾结构断言、方言标记（coalesce/`::date`/`operation_type='0'`/`CURRENT_TIMESTAMP::oradate`×2）、PILOT-PENDING 门控、字符数 269/342/258/350 与 33/33/30/32 独立复检 PASS；`rehearse_in_memory.py` 复跑 4/4+回滚 0 行；`execute_v4.py` 代码审查 PASS（目标硬锁/哈希锚/双闸/无 DELETE）；旧 `execute_t0_t1.py` 冻结闸确认。**现时重跑 §6.1 只读 P0 全绿零漂移**（四 ID 仍 0 行、历史仍 (1,0,1)/(2,0,1)、20 列一致、本院码唯一 121558 行、中文往返 True、referenced_columns 实测印证全部方言决策、EXPLAIN 8/8 PASS；仅 pat_visit 自然增长 6 行）。本地无 psycopg2——写入主体定为 84 容器内执行。证据：`review/jhemr-fileverify-056/exec-log.md`。**当前唯一阻塞=用户对 §6.3 范围的明确批准**（及 SECRET_KEY 修复的独立授权）。另记：§6.1–6.2 的 177 P0+v4 构建会话未在 01 统一修改记录单独登记，归属以本文件 §6 为准，本节补记。

### 6.6 执行器提交前校验补强（2026-09-25，Codex；零生产写）

独立审查发现原 `execute_v4.py` 在只读 P0/快照后另开写连接时仅复查目标 ID=0，且提示语读回只校验字符数。现已补为：写事务内重新执行完整 P0，要求登录账号为客户端实用 `jhemr`、目标地址精确等于 177:5432，并要求写事务表总行数与快照一致；写入前再次验证快照文件 SHA-256；提交前与提交后均按冻结 v3 原文的四条提示语 SHA-256 校验完整文本（同时保留字符数和规则 SQL 逐字符校验）。v4 候选 JSON 原始字节与 `0cccc273…` 哈希**未变**，四 ID/业务规则/ENABLE=0/审批范围均未变。

本地验证：`py_compile` PASS；隔离 SQLite 演练 4/4 读回且 ROLLBACK 后 0 行；使用假连接测试读回，原文通过、同长度提示语篡改被拒绝；四条提示语 SHA 与冻结 v3 原文独立比对一致。本机 `psycopg2` 模块文件存在但底层 DLL 导入失败，不能在本机运行在线阶段；原定 84 容器执行路径不变。**截至此节仍未进行 177 写入，也未获得 §6.3 新目标写入批准。**

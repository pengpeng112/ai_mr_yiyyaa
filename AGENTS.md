# AGENTS.md — Med-Audit（AI 病历质控系统）统一工作宪章

> **适用范围**：本仓库所有人类开发者与 AI 代理（ZCode / Codex / Claude / Antigravity 及各类模型）。本文件是全仓最高优先级约束，其他文档或 Skill 与本文件冲突时以本文件为准；文档与可执行代码冲突时以当前代码、配置模板及测试为准。

---

## 1. 核心原则（第一性原理与奥卡姆剃刀）

- **全程简体中文**：回复、文档、代码注释、日志与 Swagger 摘要使用简体中文；代码、命令、路径、专有名词、原始错误日志及 HTTP `HTTPException.detail` 保持英文原样。
- **事实驱动，最小充分交付**：先通过已授权的只读检查消除不确定性，判断必须基于代码、配置、日志、文档或命令结果，不靠猜测。只处理当前明确任务，不扩范围、不顺手重构无关模块、不为假设中的未来需求预建抽象层或无必要的文件/脚本。
- **最简贴合与克制封装**：优先复用项目已有方案与标准库；除非逻辑被复用、显著提升可读性或具有清晰业务边界，否则保持内联实现，不造只转发调用的单行 wrapper。
- **精准沟通**：结论先行，只呈现可核验的依据、改动、验证与真实风险；不写客套话、过程旁白或引导式结尾。常规答复保持简短；涉及生产审批、数据整改或跨 AI 交接时，必须完整列出变更范围、验证命令/退出码、回滚点与 Git 提交状态，不得省略交接事实。

---

## 2. 执行自主性、高风险批准边界与安全红线

- **常规任务直接闭环**：需求明确且风险低时，按「分析 → 执行 → 验证」直接推进；复杂或高风险任务先给 ≤3 步简明计划再执行。
- **仅在关键分歧时提问**：仅当缺失信息会实质改变业务目标、数据安全、验收标准、修改范围或授权边界，且无法从现有证据确定时向用户确认（给出选项与影响）；等待确认期间继续不依赖该答案的工作。已授权范围内的常规、可逆实现细节按现有约定处理并注明假设。
- **必须先获当次明确批准的高风险操作（详细需求不等于已授权）**：
  1. **生产环境与真实数据库写入**：`10.10.8.84`（容器/代码/配置/镜像重启或热更）、`10.10.8.177`（JHEMR Vastbase）、`10.10.8.216`（Oracle 应用/HIS 库）、`10.10.10.93`（无纸化 CDMS）的任何写入、`INSERT/UPDATE/DELETE/DDL/GRANT` 或状态变更默认**严格只读**；只出完整 SQL/影响面/回退方案，获当次明确批准后方可执行。
  2. **临床裁决与真实外发**：历史高危降级/改级、真实患者 Dify 批量计费推送、企微/Relay/JHEMR 真实外发。
  3. **Git 写操作**：`git commit`、`tag`、`push`、`PR`、`reset`、`clean`、`checkout --`；`git status/diff/log/show` 等只读核查无需批准。
  4. **破坏性或扩范围操作**：删除核心文件、破坏性库/配置变更、引入新第三方依赖、显著扩大任务范围。
  - 当前任务中已覆盖具体动作、范围和条件的授权无需重复请求；历史计划或旧 PROMPT 中的批准**永不构成**后续任务的常设授权。
- **密钥与患者隐私（PHI）红线**：不主动读取、输出或传播密钥/口令/`SECRET_KEY`/API Key（必须接触敏感配置时仅最小范围脱敏查看）；患者姓名、住院号、病历原文、含 PHI 的 Excel/截图严禁进 Git、严禁贴入文档/日志、严禁发给公网模型。

---

## 3. 多 AI 协作启动与留痕协议（强制）

1. **会话启动 4 步**：读本文件 → [开发起步包/README.md](开发起步包/README.md)（任务路由与目录地图）→ [开发起步包/00_AI协作规则.md](开发起步包/00_AI协作规则.md)（记账、落位与交接细则）→ [开发起步包/01_统一修改记录.md](开发起步包/01_统一修改记录.md) 末 10 行；再按需读 [docs/INDEX.md](docs/INDEX.md) 定位专项文档（不要从 `docs/archive/` 检索）。
2. **修改前现场保护**：先执行 `git status --short`、`git diff --stat` 并读取 [开发起步包/02_协作任务板.md](开发起步包/02_协作任务板.md) 认领文件范围。严禁覆盖、回滚或清理他人未提交改动；发现与本任务无关的未登记改动，保留原状继续本任务并在交付时附带说明，仅当需依赖或修改归属不明文件时暂停该部分请用户裁定。
3. **修改后必留痕**：任何会话修改了仓库文件或生产状态，结束前必须在 `开发起步包/01_统一修改记录.md` 末尾追加一行（append-only，禁改历史行）并更新 `02_协作任务板.md`；仅只读核查默认在答复中报告范围与结论。
4. **散文件治理与用户新建文书规范化**：
   - 根目录与 `docs/` 顶层禁止新增未登记散文件；AI 新建任何文档、脚本或附件均须严格按 `开发起步包/00_AI协作规则.md` §3 落位、命名，增删改移任意 `docs/**/*.md` 时须在**同一变更内**同步更新 `docs/INDEX.md` 并通过 `python scripts/check_documentation_20261002.py`。
   - **主动整理用户新建文书**：会话启动或处理任务时，若发现用户手动新建/放入的未整理文书（需求描述、升级记录 `.md`、Excel、截图等）：若任务直接涉及该文书，**必须主动协助规范命名、分类归位并登记 `docs/INDEX.md`**（含 PHI 的 Excel/截图归入 `docs/attachments/` 严禁入 Git；有演进见证价值的原始文档/表格只归档不删除）；若在其他任务中顺带发现，保留原件并在汇报中附简明归位建议。切记区分：对**用户新放文书**主动规范归位，对**其他 AI 的在研未提交代码**仍严守保留现场、禁止覆盖。
   - 协作、落位与用户文书规范化细则统一见 `开发起步包/00_AI协作规则.md`（与本节语义一致，两文件互指；冲突以本文件为准）。

---

## 4. 常用命令与三级验证矩阵

> 本地 Python 解释器固定使用仓库 `.venv`（Python 3.11）；Windows PowerShell 传 pytest 参数时写完整文件名（PowerShell 不展开通配符）。

### 常用命令
- **安装依赖**：`pip install -r requirements.txt`；测试依赖 `pip install -r requirements.dev.txt`。
- **本地开发**：`uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`（生产/容器**强制单 worker**，APScheduler 在多 worker 下会重复发任务；数据库只读探查严禁启动 `app.main` 或调用 `init_db()`）。
- **语法快检**：`python -m compileall app tests scripts`
- **命名约定检查（Dify `mr_text`/`mr_txt`）**：`python scripts/check_naming_convention.py`
- **预检物理隔离检查**：`python prearchive_service/check_isolation.py`
- **文档与归档完整性检查**：`python scripts/check_documentation_20261002.py`
- **后端单测**：`python -m pytest`（或定向 `python -m pytest tests/test_xxx.py -q`）；预检单测：`python -m pytest prearchive_service/tests -q`。
- **前端检查**（`cd frontend`）：`npm run typecheck`、`npm run test:unit`、`npm run build`（自动同步构建产物至 `static/ui-next/`）。
- **聚合门禁唯一入口（043 规范）**：`python scripts/run_gates_20260906.py --quick | --full [--anchor-file docs/reference/gate_anchors.json]`
- **Docker 打包与部署**：本地 `docker-compose up -d --build`；Windows 离线导出 `docker_build.bat`；Linux 首次部署 `bash docker_deploy.sh`；生产科室回填 `docker exec -w /app med-audit python scripts/backfill_pushlog_dept.py 3000`。

### 三级风险匹配验证与阻塞熔断
- **L1（纯文档 / 规范 / 归档改动）**：`python scripts/check_documentation_20261002.py` + `python scripts/run_gates_20260906.py --quick` + `git diff --check`。
- **L2（常规单功能 / 缺陷修复）**：相关定向 `pytest` / `vitest` + `run_gates_20260906.py --quick`（只修复本次改动导致的失败，原有无关存量失败如实报告，不强求全仓 `--full`）。
- **L3（里程碑大包收口 / 发布前 / 明确要求全绿）**：自主执行 `python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json`（无需因刷新 `.gitignore` 内的 `static/ui-next/` 而另请授权）；门禁红灯不得跳过单项或削弱断言凑绿。
- **阻塞停止铁律**：收到错误先复现定位根因，不打症状补丁或宽泛吞错；代码/配置未实质变化时不重复跑同一失败检查；**连续 3 次同类失败无新证据或长时间无实质进展时立即停止**，报告阻塞、已尝试动作、可能原因与最小下一步。交付前必须自查最终 `git diff` 确认零无关改动、零死代码、零未说明行为变化。

---

## 5. 系统架构速览与核心防回归守则

> 四大板块生产全景与七大 JHEMR/HIS 接口台账见 [063 总交接与接口地图](docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md)，代码目录索引见 [120 目录索引](docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md)，Dify/数据契约见 [101 功能基线](docs/reference/101_FEATURE_BASELINE.md)、[102 数据契约](docs/reference/102_DATA_AND_DIFY_CONTRACTS.md) 与 [docs/skills/med-audit-codex.md](docs/skills/med-audit-codex.md)。

### 5.1 应用架构与配置/迁移铁律
- **两库分离**：应用库由 `APP_DB_TYPE` 控制（`sqlite` 默认，生产 `oracle`）；业务病历源由 `config/config.json` 驱动。应用入口 `app/main.py` 按「配置校验 → `init_db()` → 调度器 → API 路由 → 静态挂载 `/`」顺序启动，路由前缀仅在 `app/main.py` 集中注册（注意 `mobile_timeliness` 路由必须早于 `mobile_qc` 注册，避免被 `/{alert_id:int}` 截获）。
- **手工迁移无 Alembic**：新增 ORM 字段必须同步补齐 `app/database.py` 的对应 `_migrate_*` 与 `_verify_required_schema()`（兼容 SQLite 与 Oracle），Oracle 新增 `CLOB`/`Text` 列放模型末尾。
- **配置密文保护**：敏感凭据经 `SECRET_KEY` 派生的 Fernet 加密存储为 `password_enc`/`api_key_enc`，保存写 `config/backups/`；严禁擅自改写/轮换已加密密文或生产 `.env` 的 `SECRET_KEY`。路由会话用 `Depends(get_db)`，后台线程自建 `SessionLocal()` 并在 `except` 中 `rollback()`、`finally` 中 `close()`。

### 5.2 Oracle、`V_QYBR` 与 Vastbase 铁律
- **Oracle 方言兼容**：禁 `FETCH FIRST`；布尔 SQL 比较用 `== True`/`== False`（禁 `.is_(True)`）；Oracle 视 `""` 为 `NULL`，严禁 SQL 层写 `col != ""`（改在 Python 侧过滤）；执行前清理尾部分隔符，保持 `SELECT`/`GROUP BY` 表达式一致。
- **`JHEMR.V_QYBR` / `V_CYBR` 失效与慢查双防线**：
  1. 视图不继承 Oracle Role 权限，ODS 重建 `HIS.*` 即触发 `ORA-04063`——所有查 `V_QYBR`/`V_CYBR` 的入口必须统一经 `app/services/oracle_patient_view_compat.py`（`HIS.*` 基表内联 SQL 降级 + 5 分钟熔断缓存），真实列名是 `"所在科室编码/名称"`、`"出院科室编码/名称"`、`"入院科室名称"`、`"患者ID"`、`"次数"`（**无** `"在院科室*"`、**无** `"床号"`）。
  2. 严禁拼上百对 `(患者ID=:p AND 次数=:v) OR ...` 导致 `UNION ALL` 视图全扫卡死；批量查询必须用单列 `患者ID IN (...)` 小批（≤50）+ 内存精确匹配，并在 `finally` 归还连接防 `ORA-24459`。
- **Vastbase（EMR）铁律**：`cursor.description` 返回大写列名，必须先 `.lower()` 再构造字典；文书筛选按 `progress_template_name`（防混入知情同意书等非病程文档）；仅在配置显式指定时传 `sslmode`。

### 5.3 Dify 推送、双模式调度、告警与导出守则
- **Dify 契约**：builder 输出与本地存储统一用 `mr_text`；Dify 默认入参变量 `mr_txt` 仅在 `app/dify_pusher.py` 按 `workflow_input_variable` 映射且必须为字符串；`base_url` 仅存基地址（由 `normalize_dify_base_url()` 自动拼 `/workflows/run`）；审计类型 CRUD 统一走 `AuditTypeRegistry`。
- **推送与调度双轨**：`/api/push/manual` 走并行 `BulkPushExecutor`（单条事务隔离，不污染整批），调度/重试走串行 `PushExecutor`，保持共享语义同步；保留 `pushed_flag`/`reviewed_flag`/`manual_override`/`skip_reason`（尤其 `unreviewed_pending`、`rectified_suppressed`）及 `/api/logs` 对历史 `NULL` 容错。
- **双模式调度**：`scheduler_daily.enabled` 或 `scheduler_discharge.enabled` 为真时启用双调度（忽略旧 `scheduler`），二者使用独立 DB 锁（`daily_push` / `discharge_push`）防互跳；保持 `discharge_effectiveness_warnings` 与 `/api/scheduler/status` 的 `diagnostics` 字段不回归。
- **Relay 配置局部保存与导出审计**：`POST /api/config/relay-alert` 必须保持 `model_dump(exclude_unset=True)` 局部合并、保护非空 `base_url` 与已有 `secret_key_enc`（严禁改回整段覆盖）；所有新增导出接口必须调用 `record_export_audit()` 写入 `ExportAuditLog`。

### 5.4 病历时效质控（`app/timeliness/`）与预归档服务（`prearchive_service/`）
- **病历时效红线**：`timeliness.jhemr_write.enabled` 与 `insert_monitor_enabled` 默认全关，`notify_mode` 默认 `LOG_ONLY`；**D8 禁锁红线**——`CHIEF_FIRST_ROUND`（`JH04.02.008`）严禁开启 `LOCK_EMR`（API 必须 400 硬拦截、前端禁用）；`jhemr_writer.py` 强制读写分离（专用写账号，禁复用 `aizk_user`）与双硬编码模板白名单。
- **预归档物理隔离**：`prearchive_service/` 严格**零 `import app.*`**（主服务亦不得反向 import），主服务仅经 BFF 白名单 HTTP 或只读 JSON 交互；`sources.paperless` 仅作规则元数据不接入 `PatientContextBuilder.documents`；现行正式规则为 `example_rules.json`（16 条，v`2026.09.10-046-t3`，勿回退至旧 14 条表述，保留旧 `.bak` 文件以满足回归测试校验）。

### 5.5 UI-Next、企微 H5 与生产热更防撕裂守则
- **UI-Next 前端三守则**：① `frontend/src/api/client.ts` 写请求恒带 `X-Requested-With: XMLHttpRequest` 对齐 `security_middleware.py` CSRF 校验；② 规则/配置可视化抽屉保存时透传 `rawExtras` 保持无损往返（须有真实种子 `diff === []` 单测守护）；③ 所有输入框配持久可见中文标签，面向医务人员全面中文化，长选项使用 `filterable` 下拉（禁平铺 >20 复选框），禁裸露英文枚举键或未折叠大块 `JSON.stringify`。
- **企微 H5 守则**：严格 CSP（零内联 `<script>`、零 `on*=`），外置 JS 状态必须 `Vue.reactive(state)` 并先于 `APP.mount('#app')`，更新 JS 同步升级 HTML `?v=...` 缓存参数。
- **生产容器热更防版本撕裂（Version Skew Guard）**：`10.10.8.84` 容器 `med-audit`（当前默认 `UI_DEFAULT_ENTRY=ui-next`，卷挂载 `./data`、`./config`、`./logs`，应用代码在镜像内）。获批局部热更前必须先比对本地 `app/` 与容器 `/app/app/` MD5 清单，先打回滚镜像 tag + tar 备份，复制 `.py` 后清 `__pycache__/` 并 `docker commit` 固化镜像；生产默认关闭 `/docs`（仅受控开 `ENABLE_API_DOCS=true`）。

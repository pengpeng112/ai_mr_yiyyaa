# 041 — 规则中心隔离环境可用性闭环一次性执行计划

> 文档编号：041 ｜ 编制：2026-09-04 ｜ 编制者：Grok 4.6
> 版本：**v1.1**（同日独立核查修订：签名链路断点、seed 角色实名、读端点无权限依赖、白名单 20 条、T8 改为状态更新）
> 性质：**从属 023 的一次性本地作业书**，不构成生产写入授权，不构成 UI 默认入口切换，不构成 EMR/HIS/医保正式对接。
> 上游事实：037 已执行（交付=038）、039 已执行（交付=040，生产框架已部署但全开关关闭）。
> 完成定义：按本文一次性做完全部必修包，门禁全绿，交付报告写入 `docs/ACTIVE/042`。
> 配套提示词：`开发起步包/PROMPT-20260904_规则中心隔离可用性一次性执行.md`

把本文全文交给执行 AI 即可开工。

---

## 0. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-09-04 | 初稿 |
| v1.1 | 2026-09-04 | 对照代码+040 独立核查后修订。P1：T3 扩为权限双修（BFF 签名 `User.permissions` 不存在导致 sidecar 全员 403；9 个读端点现状即无 `require_permission`）。T4 矩阵改为 seed 实名 admin/auditor/dept_manager/clinician。P2：ALLOWED_TARGETS=20；T6 failedApi 对 502/503 定口径；T1 脚本补编排与 HMAC `--check`。T8 改为核对更新（起草时 INDEX/023 已写一半）。T2 只认 `DEMO_MODE`；T7 复用 `auth._resolve_runtime_environment`；显式禁止改 `database.py` 的 `_ensure_default_rbac_permissions`。 |

## 0.1 用户需求与本轮为什么选这条线

用户原话：「我有一个一次免费使用并会话一次的 ai，你分析下当前系统 我需要改进哪些地方？帮我生成个详细计划，我让这个免费使用的 ai 一次性帮我执行」。

**当前系统不是“缺一个大功能”，而是“主链路已在跑、新能力停在框架层、现场项等人工”。**
一次会话的免费 AI 最容易失败的方式是：把 023 剩余现场项、004C 多源规则引擎、生产预检开闸、UI Next 切默认入口塞进同一轮。

本轮只做一件能在**本机隔离环境一次做完、用户能点开看见、测试能锁住**的事：

> 把 039 已经部署的「归档前规则中心」从“生产 503 / 演示点不动”变成“隔离 demo 里完整可点：列表→校验→试运行→审批→发布→diff→模式横幅”；修掉 BFF 权限空实现、读端点无权限依赖、以及 **BFF→sidecar 签名头权限来源断裂**（不修则 T5/T6 全员 403）。

---

## 1. 系统现状（执行 AI 禁止再当新发现重做）

### 1.1 已经完成、不要重做

| 轨道 | 状态 | 证据 |
|---|---|---|
| 六类 AI 质控主链路 | 生产在跑 | 调度 daily 09:00 + discharge 11:44；Registry/Builder/Dify/Relay/H5 已部署 |
| oneshot 缺陷修复 037 | 本地+已随 039 带上生产 | 038；配置 merge、census 400、H5 CSRF、SQLite busy_timeout 等 |
| 无纸化规则中心 039 | 代码+六表 DDL 已生产 | 040；`latest=0ff639fb78e0`；回滚 tag `rollback-pre-039-20260902` |
| 预检采集器/规则 JSON | 本地完成、规则 14 条已授权 | 032/034；`example_rules.json` v`2026.08.29-qc-authorized-v1` |
| UI Next 本地 WP0–WP5 | 本地完成 | 017/018/019；生产默认仍是 legacy `/` |
| 035 配置安全/统计口径 | 生产已热更 | 036；C2 乱码已修、RP1 允许双发已拍板 |

### 1.2 工作区事实（2026-09-04）

- 分支：`fix/ora-12609-p4-error-code`，相对 origin **ahead 16**。
- **037+039 全部代码仍在工作区未 commit**（040 写明用户当次授权不含 git 提交）。执行 AI **不得** `git checkout --` 丢这些改动，也 **不得** 自行 commit/push。
- 门禁锚（040）：主服务 **1272 passed** / prearchive **270 passed + 1 skip** / unit **54** / e2e **52 passed + 17 skipped**。
- 生产：容器 `med-audit`，BFF **未启用**（503 feature-disabled），预检**进程未启动**（036-RP7 轨道），`rule_registry.mode=file`，`result_delivery.enabled=false`，`insurance_qc.enabled=false`。

### 1.3 真正还缺什么（按能否一次会话做完分类）

**甲类：一次会话可做完（本计划必修）**

1. 规则中心在隔离 demo 无法端到端点：主服务 BFF 默认关；demo compose 没有预检 sidecar；SQLite 规则仓未作为 demo 默认。
2. **读端点现状即无权限依赖（不是假设风险）。** `prearchive_admin.py` 中 settings / list_rules / versions / dry-run / diff / outbox / fields / audit / delivery-logs **共 9 个**只挂 `Depends(get_current_user)`。BFF 一旦启用，任何登录用户都能读规则、审计、Outbox。写端点有 `require_permission`，但 `_proxy` 里 `current_user_has_permission()` **恒返回 True**，Depends 漏挂即越权。
3. **BFF→sidecar 签名链路对真实 User 必然 403。** `prearchive_admin_client._headers` 用 `getattr(actor, "permissions", [])`（client.py:93）。`User` ORM（`app/models.py`）只有 `role_id`，没有 `permissions` 属性；权限须 `get_user_permissions(user_id, db)`（`app/permissions.py:92`）另查。真实请求时 `X-Actor-Permissions` 恒为空串，HMAC 仍能对上空串（所以不是 401），sidecar `_authenticated_actor` 因 `actor.has(PERM_VIEW)` 失败对 **admin 也 403**。不修则 T5/T6 卡死。
4. demo seed 角色实名是 **admin / auditor / dept_manager / clinician**（`seed.py:50-53`），六权限目前只给 admin。缺四角色正反矩阵测试。禁止发明 `qc` / `department` 角色名。
5. `report_token.py` 生产门禁只读 `APP_ENV`，不读 `ENVIRONMENT`（023 P1-01 残留）。
6. INDEX「多源规则引擎 / 041 待执行」等陈述已由起草会话写过一半；本轮 T8 只做**状态更新**，不重写。

**乙类：有价值但本轮禁止（要批准/现场/外部依赖）**

| 项 | 为什么一轮做不完 / 不能交给免费 AI |
|---|---|
| 生产启动预检进程 + compare 7 天（036-RP7 / 040 B4） | 要 W9 开闸、生产 config.json、影子阈值、书面批准 |
| EMR/HIS 真实 destination（G2/G3/G4） | URL/认证/字段/ACK 未到 |
| 医保正式判定 / OpenDRG（G5/G6） | 年度规则包、LICENSE 未核验 |
| UI Next 生产 canary / 切默认入口（017 WP6/WP7） | 缺四角色凭据、测试科室、023 §9.1 批准单 |
| 六类 Dify 影子回放 + 临床抽检（023 P0-08） | 要 Dify 控制台导入与临床双审 |
| 历史 high 降级 / 科室回填（023 WP7） | 要脱敏包 + 精确 ID 清单 + 书面批准 |
| 004C 主服务多源规则引擎（023 WP8） | 产品立项未批；与 039 预检规则中心不是同一件事 |
| W10 系统推送规则、心电采集器、C# 助手试点机 | 用户/信息科材料未到 |
| Relay 真实患者实发 | 023 D6 仅批准测试接收人 |

**丙类：文档过时，本轮只改陈述、不改生产事实**

- INDEX 041 行从「待执行」改为「已执行，交付=042」；功能状态表只更新执行状态。
- 023 §0.6 的 041 行从待执行改为已执行（不改 023 为新入口）。

---

## 2. 本轮纪律（违反任一条=执行作废）

1. **零生产访问、零生产写入。** 不 SSH `10.10.8.84`，不改生产 `config.json`，不 docker commit，不启生产预检进程，不设生产 `PREARCHIVE_ADMIN_*`。
2. 不改 `config/config.json` 业务值；不改 `prearchive_service/rules/example_rules.json` 与 `system_push_rules.json` 的规则正文（14 条 FID / 空通道保持原样）。允许新增 **demo 专用** 配置副本，路径必须在 `config/demo/` 或 `prearchive_service/config.demo.json`。
3. 不切换 `UI_DEFAULT_ENTRY`；不删 `static/` legacy；不把 Hash 路由改 History。
4. 不实施 004C、不改 Dify workflow、不改 `dify_pusher.py` / `push_executor.py` / `bulk_push_executor.py` / `scheduler.py` / `relay_alert_service.py` 的推送语义。
5. 不启用 `result_delivery.enabled`、不启用 `insurance_qc.enabled`、不设 `opendrg.license_verified=true`。demo 里 destination 只许 `mock` + 本机回环。
6. prearchive **继续零 `import app.*`**；主服务继续不 import `prearchive_service` 包（只允许 HTTP BFF / 读 JSON 文件，与现状一致）。
7. 既有测试禁改凑绿。基线计数只增不减：主 ≥1272、prearchive ≥270+1skip、unit ≥54、e2e 0 failed（oneshot 默认 skip 保持）。
8. HTTPException `detail` 英文；注释/日志/Swagger 中文。
9. 用户未要求不 `git commit` / 不 push。结束只准备提交说明，等用户批准。
10. 改任何 `docs/**/*.md` 必须同步 `docs/INDEX.md`；结束前追加 `开发起步包/01_统一修改记录.md`。
11. PHI 不进仓库、不进测试 fixture、不进文档正文。demo 只用 022 合成患者或既有 TEST 工号。
12. 动手前记录 `git status`、HEAD、diff stat。他人已有改动（037/039 工作区）全部保留。
13. **禁止修改 `app/database.py` 的 `_ensure_default_rbac_permissions`。** 该函数每次 `init_db()` 都跑，改 `role_permissions_map` 会在下次生产重启时自动写 Oracle。非 admin 的规则中心权限只许写进 `app/demo_support/seed.py`（仅 demo）。

---

## 3. 已裁定事实（禁止再争论）

1. 039/040 的「框架部署完成 ≠ 正式对接」。本轮目标是 **隔离可用性**，不是生产 B4/B5/B6。
2. T3 是 **权限双修**：(a) `current_user_has_permission` 真实现且 9 个读端点补 `Depends(require_permission(PERM_VIEW))`；(b) `_proxy` 经 `get_db` 调用 `get_user_permissions(user.id, db)`，把权限列表交给 client 签名。两边都要真。不得只修 (a) 留下 sidecar 403。
3. 读端点收紧是 **契约变化**：BFF 启用后，无 `prearchive_rule_view` 的登录用户从“能读”变为 403。042 与 101 必须登记。
4. demo 启用 BFF **只认 `demo_mode_enabled()`（即 `DEMO_MODE`）**，不要用 `TEST_ISOLATED_MODE` 做或条件（大量单测 fixture 会意外注入）。显式优先落实为 **`PREARCHIVE_ADMIN_ENABLED` 键已在 `os.environ` 中则不注入**（`key in os.environ`，不是真值判断）。
5. T4 角色名锁死为 seed 实名：`admin` / `auditor` / `dept_manager` / `clinician`。禁止新建 `qc` / `department`。矩阵见 §5 T4，不再为角色名问用户。
6. `ALLOWED_TARGETS` 现为 **20** 条。本轮不新增白名单路径。断言写「与常量一致且长度为 20」，不要写 21。
7. 预检 sidecar 默认 `push.enabled=false`；真实源全部 `enabled=false`。
8. 004C 与 039 是两条产品线。本轮文档只更新状态，不把 004C 实现混进来。
9. T7 **import 复用** `app.auth._resolve_runtime_environment`，禁止再抄一套别名/冲突逻辑。

---

## 4. 执行顺序（按包，红则停）

```
T0 基线冻结
 → T1 预检 sidecar + demo 配置 + HMAC --check + 编排入口
 → T2 仅 DEMO_MODE 注入 BFF（显式 env 键优先）
 → T3 权限双修（读端点 + current_user_has_permission + 签名权限装载）
 → T4 四角色×六权限矩阵（seed 实名）
 → T5 规则仓导入 + 生命周期 HTTP（签名头必须带权限）
 → T6 Legacy + UI Next 规则中心 E2E（failedApi 口径 + 编排）
 → T7 report_token 复用 _resolve_runtime_environment
 → T8 文档状态更新（不重写已写内容）
 → T9 门禁 + 042 交付报告 + 01 登记
```

每包：实现 → 该包新测试绿 → 写 checkpoint 到 `review/exec-log.md`（review/ 不入库）→ 下一包。
连续两包红且根因不在本文范围 → 停，问用户。

---

## 5. 任务包规格

### T0 — 基线冻结

**做：**

1. 记录 HEAD、`git status --short`、`git diff --stat`。确认 037/039 工作区文件在。
2. 复跑门禁数字，写入 042 的「执行前基线」表。若基线已经红，**先报告用户，禁止在红基线上叠新功能**。
3. 允许修改清单=本文 §6。清单外文件只许改测试/文档/demo 配置。

**验收：** 042 含基线表；未丢工作区文件。

### T1 — 预检 sidecar、demo 配置、探测与编排

**目标：** 一条命令在本机拉起预检管理 API（只绑 127.0.0.1），fixture 源、sqlite 结果库+规则六表、admin_api 开启、推送关闭；`--check` 用完整 HMAC 探测；另提供编排入口给 T6。

**做：**

1. 新增 demo 配置：`prearchive_service/config.demo.json`（可提交）。要求：
   - 所有 host=`127.0.0.1`；真实业务源全部 `enabled: false`。
   - `sources` 走既有 fixture 网关（与 `tests` 相同假源，虚构 TEST 患者）。
   - `result_store.type=sqlite`，路径 `data/demo/prearchive_result.db`（gitignore 已覆盖 `data/`）。
   - `admin_api.enabled=true`，token/signing_secret 用**明显假值**（如 `demo-admin-token` / `demo-admin-signing-secret`），注释写明仅隔离 demo。
   - `api.port=18600`（避开 8600 与 18080-18082）。
   - `rule_registry.mode=file` 默认；提供注释说明如何切 `compare`。
   - `result_delivery.enabled=false`，`insurance_qc.enabled=false`，`push.enabled=false`。
   - `service.anchor_mode` 可 `paperless_rpa`（fixture 下安全）；不要连生产 CDMS。
2. 新增启动脚本：`scripts/run_prearchive_demo_sidecar_20260904.py`
   - 从仓库根运行；加载 `prearchive_service/config.demo.json`。
   - 只监听 `127.0.0.1:18600`。
   - `--import-rules`：调用已有 `rule_admin import-files --apply`（sqlite）。
   - `--check`：**不能只带 Admin-Token**。按 sidecar 契约组装：
     - `X-Admin-Token` = demo token
     - `X-Actor-Id` / `X-Actor-Name` / `X-Actor-Permissions` / `X-Request-Id` 合成探测 actor（权限至少含 `prearchive_rule_view`）
     - `X-Actor-Signature` = HMAC-SHA256(signing_secret, `f"{actor_id}|{actor_name}|{permissions}|{request_id}"`)，与 `prearchive.admin_api.actor_signature` 一致（name 与 BFF 一样做 percent-encode）
     - 先 GET `/healthz`，再 GET `/api/admin/settings`；settings 期望 200
   - `--check` 健壮性（Windows 易残留）：
     - 若 18600 已被本机占用 → **视为服务已在**，只探测、不二次 bind
     - healthz 重试最多 10 次、间隔 1s
     - 本脚本拉起的进程，退出时杀**整进程树**（Windows 用 job/taskkill `/T`，勿只杀父进程）
   - `--serve`：前台常驻（import 后 listen）
   - `--with-demo-e2e`（编排，给 T6）：起 sidecar + `--import-rules` → 再按仓库既有 demo serve 方式起主服务 18080（复用现有 demo 入口，不要另造一套隔离协议）→ 阻塞直到收到 SIGINT/退出码 → finally 清理 sidecar。若现有 demo serve 已经由 Playwright/人工拉起，脚本也可只保证 sidecar 侧，但 **042 必须写出两步可复制命令**。
   - 不扫局域网、不读生产 config。
3. `prearchive_service/config.example.json` 补 `admin_api` / `rule_registry` 占位（若缺失），**不填真实值**。
4. 可选：`docker-compose.demo.yml` 增加 `prearchive-demo` 服务，**仅 127.0.0.1:18600**。做不到就保持脚本启动，042 写明。不要把 sidecar 暴露到 0.0.0.0。

**测试：**

- `test_pa_demo_sidecar_config.py`（新）：config.demo.json 解析通过；无真实 IP（正则禁 `10.\d+` / `192.168.` 除注释）；`push/delivery/insurance` 为 false；端口 18600；admin_api 假 token 存在。
- `--check` 签名组装抽成可测函数（合成 actor + HMAC），单测对 `actor_signature` 向量一致；不必在每个 pytest 里常驻 HTTP（常驻放 T5 / `--check` 门禁）。

**禁改：** `rules/*.json` 正文。

### T2 — 仅 DEMO_MODE 打开 BFF

**目标：** 只有 `DEMO_MODE` 为真时自动注入 BFF env；生产代码路径默认仍关。

**做：**

1. 路由/Client 继续读 env。新增注入函数（优先 `app/demo_support/` 或 `isolated_mode.py`），在 `main.py` 路由注册前调用：
   - 条件：`demo_mode_enabled()` 为真。
   - **不要** `or test_isolated_mode_enabled()`。
   - 若 `PREARCHIVE_ADMIN_ENABLED` **键已存在于** `os.environ` → 整组四元组都不注入。
   - 否则设置：
     - `PREARCHIVE_ADMIN_ENABLED=true`
     - `PREARCHIVE_ADMIN_BASE_URL=http://127.0.0.1:18600`
     - `PREARCHIVE_ADMIN_TOKEN` / `PREARCHIVE_ADMIN_SECRET` 与 `config.demo.json` 假值一致
2. 不要把假 token 写进 `config/config.json.template`。
3. sidecar 未启动时：BFF 必须 **502**，主应用其他页面 200。禁止让 `/api/health` 变 unhealthy。
4. 非 DEMO_MODE：行为与 040 完全一致（503 feature-disabled）。

**测试：** `tests/test_isolated_prearchive_bff.py`：

| 用例 | 期望 |
|---|---|
| 默认 env、非 DEMO_MODE | settings → 503，detail 含 `disabled` |
| DEMO_MODE + sidecar 未起 | settings 鉴权后 502，health/live 仍 200 |
| DEMO_MODE + sidecar mock（签名带权限） | 200 |
| `os.environ` 已有 `PREARCHIVE_ADMIN_ENABLED=false` 即使 DEMO_MODE | 仍 503 |
| 仅 `TEST_ISOLATED_MODE=true`、无 DEMO_MODE | 不注入，503 |

**禁改：** 生产 Dockerfile 默认 ENV；`.env.example` 可加注释「生产不要设 ENABLED=true」。

### T3 — 权限双修（读端点 + 双保险 + 签名权限来源）

**现状（已对照代码）：**

- `current_user_has_permission` 恒 `True`（`prearchive_admin.py:61-67`）。
- 9 个读端点只挂 `get_current_user`：`get_settings` / `list_rules` / `list_versions` / `dry_run` / `diff` / `list_outbox` / `list_fields` / `list_audit` / `list_delivery_logs`。
- `_headers` 读 `actor.permissions`，User 模型无此属性。

**做：**

1. `_proxy` 增加 `db: Session`。路由一律 `db: Session = Depends(get_db)`。
2. 在 `_proxy` 内：
   - `perms = get_user_permissions(current_user.id, db)`（`app.permissions.get_user_permissions`，users.py 里的别名是同一函数）。
   - `current_user_has_permission(current_user, permission, db)` 用这批 perms（或等价查询）判断；admin 角色与 `require_permission` 一致：**role.name == "admin" 视为拥有全部**，避免 admin 未 seed 某新权限时签名/双保险分叉。
   - 构造签名 actor：`SimpleNamespace(id=..., username=..., permissions=perms)` 传给 `PrearchiveAdminClient.call`。**禁止**把裸 `User` 传进 `_headers` 当权限容器。
3. 9 个读端点（含 POST dry-run）改为 `Depends(require_permission(PERM_VIEW))`，与 `_proxy(..., PERM_VIEW)` 双保险同时存在。
4. 写端点保持原 `PERM_EDIT/APPROVE/PUBLISH/INTEGRATION/RETRY`。
5. 前端：`prearchive_rule_center.js` 与 UI Next 对 **403** 显示「无访问权限」，对 502/503 显示「规则中心不可用」。不要把 403 文案写成服务故障。

**测试（`test_prearchive_admin_bff.py` 扩展）：**

- 无 `prearchive_rule_view` 的登录用户：9 个读端点全部 403（mock 远端，证明根本没打到 sidecar 或打了也被 BFF 拦；优先断言 BFF 403）。
- 仅有 view：GET settings 200（mock）；POST publish 403。
- admin：GET 200，且 **发出的 mock request headers** 中 `X-Actor-Permissions` 含 `prearchive_rule_view`（或 admin 短路径下签名 actor 的 perms 非空）。
- 直接调 `_proxy`（不靠 Depends）：无权限写操作 403。
- 回归：BFF 关闭时仍 503，不因本次收紧变成 403。

**042/101：** 记「读端点从 login-only 收紧为 `prearchive_rule_view`」。

### T4 — 四角色 × 六权限矩阵（seed 实名）

**角色口径（锁死，禁止发明新名）：** `admin` / `auditor` / `dept_manager` / `clinician`（`app/demo_support/seed.py:50-53`）。

**期望矩阵（本轮锁死，不再拍板）：**

| 权限 | admin | auditor | dept_manager | clinician |
|---|---|---|---|---|
| prearchive_rule_view | ✓ | ✓ | ✗ | ✗ |
| prearchive_rule_edit | ✓ | ✗ | ✗ | ✗ |
| prearchive_rule_approve | ✓ | ✗ | ✗ | ✗ |
| prearchive_rule_publish | ✓ | ✗ | ✗ | ✗ |
| prearchive_integration_manage | ✓ | ✗ | ✗ | ✗ |
| prearchive_delivery_retry | ✓ | ✗ | ✗ | ✗ |

**seed 变更范围：** 只改 `app/demo_support/seed.py` 的 `role_permissions`：给 `auditor` **追加** `prearchive_rule_view`。admin 已有全部，不动。dept_manager / clinician 不加规则中心权限。

**禁止：** 改 `app/database.py` `_ensure_default_rbac_permissions`（生产每次 init_db 会写 Oracle）。生产角色权限保持 040「仅 admin」additive。

**测试：** `tests/test_prearchive_rbac_matrix.py`（新）：四角色 × 代表端点（settings GET / draft PUT / approve POST / publish POST / destinations POST / outbox retry POST），断言 200 vs 403。远端 mock。clinician 与 dept_manager 的 GET settings = 403（T3 收紧后的契约）。

### T5 — 规则仓导入 + 生命周期 HTTP 冒烟

**目标：** sidecar 管理 API 跑通 import 14 条 → list → validate → dry-run → approve → publish → diff → rollback。delivery 关，零外网。主服务 BFF 路径用 **带权限的签名头**（T3 之后）mock 或真 sidecar 各至少一次。

**做：**

1. `prearchive_service/tests/test_pa_demo_lifecycle_http.py`。
2. 优先线程内 TestClient（`create_admin_router` + sqlite memory）。若绑端口：仅 127.0.0.1 高位端口，`finally` 关掉。
3. 请求必须带完整 Admin-Token + Actor 四件套 + HMAC；permissions 含对应 PERM_*，否则会 403——这正是本轮要锁住的。
4. 断言：mark_item 14 条；system_push 0 条业务规则；dry-run 不连 `10.`；publish/rollback 指针；PHI 哨兵。
5. `ALLOWED_TARGETS` **保持 20 条**，不新增。主服务 BFF 代理冒烟覆盖白名单内已有路径即可。

### T6 — 双前端规则中心 E2E

**目标：** 用户级「能点」。编排与 failedApi 口径必须写清，避免正向/降级互打。

**编排（042 必须抄命令）：**

```
# 终端 A
python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules

# 终端 B（仓库既有 demo serve，端口 18080；以现有脚本/文档为准，042 写实测命令）
# 然后
npx --prefix frontend playwright test -c frontend/playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts
```

`playwright.legacy.config.ts` 的 webServer 保持 undefined（外部管理）。不要为凑方便去改成内嵌 webServer 导致与既有 legacy E2E 抢端口。

**Legacy 正向（sidecar 在 + DEMO_MODE 主服务）：**

- 新文件 `frontend/tests/e2e-legacy/rule-center.spec.ts`，守卫与既有 legacy E2E 相同。
- 登录 `demo_admin` → 质控类型页 → 「归档前规则中心」→ 表非空（14）→ 打开一条 → 校验/试运行可点。
- `failedApi`：**不得包含** `/api/prearchive-admin/` 前缀的 ≥400。其它前缀沿用既有豁免（如 favicon）。

**Legacy 降级（主服务 DEMO_MODE、sidecar 停）：**

- 同 spec 内第二用例或独立 skip 守卫（可用环境变量 `RULE_CENTER_SIDECAR=0`）。
- 页面有 502/503 降级文案，零白屏、零未捕获 exception。
- `/api/prearchive-admin/` 的 502/503 **与 favicon 同等豁免**，不计入失败。不要把降级用例的 failedApi 期望写成 0。

**UI Next：**

- unit ≥2：BFF 503→「不可用」；BFF 403→「无访问权限」；mock 200 列表渲染。基线 54 → ≥56。
- 真后端 oneshot 默认 skip（RP-I）。`RULE_CENTER_E2E=1` 可选一条，默认 skip。

**禁改：** 不为凑 E2E 放宽旧断言；不改 oneshot-sweep 的全局 failedApi 统计（新 spec 自管口径）。

### T7 — P1-01 残留：`report_token` 复用环境解析

**文件：** `app/services/report_token.py` 约第 31 行，只读 `APP_ENV`。

**做：** `from app.auth import _resolve_runtime_environment`，用它判断是否 production。禁止复制一份 aliases/冲突逻辑。`production` 未配密钥则 raise。开发 fallback 不变。

**测试：** 仅 `ENVIRONMENT=production` 无密钥 → raise；仅 `APP_ENV=prod` → raise；两者冲突 → raise（冲突发生在 `_resolve_runtime_environment`）；development fallback 可用。

**禁改：** token 算法、TTL、日志脱敏。

### T8 — 文档状态更新（不要重写已写内容）

起草 041 v1.0 时已经改过：INDEX 盘点行、041 表行、023 行注记、功能状态「多源规则引擎」分轨、023 §0.6 待执行行、起步包 README 入口。**禁止再把这些段落从头写一遍。**

**做：**

1. `docs/INDEX.md`：
   - 041 行状态改为 **已执行完毕，交付=042**。
   - 新增 042 行（交付报告）。
   - 「多源规则引擎」一行只把「隔离可用性收口见 041（待执行）」改成「041 已执行，见 042」；004C 未开始的句子保留。
   - 「安全与权限」一行去掉「BFF 空实现待 041 修」，改为「BFF 读端点已收紧为 prearchive_rule_view（041，仅代码/demo；生产 BFF 仍关）」。
2. `docs/reference/101_FEATURE_BASELINE.md` **追加**一小节（若 v1.0 未写才写；已有则只补契约变化）：隔离 demo 端口 18600、BFF 签名权限来源、读端点收紧、与 004C 边界。
3. `docs/ACTIVE/023_*` §0.6 的 041 行改为已执行（交付=042），不新增第二行、不把 023 改成新入口。
4. `开发起步包/README.md` 041 入口改为「已执行，交付=042」。

**禁做：** 不把 P0-07/P0-08/P0-09 标成已完成；不归档 023；不重写功能状态表其它行。

### T9 — 门禁与交付

见 §8、§9。

---

## 6. 允许修改的文件清单

**可新建：**

- `prearchive_service/config.demo.json`
- `scripts/run_prearchive_demo_sidecar_20260904.py`
- `prearchive_service/tests/test_pa_demo_sidecar_config.py`
- `prearchive_service/tests/test_pa_demo_lifecycle_http.py`
- `tests/test_isolated_prearchive_bff.py`
- `tests/test_prearchive_rbac_matrix.py`
- `frontend/tests/e2e-legacy/rule-center.spec.ts`
- `frontend/tests/unit/` 下规则中心降级/403 用例（若不便塞进现有文件）
- `docs/ACTIVE/042_041_EXECUTION_DELIVERY_REPORT_20260904.md`

**可修改：**

- `app/routers/prearchive_admin.py`（T3：读端点 Depends、`_proxy` 接 db、双保险真实现）
- `app/services/prearchive_admin_client.py`（T3：**权限来源修复**——`call`/`_headers` 使用显式 permissions 列表或带 permissions 的 namespace；**禁止扩大白名单**；允许为签名增加小辅助函数）
- `app/services/isolated_mode.py`、`app/demo_support/seed.py`、`app/main.py`（T2/T4；seed 只给 auditor 加 view）
- `app/services/report_token.py`（T7）
- `tests/test_prearchive_admin_bff.py`、既有 report_token 测试
- `static/scripts/modules/prearchive_rule_center.js`、`static/templates/pages/audit_types.html`（403 vs 502/503 文案，不改六类 CRUD）
- `frontend/src/features/governance/AuditTypesPage.vue`、`frontend/src/api/endpoints/prearchiveAdmin.ts`
- `frontend/tests/unit/prearchive-rule-center.test.ts`
- `docker-compose.demo.yml`（可选 sidecar）
- `prearchive_service/config.example.json`、`prearchive_service/README.md`（demo 启动一节）
- `docs/INDEX.md`、`docs/reference/101_FEATURE_BASELINE.md`、`docs/ACTIVE/023_*`（§0.6 状态字）、`开发起步包/README.md`、`开发起步包/01_统一修改记录.md`

**禁止修改（即使看起来相关）：**

- `app/database.py`（尤其 `_ensure_default_rbac_permissions`）
- `prearchive_service/rules/*.json` 规则条目
- `app/dify_pusher.py`、`app/services/push_executor.py`、`app/services/bulk_push_executor.py`
- `app/scheduler.py`、`app/services/scheduler_run_modes.py`
- `app/services/relay_alert_service.py`
- `config/config.json`、生产相关 `scripts/deploy_*.py`（可只读参考）
- `frontend/src/router` 默认入口、`UI_DEFAULT_ENTRY` 逻辑
- OpenDRG / insurance 插件行为（保持 disabled）
- `frontend/playwright.legacy.config.ts` 的 webServer 行为（保持外部管理）

---

## 7. 逐包测试表（最低集）

| 包 | 新测试最低条数 | 关键断言 |
|---|---|---|
| T1 | 4 | demo 配置无真实 IP；三开关 false；端口 18600；HMAC `--check` 向量与 `actor_signature` 一致 |
| T2 | 5 | 默认 503；DEMO_MODE 无 sidecar 502；health 200；键已在 environ 则不注入；仅 TEST_ISOLATED_MODE 不注入 |
| T3 | 9 读端点 403 + 签名非空 + 双保险 | 无 view 则读 403；admin 签名头 permissions 非空；BFF 关仍 503 |
| T4 | 4 角色 × 6 代表端点 | 与 §5 T4 矩阵逐格一致；角色名仅为 seed 四名 |
| T5 | 6 | 导入 14；HMAC 带权限；dry-run 零外连；publish/rollback；PHI；白名单长度 20 |
| T6 | legacy 正向+降级各 ≥1 + unit ≥2 | 正向 failedApi 不含 `/api/prearchive-admin/`；降级豁免该前缀 502/503；403 文案≠不可用 |
| T7 | 3 | 复用 `_resolve_runtime_environment`；ENVIRONMENT / APP_ENV / 冲突 |
| T8 | 无代码测试 | 041 行=已执行；新增 042 行；未重写 004C 未开始句 |

---

## 8. 全绿门禁（仓库根，全部 exit 0）

```
python -m compileall app tests scripts prearchive_service
python -m pytest
python scripts/check_naming_convention.py
python -m pytest prearchive_service/tests -q
python prearchive_service/check_isolation.py
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

附加（T1 脚本；可先 `--serve` 于另一进程，或让 `--check` 自己拉起并在退出时杀进程树）：

```
python scripts/run_prearchive_demo_sidecar_20260904.py --check
```

`--check` 失败则 T1 未完成。18600 已被占用时只探测不二次 bind。

判据：0 failed；prearchive 1 个预期 skip（cx_Oracle 真连）允许；oneshot uinext 默认 skip；计数不低于 §1.2 锚。

---

## 9. 交付物（042）必须包含

1. 执行前/后 git status 摘要（证明未丢 037/039 工作区）。
2. 逐包勾选 + 新测试文件名 + 测试数。
3. 门禁表（复制命令输出的 passed/skipped/failed）。
4. **用户怎么点开**（两步命令：sidecar `--serve --import-rules` + demo 主服务 18080；浏览器打开质控类型页规则中心区）。
5. 契约变化：读端点收紧、auditor demo 增加 view、签名权限来源。
6. 偏差说明（与 041 v1.1 不同处）。
7. 明确未做=乙类清单复述。
8. 回滚：删 demo 配置/脚本即可；主服务默认仍 503；生产 `database.py` 未改。
9. INDEX + 01 登记。

---

## 10. 升级出口（停下问用户，不要自行改道）

- 必须改推送/调度/Dify/Relay 才能过测试。
- 必须改 14 条正式规则。
- 必须生产写入或启动预检进程。
- 必须改 `database.py` / `_ensure_default_rbac_permissions` 才能让矩阵变绿 → **停下来**，不要改，报告用户。
- 门禁连续两轮红且根因不在 T0–T8。
- 发现 BFF 白名单缺路径导致前端功能不可用——先在 042 登记，**不要擅自加路径**。
- 角色矩阵不要再问；已锁死。若代码里出现第五个角色名，测试忽略它，不要新建。

---

## 11. 给用户的下一阶段（本轮不做，042 文末抄送）

1. **git 提交 037+039+041**（用户一句话批准即可）。
2. **036-RP7 生产预检影子 7 天**（W9 核对清单过后再做；compare 模式）。
3. **四角色现场 + UI Next canary**（017 WP6，023 §9.1 批准单）。
4. **六类 Dify 影子/临床抽检**（P0-08）。
5. **G2/G3/G5 接口材料到位后** 才谈 EMR/HIS/医保正式对接。
6. **004C** 仅在产品书面立项后单独开一轮，不要和预检规则中心搅在一起。

---

## 12. 完成定义

- [ ] T0–T8 验收勾选（含 T3 签名头非空、9 读端点 403、白名单 20）
- [ ] §8 门禁全绿
- [ ] 用户按 042 两步命令能在 127.0.0.1 看到规则列表（或降级文案），无生产副作用
- [ ] `docs/ACTIVE/042` + INDEX 状态更新 + 01 已写
- [ ] 未 commit、未 push、未部署生产
- [ ] 未改 `app/database.py`

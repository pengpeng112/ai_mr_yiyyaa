# 040 — 039 无纸化规则中心一次性开发升级执行交付报告

> 文档编号：040 ｜ 编制日期：2026-09-02 ｜ 执行者：ZCode/GLM-5.3
> 上游计划：`docs/ACTIVE/039_..._ONE_SHOT_PLAN_20260902.md` v1.1
> 前置：037 已执行完毕（交付=038，本会话先行完成）
> 执行时 HEAD：`52998cc`（037/038/039 全部变更未 commit——本次授权不含 git 提交）

## 0. 执行摘要

单会话完成 037（九修复包，038 交付）→ 039 阶段 A（T0-T10 全包）→ 039 B3 生产安全升级。
测试基线：主服务 1211→**1272 passed**（037 +43 / 039 +18）、prearchive 211→**270 passed +1 skip**
（+59）、UI Next unit 50→**54**、legacy E2E **6 passed**（真后端）、ui-next oneshot 扫荡真后端 **1 passed**、
默认 e2e 52+17skip 0fail。生产：六表 DDL 已建、代码/UI 已部署、镜像已固化（latest=0ff639fb78e0）、
三重回滚点齐备、全部业务开关保持关闭、零真实外发。

## 1. T0-T10 逐包结果

- [x] **T0 基线/冲突**：038 不存在→先执行 037（见 038）；git status 他人改动（037/039 计划、
  oneshot specs、README/01/INDEX 修改）全部已登记保留；规则文件 SHA-256 执行前后一致
  （example `ecb3e20c…` / system_push `1897bdbd…` / 快照 `b735bdfc…`）。
- [x] **T1 Schema 与领域模型**：`rule_models.py` 六表（RULE_VERSION/RULE_POINTER/RULE_AUDIT/
  DESTINATION/OUTBOX/DELIVERY_LOG，字符串主键免 Oracle 序列）+ `schemas/qc-result-v1|qc-ack-v1|
  rule-dsl-v2.schema.json` 三份机器可读契约 + `result_contract.py`（Pydantic 模型/序列化器/
  ACK 校验/PHI 哨兵/投递判定）+ Oracle 手工 DDL 与反向清理脚本。
- [x] **T2 规则仓/状态机/三模式/CLI**：`rule_repository.py`（乐观锁/原子 claim/审计 append-only）
  + `rule_service.py`（draft→validated→approved→published→retired 全状态机、发布指针、回滚、
  FID 硬门、危险内容扫描、文件导入幂等、file/compare/registry 三模式）+ `rule_admin.py` CLI
  （import-files --dry-run/--apply、compare-fixtures）+ golden 零差异测试
  （导入 14 条正式规则后 file 与 registry 逐字段一致）。
- [x] **T3 管理 API**：`admin_api.py` 全部 §9.1 端点（rules 生命周期/versions/draft/validate/
  dry-run/approve/publish/rollback/retire/diff、destinations/contract-test、outbox/retry、
  fields、audit、delivery-logs）；X-Admin-Token + X-Actor-Signature（HMAC）双因子；
  dry-run 只用 demo fixtures 不查真实库；并发冲突 409。
- [x] **T4 JSON 结果与 Outbox**：v1 序列化器（最小患者字段+PHI 哨兵+08:00 时区）、
  ACK 判定（2xx/409/408/429/5xx/超时/坏 ACK 全矩阵）、destination HMAC 固定契约向量、
  SSRF 防护（https 默认/内网 http 显式开关/禁 URL 凭据）、Outbox 原子 claim/指数退避+Retry-After/
  lease 回收/dead/对账补齐；本地 Mock receiver（ThreadingHTTPServer）覆盖全部故障形态；
  delivery=false 时断言零网络调用。
- [x] **T5 医保插件**：`insurance/` 包（Protocol+Noop+确定性编码+OpenDRG 隔离壳）；
  配置校验强制"无年度规则包→enabled 视为 false"、opendrg 需 license_verified（G6）；
  插件异常回退 Noop（fail-open）。零第三方源码 vendoring。
- [x] **T6 主服务 BFF+RBAC**：`prearchive_admin_client.py`（显式白名单 21 目标/3+10s 超时上限/
  actor 签名）+ `prearchive_admin.py` 路由（默认 503 feature-disabled，热切换读 env）+
  `database.py`/`seed.py` 六权限 additive seed（仅 admin）+ `main.py` 注册（static mount 之前）；
  不可用/超时/坏 JSON → 502 fail-open；既有 `/api/audit-types/prearchive` 原样。
- [x] **T7 Legacy 前端**：audit_types.html 增"归档前规则中心"区（规则列表/校验/试运行/审批/
  发布/回滚/版本 diff/目标/Outbox/模式横幅）+ `prearchive_rule_center.js` 新模块 + app.js 接线；
  既有六类 CRUD 与只读预检展示未动；9 条静态契约测试。
- [x] **T8 UI Next**：`api/endpoints/prearchiveAdmin.ts`（全类型化）+ AuditTypesPage.vue 同等能力
  （含降级提示/危险操作确认/版本 diff 对话框）+ Vitest 4 条（白名单路径锚/encodeURIComponent/
  类型面）；typecheck 0 错、build 镜像到 static/ui-next。
- [x] **T9 数据资产适配**：`field_registry.py` 16 条字段注册（confirmed=采集器在用实测列；
  candidate=数据资产快照对象 HIS.INP_SETTLE_MASTER(_YB)/ZNT BASYFY/DBZ DRG 字典，
  注明快照日期与路径；blocked=G2/G3/G5/G 心电）；candidate/blocked 不得用于发布规则
  （管理 API /fields 暴露 usable_for_publish=false）。零外仓大文件复制、零活库连接。
- [x] **T10 门禁+文档**：§12.2 全过（数字见 §2）；本报告+INDEX+prearchive README+01 登记。

## 2. 门禁数字（039 §12.2 全项）

| 门禁 | 结果 |
|---|---|
| `python -m pytest prearchive_service/tests -q` | **270 passed + 1 skipped**（基线 211+1 → +59） |
| `python prearchive_service/check_isolation.py` | PASSED（65 文件零 `import app.*`） |
| `python -m pytest`（主服务） | **1272 passed**，0 failed（037 后 1254 → +18：BFF 9+前端静态 9） |
| `python -m compileall app tests scripts prearchive_service` | exit 0 |
| `python scripts/check_naming_convention.py` | PASS |
| `npm --prefix frontend run typecheck` | 0 errors |
| `npm --prefix frontend run test:unit` | **54 passed**（15 文件；基线 50 → +4） |
| `npm --prefix frontend run build` | 成功，dist 镜像至 static/ui-next |
| `npm --prefix frontend run test:e2e` | **52 passed + 17 skipped，0 failed**（oneshot 默认跳过=RP-I 生效） |
| legacy 真后端 E2E（demo env 127.0.0.1:18080） | **6 passed**（含 oneshot 全页扫荡：质控类型页含新规则中心区 errors=0/failedApi=0） |
| ui-next oneshot 扫荡（真后端） | **1 passed**（16 路由 errors=0） |
| CLI 冒烟 | `import-files --dry-run`：14 条/0 冲突/0 错误 |

## 3. B3 生产安全升级（用户 2026-09-02 授权，已执行）

| 项 | 结果 |
|---|---|
| 预检（只读） | 容器 healthy（ef05862cf081）；预检进程未运行、无 config.json（属 036-RP7 轨道）；生产 app 库无任何 MED_PREARCHIVE 表 |
| 备份 | 宿主 `/root/hotfix_backup_039_20260902.tar.gz`（容器内 app/static/prearchive_service）+ 回滚镜像 tag `rollback-pre-039-20260902`（7b158dccd458）+ 既有 `rollback-pre-hotfix-20260901` 仍在 |
| DDL | 六表全部创建（经容器内应用库受控连接逐条执行；ORA-00955 幂等跳过；实测教训=索引名 ≤30 字符，`IX_PREARCH_RULE_DOMAIN_TRACK`） |
| 部署 | 1.4MB tar（341 条目：app 受影响面/static 两套前端/prearchive_service 增量）→ 覆盖 /app → 清 __pycache__ → 重启（停机约 25s） |
| 验证 | 健康 200；六类核心审计类型在（生产共 12 类型，core_missing=[]）；BFF 路由已注册（未认证 403 非 404）；六权限已 seed 至 admin（实测 6/6）；legacy 规则中心 JS 200；ui-next 200；qc_detail 版本锚 20260902-csrf-header；规则中心模块容器内导入 OK；双调度重注册（daily 09:00 + discharge 11:44）+留存清理 02:00；近 5 分钟日志 0 traceback |
| 固化 | `docker commit` → **med-audit:latest = 0ff639fb78e0**（运行容器继续热更层服务，重建时用新镜像——与 20260901 惯例一致） |
| 开关终态 | `rule_registry.mode=file`（默认）；`result_delivery.enabled=false`；`insurance_qc.enabled=false`；BFF env 未设置（503 feature-disabled） |
| 真实外发次数 | **0**（EMR/HIS/医保/Dify/Relay 全零调用） |

**注意**：本次部署携带 037+039 合并代码（两包共享 main.py/database.py 等文件，037 九包已过全门禁；
037 的生产效果：SQLite busy_timeout 对 Oracle 应用库模式无效但无害、配置空 body 防覆盖、
census/export 400 语义、H5 反馈 CSRF 豁免、审计类型删除 404 均已在生产生效）。

## 4. 用户拍板落实核对

| 拍板项 | 落实 |
|---|---|
| 不强制双人审批 | `require_separate_approver=false` 默认（配置节+校验+专测；true 时审批人≠创建人） |
| 山东济南 DRG | config 默认 region=山东省济南市/insurance_type=DRG；无 ruleset_year 时配置校验强制 enabled=false |
| OpenDRG 隔离 | adapter 壳恒 blocked（未核验 LICENSE 前零 vendoring 零下载零触网）；license_verified 门 |
| 试点/扣分/阻断可配置 | governance 节（pilot_dept_codes 空=不触达；action_policy 默认 notify_only） |
| 生产 DDL/部署/开关授权 | B3 已执行（本节） |

## 5. 与 039 的偏差说明

1. **发布指针粒度**：§5.4"每 DOMAIN+TRACK 一行"细化为域内每规则一指针
   （DOMAIN+TRACK+RULE_KEY 唯一）——回滚语义更精确，§13.1 允许的微调。
2. **delivery_worker 并入 outbox.py**：单一模块承载 enqueue/claim/send/retry/reconcile
   （§13.1 文件清单微调；功能全覆盖）。
3. **registry 组合版本字符串**：registry 模式 rule_version=`v1`（不含空轨 channel-reserved 后缀），
   file=`v1+channel-reserved`；零差异测试按"逐条规则内容+problems 逐字段"断言（§5.5 口径），
   容器级版本串差异已在测试注释说明。
4. **BFF 保持关闭**：§14-B3"可以启用管理页面/BFF"为许可而非要求——预检服务进程未启动
   （036-RP7 轨道），启用 BFF 只会得到 502；保持 503 feature-disabled 提示更准确。
   启用三步：容器 env 设 PREARCHIVE_ADMIN_ENABLED/BASE_URL/ADMIN_TOKEN/SECRET + 预检 config.json
   admin_api 节 + 启动预检服务。
5. **六表 DDL 首跑失败两次后成功**：①注释块分割 bug（本地脚本，已修）②索引名 31 字符 ORA-00972
   （已改 ≤30 并同步模型）；幂等 SKIP-EXISTS 逻辑保证重试安全。

## 6. 未完成项与 G 门禁状态

| 项 | 状态 | 阻塞门 |
|---|---|---|
| EMR 真实对接 | 框架就绪，destination=emr_mock 禁用 | G2（URL/认证/字段映射/ACK 未到） |
| HIS 真实对接 | 同上 his_mock 禁用 | G3 |
| 接收方字段最小集确认 | 默认只传 patient_id+visit_number | G4 |
| 医保正式判定 | 插件/壳就绪，恒 disabled | G5（年度规则包未到） |
| OpenDRG 启用 | adapter 壳+许可证门 | G6（LICENSE 未核验） |
| B4 规则仓影子（compare 7 天） | **未开始** | 需预检服务生产启动（036-RP7）+ import apply |
| B5 对外影子 / B6 正式启用 | 未开始 | 依赖 B4 清零 + G2/G3/G5 |

**结论：框架部署完成 ≠ 正式对接完成**。EMR/HIS/医保均为"目标未启用"状态。

## 7. OpenDRG 许可证结论

未下载、未复制、未 vendoring 任何 OpenDRG 源码或规则包（G5/G6 未过，§8.2 纪律）。
适配器是纯壳：启用需 `license_verified=true` + 规则包元数据（region/year/version/sha256）
齐备且 sha 校验通过；当前恒返回 unknown+blocked 诊断。**不存在许可证违规面**；
真实集成时的 LICENSE 核验与 NOTICE 生成留待 B0 阶段执行。

## 8. 改动文件清单

**prearchive_service 新增**：`prearchive/{rule_models,rule_repository,rule_service,rule_admin,
result_contract,destinations,outbox,admin_api,field_registry}.py`、`prearchive/insurance/{__init__,
noop,deterministic,opendrg_adapter}.py`、`schemas/*.schema.json`×3、
`sql/{create,drop}_prearchive_rule_center_oracle.sql`、tests×6 新文件；
**修改**：`prearchive/{api,config}.py`、`run_service.py`、`README.md`、`tests/test_pa_his_base.py`。
**主服务新增**：`app/routers/prearchive_admin.py`、`app/services/prearchive_admin_client.py`；
**修改**：`app/{main,database}.py`、`app/demo_support/seed.py`。
**前端**：`static/scripts/modules/prearchive_rule_center.js`（新）、`static/scripts/app.js`、
`static/scripts/modules/audit_types.js`、`static/templates/pages/audit_types.html`、
`frontend/src/api/endpoints/prearchiveAdmin.ts`（新）、`frontend/src/features/governance/AuditTypesPage.vue`、
`frontend/tests/unit/prearchive-rule-center.test.ts`（新）、`static/ui-next/**`（构建产物）。
**测试**：`tests/test_prearchive_admin_bff.py`、`tests/test_prearchive_rule_center_frontend_static.py`（新）。
**脚本**：`scripts/precheck_039_b3_20260902.py`、`scripts/deploy_039_b3_20260902.py`（新）。
（另有 037 全部改动见 038 §4。）

## 9. 生产备份/回滚点汇总

| 回滚点 | 位置 |
|---|---|
| 文件备份 tar | `10.10.8.84:/root/hotfix_backup_039_20260902.tar.gz` |
| 回滚镜像 | `med-audit:rollback-pre-039-20260902`（7b158dccd458） |
| 上一回滚点 | `rollback-pre-hotfix-20260901`（5f0d72b283de）仍在 |
| DDL 反向 | `/app/prearchive_service/sql/drop_prearchive_rule_center_oracle.sql`（确认无数据后 DBA 手工） |
| 回滚命令 | `docker tag med-audit:rollback-pre-039-20260902 med-audit:latest && cd /opt/med-audit-docker && docker compose down && docker compose up -d`（或还原备份 tar 后 restart） |

## 10. 给下一任的核查清单

1. `docker exec med-audit python -c "…user_tables LIKE 'MED_PREARCHIVE%'"` 应六表；
2. 生产 `curl /api/prearchive-admin/settings`（未认证）应 403（路由在）而非 404；
3. 本地全量：主 1272 / prearchive 270+1skip / unit 54 / e2e 52+17skip；
4. 启用规则中心的路径：预检 config.json（result_store=oracle+admin_api 节）→ 启动预检服务 →
   容器 env BFF 四元组 → `python -m prearchive.rule_admin import-files --apply` → compare 7 天；
5. 未经用户批准不得 commit/push（本报告全部变更仍在工作区）。

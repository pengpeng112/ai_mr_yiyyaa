# 042 — 041 规则中心隔离可用性一次性执行交付报告

> 文档编号：042 ｜ 日期：2026-09-04 ｜ 执行者：ZCode/GLM-5.3
> 作业书：`docs/ACTIVE/041_ISOLATED_RULE_CENTER_USABILITY_ONE_SHOT_PLAN_20260904.md` **v1.1**
> 性质：隔离 demo 本地执行交付；**零生产访问、零生产写入、未 commit、未 push、未部署**。
> 完成定义对照：041 §12 各项见 §3 勾选。

---

## 1. 执行前/后 git 状态（证明未丢 037/039 工作区）

| 项 | 执行前（T0 冻结） | 执行后 |
|---|---|---|
| HEAD | `52998cc8d9aa7e908c912597ff13e60e1e2d7a72` | 同（零 commit） |
| `git status --short` 计数 | 74（037+039 全部未 commit 保留） | 86（只增未减；037/039 文件全部在位，无 checkout/reset） |
| 分支 | `fix/ora-12609-p4-error-code` | 同 |

本轮净新增文件：`prearchive_service/config.demo.json`、`scripts/run_prearchive_demo_sidecar_20260904.py`、`prearchive_service/tests/test_pa_demo_sidecar_config.py`、`prearchive_service/tests/test_pa_demo_lifecycle_http.py`、`tests/test_isolated_prearchive_bff.py`、`tests/test_prearchive_rbac_matrix.py`、`frontend/tests/e2e-legacy/rule-center.spec.ts`、`frontend/src/utils/prc-degradation.ts`、本报告。

本轮修改文件：`app/routers/prearchive_admin.py`、`app/services/isolated_mode.py`、`app/demo_support/seed.py`、`app/main.py`、`app/services/report_token.py`、`static/scripts/modules/prearchive_rule_center.js`、`static/templates/pages/audit_types.html`、`frontend/src/features/governance/AuditTypesPage.vue`、`frontend/tests/unit/prearchive-rule-center.test.ts`、`tests/test_prearchive_admin_bff.py`、`tests/test_prearchive_rule_center_frontend_static.py`、`tests/test_report_auth.py`、`prearchive_service/config.example.json`、`prearchive_service/README.md`、`docs/INDEX.md`、`docs/reference/101_FEATURE_BASELINE.md`、`docs/ACTIVE/023_*`（§0.6 状态字）、`开发起步包/README.md`。

**未改**（041 §6 红线全部守住）：`app/database.py`、`prearchive_service/rules/*.json`（14 条 FID/空通道原样）、Dify/推送/调度/Relay 各文件、`config/config.json`、`frontend` 路由默认入口、`playwright.legacy.config.ts` webServer、OpenDRG/insurance 行为。

## 2. 执行前基线（T0 复跑，与 040 锚一致）

主服务 **1272 passed** ／ prearchive **270 passed + 1 skipped** ／ unit **54** ／ e2e **52 + 17 skipped** ／ compileall OK ／ naming PASS ／ isolation PASSED。

## 3. 逐包勾选（041 §4 顺序）

| 包 | 状态 | 交付物与测试 |
|---|---|---|
| T0 基线冻结 | ✅ | §1/§2；工作区 74 文件全保留 |
| T1 sidecar+配置+HMAC --check+编排 | ✅ | `config.demo.json`（127.0.0.1:18600、源全关、三开关 false、假 token）；`scripts/run_prearchive_demo_sidecar_20260904.py`（`--serve`/`--import-rules`/`--check`/`--with-demo-e2e`；`build_probe_headers` HMAC 四件套；taskkill /T 杀树）；`test_pa_demo_sidecar_config.py` **7 passed**；`--check` 门禁 PASS（导入 14 条→healthz 200→settings HMAC 200→树回收）；`config.example.json` 补 admin_api/rule_registry/result_delivery/insurance_qc 占位节 |
| T2 仅 DEMO_MODE 注入 BFF | ✅ | `isolated_mode.py` `inject_prearchive_admin_bff_env()`（`PREARCHIVE_ADMIN_ENABLED` 键存在即整组不注入；不叠加 TEST_ISOLATED_MODE）；`main.py` 路由注册前调用；`test_isolated_prearchive_bff.py` **9 passed**（默认 503／DEMO 无 sidecar 502+health 200／mock 200+签名带权限／键存在不注入／仅 TEST_ISOLATED_MODE 不注入） |
| T3 权限双修 | ✅ | 9 读端点改 `require_permission(PERM_VIEW)`+`Depends(get_db)`；`current_user_has_permission(user, perm, db)` 真实现（admin 全通过/其余查库）；`_proxy` 构造 `SimpleNamespace(id, username, permissions=查库∪admin 六权限全集)` 签名（裸 User 禁入）；`test_prearchive_admin_bff.py` 扩展 **+7**（9 读端点 403 零触达／viewer 读 200 写 403／admin 签名头含权限／`_proxy` 直调 403／bare-admin 权限全集／BFF 关仍 503／白名单=20）；前端 403=「无访问权限」≠502/503=「规则中心不可用」（legacy `prcDisabledTitle()` + UI Next `utils/prc-degradation.ts` 同口径） |
| T4 四角色×六权限矩阵 | ✅ | `seed.py` 仅 auditor 追加 `prearchive_rule_view`；`test_prearchive_rbac_matrix.py` **3 passed**（seed 真源 `_seed_rbac`，四实名角色×8 代表端点逐格断言；`database.py` 未动） |
| T5 规则仓导入+生命周期 HTTP | ✅ | `test_pa_demo_lifecycle_http.py` **6 passed**（导入 14 条 published+system_push 0／只带 token 401+无 view 403／草稿 validate→approve→publish→指针／双版本+rollback 指针回 v1／dry-run TEST 前缀 PHI 哨兵+无 10. 地址／审计留痕解 percent-encode 真名）；真 sidecar BFF 路径由 `--check`+E2E 覆盖 |
| T6 双前端 E2E | ✅ | legacy `rule-center.spec.ts` **正向 1 passed（4.5s）**：14 行/published tag/试运行弹窗 TEST 患者/`failedApi` 不含 `/api/prearchive-admin/`≥400；**降级 1 passed（5.4s）**：`RULE_CENTER_SIDECAR=0`→「规则中心不可用」文案+「不受影响」+零 pageerror+该前缀仅 502/503 豁免；既有 `legacy-pages.spec.ts` **5/5** 无回归；unit **+3（54→57）**（502/503→不可用、403→无访问权限不写服务故障、页面接线+200 列表渲染契约） |
| T7 report_token 环境解析 | ✅ | 复用 `app.auth._resolve_runtime_environment`（import，无复制逻辑）；`test_report_auth.py` **+4**（ENVIRONMENT=production raise／APP_ENV=prod raise／冲突 raise／development fallback），文件 9 passed |
| T8 文档状态更新 | ✅ | INDEX（盘点行+041 行=已执行+新增 042 行+多源规则引擎/安全与权限两行只改状态句）；101 追加「2026-09-04，041」契约节；023 §0.6 041 行改已执行（未加第二行）；起步包 README 入口改已执行；prearchive README §10 demo 启动 |
| T9 门禁+交付 | ✅ | §4 门禁表+本报告+INDEX+01 登记 |

## 4. 全绿门禁（仓库根实测输出）

| 命令 | 结果 |
|---|---|
| `python -m compileall app tests scripts prearchive_service` | OK（零错误） |
| `python -m pytest` | **1295 passed**（基线 1272，+23 新增，0 failed） |
| `python scripts/check_naming_convention.py` | PASS |
| `python -m pytest prearchive_service/tests -q` | **283 passed + 1 skipped**（284 total；基线 270+1，+13 新增，0 failed） |
| `python prearchive_service/check_isolation.py` | PASSED（67 文件零 `import app.*`） |
| `npm --prefix frontend run typecheck` | OK（零错误） |
| `npm --prefix frontend run test:unit` | **57 passed**（基线 54，+3） |
| `npm --prefix frontend run build` | OK（dist 镜像同步 static/ui-next） |
| `npm --prefix frontend run test:e2e` | **52 passed + 17 skipped，0 failed**（oneshot 默认 skip 保持） |
| `python scripts/run_prearchive_demo_sidecar_20260904.py --check` | PASS（healthz 200 + settings HMAC 200 + 进程树回收） |
| 附加：legacy 规则中心 E2E 双轮（T6） | 正向 1 passed／降级 1 passed；legacy-pages 5/5 |

## 5. 用户怎么点开（两步命令，Windows 本机）

```
# 终端 A：规则中心 sidecar（先幂等导入 14 条正式规则，监听 127.0.0.1:18600）
python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules

# 终端 B：主服务 demo（DEMO_MODE 自动注入 BFF；首次先 create）
python scripts/demo_env.py create --run-id rulecenter --profile smoke   # 仅首次
python scripts/demo_env.py serve --run-id rulecenter                    # 18080
```

浏览器打开 `http://127.0.0.1:18080/index.html` → 登录 `demo_admin` / `Demo-12Dept!2026` →
左侧菜单「质控类型」→ 页面下方「归档前规则中心」：14 条规则列表（published）、运行模式横幅
（file）、校验/试运行（demo fixtures 虚构 TEST 患者）、审批/发布/回滚（二次确认+SHA）、
版本/diff、投递目标（全禁用）、Outbox。auditor 登录（`demo_auditor`）只读可见；
dept_manager/clinician 登录该区域显示「无访问权限」。
**降级演示**：关掉终端 A → 刷新页面 → 该区域显示「规则中心不可用…上方六类不受影响」，其余页面正常。
（本轮实测 run：`rulecenter` 已 create；结束后 serve/sidecar 均已停止，端口 18080-18082/18600 已释放。）

## 6. 契约变化（042/101 已登记）

1. **读端点收紧**：`/api/prearchive-admin/` 9 个读端点从 login-only 收紧为 `prearchive_rule_view`——BFF 启用后无该权限的登录用户从「能读」变 403（041 §3.3 裁定）。
2. **auditor demo 增加 view**：仅 `app/demo_support/seed.py`（demo 专用）；生产 `database.py _ensure_default_rbac_permissions` 未动，生产仍仅 admin 拥有六权限。
3. **签名权限来源**：BFF→sidecar 的 `X-Actor-Permissions` 从恒空串改为 `get_user_permissions` 查库（admin 并上六权限全集）——修复了 sidecar 对 admin 也 403 的断链。
4. **BFF env 注入**：仅 `DEMO_MODE` 为真注入四元组（假 token 与 config.demo.json 一致）；`PREARCHIVE_ADMIN_ENABLED` 键已存在于 `os.environ` 则整组不注入；生产默认行为与 040 完全一致（503 feature-disabled）。
5. **白名单 20 条不变**（测试锁死 `len(ALLOWED_TARGETS) == 20`）。

## 7. 偏差说明（与 041 v1.1 不同处）

1. **T1 docker-compose.demo.yml 可选项未做**——sidecar 以脚本启动（041 §5 T1.4 允许"做不到就保持脚本启动，042 写明"）；未把 sidecar 暴露到 0.0.0.0。
2. **T6 ui-next `RULE_CENTER_E2E=1` 可选真后端用例未加**（041 标"可选一条，默认 skip"）；ui-next 侧以 3 条 unit + mock 200 渲染契约覆盖，oneshot uinext sweep 保持默认 skip 未动。
3. **T5 import 状态适配**：实测 `rule_admin import-files --apply` 将 14 条直接以 **published**（含指针）落库——生命周期测试改为自建草稿走全链（这是仓库既有行为，非本轮变更）。
4. **T6 降级轮 failedApi 口径补充豁免 `/api/users/me` 403**：legacy 冷加载 `restoreSession` 的未认证探测为既有行为（与本轮无关），本 spec 自管口径内豁免；未动 oneshot sweep 全局统计。
5. **`--serve` 自动先导入**：041 写「`--serve`：前台常驻（import 后 listen）」——实现为 `--serve` 恒先幂等导入（重复启动零副作用，`--import-rules` 单独可用）。

## 8. 明确未做＝041 乙类清单复述

生产启动预检进程+compare 7 天（036-RP7/040 B4）／EMR/HIS 真实 destination（G2/G3/G4）／医保正式判定+OpenDRG（G5/G6）／UI Next 生产 canary+切默认入口（017 WP6/WP7）／六类 Dify 影子回放+临床抽检（023 P0-08）／历史 high 降级+科室回填（023 WP7）／004C 主服务多源规则引擎（023 WP8）／W10 系统推送规则/心电采集器/C# 助手试点机／Relay 真实患者实发——**均未做、均未授权**。

## 9. 回滚方式

- 删除 `prearchive_service/config.demo.json`、`scripts/run_prearchive_demo_sidecar_20260904.py`、`frontend/tests/e2e-legacy/rule-center.spec.ts` 及本轮测试文件即可回到 040 形态；
- 主服务默认仍 503 feature-disabled（非 DEMO_MODE 不注入 env，行为与 040 一致，有测试锁死）；
- 生产 `database.py` 未改（角色权限仍=040 additive）；生产无任何访问/写入；
- demo 数据目录 `data/demo/rulecenter`（smoke）与 `prearchive_service/data/demo/`（sqlite 规则仓/心跳）可整体删除无副作用。

## 10. 下一阶段（041 §11 抄送，本轮不做）

1. **git 提交 037+039+041 三包**（用户一句话批准即可，提交说明已备好）。2. 036-RP7 生产预检影子 7 天（W9 清单后，compare 模式）。3. 四角色现场+UI Next canary（023 §9.1 批准单）。4. 六类 Dify 影子/临床抽检（P0-08）。5. G2/G3/G5 材料到位后 EMR/HIS/医保正式对接。6. 004C 仅在产品书面立项后单独开一轮。

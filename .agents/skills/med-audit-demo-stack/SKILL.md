---
name: med-audit-demo-stack
description: Med-Audit 隔离 demo 环境与规则中心 sidecar 起停编排（demo_env.py create/serve/stop + run_prearchive_demo_sidecar_20260904.py --serve/--check + 端口清理脚本）。要起停 12 科室隔离 demo、跑规则中心 E2E（正向/降级双轮）、编排 sidecar:18600、清理 18080-18082/18600 端口残留、排查 E2E 偶发端口占用失败时必须使用。含 4173 只报不杀口径与已知豁免 /api/users/me。
---

# Med-Audit 隔离 Demo 与规则中心编排规程

## 1. Demo 主服务（12 科室脱敏合成环境，127.0.0.1:18080-18082）

```bash
python scripts/demo_env.py create --run-id <id>   # 创建+确定性造数
python scripts/demo_env.py serve --run-id <id>    # 起主服务（18080 起）
python scripts/demo_env.py status / stop          # 状态 / 停止
python scripts/demo_env.py destroy                # 停止后整体销毁三个隔离目录
```

只绑 127.0.0.1，零生产接触；数据目录在 `review/` 侧隔离存放（不入库）。

## 2. 规则中心 sidecar（127.0.0.1:18600）

```bash
python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules  # 前台常驻：幂等导入 14 条正式规则再监听
python scripts/run_prearchive_demo_sidecar_20260904.py --check                 # 自检：拉起→healthz→HMAC settings 200→杀整进程树
python scripts/run_prearchive_demo_sidecar_20260904.py --with-demo-e2e         # 编排：sidecar + demo 主服务一起
```

- BFF 四元组只在 `DEMO_MODE` 注入（`app/services/isolated_mode.py`）；sidecar 配置=`prearchive_service/config.demo.json`。
- 18600 被占用时 `--check` 只探测不二次 bind。

## 3. 规则中心 E2E 双轮（legacy，demo 真后端）

```bash
# 手工正向轮前置：demo serve（18080）+ 自己管理的 sidecar（18600）在听
# 手工降级轮前必须停止自己的 sidecar；下面环境变量不会替你停止进程
cd frontend
LEGACY_E2E=true npx playwright test -c playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts   # 正向轮
RULE_CENTER_SIDECAR=0 LEGACY_E2E=true npx playwright test -c playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts  # 降级轮
```

- 降级轮口径：规则中心"不可用"文案 + 其余页面不受影响 + 零 pageerror + `prearchive-admin` 仅 502/503 豁免。
- **已知豁免 `/api/users/me`**：legacy 冷加载 `restoreSession` 未认证探测返回 403 是既有行为，spec 自管豁免，不算失败。
- 聚合入口：`python scripts/run_gates_20260906.py --full` 在 demo 主服务 18080 在听时运行，并自行管理 sidecar。聚合双轮前只启动 demo 主服务；不要预先启动外部 sidecar。无 demo 时标 `SKIPPED(no-demo)`；外部 sidecar 占用时不得擅杀，降级轮及双轮汇总标 SKIPPED，不能算双轮完成。

## 4. 端口清理

```bash
python scripts/clean_demo_ports_20260906.py            # 默认 dry-run：只打印
python scripts/clean_demo_ports_20260906.py --yes      # 真杀
```

- 候选清理端口：**18080/18081/18082/18600**。执行 `--yes` 前核对 PID、命令行和归属，只终止本任务管理或已获准停止的 demo 主服务/sidecar；端口号本身不构成终止未知进程的授权。
- **4173 只报告不杀（REPORT-ONLY）**：Playwright preview webServer 归属，`reuseExistingServer:!CI` 设计为复用。
- netstat 解析同时匹配 `LISTENING` 与 `侦听`（中文 Windows）；Windows 用 `taskkill /PID <pid> /T /F` 杀进程树。

## 5. 红线引用（不复制正文）

- `AGENTS.md` — "Prearchive Service（028/031 轨道）"节（隔离红线：零 `import app.*`）、"Remote Production Server"节（demo 与生产严格分离）。
- `开发起步包/00_AI协作规则.md` — §7 隐私红线（demo 数据也不外发）。
- `docs/ACTIVE/042_*.md` — §5 两步启动、§7 偏差（`--with-demo-e2e` 存在但 041 实际手工双终端）。

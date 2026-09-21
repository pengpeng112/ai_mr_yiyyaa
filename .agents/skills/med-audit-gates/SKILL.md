---
name: med-audit-gates
description: Med-Audit 仓库全绿门禁唯一执行入口（脚本 scripts/run_gates_20260906.py）。任何代码/测试/脚本/文档改动后要跑回归、交付前做全绿检查、门禁汇总、基线锚比对、或遇到"跑门禁/全绿/回归验证/冒烟检查"需求时必须使用。含 --quick 冒烟与 --full 全量两档命令、锚源 gate_anchors.json 位置、失败处置流程（禁止跳过单项、以脚本 Markdown 门禁表为准）。
---

# Med-Audit 全绿门禁执行规程

## 1. 适用场景

- 任何改动（代码/测试/脚本/配置/文档）后的回归验证；
- 一次性执行任务（见 `med-audit-oneshot-delivery`）交付前的全绿检查；
- 基线锚比对（改动后测试数是否低于锚）；
- CI 或手工冒烟（分钟级快速验证）。

## 2. 命令（唯一入口）

```bash
# 冒烟（分钟级）：compileall(app tests scripts prearchive_service) + naming + isolation + sidecar --check
python scripts/run_gates_20260906.py --quick

# 全量（数十分钟）：quick 全部 + 主 pytest + prearchive pytest + typecheck + unit + build + e2e + 可选 legacy 规则中心 E2E
python scripts/run_gates_20260906.py --full

# 与锚比较（低于锚退出非零；未传 --anchor-file 或文件不存在只出表不比锚）
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```

门禁项与判据全集见 `docs/ACTIVE/041_*.md` §8；compileall 范围使用聚合脚本（含 `prearchive_service`）；AGENTS.md 的直接命令只是局部语法检查。

"唯一入口"限定为**正式门禁汇总**（跑门禁/全绿检查/回归汇总/锚比对时必须经本脚本得出），不禁止定向测试与诊断命令（聚焦 pytest、单文件编译、失败复跑等可单独执行）。档位选择：普通文档或说明修改默认执行 `--quick` 及相关一致性检查；代码/测试/脚本修改另跑相关定向测试；一次性交付、任务明确要求全绿或专项计划指定时执行 `--full`（需比锚时带 `--anchor-file`）。不得用 quick 替代已明确要求的 full，也不得将必测项 SKIPPED 算作完成。

## 3. 锚单一来源

- 机器源：`docs/reference/gate_anchors.json`（主 pytest / prearchive pytest / unit / e2e / sidecar check 的当前锚数字）。
- 更新锚：`python scripts/update_gate_anchor_20260906.py <run_gates 结果 JSON>`——只改 json，不碰 101/INDEX。
- 历史交付报告（036-042 等）正文中的带日期数字一律不改写；当前口径以 json 为准。

## 4. 失败处置

1. **以脚本打印的 Markdown 门禁表为汇总证据，并核对必测子项和跳过原因**；必测项 SKIPPED 不算完成，退出码 0 也不代表所有专项要求均已覆盖；完整原始输出在 `review/gate-runs/<时间戳>/`（不入库），可能截断；发生矛盾时核对原始输出和脚本实现，修正汇总缺陷，不能只凭汇总 PASS 宣称完成。
2. 先定位根因再重跑：单看哪个门红 → 读该门对应输出的失败段（脚本已做二进制安全解析）→ 归因（环境/代码/口径）。
3. **禁止跳过单项硬过**（例如门红就只跑其余项充数）；**禁止为凑绿修改既有测试断言**；获批行为变更可同步更新相关测试并说明覆盖变化。数量下降须核查覆盖，不得自动下调锚掩盖失败；改变既定验收标准仍需批准。
4. 验收失败时暂停依赖该结果的后续工作，先在授权范围内修复代码、环境或脚本并重跑；只有扩大范围、修改业务裁定或降低验收标准时才走升级出口。继续不依赖该失败项的工作。
5. e2e 端口 4173 被占用时脚本只警告并复用（与 Playwright `reuseExistingServer:!CI` 一致）；除非 `--strict-ports` 才 fail。

## 5. 红线引用（不复制正文）

- `AGENTS.md` — "Commands" 节（测试与门禁命令）、"Regression-Sensitive Behavior" 节（勿破坏的回归行为）。
- `开发起步包/00_AI协作规则.md` — §6 git 提交规范（门禁绿 ≠ 可 commit，须用户批准）。
- `docs/ACTIVE/043_*.md` §3 已裁定事实（脚本行为细节）。

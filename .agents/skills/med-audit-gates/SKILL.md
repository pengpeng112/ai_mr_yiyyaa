---
name: med-audit-gates
description: Med-Audit 仓库正式门禁汇总唯一入口（scripts/run_gates_20260906.py）。文档/常规代码改动用 --quick 配合定向测试；里程碑大包交付、发布前全绿验收或基线锚比对时使用 --full --anchor-file。含两档命令、锚源 gate_anchors.json 位置与失败处置流程。
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

门禁项与判据全集见归档作业书 `docs/archive/completed-plans-phase3-prearchive-202609/041_ISOLATED_RULE_CENTER_USABILITY_ONE_SHOT_PLAN_20260904.md` §8；compileall 范围使用聚合脚本（含 `prearchive_service`）；`AGENTS.md` 的直接命令用于局部快检。

"唯一入口"限定为**正式门禁汇总**，不禁止定向测试与诊断命令。三级档位与 `AGENTS.md` §4 对齐：
- **L1（文档/导航改动）**：`check_documentation_20261002.py` + `--quick`；
- **L2（常规单功能/缺陷修复）**：相关定向测试 + `--quick`（原无关存量失败如实报告，不强求全仓 `--full`）；
- **L3（一次性总交付 / 发布前 / 明确要求全绿）**：自主执行 `--full --anchor-file docs/reference/gate_anchors.json`（刷新 `.gitignore` 内的 `static/ui-next/` 无需额外请示授权）。不得用 `--quick` 替代已明确要求的 `--full`，也不得将必测项 SKIPPED 算作完成。

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

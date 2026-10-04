# governance-20260925 归档说明

> 迁移执行：2026-09-28（057 G3，ZCode/GLM-5.3）。本目录是启动治理专项的归档区，与 `navigation-20260925/`（INDEX 历史快照）并列。

## prompts/ — 开发起步包 16 个已完成一次性执行 PROMPT

- 来源：`开发起步包/PROMPT-*.md`（2026-08-27 至 2026-09-21 的 16 份一次性执行提示词，对应任务全部交付，见 `docs/INDEX.md` 各行）。
- 迁移原因：任务均已交付，PROMPT 是当时任务说明、不构成当前授权（`开发起步包/README.md` §3 口径）；启动目录仅保留 00/01/README 三个启动文件。
- 完整性：16 文件逐个按原始字节 SHA-256 前 16 位核对后移动（`review/governance-20260925/archive-manifest.json` 含 old→new 映射与哈希；批次执行记录在 `review/governance-20260925/exec-log.md` G3 节）。
- 旧路径引用：`docs/INDEX.md` 已同步新路径；历史交付报告与《01_统一修改记录》中的旧路径为当时事实，不改写，按 manifest 追溯。
- 恢复方式：按 manifest 反向映射将文件移回 `开发起步包/`（先核实现字节哈希一致），禁止用 git reset/clean 恢复。

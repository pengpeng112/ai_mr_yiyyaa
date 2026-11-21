# 文档入口

请先阅读 [`INDEX.md`](INDEX.md)。它是本项目唯一的文档编号台账、现役状态清单与归档导航。

多 AI 启动流程见 [开发起步包/README.md](../开发起步包/README.md)，跨工具交接模板见 [119 多 AI 协作指南](reference/119_MULTI_AI_COLLABORATION_GUIDE.md)，系统历史升级脉络见 [124 系统历史升级演进总览](reference/124_SYSTEM_EVOLUTION_HISTORY.md)。

- `ACTIVE/`：仅保留真正现役计划、总交接与有效红线文档（9 份），不再堆积历史完结稿。
- `reference/`：长期有效的功能基线、数据/Dify/危急值/企微代理契约、代码目录索引（`120`）、演进编年史（`124`）及门禁锚（`gate_anchors.json`）。
- `archive/`：按演化阶段原字节封存的历史计划、报告、PROMPT、台账封卷与早期草稿；仅用于追溯，不作现行依据。
- `remediation/`：生产整改证据、备份 JSON 与回退说明（`MOCK-20260813`）。
- `attachments/`：历史高危 Excel 报表与架构截图（含 PHI，`.gitignore` 已忽略，禁提交禁外发）。
- `skills/`、`sql/`：防回归参考卡（`med-audit-codex.md`）与 SQL 资产；可执行工作流 Skill 统一归口仓库根 `.agents/skills/`。
- `3一致性核查正式版-质控门禁影子V2.yml`：唯一 Dify 待复核影子工作流，路径被测试和构建脚本硬编码，保留在 `docs/` 顶层。

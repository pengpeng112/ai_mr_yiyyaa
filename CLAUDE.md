# CLAUDE.md

This file provides a lightweight entrypoint for Claude Code when working in this repository.

## 共同启动与规则入口（单一事实源）

1. **最高规则与防回归守则**：先读根目录 [AGENTS.md](AGENTS.md)（核心原则、生产/Git/PHI 授权边界、三级验证矩阵及全栈技术防坑守则）。
2. **多 AI 协作启动与现场恢复**：按 `AGENTS.md` → [开发起步包/README.md](开发起步包/README.md) → [开发起步包/00_AI协作规则.md](开发起步包/00_AI协作规则.md) → [开发起步包/01_统一修改记录.md](开发起步包/01_统一修改记录.md) 末 10 行执行；修改前读 [开发起步包/02_协作任务板.md](开发起步包/02_协作任务板.md) 并核对 `git status --short`，完整保留他人未提交代码；发现用户新建的散落文书/文档时按 `00_AI协作规则.md` §3.1 主动协助规范归位并登记 `INDEX.md`。
3. **跨工具接手与模块导航**：
   - 全栈现状与 JHEMR 七大接口全景：[docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md](docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md)
   - 代码目录与模块索引：[docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md](docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md)
   - 跨 AI 协作与交接模板：[docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md](docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md)
   - 文档索引与现役计划：[docs/INDEX.md](docs/INDEX.md)

> 历史过时的模块地图已于 2026-11-21 移除（避免与 `063` / `120` 重复漂移）。本仓库包含四大业务板块：AI 内涵质控（`app/`）、病历时效质控（`app/timeliness/`）、独立预归档服务（`prearchive_service/`，严禁与主服务互 import）以及 Vue 3 前端（`frontend/`，默认入口 `ui-next`）与企微 H5（`static/*/mobile/`）。

## 常用命令

命令唯一来源 = `AGENTS.md`「常用命令与三级验证矩阵」节（安装、本地启动、测试、门禁聚合 `run_gates_20260906.py`、Docker 全集），此处不重复维护。仅保留以下两条常用运维辅助命令：

```bash
# RBAC 角色与权限首次初始化
python scripts/init_rbac.py

# 查看生产/本地容器实时日志
docker logs -f med-audit
```

# 医疗记录一致性审计系统（Med-Audit / `ai_mrzk`）

## 1. 系统简介

Python 3.11 + FastAPI + Vue 3（UI-Next）全栈病历质控平台，涵盖四大业务板块：
- **AI 语义内涵质控**：从 Oracle / Vastbase(EMR) 抽取多源病历数据，经 Dify Workflow 做 6 类临床一致性审计、四色预警（`red / yellow / blue / gray`）与企业微信高危告警闭环。
- **病历时效质控（`app/timeliness/`）**：18 条时效规则与 5 分钟自动扫描，融合 JHEMR Vastbase 与 HIS/手麻 Oracle，提供全院超时解锁审批、扣罚台账与月度考核。
- **归档前形式预检（`prearchive_service/`）**：与主服务物理隔离（零 `import app.*`）的无纸化规则中心与归档前核查引擎。
- **企微手机端 H5**：面向医务/科室人员的「病历超时解锁查询与时效统计」三 Tab 移动门户。

---

## 2. 文档与协作入口

- **AI 代理总宪章（必读）**：[AGENTS.md](AGENTS.md)
- **多 AI 启动卡与任务路由**：[开发起步包/README.md](开发起步包/README.md)（协作规则 `00`、修改记录 `01`、当前任务板 `02`）
- **文档总索引（编号/状态/归档）**：[docs/INDEX.md](docs/INDEX.md)
- **独立工作区总交接与接口地图**：[docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md](docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md)
- **系统历史升级演进总览**：[docs/reference/124_SYSTEM_EVOLUTION_HISTORY.md](docs/reference/124_SYSTEM_EVOLUTION_HISTORY.md)
- **代码目录索引与协作指南**：[120 目录索引](docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md)、[119 多 AI 协作指南](docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md)
- **架构、部署与代码风格**：[ARCHITECTURE.md](ARCHITECTURE.md)、[DEPLOY.md](DEPLOY.md)、[CODE_STYLE.md](CODE_STYLE.md)

---

## 3. 常用命令速查

```bash
# 本地启动后端（仅开发；生产容器强制 --workers 1；只读查库切勿启动 app.main）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 本地快速门禁（语法 + 命名 + 预检隔离 + sidecar 自检）
python scripts/run_gates_20260906.py --quick

# 文档与归档完整性只读校验
python scripts/check_documentation_20261002.py

# Windows 离线镜像构建与导出
docker_build.bat
```

更多测试、前端构建、全量门禁与生产部署命令统一见 [AGENTS.md](AGENTS.md) 与 [DEPLOY.md](DEPLOY.md)。

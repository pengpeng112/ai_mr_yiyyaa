# 医疗记录一致性审计系统（Backend）

## 1. 项目简介
- FastAPI 后端
- 支持 `SQLite / Oracle` 应用数据库
- 从 Oracle / PostgreSQL 抽取病历与护理记录
- 推送到 Dify 做一致性审计
- 支持四色预警：`red / yellow / blue / gray`

---

## 2. 文档入口

### 快速入口
- 项目总入口：`README_CN.md`
- 当前架构说明：`ARCHITECTURE.md`
- 部署与升级：`DEPLOY.md`
- AI/代理规则：`AGENTS.md`
- 多工具/模型共同启动：`开发起步包/README.md`；当前文件认领与恢复点：`开发起步包/02_协作任务板.md`
- ZCode/zcod、Codex、Claude及GPT/Kimi/GLM/Grok接手方法：`docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md`
- 当前功能计划与文档索引：`docs/INDEX.md`

### prompts
- `prompts/v2_consistency_audit.md`：审计规则（已精简，适合 DeepSeek 30B）
- `prompts/v2_json_output_schema.md`：JSON 输出结构（已精简）

---

## 3. 常用命令

### 本地启动
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 解析器测试
```bash
python scripts/test_parser_v2.py
```

### Docker 打包（Windows）
```bat
docker_build.bat
```

### 健康检查
```bash
curl http://localhost:8000/api/health
```

---

## 4. 推荐阅读顺序

AI 会话统一按 `AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → 按需读取 `docs/INDEX.md`。目录职责及当前任务路由集中在开发起步包 README。

人工了解架构可读 `ARCHITECTURE.md`，部署读 `DEPLOY.md`；具体行为以代码、配置和最新验证为准。仅数据库只读调查时不要启动应用：启动包含数据库初始化和可选调度。

---

## 5. 当前整理结果

- 统一启动、协作任务板、修改登记和检查点，切换工具/模型时共用仓库事实。
- INDEX按用途导航；045/048/050/057原文归档，承接报告保留，不重复执行旧计划。
- 文档专项检查：`python scripts/check_documentation_20261002.py`；正式回归仍使用AGENTS中的门禁入口。
- 文件按模块/生命周期分类；运行代码、配置、数据库、驱动、隐私附件和工具缓存遵守原目录边界。

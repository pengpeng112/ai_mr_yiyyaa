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
1. 先看 `README_CN.md`
2. 开发先看 `docs/INDEX.md`，再按任务读取现役计划与参考契约
3. 部署请看 `DEPLOY.md`
4. 调整 Dify 请看 `prompts/`
5. AI 辅助开发请看 `AGENTS.md`

---

## 5. 当前整理结果
- 已删除重复文档：`开发概述.md`
- 已删除重复提示说明：`docs/dify_json_prompt.md`
- 保留 `AGENTS.md`，因为它会被 AI 工具读取
- `docs/` 的唯一入口为 `docs/INDEX.md`；历史文档仅在 `docs/archive/` 中追溯

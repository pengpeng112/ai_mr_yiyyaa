# 会话压缩记忆（精简版，2026-04-03）

## 1) 当前唯一未完成事项（保留）
- 服务器容器启动失败，最新错误：
  - `ORA-00904: "id": invalid identifier`
  - 触发点：`app/database.py::_ensure_oracle_sequences()` 在 Oracle 中按 `"id"` 查询 `MAX()` 时列名大小写不匹配。
- 本地已修复：
  - `_ensure_oracle_sequences()` 先读取 Oracle 实际列名，再计算 `MAX(实际列名)`。
  - 已本地通过 `py_compile app/models.py app/database.py app/main.py`。
- 下一步：重新打包镜像并上传服务器复测。

## 2) 本地已完成的关键修复（保留）
- Oracle 主键策略：`Identity -> Sequence`（兼容旧 Oracle 环境）。
- 启动阶段自动补齐缺失 Oracle sequence（按 `MAX(id)+1`）。
- 修复 Oracle 重复索引报错（`ORA-01408`）。
- 修复 fallback 解析结果“通知有但不落库”。
- 增强 retry payload 保全（`request_json` 损坏回退 `mr_text`）。
- 强制覆盖 parsed_output 的患者基础信息为权威输入（不信任 LLM 产出）。
- Dockerfile 内置 Oracle 客户端依赖兼容（`libaio.so.1` 软链、`LD_LIBRARY_PATH`）。
- 打包脚本统一 LF 转换，避免 Linux 上 `$'\r'` 报错。

## 3) 已归档（删除后续跟进）
- Docker 网络地址池冲突（已解决，属环境操作问题）。
- `docker_deploy.sh` CRLF 执行失败（已解决）。
- `DPI-1047` 动态库缺失（已解决）。
- `ORA-01400` 主键为空（已通过 Sequence 策略解决）。
- `ORA-02289` sequence 不存在（已加自动补齐逻辑）。
- 提示词过长、文档结构混乱（已精简并整理）。

## 4) 重新部署最短动作
1. 本地 `docker_build.bat` 重新打包。
2. 上传新版 `med-audit-image.tar` 与 `med-audit-docker/`。
3. 服务器停旧容器、`docker load` 新镜像。
4. 保持 Oracle `.env` 配置后执行 `bash docker_deploy.sh`。
5. 验证：`docker logs --tail 200 med-audit`、`/api/health`、`engine.dialect.name`。

---

本记忆文件已按“只保留未完成关键项”压缩，已解决问题全部归档，不再重复跟进。

---
name: ai-mrzk-triage-and-handoff
description: >-
  AI 病历质控系统（ai_mrzk / 10.10.8.84 med-audit）只读线上排障、他方 AI 交付物走查与防呆执行提示词生成规程。
  当用户要求排查 10.10.8.84 质控不通/报错、审查本地开发记录或前端界面、
  或生成给其他 AI 执行的修复/优化/测试任务书提示词时激活本技能。
---

# AI 病历质控（ai_mrzk）只读排障、交付审查与防呆提示词规程

## 1. 安全与红线前置检查
1. 启动与登机前必读本仓 `AGENTS.md` 与 `docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md`（若本机可访问外部运维仓且需核查堡垒机命令细节，可选参考只读文档 `E:\嘉和\docs\通用-环境与连接\63-服务器只读检查手册与速查卡.md`；无法访问时以本仓 `063` 为准，不得据此阻塞）。
2. 默认**严格只读**：严禁未经用户当次明确授权重启容器、修改服务器文件、执行数据库写操作或 DDL/DCL（如 `GRANT` / `ALTER VIEW`），严禁启动 `app.main` 或 `init_db()` 做只读探查。
3. 凭据仅在内存中按需读取或走环境变量，**严禁在脚本字面量、命令行回显、日志或回复中输出明文口令、`SECRET_KEY`、API Key 或真实患者姓名/住院号（6 位及以上数字号段脱敏为 `<ID>`）**。

## 2. 线上故障 4 步只读取证法（消除猜测，先抓铁证）
当用户反馈「AI 质控不通 / 定时不跑 / 页面报错」时，用单次只读诊断脚本在 `10.10.8.84` `med-audit` 容器内顺序核验：
1. **容器与写闸门状态**：核 `docker ps`、`UI_DEFAULT_ENTRY`、`SECRET_KEY` 是否存在（仅打印布尔与长度），以及时效写闸（`jhemr_write.enabled`、`insert_monitor_enabled`、`notify_mode`、`JHEMR_INTEGRATION_ENABLED`）是否保持安全关闭。
2. **前后端版本撕裂比对（MD5 Diff）**：计算容器 `/app/app/` 核心文件（`config.py`、`database.py`、`dify_pusher.py`、`scheduler.py`、`routers/*.py`、`services/*.py`）与本地 `app/` 的 MD5，识别是否存在「新前端 + 旧后端」局部热更错位。
3. **数据源与视图健康穿透**：
   - 检查 `/app/logs/app.log` 尾部非时效报错（重点识别 `ORA-04063` 视图失效、`ORA-24459` 连接池耗尽、Vastbase 超时）；
   - 若遇 `ORA-04063`（如 `JHEMR.V_QYBR` / `V_CYBR`），只读查 `ALL_OBJECTS`、`ALL_ERRORS`、`ALL_DEPENDENCIES` 定位失效子视图，并用 `SELECT 1 FROM HIS.<基表> WHERE 1=0` 验证会话级角色查询权是否仍为 `SELECT_OK`，并核查 `app/services/oracle_patient_view_compat.py` 降级链路是否生效。
4. **Dify 连通性只读验证**：复用 `ConfigParser.parse_dify_config` 解密内存态 Key（不打印），请求 `GET {base_url}/parameters` 验证是否返回 `HTTP 200`，区分「上游取数断」与「下游 Dify 断」。

## 3. 审查他方交付物的 5 项必查清单
1. **无损编辑契约**：表单抽屉保存时是否会洗丢未接管的 JSON 字段（`rawExtras`）？是否有真实种子 `diff === []` 往返单测？
2. **查询与锁安全**：是否存在大视图 `OR` 双列批查慢 SQL？CLI / 后台任务被杀后是否会残留调度锁？异常分支是否 100% 归还数据库连接？
3. **部署完整性**：部署脚本推送文件清单是否漏拷依赖的后端路由/服务文件？是否清理了 `__pycache__` 并 `docker commit` 固化镜像？
4. **认证与安全头**：写请求是否兼容 `security_middleware.py` 的 `X-Requested-With` CSRF 校验？H5 是否严格零内联 `<script>` 且状态使用 `Vue.reactive(state)`？权限未加载时是否 fail-closed？
5. **医务端界面体验**：所有输入框是否有固定中文标签（而非仅靠 `placeholder`）？是否消除了英文状态码/`high-medium-low`/`NULL`/`BFF`/裸 `JSON.stringify`？操作列按钮是否过多挤压？

## 4. 给其他执行 AI 生成「防呆任务书提示词」的标准结构
当用户要求生成提示词交给其他 AI 执行时，提示词必须具体到文件路径、字段名与验收动作，包含以下 5 段：
1. **红线声明**：明确禁写库 IP（`177`/`216`）、保持关闭的写闸开关、禁 `git reset/commit/push`、脱敏要求、部署前打回滚镜像 tag + tar 备份要求。
2. **根因与事实锚点**：把已只读查明的报错原文、失效视图/表名、版本差异文件清单直接喂给执行 AI，禁止执行 AI 盲猜或乱改无关配置。
3. **分阶段精确指令**：指名具体修改文件、函数职责、兼容降级策略（如 `HIS.*` 基表内联降级 + 5 分钟熔断记忆）及前端具体组件改造项。
4. **本地门禁与线上只读冒烟矩阵**：要求 `pytest` + `typecheck` + `vitest` + `npm run build` 全绿，并列出按业务域划分的只读/`dry_run=true` 冒烟清单（严禁触发真实批量计费推送或业务写库）。
5. **交付留痕**：要求产出 `review/` 体检报告并登记 `开发起步包/01_统一修改记录.md` 与 `02_协作任务板.md`。

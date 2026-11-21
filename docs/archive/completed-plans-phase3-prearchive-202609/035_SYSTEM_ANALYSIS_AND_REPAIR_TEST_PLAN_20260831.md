# 035 — 系统前后端问题分析与修复测试计划（multi-review round-4 定稿）

> 文档编号：035 ｜ 编制：2026-08-31 ｜ ZCode/GLM-5.3（multi-review：GLM 起草+初审、kimi/codex 独立审查、grok 缺席-网络故障；分歧表/证据终审见 `review/round-4/`，不入库）
> 性质：修复与测试执行计划。从属 023 体系，不构成生产写入授权。

## 0. 用户原始需求与交付边界（已拍板 2026-08-31）

原话："对系统进行分析看看哪里有问题包括前端和后端，并生成一个详细的测试md计划，我要进行修复和测试，需要一次性执行完成"

**用户裁定（2026-08-31）**：
- **解释甲生效**：本轮只出计划（本文档即交付物）；修复由后续执行者按本计划一次性顺序执行（执行提示词=`开发起步包/PROMPT-20260831_系统修复测试执行.md`）。
- **RP0 已裁定=W1 保留补登记**：8 文件改动已验证（prearchive 212 项：211 passed+1 skipped，isolation/compileall 过）并补登记提交（`fba8090`）。**基线重锚：prearchive=212 项**（原 209 作废）；主服务 1176、ui-next Playwright 46 不变。
- 执行者从 RP8/RP9 起跑（RP0 已完成）。

## 1. 问题清单（终版，三方交叉核验后）

### 配置与安全（本轮新发现，kimi 提出、GLM 实测证实）

| # | 问题 | 证据 | 级别 | 处置去向 |
|---|---|---|---|---|
| C1 | `relay_alert` 明文占位密钥且 config.json 被 git 跟踪：`enabled=true`+`secret_key="change_this_to_a_random_32char_string"`（明文）+`secret_key_enc=""`；`_resolve_secret()` 明文优先。生产实际值未核验（生产 config 为服务器卷挂载，非此文件）；仓库侧=跟踪卫生问题 | config/config.json relay_alert 节；relay_alert_service.py:537-544；`git ls-files` 含 config/config.json（先提交后 ignore，ignore 对已跟踪文件无效） | 中高（待生产核验定级） | RP8 |
| C2 | jyjc_vs_bcnursing 的 nursing fanout `field_mapping` 编码损坏：`patient_id='??ID'`、`visit_number='??'`（同源 lab/exam/progress 均为正确中文列名"患者ID"/"次数"）→ fanout 患者键静默失配风险 | config/config.json jyjc sources.nursing.field_mapping 实测 | 中 | RP9 |
| C3 | syssvsscbc 10 个 enabled Dify target `api_key_enc` 全空且类型级无兜底 key（对比 progress_vs_nursing/jyjc 均有）→ 推送批量 401 风险（全局回退是否存在待证） | config/config.json 实测：targets=10 empty=10 | 中 | RP9 |

### 后端（主服务）

| # | 问题 | 证据（终版） | 级别 | 处置 |
|---|---|---|---|---|
| B1 | discharge_final 转换：3 类型有专属转换；**通用 fallback 已在**（scheduler_run_modes.py:187-205 全 source 追加出院日期过滤，无 {dept_filter} 时按 date_dimension=discharge_date 加载）——原"仅 3/6、其余漏患者"说法系 AGENTS.md 旧文档漂移（文档须同步）。**残余风险=①fallback 对 admission_vs_first_progress/surgery_chain/discharge_vs_frontpage 真实 SQL 的有效性未验证（过滤硬编码别名 a."出院日期"，SQL 无该别名即失效且无告警）②合法类型 fallback 未命中时仅 info 日志无告警** | 实读 scheduler_run_modes.py:140-210；kimi 证 scheduler.py:517-520 已拒绝不存在的类型（防呆仅缺"合法但不生效"） | 中 | RP2（验证+告警+文档同步） |
| B2 | 双调度确定重叠：daily.codes=[] 回退 default_for_schedule（三类型均 true）→daily 必跑 progress_vs_nursing；discharge.codes=['progress_vs_nursing'] → **同一类型两 job 双跑**。结果层 superseded 覆盖在，**推送层是否双发待实测**；终末结果不应被简单"当日去重"吞掉（codex 裁定） | config.json:1192/1201 双 enabled；scheduler.py:551-552 回退逻辑；kimi 行号级核验 | 中 | RP1（时间线实测→策略设计） |
| B3 | requests==2.32.3（CVE-2024-47081 修复版 2.32.4）；cx_Oracle 8.3.0 legacy；passlib 1.7.4 无维护（bcrypt 锁 4.0.1） | requirements.txt:6,8,11,12 | 低 | RP5（仅升 requests==2.32.4；其余注记+风险登记） |
| B4 | 主服务 pytest 37 条 SQLAlchemy deprecation（开发机 Python 3.14 环境；生产 pin 3.11 不受影响——codex 环境定位修正） | 2026-08-30 全量 pytest 输出（1176 passed/37 warnings） | 低（开发环境） | RP5（显式 adapter 注册，或登记接受） |
| B5 | 运行指标快照漂移：PPT 164,865/105,694/705,432 vs 生产实测 190,271/120,197/828,771（2026-01-01~09-01，MED_PUSH_LOG/MED_AUDIT_DIMENSION_RESULT，容器内只读 SQL）；系统无指标元数据 | 2026-08-31 生产容器只读核验 | 中 | RP3（元数据块，非仅 as_of） |

### 前端

| # | 问题 | 证据（终版） | 级别 | 处置 |
|---|---|---|---|---|
| F1 | ~~响应无 CSP~~ **已被 codex 推翻**：security_middleware.py 已设 CSP（`script-src 'self' 'unsafe-eval'`，unsafe-eval 为 legacy Vue 运行时模板编译必要）+nosniff+Referrer-Policy，含单测。app.js:49 innerHTML 为同源模板加载，现状可接受 | app/main.py:158-159；security_middleware.py:20-30；tests/test_cookie_csrf_security.py:144 | 低（观察项） | RP6（不收紧 CSP；追踪 unsafe-eval 解除条件） |
| F2 | 双 UI 并存生产入口=legacy；WP6 canary BLOCKED（四角色凭据/Relay 批准包/测试科室/脱敏长数据）；ui-next 镜像手工 sync 漂移风险 | 020；frontend/package.json | 中（验收类） | RP6 + 外部依赖登记 |
| F3 | 现场验收缺口：audit_types prearchive 卡片/P1-08 对称性未跑真浏览器 E2E；**Playwright 基线配置 base URL=/ui-next/，不覆盖 legacy 页**（codex 证）——legacy 用例需独立配置 | frontend/playwright.config.ts:3-6,32-39 | 中 | RP6 |

### 预检服务/流程

| # | 问题 | 级别 | 处置 |
|---|---|---|---|
| P1 | 生产未启动；上线须 anchor_mode=paperless_rpa（默认 finished 在 177 全 NULL=零触发） | 中 | RP7（runbook） |
| P2 | 心电 xd 未接、检验/首页 FID null、visit_index 映射待 W9 | 低 | 外部依赖登记（§8） |
| W1 | 工作区 8 文件未登记改动（+137/-35，T8-3 后续 dept_matcher 等）。**处置禁裸 checkout（kimi/codex 共识）：先 `git diff > patch 备份` → 用户裁定 保留补登记 / 丢弃（用备份可恢复）** | 高（前置阻塞） | RP0 |

## 2. 覆盖矩阵（已检查/未检查，如实标注）

| 域 | 已检查（方法） | 未检查（后续） |
|---|---|---|
| 后端 | 调度双模式源码实读、安全中间件实读、依赖 pin、pytest 全量（1176）、生产指标只读对账 | 全部路由逐个权限矩阵正反测、DB 迁移/后台线程逐线审、Oracle p95/p99 性能、023 已登记开放项（WP5-WP11 现场类，见 §8 引用不重复盘点） |
| 配置 | relay 密钥链路、6 类 field_mapping 对照、Dify target key 完整性 | 其余配置节（dify 重试/熔断参数、notify、RBAC 种子） |
| 前端 | XSS 面（innerHTML 2 处定位）、CSP 中间件、双轨入口、测试基建、TODO 清零 | 逐页交互逻辑（表单校验/分页边界/权限 UI）、WCAG、长文本/错误态 |
| 预检 | 生产启动状态、anchor 适配、规则版本 | 真实源影子运行（W9 后） |

## 3. 修复任务包（终版，按依赖重排）

- **RP0 前置裁定（W1）**：`git diff prearchive_service/ > review/round-4/w1_backup.patch` 备份 → 用户裁定：a) 保留→补 01 登记+提交（prearchive 基线重锚）；b) 丢弃→`git checkout -- prearchive_service/`（patch 已备份可恢复）。**未裁定不得进 RP1+**。
- **RP1 双调度双发实测与治理（B2）**：①生产只读建事件时间线（同患者同日 daily+discharge 双结果、双告警计数）②本地 fixture 复现③按证据选策略：允许双发（业务两时点）/终末覆盖时抑制 daily 推送/延迟 daily/仅抑制完全相同版本——**不做盲目当日去重**。补 pytest ≥6。
- **RP2 discharge fallback 验证+防呆（B1）**：①对 3 类型真实 SQL 静态验证 {dept_filter} 存在性与 a."出院日期" 别名适配（不匹配=改写或显式不支持清单）②scheduler 配置保存与 /api/scheduler/status 增"fallback 未生效"告警③AGENTS.md/INDEX 双模式节同步代码现状。补 pytest ≥4。
- **RP3 指标元数据（B5）**：统计/导出响应附元数据块 `generated_at/date_from/date_to/timezone/filters/semantics(current-only)`；前端统计页展示口径时间；导出链路保持 record_export_audit()。补 pytest ≥3+前端断言。
- **RP4（撤销原 CSP 方案）**：改为 CSP 现状回归用例固化（防未来误删 unsafe-eval）+ 登记 unsafe-eval 解除条件（legacy 下线后收紧）。零生产变更。
- **RP5 依赖与告警（B3/B4）**：requests `==2.32.4`（精确 pin，非 2.32.4+）→ 同步 requirements.linux/windows.txt + packages/ 离线轮子重打包 + 镜像重建验证（生产生效链）；cx_Oracle/passlib 登记风险接受人=用户。B4 在生产 3.11 不受影响前提下登记接受，开发机 adapter 修复为可选。
- **RP6 前端验收包（F2/F3）**：①legacy E2E 独立 playwright 项目/配置（base URL=/，登录态，mock /api/audit-types/prearchive）覆盖登录/菜单/质控类型页含 prearchive 卡片/推送/日志/统计/配置错误态 ②ui-next 基线 46 不回退+新增 ≥2 ③E2E 前置 `npm --prefix frontend run build` ④四角色现场验收 checklist（材料齐备前不启动 canary）。
- **RP7 预检上线 runbook（P1）**：纯命令清单（非脚本，codex 口径）：生产 config 受控回填 anchor_mode=paperless_rpa 步骤、影子运行（push.enabled=false）7 天对账门禁（成功率/误报阈值在 runbook 定义）、心电留位。跨天阶段，不阻塞 RP1-RP6。
- **RP8 配置卫生（C1）**：生产只读核验 relay secret 实际值（占位串是否真在生产）→ 是：当次授权换 enc 密钥+更新 relay 侧；仓库侧：config.json 移出 git 跟踪（`git rm --cached` + 保留 example），历史占位串评估轮换。
- **RP9 配置修复（C2/C3）**：C2 修复 nursing field_mapping 编码（对照列名实库核验后改）+fanout 加载回归测试；C3 补 syssvsscbc 类型级 api_key_enc（或确认全局回退存在并补测试）——**涉及生产凭据写入走受控配置，不落仓库**。

## 4. 详细测试用例（关键包逐用例）

**RP1（test_scheduler_dedup）**：T1 同患者同类型 daily 后 discharge 到达→按选定策略断言推送次数与 current 归属；T2 不同患者互不影响；T3 discharge 先到 daily 后到（迟到场景）；T4 重试路径不重复计费推送；T5 Oracle 方言（SQL 文本断言/monkeypatch dialect）；T6 supersede 语义不破坏（复用 test_push_log_supersede 断言集）。
**RP2（test_discharge_fallback_guard）**：T1 admission_vs_first_progress SQL 含 {dept_filter}→fallback 注入断言；T2 surgery_chain 无别名 a→告警字段触发；T3 配置保存拒绝/告警合法但不支持类型；T4 /api/scheduler/status 含告警键。
**RP3（test_metrics_metadata）**：T1 统计响应含完整元数据块；T2 窗口过滤正确；T3 导出审计仍记录。
**RP6（legacy e2e）**：T1 登录→质控类型页→prearchive 卡片渲染 14 条；T2 prearchive 目录不可用时 fail-open 提示；T3 CSP 头存在且含 unsafe-eval（现状固化）。

## 5. 回归矩阵（AGENTS regression-sensitive 逐项过）

serial/bulk 推送语义一致；单条事务失败隔离；双 job 独立锁；Oracle 空串=NULL；pushed/reviewed/manual_override/skip_reason 保留；/api/logs NULL 容忍+全字段；新导出 record_export_audit；Dify mr_text→mr_txt 仅 pusher 映射；base_url 规范化；relay 部分保存不覆盖；Vastbase 大写列名 .lower()；paperless 不入 documents；两轨规则合并加载；PHI（IDNo）丢弃。执行方式：指向既有测试文件清单（test_push_executor/test_push_log_supersede/test_logs_export…/test_pa_*）逐套跑通+新增断言。

## 6. 一次性执行主线与 checkpoint

RP0(裁定) → RP9/RP8(配置，先治标防 401/失配) → RP1 → RP2 → RP3 → RP4 → RP5 → RP6 → 全绿门禁 → （RP7 跨天并行）。每包完成写 checkpoint（完成态/测试数/未决项）到 `review/exec-log.md`，中断可从断点续跑；门禁任何一步红即停该包修复，不带病前进。

## 7. 全绿门禁（终版命令，仓库根执行）

```
python -m compileall app tests scripts
python -m pytest                      # 0 failed，无意外 skip；计数对比 RP0 后重锚基线
python scripts/check_naming_convention.py
python -m pytest prearchive_service/tests -q
python prearchive_service/check_isolation.py
npm --prefix frontend run typecheck && npm --prefix frontend run test:unit
npm --prefix frontend run build       # E2E 前置
npm --prefix frontend run test:e2e
```
基线主判据=0 failed+无意外 skip；基线计数（当前 1176/209/46）仅报告用，RP0 裁定后重锚。

## 8. 不修复/外部依赖登记（责任与触发条件）

| 项 | 等什么 | 风险接受 |
|---|---|---|
| WP6 canary/四角色现场 | 凭据/批准包/测试科室/脱敏长数据 | 用户 |
| 023 WP5-WP11 现场类开放项 | 现场资源 | 用户（已登记于 023，不重复） |
| 心电/FID/W10/W9 | 用户提供 | 用户 |
| cx_Oracle/passlib 维护性 | 下一代重构窗口 | 用户 |

## 9. 验收清单

- [ ] 用户拍板 §0 解释甲/乙；[ ] RP0 裁定+基线重锚；[ ] RP1-RP9 各带测试全绿；[ ] §5 回归矩阵逐项过；[ ] §7 门禁一次通过；[ ] 每条问题有 RP 或 §8 登记；[ ] 035/INDEX/01 登记齐；[ ] 报告标注 grok 缺席。

## 10. multi-review 记录

GLM 初审 sha256 9f88a1fd…；kimi 审查 3.6K 字（8 项断言核验全属实+3 新发现）；codex 检查 30 条（2 项推翻 GLM 事实引用均经代码实读证实）；grok 缺席（网络错误）；分歧表 7 事实+8 取舍全部证据/共识裁决，无仍冲突免对辩。产物 `review/round-4/`（不入库）。

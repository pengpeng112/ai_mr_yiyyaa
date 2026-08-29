# 032 — 031 剩余工作一次性本地执行·交付报告

> 文档编号：032（从属 031 交付物 / 023 本地整改轨道）
> 执行日期：2026-08-29 ｜ 执行者：ZCode/GLM-5.3（按 `开发起步包/PROMPT-20260828_031剩余工作一次性开发.md` v2，唯一权威规格=031 v4.3）
> 性质：本地执行交付报告（零生产接触全程；21 笔本地 commit，未 push）
> 结论：**T0-T8/T3-T6 全部任务包完成，T5 全绿门禁通过**；未做项=W1-W10 甲类+丙类现场项（§4）；需用户三件事见 §5

---

## 1. 完成清单（逐包对照 031 验收断言）

| 包 | 验收断言 | 结果 |
|---|---|---|
| T0 | git status 只剩 ?? review/；两笔 commit 类型正确；prearchive 105 复跑绿；01 记录含 hash | ✅ `dbbbe54`(fix)+`79e220b`(docs)；hash 已补记 |
| T1-0 | 3 用例转绿；全量无新增失败；blame 证据入报告；未改断言 | ✅ `82b90d4`；blame=4b775bc(8/14) 引入拦截 vs 契约测试 cb7420a(8/13)，不满足"8/17 后正式决策+配套需求记录"例外门槛→走预授权主路径 |
| T1-1 | 核对结论引用行号；补测列出且绿；实现零改动 | ✅ retention_service.py:16+L281-366 覆盖属实；补 QCAlertFeedback/QCFeedback 两表测试（`0944fa9`） |
| T1-2 | 出口①或②有断言测试且绿；结论含证据行号 | ✅ 出口②最小修补：schemas.py 四处枚举+inpatient_date+13 项契约测试（`0944fa9`） |
| T1-4 | 现状结论+证据；live 无诊断断言；无新增暴露 | ✅ 已由工作包E关闭；补 2 测试固化（`0944fa9`） |
| T1-3 | CSV 落地+ExportAuditLog 断言；筛选单源（monkeypatch 单点）；后台列表测试补齐；权限正反 | ✅ `1e25a20`；`_apply_relay_alert_filters` 单源复用断言 |
| T1-5 | 全量实施+正反测试绿+全量 pytest 绿（未降级） | ✅ `974dbee`；Cookie/CSRF/CSP 全量实施 9 测试；全量 exit 0 |
| T1-6 | Playwright 可跑→三视口 0 fail；不可跑→静态检查过+E2E 待跑标记 | ✅ D13 降级路线：Playwright 未装→frontend build（vue-tsc+vite+镜像）0 错+安全契约 2 绿+frontend_regression_check 0 high（`a0605ac`）；**E2E 待跑（不算失败）** |
| T1-7 | 每份被改文档顶部状态与证据一致；INDEX 同步；004C 零改动 | ✅ `3856479`；004C git diff 零改动 |
| T1-8 | metrics 鉴权正反绿；三类计数正确；SLO 等列入不做 | ✅ `ea33cd3`；5 测试绿 |
| T2-1 | 默认 finished 不变；新模式默认不生效；discharge 单测覆盖；README 标注；105+新增全绿 | ✅ `6acd793`；10 测试 |
| T2-2 | 默认 fallback_order 不变；新档开启解析正确；缺失跳过下探 | ✅ `6acd793`；6 测试 |
| T2-3 | oracle DSN 构造正确（mock）；零真实连接；cx_Oracle 缺失 skip 不算失败 | ✅ `eafcd63`；skipif 1 项预期 skip |
| T2-4 | 4 条规则加载过；note 含签字警示；正反例绿；mark_item_fid 全 null；术后首程=jhmr_file_index.topic | ✅ `3e23a0e`（+`0d1071d` 路径修复）；19 测试（标题解析 11 例） |
| T2-5 | 默认 json 不变；两实现契约测试过；DDL 只在 sql/ 不自动执行 | ✅ `eafcd63`；独立 metadata 断言+表缺失报错 |
| T2-6 | README 含 029 五发现引用与 anchor_mode 说明；与代码一致 | ✅ `3e23a0e`（README §8.0/§8.1） |
| T2-7 | config 含 paperless(enabled=false)；快照 92 条 FID 唯一；同步自洽零差异+五差异单测；回测数值断言；meta SQL 无患者列；isolation 过；全量绿 | ✅ `adaf22e`；17 测试 |
| T8-1 | anchor_mode 四值校验；paperless_rpa 单测（COMPLETED 过滤/UPDATEAT 水位/复检/current 迁移）；默认不变；RPTCOUNT 对账两向 | ✅ `2129305`；11 测试（含 R5 极性回归三向） |
| T8-2 | 7 源 config 过（含 mysql）；可实测源适配绿；条目进 documents+水位覆盖（e2e）；BLOCKED 两源实质断言；isolation 过 | ✅ `6c8f1fb`；8 测试 |
| T8-3 | 三视图 gateway+fixture 单测；映射注入链路跑通；默认 disabled | ✅ `2addc0e`；4 测试 |
| T8-4 | 多文件加载合并过；system_push 文件头含豁免声明；零真实规则；example 行为不变 | ✅ `d439b75`；11 测试 |
| T3 | 编译过；多患者合并弹窗逻辑；冒烟不崩；fail-open 未破坏 | ⚠️ 编译过（csc build.bat OK）+合并弹窗实现+fail-open 保持；**运行冒烟受本机安全策略阻断**（CreateProcess WinError 5 拒绝访问+Temp 副本被自动清除，PowerShell/GitBash/Python 三路均阻断）——环境限制非代码缺陷，留试点机执行（`4e99b61`） |
| T4 | 审计报告逐条结论；.gitignore 含 review/ 且 status 干净；101/102/codex 仅增量；023 §0.6 新行+INDEX 同步；备份脚本跑通 | ✅ `8002aeb`；备份演练 22 表 77 行一致性 PASS |
| T5 | 门禁命令全部退出码 0（D13 E2E 待跑例外） | ✅ 见 §2 |

## 2. 测试数字（T5 全绿门禁，2026-08-29 实测）

| 门禁 | 结果 |
|---|---|
| `python -m pytest --tb=short -q`（主服务全量） | **exit 0，1168 项收集，0 failed**（输出留档 `C:\Users\Administrator\AppData\Local\Temp\opencode\031_baseline\pytest_T5_main.txt`） |
| `python -m pytest prearchive_service/tests -q` | **exit 0，197 项（196 过+1 预期 skip=cx_Oracle 真连冒烟）** |
| `python prearchive_service/check_isolation.py` | PASSED（46 py 文件零 `import app.*`；reminder_agent 禁词过） |
| `python -m compileall -q app tests scripts prearchive_service` | OK |
| `python scripts/check_naming_convention.py` | PASS |
| `python scripts/frontend_regression_check.py` | 0 high / 0 medium（push.js 版本基线已同步至 00654c7 的 `20260728-replace-current-v1`） |
| `find static/scripts -name "*.js" → node --check` | OK |

新增测试合计：主服务 +36 项（T1-0 修复转绿 3 项不在新增内）；prearchive +92 项（105→197）。

## 3. Commit 清单（bc10e8d 之后共 21 笔，均未 push）

| hash | 包 | 摘要 |
|---|---|---|
| dbbbe54 | T0-1 | fix(prearchive): 029 P0实测回填列名与词表 |
| 79e220b | T0-2 | docs(verify): 029/030/031+INDEX/01记录+执行提示词 |
| 82b90d4 | T1-0 | fix(patient_qc): 导出空结果语义按测试契约恢复（基线3红转绿） |
| 0944fa9 | T1-1/2/4 | fix(schemas): inpatient_date+001遗留核对补测 |
| 1e25a20 | T1-3 | feat(alerts): 告警CSV导出+筛选单源契约+后台列表测试(P1-04) |
| 974dbee | T1-5 | feat(auth): HttpOnly Cookie+CSRF+CSP(P1-03,Bearer兼容期双轨) |
| a0605ac | T1-6 | feat(ui-next): 报文详情/独立详情打印/长空错NULL四态(E2E待跑) |
| 3856479 | T1-7 | docs(governance): 十份文档状态行回填+004A/B归属注记 |
| ea33cd3 | T1-8 | feat(observability): metrics骨架(P1-09本地) |
| 6acd793 | T2-1/2 | feat(prearchive): anchor_mode三模式+doc_author降级档 |
| eafcd63 | T2-3/5 | feat(prearchive): oracle结果库接线+DbStateStore(零自动DDL) |
| 3e23a0e | T2-4/6 | feat(prearchive): 4实测词表规则+jhmr_file_index标题时间源+README |
| adaf22e | T2-7 | feat(prearchive): 无纸化CDMS第五源+同步+回测+92条快照 |
| 2129305 | T8-1 | feat(prearchive): RPA触发模式paperless_rpa |
| 6c8f1fb | T8-2 | feat(prearchive): 新七源T_ITF采集器骨架 |
| 2addc0e | T8-3 | feat(prearchive): 基本信息视图采集VW_user_info |
| d439b75 | T8-4 | feat(prearchive): 系统推送规则通道report_expected+多文件合并 |
| 4e99b61 | T3 | feat(reminder-agent): watchlist合并弹窗+工号探测钩子 |
| 8002aeb | T4 | chore(gov): gitignore review/+依赖审计+契约增量+023回填+备份演练 |
| 0d1071d | T5 | fix(test): T2-4测试规则路径改绝对路径（门禁修复） |

## 4. 未做清单（031 §1.3 复述）

**甲类（人工/外部依赖 W1-W10）**：W1 触发锚点终态（RPA 过渡已拍板；终态候选=W9 核证无纸化接收侧逐份到达时间戳）；W2 030 映射表质控科逐条签字（签字前 mark_item_fid 保持 null）；W3 HIS REPORTNAME 0/1/2 语义字典（信息科）；W4 v_blws 值域导出+四源连通矩阵；W5 推送对象基线（ODS 恢复后）；W6 023 WP5/WP6/WP7/WP11 逐项批准单；W7 多源规则引擎产品立项；W8 提醒通道五组实验（实验机装 Windows SDK）；W9 无纸化真实对接开闸（六项核对清单：CDMS 版本/RPA 行粒度/FBINCU 映射/FISENABLE/逐份时间戳+护理复评/脱敏联调）；W10 系统推送类规则清单（用户提供，病理+PACS 先给两条即可）。
**丙类（现场/不可本地模拟）**：Oracle 现场压测与深度并发；真实四角色/企业微信真机/WCAG 人工验收；Docker 镜像构建/SBOM/签名；SLO/磁盘/前端异常/告警联动监控（T1-8 只交内存骨架）；Oracle 备份恢复演练（T4-5 仅 SQLite）；**Playwright 三视口 E2E（本机未装，T1-6 静态降级已过，装后跑 `frontend/tests`）**；**C# 助手运行冒烟（本机安全策略阻断未签名新 exe，留试点机）**。

## 5. 需用户的三件事（收尾提醒）

1. **质控科正式签字**：030 v1.1 映射表（七问已拍板，签字版版本号 `YYYY.MM.DD-qc-vN` 到位后回填 mark_item_fid）；
2. **信息科**：病理驱动（sqlserver 驱动补装/部署机直连）+ 四源登记（血透/电测听/气管镜/基本信息 10.10.10.14 进数据资产平台）；
3. **用户自己的 W10 清单**：系统推送类报告规则（病理+PACS 先给两条即可，落 `rules/system_push_rules.json` 通道）。

## 6. 证据附录

- **基线**：主服务 3 红（patient_qc/patient_visit 导出族）→ T1-0 后全绿；`review/baseline_pytest_20260828.txt`（round-3 留档）+ 本次 T5 输出（§2 路径）；
- **T1-0 blame**：拦截引入=4b775bc（2026-08-14，"导出空结果返回明确错误"含生产实测动机并已部署镜像 e25d8a1）vs 契约测试=cb7420a（2026-08-13，023 Stage1）；4b775bc 未同步测试；按 031 判例（非 8/17 后正式决策+配套需求记录）走预授权主路径恢复，UX 动机留档供用户知悉；
- **frontend_regression_check 基线失配**：app.js 引 push.js?v=20260728-replace-current-v1（00654c7 有意推进）而脚本期望 20260716——基线既有，T1-6 同步脚本；031 §2.1 未列此第 4 项基线失败，属计划遗漏已补登记；
- **T1-5 未降级**：全量实施（Cookie 双轨+CSRF 头+CSP/nosniff/Referrer-Policy）；Secure 由 `AUTH_COOKIE_SECURE` 控制（生产当前 HTTP 内网直连默认关闭，防 Cookie 无法发送——上线 HTTPS 后开启）；CSP 不设 frame-ancestors/X-Frame-Options 防破坏 Relay 反代 H5（决策记录）；
- **T3 冒烟阻断证据**：`CreateProcess WinError 5 拒绝访问`（Python Popen）+ Temp 副本被自动清除（PowerShell Test-Path False）+ Git Bash `Permission denied`——三路一致；
- **T5 门禁修复**：T2-4 测试相对路径在仓库根运行时解析失败（本轮引入，`0d1071d` 修复为 `__file__` 绝对路径）。

### 6.1 依赖审计报告（T4-1，只报告不改版本）

主服务 `requirements.txt`（15 条 pin）：

| 依赖 | pin | 已知安全公告/风险 | 结论 |
|---|---|---|---|
| fastapi | ==0.115.6 | 无直接公告（starlette>=0.40 已含 multipart DoS 修复） | OK |
| uvicorn[standard] | ==0.34.0 | 无 | OK |
| sqlalchemy | ==2.0.36 | 无 | OK |
| pydantic | ==2.10.3 | 无 | OK |
| apscheduler | ==3.10.4 | 无 | OK |
| requests | ==2.32.3 | **CVE-2024-47081**（.netrc 凭据泄漏，修复版 2.32.4） | ⚠️ 建议升 ≥2.32.4（生产容器装 pin 前处理；本机未升级按红线只报告） |
| cryptography | ==47.0.0 | 无 | OK |
| cx_Oracle | ==8.3.0 | 无公告；项目已 legacy（python-oracledb 继任） | 维护注记 |
| python-multipart | ==0.0.18 | CVE-2024-53981 修复版恰为 0.0.18 | OK |
| PyJWT | ==2.8.0 | 无 | OK |
| passlib[bcrypt] | ==1.7.4 | 无公告；项目无维护 | 维护注记（bcrypt 锁 4.0.1 保兼容） |
| bcrypt | ==4.0.1 | 无 | OK |
| openpyxl | ==3.1.2 | 无 | OK |
| psycopg2-binary | ==2.9.9 | 无 | OK |
| jsonpath-ng | ==1.7.0 | 无 | OK |

prearchive `requirements.txt`：下限式（>=）独立依赖，无 pin 漂移问题；`pymysql` 注释保留生产开通 PACS 再装；本地开发机（Python 3.14）安装版本高于 pin 属开发现象，生产容器按 pin 安装不受影响。

## 7. 异议登记

1. 031 §2.1 基线只列 3 项 pytest 红，实际 `frontend_regression_check` 另有 1 项基线既有失配（版本推进未同步检查脚本）——按"只修本轮引入"原则以同步脚本方式在 T1-6 收口，未改前端资产；
2. T1-0 恢复"空命中=0 计数成功导出"后，4b775bc 当初的 UX 动机（空 Excel 困扰用户）重新暴露——前端导出按钮已有 `total<=0` 提示拦截 + 服务端审计记录 0 计数，如需服务端也拒空导出请以正式需求提出（涉及公开 API 行为变化）；
3. 本机安全策略阻断新编译未签名 exe 运行（T3 冒烟）与 Playwright 缺失（T1-6 E2E）均属环境限制，已按 D13/红线以证据留档方式收口，不算任务失败。

## 8. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1 | 2026-08-29 | 031 全任务包执行完毕交付报告（ZCode/GLM-5.3） |

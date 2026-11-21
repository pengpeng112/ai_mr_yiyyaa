# 执行任务书 `PROMPT-WP06`：质控规则中心三轨重构 + 交互简化 + JHEMR 提交前 AI 提醒预留（主推路线 B）

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 6 / 10）  
> **预计耗时**：约 3.5 小时  
> **前置依赖**：必须已完成 `WP-02`（`prearchive-rules` 菜单与路由占位已注册）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → `开发起步包/02_协作任务板.md` → **`开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`** → `git status --short` 存 `review/064-wp06/git_status_before.txt`。

---

## 一、任务背景与已拍板业务口径

解决用户反馈第 9 项（**用户正式拍板 D4**）：
1. **质控规则中心清晰三轨架构**：
   - **第一轨 · 时效锁定规则（菜单 `timeliness-rules`，路由 `/governance/timeliness-rules`，页面 `features/timeliness/RuleListPage.vue`）**：联动嘉和电子病历（JHEMR）做事前/事中时限锁控与预警；
   - **第二轨 · AI 内涵质控规则（`/governance/audit-types`）**：基于 Dify 大模型做内涵语义质控，**并预留后期将 AI 高危问题推送 JHEMR 在提交病历时提醒的能力**；
   - **第三轨 · 归档前形式预检规则（`/governance/prearchive-rules`）**：独立成页（从原 `AuditTypesPage` Tab 2 剥离），面向病案室管理无纸化常见打回规则与系统推送报告规则，并预留 **「确定性规则 + AI 语义混合规则」** 扩展位。
2. **AI 高危问题推送 JHEMR 提交提醒（用户拍板 D4）**：
   - **双路支持，主推路线 B**（嘉和客户端提交病历前调用本系统 HTTP 接口拉取该患者未闭环高危 AI 问题，配合后续客户端对接），同时配置与数据结构兼容路线 A（`177 FILEVERIFY` 受控写入）。
3. **界面去繁就简、方便人维护、强守无损往返**：
   - 隐藏开发级 SQL/JSONPath/Schema 到默认折叠的「技术高级配置」；
   - 规则编辑抽屉强制 `rawExtras` 透传，确保保存一次绝不洗丢任何高级字段（附 Vitest 真实模板 `diff === []` 往返单测）。

---

## 二、允许修改与新增的文件白名单（严禁改动白名单外文件）

### 允许新增
1. `frontend/src/features/governance/components/AuditTypeWizardDrawer.vue`（AI 规则 3 步式清爽编辑抽屉，带 `rawExtras` 无损透传）
2. `frontend/tests/unit/audit-type-roundtrip.test.ts`（基于真实 `config/config.json.template` 的无损往返单测）+ `tests/test_wp06_jhemr_ai_reminders.py` + `review/064-wp06/`
3. `tests/test_wp06_jhemr_ai_reminders.py`

### 允许修改
1. `app/services/audit_type_registry.py` & `app/routers/audit_types.py`（支持保存/读取可选 `jhemr_reminder_policy` 配置块，向后兼容零破坏）
2. `app/routers/jhemr_integration.py`（新增面向嘉和客户端路线 B 的标准化只读拉取接口 `GET /api/integrations/jhemr/ai-reminders`）
3. `app/services/prearchive_rules_view.py`（兼容透传可选 `engine_mode`：`deterministic` / `ai_hybrid` 字段，缺省默认 `deterministic`）
4. `frontend/src/features/timeliness/RuleListPage.vue`（按三轨统一视觉优化：顶部定位横幅 + 临床阶段胶囊筛选 + 精简 7 列表）
5. `frontend/src/features/governance/AuditTypesPage.vue`（专注第二轨 AI 规则：拆分活跃 6 条与待配置模板 6 条 + 接入 3 步式抽屉，移除原预检混合 Tab）
6. `frontend/src/features/governance/PrearchiveRulesPage.vue`（替换 WP-02 占位页，建成独立清晰的第三轨规则页）
7. `开发起步包/01_统一修改记录.md` & `开发起步包/02_协作任务板.md`

> **注意**：严禁在 `prearchive_service/` 中引入任何 `app.*` 导入；本包无需触碰 `prearchive_service/` 核心引擎代码。

---

## 三、后端详细实施规范

### 3.1 `audit_types` 扩展 `jhemr_reminder_policy` 配置段（零破坏既有配置）
1. 在 `app/services/audit_type_registry.py` 允许每条 `audit_type` 携带可选嵌套对象 `jhemr_reminder_policy`（缺省自动补全安全默认值，**默认关闭 `enabled: false`**；先读该文件中已有的字段白名单/校验/脱敏逻辑，若存在「未知键拒绝或剔除」的机制，必须把 `jhemr_reminder_policy` 加入允许列表，否则保存后会被洗掉）：
   ```json
   "jhemr_reminder_policy": {
     "enabled": false,
     "delivery_mode": "pull_api",
     "severities": ["high"],
     "trigger_stage": "before_submit",
     "block_submit": false,
     "exclude_reviewed": true,
     "message_template": "【AI内涵质控提醒】发现{severity}风险（{audit_type_name}）：{summary}"
   }
   ```
   - 校验约束：`delivery_mode in {"pull_api", "fileverify_write", "both"}`；`severities` 仅允许 `{"high", "medium", "low"}` 子集；`trigger_stage in {"before_submit", "on_save", "before_discharge"}`；
   - 保留原有全部校验（SQL、`$` 开头 JSONPath、API Key 加密脱敏、`mr_text` 命名），老配置缺失该键时 100% 兼容不报错。

### 3.2 新增面向嘉和客户端（路线 B 主推）的高危提醒拉取接口
在 `app/routers/jhemr_integration.py` 新增：
- **端点**：`GET /api/integrations/jhemr/ai-reminders`
- **鉴权与开关**：
  - **必须复用** `app/routers/jhemr_integration.py::_verify_request(request, body)`：它已包含 `JHEMR_INTEGRATION_ENABLED`（默认 false → 503）与 `X-Jhemr-Client-Id / Timestamp / Nonce / Signature` HMAC 校验。GET 请求 `body=b""`，照文件内其他 GET 端点（如 `GET /integrations/jhemr/submission-checks/{check_id}`）的写法调用。**不得新增 API Key、IP 白名单等任何其他鉴权方式，不得绕过该函数。**
  - 另增配置开关 `jhemr_ai_reminder.enabled`（`config.json` 顶层，默认 `false`）：总开关已开但此开关关闭时，返回 200 + `{"has_reminders": false, "items": [], "disabled": true}`（便于嘉和端联调时区分）。
- **查询参数**：
  - `patient_id: str = Query(..., min_length=1)`
  - `visit_id: int | None = Query(None)`
  - `doctor_code: str | None = Query(None)`
  - `stage: str = Query("before_submit")`
- **核心查询逻辑（严控 <100ms，严禁加载 4 个 CLOB！）**：
  1. 从当前生效配置读取所有 `enabled == True` 且 `jhemr_reminder_policy.enabled == True` 且 `delivery_mode in ("pull_api", "both")` 且匹配 `stage` 的 `audit_type`；若没有任何规则开启，直接返回 `{"patient_id": ..., "has_reminders": false, "should_block": false, "items": []}`；
  2. 查 `PushLog`（强制套用 `apply_current_result_filter`、`defer()` 全部 4 个 CLOB、限定 `patient_id`、可选 `visit_number == visit_id`、匹配开启的 `audit_type_code` 与 `severities`、且排除 `exclude_reviewed` 时已复核/已整改闭环记录）；
  3. 左连 `AuditConclusion` 与 `AuditDimensionResult` 拼装简洁临床提醒列表，返回：
     ```json
     {
       "patient_id": "00985003",
       "visit_id": 1,
       "stage": "before_submit",
       "delivery_mode": "pull_api",
       "has_reminders": true,
       "should_block": false,
       "count": 2,
       "items": [
         {
           "log_id": 1001,
           "audit_type_code": "progress_vs_nursing",
           "audit_type_name": "病程与护理一致性",
           "severity": "high",
           "severity_label": "高危",
           "block_submit": false,
           "title": "病程记录与护理记录矛盾",
           "message": "【AI内涵质控提醒】发现高危风险（病程与护理一致性）：...",
           "push_time": "2026-11-19T09:15:00",
           "detail_path": "/ui-next/#/quality/patient-detail?patient_id=00985003&visit_number=1"
         }
       ]
     }
     ```
  4. 同文件再补一个轻量说明注释或兼容辅助函数，说明路线 A（`fileverify_write`）消费同一份 `jhemr_reminder_policy` 策略（`delivery_mode in ("fileverify_write", "both")`），后续启用 056 v4 写回时直接复用策略开关无需改模型。

---

## 四、超详细前端实现蓝图（三轨统一极简清晰风格）

> **三轨通用顶部「定位横幅」样式（三页完全统一）**：
> ```html
> <div class="track-banner track-banner--blue"> <!-- 时效用 amber / AI 用 blue / 预检用 cyan -->
>   <div class="track-banner__title">第二轨 · AI 内涵质控规则（Dify 大模型语义质控）</div>
>   <div class="track-banner__desc">负责深度核查病历临床逻辑一致性，支持企微高危推送，并已预留对接嘉和病历（JHEMR）提交前弹窗提醒策略。</div>
> </div>
> ```

### 4.1 第一轨：`frontend/src/features/timeliness/RuleListPage.vue`（时效锁定规则）
- 顶部加入橙色定位横幅「第一轨 · 时效锁定规则（嘉和病历事前/事中干预）」；
- 横幅下方加一行 **临床阶段快捷过滤胶囊**：`全部(18)` | `入院类` | `查房类` | `手术/麻醉` | `抢救/死亡` | `会诊/输血` | `出院类`；
- 表格精简为清晰 7 列（固定表头）：
  1. 规则中文名（下方小字灰色规则码 + 监控码）；
  2. 触发事件中文说明（如「入院登记后」「手术结束后」）；
  3. 时限要求（如「24 小时内」「术前（提前 2h 预警）」）；
  4. **JHEMR 锁控状态徽章**：`原生已锁`（绿） / `影子观察`（橙） / `预警模式`（蓝） / `临床禁锁(D8)`（灰带提示）；
  5. 适用范围（全院 / 指定科室数）；
  6. 启用开关；
  7. 操作（编辑 / 试算 / 历史版本）；
- **严禁破坏既有 `RuleEditorDrawer.vue` 的 `rawTargetExtras` 无损透传与 D8 `CHIEF_FIRST_ROUND` 禁锁护栏！**

### 4.2 第二轨：`frontend/src/features/governance/AuditTypesPage.vue` + `AuditTypeWizardDrawer.vue`（AI 内涵质控规则）
- **移除原 Tab 2「归档前形式预检」**（已独立至第三轨，页头右方给一个轻链接「前往归档前形式预检规则 →」）；
- **主视图分区去噪音**：
  - **区域 1「运行中生产规则」**：默认全展，用直观卡片网格（`grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px`）或干净 6 列表格展示每个已启用规则（规则中文名、核心检查场景一句说明、运行模式徽章[每日在院/出院终末]、Dify 连通状态、**JHEMR 提交提醒状态徽章**[`已开启·路线B拉取` / `已预留·未开启`]、操作按钮组：`编辑规则` / `测试 Dify` / `启停`）；
  - **区域 2「草稿与待扩展规则模板」**：放入 `<el-collapse>`（默认折叠，标题显示「草稿与待扩展规则模板（N 条，点击展开）」），不再和生产 6 条混在一起让人眼花缭乱！
- **全新 3 步式清爽编辑抽屉 `AuditTypeWizardDrawer.vue`（宽 760px）**：
  - 顶部 `<el-steps :active="step" simple>`（支持点击步骤自由切换，不死卡！）：
    - **第 1 步「基础信息与触发范围」**：规则中文名称、业务描述、启用开关、适用运行模式（每日在院 / 出院终末）、规则编码（新建可填、编辑只读）；
    - **第 2 步「AI 模型（Dify）与数据来源」**：
      - 上半常用区：Dify API 基础地址（附规范提示「不要带 `/workflows/run`」）、API 密钥（留空保持原密文，绝不回显明文！）、工作流输入变量名（默认 `mr_txt`）、超时时间 + 一键「测试 Dify 连通」按钮；
      - 下半折叠区（`<el-collapse>`，**默认收起**）：标题「高级技术配置（SQL 数据源、字段映射与 JSONPath — 仅信息科/开发者维护）」——保留完整编辑能力，普通质控员平时完全不被满屏 SQL 干扰！
    - **第 3 步「告警与 JHEMR 提交前提醒（可扩展）」**：
      - 清晰开关：**开启 JHEMR 提交病历前高危提醒**；
      - 对接通道单选：`嘉和客户端接口拉取（路线 B，推荐）` | `177 FILEVERIFY 规则写入（路线 A）` | `双路同时启用`；
      - 触发风险等级多选：`高危`（默认勾选） / `中危` / `低危`；
      - 提醒方式单选：`仅弹窗提醒（允许继续提交）` | `高危阻断提示（需说明/整改）`；
      - 提醒文案模板（支持 `{severity}` `{audit_type_name}` `{summary}` 占位符 + 实时预览效果盒！）。
  - **无损往返铁律**：打开抽屉时把后端返回的完整规则 JSON 拆成 `formModel` + `rawExtras`（所有抽屉未接管的底层扩展键）；保存时 `{ ...rawExtras, ...mappedForm }` 合并写回，**保证未修改的高级配置字段 100% 零丢失**！

### 4.3 第三轨：`frontend/src/features/governance/PrearchiveRulesPage.vue`（归档前形式预检规则，新建独立页）
- 顶部青色定位横幅「第三轨 · 归档前形式预检规则（病案室无纸化打回与系统报告规则）」；
- 顶部 `SummaryStrip` 4 卡：生效中形式规则数（16 条） / 无纸化 92 项已规则化（A 类） / 规划转 AI 语义辅助（B 类） / 系统推送报告类规则；
- 页内 3 个清爽 `<el-tabs>`：
  1. **Tab 1「无纸化打回形式规则」**：
     - 顶部按引擎类型筛选胶囊：`全部` | `确定性形式规则` | `AI 辅助混合规则（扩展位）`；
     - 固定表头表格：规则中文名、对应无纸化扣分项（`t_mark_item` 名称与历史扣分频次）、**引擎类型标签**（蓝 `形式规则` / 紫 `AI 混合规则`）、严重度（高/中/低危）、当前状态（生效中/草稿/停用）、操作（查看详情 / 编辑 / 启停）；
  2. **Tab 2「系统推送类报告规则」**：清晰展示来自 `system_push_rules.json` 的医技/系统推送报告完整性规则；
  3. **Tab 3「规则版本与发布管理」**：把原 `AuditTypesPage` 中复杂的 8 按钮操作列精简为「校验 / 试跑 / 发布启用 / 停用」清晰 3 主操作 + 更多下拉，原始 JSON Schema 默认折叠进「查看高级规则定义」。
- 规则详情/编辑抽屉预留清晰的「扩展引擎模式」只读/可选区域（`确定性规则引擎` vs `AI 辅助混合引擎 [支持绑定 Dify 提示词模板]`），为后续在归档前规则里加入 AI 语义能力留好平滑入口！

---

## 五、绝对红线与禁令

1. **`rawExtras` 绝对不可丢字段**：必须编写真实配置模板往返单测证明 `diff === []`。
2. **严禁破坏 `AuditTypesPage` 既有的 Dify 测试连通与 API Key 加密保护语义**（留空密文框绝不能覆盖旧 `api_key_enc`）。
3. **严禁破坏 `RuleListPage` 对 D8 `CHIEF_FIRST_ROUND` 的禁锁保护**。
4. 严禁 `prearchive_service/` 导入 `app.*`；严禁 `git commit/push` 或连接生产写入。

---

## 六、验收测试与交付标准

1. `tests/test_wp06_jhemr_ai_reminders.py` 至少覆盖 7 个用例：
   - `jhemr_reminder_policy` 保存、缺省兼容与非法枚举校验 400；
   - `GET /api/integrations/jhemr/ai-reminders` 开关关闭返回 503；
   - 开启后仅返回 `jhemr_reminder_policy.enabled=True` 且 `delivery_mode in ("pull_api", "both")` 且匹配严重度的高危未复核提醒；
   - `exclude_reviewed=True` 时已复核记录自动排除；
   - 无提醒时返回 `has_reminders: false, items: []`；
   - 确认查询 `defer()` 了 4 个 CLOB 列。
2. `frontend/tests/unit/audit-type-roundtrip.test.ts`：读取真实 `config/config.json.template` 中全部 `audit_types[]`，执行 `ruleToForm -> formToPayload` 往返转换，断言关键底层字段（`sources`、`sql`、`jsonpath`、`field_mapping`、未知扩展键）**100% 一致零丢失**！（vitest 中用 `fs.readFileSync(path.resolve(__dirname, '../../../config/config.json.template'), 'utf-8')` 读取。）

**收工必跑验收命令**：
```powershell
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python prearchive_service/check_isolation.py
python -m pytest tests/test_wp06_jhemr_ai_reminders.py tests/test_audit_type_registry.py tests/test_audit_types_api.py tests/test_audit_types_frontend_static.py tests/test_audit_types_runtime_summary_frontend_static.py -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/audit-type-roundtrip.test.ts
npm run test:unit
npm run build
cd .. && python scripts/run_gates_20260906.py --quick
```
收工前登记 `开发起步包/01_统一修改记录.md` 与 `02_协作任务板.md`（本地交付完成，未提交）。

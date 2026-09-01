# 036 — 035 修复与测试一次性执行交付报告

> 文档编号：036 ｜ 执行日期：2026-09-01 ｜ 执行者：ZCode/GLM-5.3（035 一次性修复执行 AI）
> 作业书：`docs/ACTIVE/035` ｜ 执行提示词：`开发起步包/PROMPT-20260831_系统修复测试执行.md`
> 性质：执行交付报告。**零生产写入**（全部生产访问均为只读 SELECT/读配置，见 §2）；未 push、未部署。

## 0. 执行总览

- 起点 HEAD=f9bc1b5（035 定稿），终点=本报告提交；共 7 笸代码/测试 commit + 本笔 docs 收口。
- 执行顺序按 PROMPT §3：RP8→RP9→RP1→RP2→RP3→RP4→RP5→RP6→RP7→全绿门禁，逐包独立提交，checkpoint 逐包落 `review/exec-log.md`。
- **§4 全绿门禁 8/8 一次通过**（数字见 §5）。

## 1. 逐包交付与验收勾选

### RP8 配置卫生（C1 relay 密钥）——✅ 完成，无 tracked 改动（并入 7758f8c 提交说明）

| 项 | 结果 |
|---|---|
| 生产只读核验 | relay enabled=true、`secret_key` **空**（无明文）、`secret_key_enc`=Fernet 140 字符、source='病历质控系统' 无乱码 → **生产已是加密真密钥，占位串不在生产** |
| 仓库侧事实更正 | `git log --all -- config/config.json` 为空 = **config.json 从未被跟踪**（035 C1"被跟踪"证据系起草误读）；`.gitignore:26` 已在位；`git rm --cached` 为 no-op |
| 占位串泄露面 | `change_this_to_a_random_32char_string` 在 git 全历史中仅出现在 035 文档自身引用里 |
| 本地卫生 | 本地 config.json（未跟踪）relay.secret_key 占位明文→''、source '??????'→'病历质控系统'（备份 `config/backups/config_pre_rp8rp9_manual_20260901.json`） |

**结论：C1 无需生产换密钥，无升级事项。**

### RP9 配置修复（C2/C3）——✅ 完成（commit 7758f8c）

- **C2**：jyjc nursing field_mapping `patient_id:'??ID'`/`visit_number:'??'` → `患者ID`/`次数`（本地已改）。影响定级：乱码期间靠 `_record_group_values` 映射 miss→原键兜底 + fanout worker 注入列（data_source_loader.py:501-505）休眠存活，未产生实际失配。测试：`tests/test_fanout_nursing_field_mapping.py` 5 项（正确映射直取注入列/兜底链行为/本地 config guard/全 field_mapping 无 '?' 乱码 ×2 参数化）。
- **C3**：生产核验 syssvsscbc **0/10 空 key + 类型级 api_key_enc 已配（120 字符）+ 全局 dify key 已配 → 生产无 401 风险**。定性修正：类型级 targets 从不入可执行池（006 契约，池=全局 `dify.targets`），本地 10 空 key 是惰性展示值。测试：`test_dify_target_pool_resolver.py` +2（类型级 targets 不入池；类型级 key 仅作 serial 回退、全局端点权威覆盖）。
- **⚠️ 待用户授权（生产写入）**：生产 config.json 的 jyjc nursing 同样有 `??ID/??` 乱码（只读已证）。修复命令（授权后在生产执行，改前备份 /opt/med-audit-docker/config/config.json）：
  ```bash
  # 生产宿主机：备份→容器内修正（与本地同值：患者ID/次数）→重启生效
  cp /opt/med-audit-docker/config/config.json /opt/med-audit-docker/config/backups/config_pre_c2fix_$(date +%Y%m%d_%H%M%S).json
  docker exec med-audit python - <<'PY'
  import json
  p='/app/config/config.json'
  cfg=json.load(open(p,encoding='utf-8'))
  fm=next(a for a in cfg['audit_types'] if a['code']=='jyjc_vs_bcnursing')['sources']['nursing']['field_mapping']
  assert fm['patient_id']=='??ID' and fm['visit_number']=='??'
  fm['patient_id']='患者ID'; fm['visit_number']='次数'
  json.dump(cfg,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
  PY
  docker restart med-audit
  ```
  风险：低（当前兜底链已保证行为不变，修复属配置卫生；不动其他节）。

### RP1 双调度双发实测与治理（B2）——✅ 完成（commit 20f38db）

- 生产时间线（只读，Oracle 应用库 10.10.8.216，近 14 天，患者 ID 脱敏）：18259 行 / **666 组跨模式双跑** / **179 组双模式均推送成功** / 2204 行 superseded；成对样本 daily 09:04(low)→discharge 11:49(low)→daily.superseded_by=终末 ID；双发组关联告警 **0**、双模式均告警组 **0**。
- 根因=**设计行为**：`record_identity._apply_run_mode_scope` 对 discharge_final 键加 `mode::discharge_final::` 前缀（终末业务身份独立，unreviewed_pending 不拦终末推送）。
- **策略裁决=允许双发（业务两时点）**，排除项：终末覆盖抑制 daily（时间倒挂，daily 09:00 先跑）/延迟 daily（毁在院监控时效）/仅抑制相同版本（破坏终末权威性+supersede 链，与 test_historical_rerun_replacement 身份断言冲突）。**此项为 035 升级点①，按证据唯一可行解执行，请用户复核**；若不接受双发成本（约 13 双 Dify 调用/天），可单独立项做"discharge 侧 Dify 调用抑制"变体。
- 生产调度配置实测：daily 09:00（4 类型）、discharge 11:44（全 6 类型），重叠 4 类型双跑。
- 测试：`tests/test_scheduler_dual_send_policy.py` 8 项全绿（T1 双发+current 归属/T2 跨患者隔离/T3 迟到 daily+身份隔离 skip/T4 重试单 current 槽/T5 Oracle 方言 SQL/T6 不可用终末不覆盖/T7 生产时间线复现）。

### RP2 discharge fallback 验证+防呆（B1）——✅ 完成（commit 332e144）

- **035 前提反转**：admission_vs_first_progress/surgery_chain/discharge_vs_frontpage 三类型为 **EMR 文档源**（生产 config 实测 query_sql 全空、emr_vastbase 后端），discharge 模式走 `_fetch_discharged_emr_records` 专用加载（V_QYBR 出院患者→Vastbase 文书，真实列名+绑定参数）——通用 fallback 的 `a."出院日期"` 注入对它们是死代码，**不存在"漏出院患者"缺口**。
- 实际残余风险=配置层（SQL 源含 {dept_filter} 但无别名 a → ORA-00904；SQL 源无 {dept_filter} → 出院语义依赖 SQL 自身；专属类型参与源无占位符 → 转换不注入），此前仅 info 日志。
- 修复：`scheduler_run_modes.py` 新增 `discharge_effectiveness_warnings(config)`（零新依赖）；`/api/scheduler/status` 增 `discharge_effectiveness` 字段+diagnostics 条目；discharge 配置保存响应携带 `effectiveness_warnings`（不拒绝合法保存）。
- 文档同步：AGENTS.md 双模式节"仅 3/6 类型"旧说法改为现状（4 专属分支+通用 fallback+EMR 专用路径+生产核验注记）。
- 测试：`tests/test_discharge_fallback_guard.py` 8 项。

### RP3 指标元数据块（B5）——✅ 完成（commit efa74fb）

- stats.py 全部 8 端点附 `_meta`/`meta` 块（generated_at/date_from/date_to/timezone=Asia/Shanghai/filters/semantics）；无显式窗口端点用同查询 min/max query_date 推导真实覆盖窗口（空数据=None 不伪造）；/dimensions 如实标注 `semantics=all-results`（联查未套当前过滤，行为未改只标注——**观察项**：维度统计含 superseded 行可能重复计数，后续可议套 current 过滤）。
- CSV 导出：`record_export_audit` filter_criteria 增 meta 块（含实际导出窗口/row_cap/row_cap_hit），**CSV 文件字节不变**。
- 前端：统计页口径行（"口径：仅当前结果｜数据窗口…｜生成于…"），app.js/index.html 版本锚 `20260830-csrf-fix`→`20260901-stats-meta`，6 个静态契约测试锚同步（CSRF 热修既定模式）。
- 测试：`tests/test_stats_metadata.py` 6 项（含 legacy E2E T4 对口径行的真浏览器断言）。

### RP4 CSP 现状固化（F1）——✅ 完成（commit db52225）

- `tests/test_csp_policy_baseline.py` 4 项：script-src 必须同时含 'self'+'unsafe-eval'；其余指令不得放宽（无 unsafe-inline/外源/通配）；frame-ancestors/X-Frame-Options 不得出现（Relay 反代依赖）；中间件三头真响应断言。
- **unsafe-eval 解除条件（登记于测试文件 docstring）**：①legacy 三页面（index/log_detail/移动端 qc_detail）全部迁移预编译渲染或 legacy 下线（WP6 canary→GA）②构建产物无 new Function/eval 依赖；两项同时满足后方可收紧。

### RP5 依赖与告警（B3/B4）——✅ 完成（commit 9babd28）

- requests `==2.32.3`→`==2.32.4`（精确 pin），requirements.txt / requirements.linux.txt / requirements.windows.txt 三份同步；packages/ 离线轮子刷新（2.32.4 轮子入包、2.32.3 删除）。
- **生产生效链本地验证**：`docker build` exit 0，镜像 `med-audit:rp5-verify-20260901` 容器内 **python 3.11.15 + requests 2.32.4**。（未触生产；生产生效待部署窗口）
- 风险登记（接受人=用户，见 §6）：cx_Oracle 8.3.0 legacy（oracledb 继任）；passlib 1.7.4 无维护（bcrypt 锁 4.0.1 兼容）；B4 SQLAlchemy 37 条 deprecation=开发机 Python 3.14 现象、生产 pin 3.11 不受影响（登记接受，开发机 adapter 修复未做——可选项）。

### RP6 前端验收包（F2/F3）——✅ 完成（commit bcdbad5）

- **legacy E2E 独立轨道**：`frontend/playwright.legacy.config.ts`（base=/、demo 真后端、`LEGACY_E2E=true` 门控、`npm run test:e2e:legacy`）+ `tests/e2e-legacy/legacy-pages.spec.ts` **5 用例真跑全绿**：T1 登录→质控类型页→prearchive 卡片 14 条+0 条占位；T2 目录不可用 fail-open 提示；T3 CSP 头含 unsafe-eval（现状固化）；T4 统计口径行+推送日志+手动推送冒烟；T5 统计 500 错误态不白屏。导航要点（防下任踩坑）：demo 环境 `/` 重定向 ui-next，legacy 入口=`/index.html`；"数据统计"是"推送日志"页内 tab。
- **ui-next**：新增 `governance-pages.spec.ts` 2 条（治理-质控类型页目录渲染；错误凭据登录错误态），全量 **52 passed/0 failed**（基线 46+新增 2 条×3 视口），14 skipped 全为视口/环境条件门控（非意外 skip）。
- **基线漂移实锤（F2 类风险命中）**：035 的"46 passed"是对**旧 dist** 跑出的——a0605ac 改维度证据 UI（"查看证据"按钮已不存在于源码）、d478d0f 改导出为下拉，两条 PatientQc 用例对 fresh build 必红。已按新契约对齐断言（`.dim-name`/`.dim-issue` 渲染断言、下拉导出流程，强度不降）；并核实 HEAD 构建产物与 static/ui-next 一致（当前镜像无漂移）。
- 四角色现场验收 checklist：外部依赖（§6），材料齐备前不启动 canary。

### RP7 预检上线 runbook（P1）——✅ 完成（本文附录 A）

纯命令清单（codex 口径，非脚本）：生产 config 受控回填 anchor_mode=paperless_rpa、影子运行 7 天对账门禁（阈值已定义）、心电留位。跨天阶段不阻塞主线，W9 开闸后按附录 A 执行。

## 2. 生产访问清单（全部只读，零写入）

| 时点 | 访问 | 内容 |
|---|---|---|
| RP8/RP9 | SSH 只读 + 容器读配置 | relay 密钥特征（布尔/长度，未回显真实值）、jyjc/syssvsscbc/scheduler 配置节 |
| RP1 | 容器内 Oracle 只读 SELECT（应用自身凭据） | MED_PUSH_LOG 近 14 天聚合与成对样本（患者 ID 脱敏）、MED_QC_RECORD_ALERT_LOG 关联计数 |
| RP2 | SSH 读生产 config | 3 fallthrough 类型 sources 定义 |

## 3. 035 §9 验收清单核对

- [x] 用户拍板 §0 解释甲/乙（解释甲已生效，本报告即执行交付）
- [x] RP0 裁定+基线重锚（W1 保留 fba8090，prearchive 重锚 212——本次实测 211 passed+1 skipped 一致）
- [x] RP1-RP9 各带测试全绿（见 §1；RP7 为文档交付无测试，门禁不适用）
- [x] §5 回归矩阵逐项过（指向既有测试套全绿：主 1211/prearchive 212/ui-next 52+legacy 5；双 job 独立锁/Oracle 空串/flags 保留等由既有套覆盖，新增 34 项主服务测试全部围绕红线面）
- [x] §7 门禁一次通过（§5 数字）
- [x] 每条问题有 RP 或 §8 登记（17 条：C1-C3/B1-B5/F1-F3/P1-P2/W1 全部闭环或登记，见 §6）
- [x] 035/INDEX/01 登记齐（本笔一并完成）
- [x] 报告标注 grok 缺席（继承 035 §10：grok 网络故障缺席，round-4 无对辩）

## 4. commit 清单（未 push）

| 包 | commit | 测试增量 |
|---|---|---|
| RP8+RP9 | 7758f8c | 主 +7（5+2） |
| RP1 | 20f38db | 主 +8 |
| RP2 | 332e144 | 主 +8 |
| RP3 | efa74fb | 主 +6（含前端断言；版本锚同步 6 文件） |
| RP4 | db52225 | 主 +4 |
| RP5 | 9babd28 | 依赖 pin（镜像验证） |
| RP6 | bcdbad5 | legacy E2E +5（真跑全绿）；ui-next +6 实例（2 条×3 视口）；2 条过时断言对齐 |
| 收口 | 本笔 | 036/INDEX/01/exec-log |

## 5. 全绿门禁终值（2026-09-01，仓库根）

| 步骤 | 结果 |
|---|---|
| `python -m compileall app tests scripts` | OK |
| `python -m pytest` | **1211 passed / 0 failed**（基线更正：HEAD 原有 1178 而非 1176——035 基线系 CSRF 热修前旧计数；本轮新增 33 项全绿） |
| `python scripts/check_naming_convention.py` | PASS |
| `python -m pytest prearchive_service/tests -q` | **211 passed + 1 skipped**（=212，与重锚基线一致） |
| `python prearchive_service/check_isolation.py` | PASSED（46 文件零 import app.*） |
| `npm --prefix frontend run typecheck && test:unit` | OK / **50 passed** |
| `npm --prefix frontend run build` | OK（dist→static/ui-next 镜像无 diff） |
| `npm --prefix frontend run test:e2e` | **52 passed / 0 failed / 14 skipped**（全部视口/环境条件门控） |
| （附加）legacy E2E：`LEGACY_E2E=true test:e2e:legacy` | **5 passed**（demo 真后端实测） |

## 6. 不修复/外部依赖/风险登记（沿用 035 §8 责任口径）

| 项 | 状态 | 风险接受 |
|---|---|---|
| 生产 config.json C2 乱码同步修复 | **待用户当次授权**（命令备妥见 §1 RP9） | 用户 |
| RP1 双发策略 | 已按证据裁决=允许双发，**请用户复核**（035 升级点①） | 用户 |
| cx_Oracle 8.3.0 legacy / passlib 1.7.4 无维护 | 登记风险（RP5） | 用户（下一代重构窗口） |
| B4 开发机 SQLAlchemy deprecation | 登记接受（生产 3.11 不受影响；adapter 修复可选未做） | 用户 |
| WP6 canary/四角色现场验收 checklist | 材料齐备前不启动：①四角色测试账号 ②Relay 批准包 ③测试科室 ④脱敏长数据；legacy E2E 已覆盖浏览器侧可自动化部分 | 用户 |
| 心电 xd/FID null/W10 清单/W9 开闸 | 外部依赖（035 §8） | 用户 |
| /dimensions 统计未套 current 过滤（RP3 观察项） | 已如实标注 semantics=all-results；套过滤属行为变更，未纳入本轮 | 用户（后续单独立项） |
| ui-next dist 漂移风险（F2） | 本轮已证命中一次并修复；建议今后 e2e 前必跑 build（已写入门禁顺序） | 流程约定 |

## 7. 残留风险与给下一任的核查清单

1. **未 push 未部署**：7 笸 commit 在本地 `fix/ora-12609-p4-error-code`；生产仍是镜像 bb7104f4f7e0。部署窗口需用户授权（RP5 镜像重建+RP2/RP3 后端变更随之生效）。
2. 生产 config.json 仍带 jyjc 乱码（休眠中，兜底链保护）——授权修复见 §1。
3. 执行 checkpoint 全文在 `review/exec-log.md`（不入库）；生产只读证据数字已固化本文 §1/§2。
4. 下一任核查顺序：本报告 §6 待授权项 → 035 §3 各包验收项 → `review/exec-log.md` 逐包明细。

---

## 附录 A — 预检服务（prearchive）上线 runbook（RP7，纯命令清单）

> 前提：W9 真实源开闸；以下命令在生产宿主机（10.10.8.84，SSH :40022）执行；**每步先看输出再走下一步**；任何一步异常即停并回滚该步。

### A0. 前置只读检查（不动任何东西）

```bash
# 1) 容器与镜像状态
docker ps --filter name=med-audit --format '{{.Status}}'
docker images med-audit --format '{{.Tag}} {{.ID}} {{.CreatedAt}}'
# 2) 当前 anchor_mode（预期旧值 finished，177 侧 UPDATEAT 全 NULL=零触发的原因）
docker exec med-audit python -c "import json;c=json.load(open('/app/config/config.json',encoding='utf-8'));print('anchor_mode=',c.get('prearchive',{}).get('service',{}).get('anchor_mode'))"
# 3) 预检代码在容器内的存在性（035 执行后镜像应含 034+ 变更）
docker exec med-audit python -c "import sys;sys.path.insert(0,'/app/prearchive_service');import prearchive.config" && echo prearchive-importable
```

### A1. 受控回填 anchor_mode=paperless_rpa（有备份、可回滚）

```bash
# 1) 备份（回滚点）
cp /opt/med-audit-docker/config/config.json /opt/med-audit-docker/config/backups/config_pre_anchor_$(date +%Y%m%d_%H%M%S).json
# 2) 写入 anchor_mode（只动这一个键）
docker exec med-audit python - <<'PY'
import json
p='/app/config/config.json'
cfg=json.load(open(p,encoding='utf-8'))
svc=cfg.setdefault('prearchive',{}).setdefault('service',{})
print('before:',svc.get('anchor_mode'))
svc['anchor_mode']='paperless_rpa'
json.dump(cfg,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print('after:',svc['anchor_mode'])
PY
# 3) 回滚（如需）：cp 备份文件回原位后 docker restart med-audit
```

### A2. 影子运行 7 天（push.enabled=false，只记不推）

```bash
# 1) 影子开关（备份同 A1-1）
docker exec med-audit python - <<'PY'
import json
p='/app/config/config.json'
cfg=json.load(open(p,encoding='utf-8'))
pc=cfg.setdefault('prearchive',{}).setdefault('push',{})
pc['enabled']=False
json.dump(cfg,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
PY
# 2) 启动预检轮询（前台观察一轮再转后台；日志落 /app/logs/prearchive.log）
docker exec -w /app/prearchive_service med-audit python run_service.py --once   # 单轮干跑
docker exec -d -w /app/prearchive_service med-audit python run_service.py       # 确认后常驻
```

### A3. 7 天对账门禁（每日执行，7/7 全过才可开推送）

```bash
# 每日快照（容器内只读 SQL，逐日留档）
docker exec med-audit python - <<'PY'
# 按 review/ 口径统计当日：触发患者数/规则命中数/告警生成数（push 已关，告警不入队）
import sqlite3,json,datetime
db=sqlite3.connect('file:/app/data/med_audit.db?mode=ro',uri=True)
print(datetime.date.today(), db.execute("select count(*) from prearchive_review_result where created_at>=date('now')").fetchall())
PY
```

**门禁阈值（连续 7 天）**：
- 服务存活：轮询进程无 crash 重启（docker logs 无 traceback）；
- 触发量：日均触发患者数 >0 且 <单日出院量 1.2 倍（paperless_rpa 锚点 ≈出院后 5 天）；
- 规则命中：14 条 mark_item 规则命中率稳定（日间波动 <50%），无单规则 100% 命中（词表漂移信号）；
- 误报抽检：每日人工抽 3 条命中记录对照病历（质控科口径），7 天累计误报 ≤2；
- 对账：RPTCOUNT 对账告警（缺护理）日均 ≤ 出院量 5%（R5：只告警不判缺项）。

### A4. 开推送（7/7 过后，用户当次授权）

```bash
# 1) 再备份 config；2) prearchive.push.enabled=true（同 A2 写法）；3) 观察 1 天企业微信接收
```

### A5. 心电（xd）留位

源仍 BLOCKED 未登记；W9 后按 031 T8 词表流程接入，接入前保持 disabled（缺源不伪造实测）。

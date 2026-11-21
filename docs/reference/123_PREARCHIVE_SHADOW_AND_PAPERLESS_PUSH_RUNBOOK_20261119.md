# 123 归档前核查影子激活与无纸化推送对接 Runbook（2026-11-20 拍板 D3 / WP07 交付）

> 归属：064 总计划 WP-07。**本 Runbook 只是操作手册——生产配置修改、规则入库、
> 容器重启全部放到 WP-10，由用户逐项批准后执行；本文档不构成任何执行授权。**
> 关联：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`、
> `docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md`、
> `prearchive_service/README.md` §11、AGENTS.md「Prearchive Service」节。

---

## 一、线上实锤（为什么「一直不行」）

2026-11-19 只读核查：`med-prearchive` 容器运行 8 周，Oracle 18 张 `MED_PREARCHIVE_*`
表已建但**全部 0 行**；每 5 分钟日志 `[poll] fetch failed`。根因=生产
`/app/config/prearchive.prod.json` 三连：
1. `service.anchor_mode="finished"`——177 上 `finished_date_time` 100% NULL，轮询永远取不到就诊；
2. 13 个数据源全部 `enabled:false` 且主机为 `<..._PLACEHOLDER>`；
3. 规则从未导入生产库。

---

## 二、影子激活 6 步（第 1 步：纯观察，零对外投递）

> 前置：宿主机（med-prearchive 所在 Docker 主机）root；177 Vastbase、216 Oracle
> 已验证连通（063 文档）；病案室已开通主服务账号（`prearchive_check_view` +
> `prearchive_issue_feedback`）。

| 步骤 | 操作 | 验证 | 回滚方法 |
| --- | --- | --- | --- |
| 1. 备份现配置 | `docker exec med-prearchive cp /app/config/prearchive.prod.json /app/config/prearchive.prod.json.bak-$(date +%Y%m%d)` 并 `docker cp med-prearchive:/app/config/prearchive.prod.json.bak-* ./` | 宿主机可见备份文件 | 无需（只读操作） |
| 2. 注入密码环境变量 | 宿主机 compose/环境注入：`PREARCHIVE_SECRET_KEY`（Fernet 主密钥，用于解密 password_enc）+ 各源密文由 `python -m prearchive.config encrypt` 生成后替换模板 `<ENC_*_PLACEHOLDER>`。**AI 严禁索要/转发明文口令，全部由用户本人在宿主机键入** | `docker exec med-prearchive env \| grep -c PREARCHIVE` 与预期一致 | 还原 env/compose |
| 3. 替换为影子模板 | 以 `prearchive_service/config.shadow.prod.template.json` 为底替换 `/app/config/prearchive.prod.json`（仅改占位值，结构不改）；核对 `anchor_mode=discharge`、`sources.jhemr/his/sm.enabled=true`、`push.enabled=false`、`result_delivery.enabled=false`、`staging_table.enabled=false` | `python -c "import json;print(json.load(open('prearchive.prod.json'))['service']['anchor_mode'])"` 输出 discharge | 从步骤 1 备份回灌原文件 |
| 4. 导入规则（先 dry-run 后 apply） | 宿主机：`docker exec -w /app med-prearchive python prearchive_service/scripts/import_rules_cli.py --config /app/config/prearchive.prod.json --files rules/example_rules.json rules/system_push_rules.json`（dry-run）→ 确认报告 `errors=[]` → 加 `--apply --actor "med-audit-wp07"` | dry-run 零写入；apply 报告 `created=16, skipped=0`；重复 apply `created=0, skipped=16`（幂等） | 规则仓版本化：用规则中心回滚/退役接口，或 `MED_PREARCHIVE_RULE_VERSION` 表按版本删除（WP-10 批准后） |
| 5. 重启容器 | `docker restart med-prearchive`（单容器；无多 worker 副作用） | 日志不再出现 `[poll] fetch failed`；出现就诊拉取/检查日志 | 步骤 3 回滚后再次 restart |
| 6. 核验影子产出与零投递 | SQL/SQLite 结果库：`MED_PREARCHIVE_RUN`/`MED_PREARCHIVE_RESULT`/`MED_PREARCHIVE_ISSUE` 开始有数据；Outbox 表 0 行（`result_delivery.enabled=false` 保证）；主服务病案室工作台（`/ui-next/#/governance/workbench`）出现当日出院病历 | 影子检出非全零；Outbox 0 行；`push.enabled=false` 下企微链路零消息 | 停用不影响历史数据（只读）；整体回滚=步骤 1 备份回灌+restart |

病案室核对动作：工作台逐条缺陷「确认缺陷（已查看）/提交整改/误报（必须选原因：
文书其实存在 / 规则不适用本科室 / 时间判断错误 / 其他）」——全部经
`POST /api/prearchive-admin/issues/{issue_id}/actions` 留痕（权限
`prearchive_issue_feedback`/`prearchive_issue_review`）。

---

## 三、CDMS 账号到位后：盘点与回测（第 2 步准备）

> 无纸化 10.10.10.93 只读账号由信息科开通后使用；凭据只走环境变量，AI 不经手。

```bash
# 1) 人工质控盘点（近 30 天；TOP 扣分项+三组覆盖分类+返工/词频；零患者标识）
export PAPERLESS_ORACLE_DSN=10.10.10.93:1521/<SID> PAPERLESS_ORACLE_USER=<只读账号> PAPERLESS_ORACLE_PASSWORD=<口令>
python prearchive_service/scripts/analyze_paperless_rejections_ro.py --days 30

# 2) 金标准回测（影子结果 vs 人工扣分；离线模式先在本地演练）
python prearchive_service/scripts/paperless_gold_backtest_ro.py \
  --results-json review/prearchive/shadow_results.json \
  --manual-json review/prearchive/manual_gold.json \
  --output review/prearchive/paperless_gold_backtest_$(date +%Y%m%d).md
```

- 人工金标准 `manual` 结构（与 `backtest_v2` 对齐，046 T8）：`deductions`
  [{patient_id, visit_id, fid, clause_id?, reviewed_at, data_as_of?}]、
  `evaluated_negatives` [{patient_id, visit_id, fids:[...], reviewed_at}]、
  `hit_annotations`（confirmed/false_positive/pending_review）、`confirmation`。
- **影子转「辅助上线」建议阈值**（需病案室书面确认）：按 FID 维度命中率
  （recall）≥ 80%、误报率（FP/judged）≤ 20%、unknown 占比 ≤ 10%、对齐排除
  占比 ≤ 5%；连续两个统计周期（建议两周）达标方可评估退出纯观察。
- 输出零患者姓名/完整住院号（患者号仅 `P***后4位` 掩码）。

---

## 四、无纸化推送对接（后期；两种通道均默认关闭，只推送人工确认过的缺陷）

### 4.1 HTTP/WebService 报文草案（主推）

`POST https://<无纸化网关>/api/v1/prearchive-defects`，请求头
`Content-Type: application/json`、`X-Delivery-Schema-Version: v1`、HMAC
（复用现 `destinations.build_delivery_headers`，`X-Delivery-Timestamp` +
`X-Delivery-Signature = hmac-sha256(secret, timestamp + "." + body)`）：

```json
{
  "event_id": "res-<sha256-32>",           // 幂等键（结果身份确定性生成）
  "idempotency_key": "res-<sha256-32>.<destination_code>",
  "shadow": false,
  "patient_id": "00985003",                // 病案室确认过的缺陷才推送
  "visit_number": "1",
  "dept_code": "040112",
  "checked_at": "2026-11-19T10:00:00",
  "rule_version": "2026.09.10-046-t3",
  "problems": [
    {
      "rule_id": "R-MISS-SURGERY-CHECKTABLE",
      "t_mark_item_fid": 63,               // 无纸化 T_MARK_ITEM.FID（扣分项定位）
      "severity": "medium",
      "issue_summary": "手术安全核查表未归档（规则命中，病案室已确认）",
      "confirmed_by": "病案室-张三",        // 确认人与确认时间（审计）
      "confirmed_at": "2026-11-20T09:15:00",
      "idempotency_key": "res-....stg1"    // 接收端去重建议字段
    }
  ]
}
```

SOAP/WebService 备选：字段一一映射为 `<DefectNotice><PatientID/><VisitNo/>
<MarkItemFID/><RuleCode/><DefectDesc/><ConfirmBy/><ConfirmAt/><IdempotencyKey/></DefectNotice>`；
接收端以 `IdempotencyKey` 做幂等去重。响应约定：2xx+回显 event_id=成功；
409=重复（视为成功）；429/5xx=重试；其余 4xx=终态死信（人工处理）。

### 4.2 受控中间表建议 DDL（评审草案，默认禁用）

```sql
CREATE TABLE MED_PREARCHIVE_PUSH_QUEUE (
  IDEMPOTENCY_KEY VARCHAR2(80)  NOT NULL,   -- 幂等键（event_id.destination_code）
  PAYLOAD_JSON    CLOB          NOT NULL,   -- 与 HTTP 报文同结构
  CREATED_AT      DATE          DEFAULT SYSDATE NOT NULL,
  CONSTRAINT PK_MED_PREARCHIVE_PUSH_QUEUE PRIMARY KEY (IDEMPOTENCY_KEY)
);
CREATE INDEX IDX_MED_PREARCHIVE_QUEUE_CREATED ON MED_PREARCHIVE_PUSH_QUEUE (CREATED_AT);
```

- 配置（`result_delivery.staging_table`，默认 `enabled:false`）：
  `dsn_env=PREARCHIVE_STAGING_DSN`、`table=MED_PREARCHIVE_PUSH_QUEUE`、
  `idempotency_column=IDEMPOTENCY_KEY`；表名白名单正则
  `^[A-Za-z][A-Za-z0-9_]{0,29}(\.[A-Za-z][A-Za-z0-9_]{0,29})?$`，非法拒绝启动；
- 写入语义：参数化
  `INSERT ... SELECT :k, :p, SYSDATE FROM dual WHERE NOT EXISTS (SELECT 1 FROM <表> WHERE <幂等列> = :k)`；
  rowcount=0 → 幂等命中（duplicate）→ 按 sent 收敛；失败走同一指数退避+死信；
- 闸门：`result_delivery.require_manual_confirm=true`（默认）——未人工确认的
  缺陷不入 Outbox（`DeliveryGovernance.manual_confirm_allowed`）；
- 病案室复核定稿：无纸化接收端建议回写「已接收/已整改」至
  `POST /api/prearchive-admin/issues/{issue_id}/actions`（复用既有动作枚举）。

---

## 五、边界与红线

1. 本文全部命令在 WP-10 前仅限本地演练（`--mock-json`/临时 SQLite）；生产执行
   逐项走用户审批；
2. 凭据零明文：password_enc 密文 + PREARCHIVE_SECRET_KEY 环境变量；AI 严禁索要/
   转发任何口令；
3. 报告/脚本零患者姓名与完整患者号（盘点只出计数词频；回测 P***后 4 位）；
4. `prearchive_service/` 零 `import app.*`（check_isolation 门禁持续 PASS）；
5. 无纸化 CDMS 为规则目录/元数据源（AGENTS.md 口径），禁止接入
   PatientContextBuilder.documents。

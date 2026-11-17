"""生成 JHEMR 受控写入审批材料包（病历时效质控 T8；2026-11-12 按 D3 答复修订）。

产出 `review/timeliness/T8_approval_package.md`，内容为主设计文档 §15 T8 要求的
审批五要素：目标库、账号要求、参数化语句模板、单患者实测步骤（§15.3）、回滚 SQL。

- 两个可执行语句模板**直接导入** `app.timeliness.jhemr_writer` 的硬编码常量，
  与代码单一事实源一致，本脚本不另行抄写；
- 本脚本只生成 Markdown 材料，不连接任何数据库、不执行任何语句；
- 包内 SQL 仅供用户/DBA 审阅与手工执行，AI 不执行（生产写入须用户逐批复）。

v2 修订（2026-11-12，依据用户答复）：
- D3 闭环：原生生成机制已实证（jhinpat_mr_monitor_order），E6 外插真机验证通过；
  模板 A 已实现但受 `insert_monitor_enabled` 子开关控制默认关闭，**仅限跨系统节点**；
- hospital_no 裁定：jhmr_monitor_limit_log 共 14 列且 hospital_no NOT NULL（T1 两份
  实证 + 用户答复），模板 B WHERE 保留该条件，T9 报告"10 列"疑点关闭；
- 生产试点同步：pilot_dept_codes 四码、原生锁定 001/002/011 三文书已开启。

用法：
    python scripts/timeliness/build_write_approval_package.py
    python scripts/timeliness/build_write_approval_package.py --out review/timeliness/T8_approval_package.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 保证以 `python scripts/timeliness/build_write_approval_package.py` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.timeliness.jhemr_writer import (  # noqa: E402
    SQL_APPROVE_LIMIT_LOG_TEMPLATE,
    SQL_CHECK_MONITOR_ITEM_TEMPLATE,
    SQL_INSERT_MONITOR_TEMPLATE,
    WRITE_PASSWORD_ENV_VAR,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "review" / "timeliness" / "T8_approval_package.md"


def _insert_columns() -> list[str]:
    """模板 A 的 INSERT 列清单（自常量解析，避免脚本内再抄一份）。"""
    text = SQL_INSERT_MONITOR_TEMPLATE
    inner = text[text.index("(") + 1 : text.index(") SELECT")]
    return [c.strip() for c in inner.split(",")]


def build_markdown(generated_at: datetime) -> str:
    cols = _insert_columns()
    insert_head = SQL_INSERT_MONITOR_TEMPLATE.split(") SELECT")[0] + ")"
    approve_params_table = """| 序 | 占位符 | 参数 | 说明 |
| --- | --- | --- | --- |
| 1 | approve_user_id | 审批人账号 | 科室主任/授权审批人在 ai_mrzk 的操作者标识 |
| 2 | approve_date_time | 审批时间 | 缺省取执行时刻 |
| 3 | patient_id | 患者 ID | 与 jhemr.jhmr_monitor_limit_log.patient_id 一致 |
| 4 | visit_id | 住院次数 | 同上 |
| 5 | monitor_code | 监控码 | 如 JH04.02.002（首次病程） |
| 6 | apply_date_time | 申请时间 | 超时解锁申请的提交时间（唯一键之一） |
| 7 | type | 申请类型 | 与源表 type 列一致（数字） |
| 8 | hospital_no | 院区号 | 与源表 hospital_no 列一致（2026-11-12 裁定：该列存在且 NOT NULL） |"""
    return f"""# T8 JHEMR 受控写入审批材料包（病历时效质控，v2）

> 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}（脚本 `scripts/timeliness/build_write_approval_package.py`）
> 依据：主设计文档 §15 T8 / §15.3 P4 / §18.1 D3、D8 / §18.3 / 勘误 E6；**2026-11-12 用户答复（D3 闭环 + hospital_no 裁定 + P4 暂缓）**
> 红线：**AI 不执行本包任何写语句**；每条语句的执行均需你对当批 SQL 明确回复"同意执行"或由你本人/DBA 执行；`emr_online_monitor.completed_date` 永不写入（勘误 R1/E4，由 JHEMR 客户端自动回填）。

## 〇、2026-11-12 状态更新（v2 修订要点）

1. **D3 已闭环**：反编译 `JHMonitorOrderBll` + 生产验证确认 JHEMR 经 `jhemr.jhinpat_mr_monitor_order` 在 ADT 事件时自动生成监控行；2026-11-10 生产已补齐模板 `monitor_code`、清理幽灵行（R3 清零）、配置出院记录 `JH07.01.0004 → JH04.02.011` 原生生成。
2. **E6 已真机验证**：试点科室患者 `c1056175`（visit_id=5）外插 `monitor_no=516153`（JH04.02.011）→ 客户端超时弹窗 + `jhmr_monitor_limit_log(flag=1,type=1)` → 审核通过 flag=2 解锁 → 医生签名后客户端自动回填 `completed_date/file_no/leave_time/finished_write_times=1`。
3. **职责边界**：入院 001、首程 002、出院 011 及后续原生可配节点由 **JHEMR 原生生成**，`ai_mrzk` **严禁重复外插**；模板 A 仅留给跨系统节点（手麻、危急值、抢救医嘱、输血）对接时使用，`timeliness.jhemr_write.insert_monitor_enabled` 默认 `false`。
4. **hospital_no 裁定**：`jhmr_monitor_limit_log` 共 14 列且 `hospital_no` NOT NULL（T1 两份实证 + 用户答复；T9 报告"10 列无该列"判断有误，疑点已关闭）；模板 B WHERE 保留该条件。

## 一、目标库与影响面

| 项 | 值 |
| --- | --- |
| 目标库 | `10.10.8.177:5432/jhemr`（Vastbase/openGauss，Oracle 兼容模式，schema `jhemr`） |
| 影响表 1 | `jhemr.emr_online_monitor`（原生监控行；仅模板 A，**默认关闭、仅限跨系统节点**） |
| 影响表 2 | `jhemr.jhmr_monitor_limit_log`（超时申请/审批台账；仅模板 B） |
| 当前生产试点 | 科室白名单 `["040112","030442","030443","030427"]`（肝胆外科+内分泌科）；已开锁文书 001（24h）/002（8h）/011（24h），均按首次签名时间（`20150616WHL001='0'`、`20200623WHL002='0'`） |
| 不影响 | `goal_setting_table` 原生锁定开关（§18.4 单独审批）；两表结构与其他数据 |

## 二、写账号要求（与只读账号分离，D2/T8 约束）

1. **专用写账号**：新建独立账号（示例名 `mrzk_timeliness_write`），严禁复用只读账号 `aizk_user`（`ai_mrzk` 代码层面亦直接拒绝同名账号）；
2. **最小权限**：模板 B 先行只需 `jhmr_monitor_limit_log` 的 UPDATE；`emr_online_monitor` 的 INSERT 待跨系统节点对接启用模板 A 时再授。参考授权 SQL（由 DBA 审阅执行）：

```sql
-- 影响面：仅新增一个最小权限写账号
GRANT USAGE ON SCHEMA jhemr TO mrzk_timeliness_write;
GRANT UPDATE ON jhemr.jhmr_monitor_limit_log  TO mrzk_timeliness_write;
-- 模板 A 启用（跨系统节点对接）时再授：
-- GRANT INSERT ON jhemr.emr_online_monitor     TO mrzk_timeliness_write;
-- 回退（收回写权限，10 秒内生效）：
-- REVOKE UPDATE ON jhemr.jhmr_monitor_limit_log FROM mrzk_timeliness_write;
-- REVOKE INSERT ON jhemr.emr_online_monitor     FROM mrzk_timeliness_write;
```

3. **口令交付**：口令不写入代码/文档/日志；由你以 Fernet 密文填入 `config.json` 的 `timeliness.jhemr_write.password_enc`，或部署时注入环境变量 `{WRITE_PASSWORD_ENV_VAR}`；
4. **配置段**（`config.json.template` 已补全骨架，默认全部关闭）：

```json
"jhemr_write": {{"enabled": false, "insert_monitor_enabled": false, "host": "", "port": 5432,
  "database": "jhemr", "username": "mrzk_timeliness_write", "password_enc": "",
  "statement_timeout_ms": 60000, "connect_timeout_seconds": 10, "sslmode": ""}}
```

## 三、参数化语句模板（硬编码白名单，禁止外部传入 SQL）

### 模板 A：插入监控行 —— **已实现，默认关闭（仅限跨系统节点）**

`app/timeliness/jhemr_writer.py::insert_monitor_row` 已按 Q3 规范实现：`monitor_no` 取号 = 同 `hospital_no` 内 `MAX+1`（首行 1，无 Sequence，反编译 GetMonitorNoSQL 同款）；幂等防重 = 同患者+住院次+监控码+`AI_MRZK` 已有行则整条不插入（NOT EXISTS，rowcount=0 → duplicate 幂等返回）；连库后先执行字典白名单校验（下述 SELECT），不通过 = BLOCKED 回滚。骨架预览（列清单 = {len(cols)} 列，均 ⊆ T1 实证 23 列，**不含 `completed_date`**）：

```sql
{insert_head}
SELECT %s, %s, %s,
  (CASE WHEN (SELECT MAX(monitor_no) FROM jhemr.emr_online_monitor WHERE hospital_no = %s) IS NULL
        THEN 1 ELSE (SELECT MAX(monitor_no) + 1 FROM jhemr.emr_online_monitor WHERE hospital_no = %s) END),
  %s, %s, %s, %s, 0, 0, 1, 0, %s, 'AI_MRZK', %s
WHERE NOT EXISTS (SELECT 1 FROM jhemr.emr_online_monitor
  WHERE patient_id = %s AND visit_id = %s AND item_code = %s AND source_system_identity = 'AI_MRZK')
```

字典白名单校验（真实执行前自动执行，只读）：

```sql
{SQL_CHECK_MONITOR_ITEM_TEMPLATE}
```

- **启用前提（三重）**：`jhemr_write.enabled=true` + `insert_monitor_enabled=true` + 科室在 `pilot_dept_codes`；子开关默认 `false`，**严禁对原生已配节点（001/002/011 等 `jhinpat_mr_monitor_order` 已配项）外插**；
- `dry_run=True`（默认）只留痕不连库；`end_date = start_date + monitor_limit 小时`（由调用方按字典时限计算）；`timeout_indicator=0`、`monitor_type=0`、`total_write_times=1`、`finished_write_times=0` 按 Q3 规范硬编码。

### 模板 B：审批通过回写（与原生 IPMCWidgetMRMONITORLIMIT 条件一致 + flag=1 防重复）

```sql
{SQL_APPROVE_LIMIT_LOG_TEMPLATE}
```

{approve_params_table}

- 语义：把一条 `flag=1`（待审批锁定）申请置为 `flag=2`（审批通过解锁）并记录审批人/时间；
- 安全约束：受影响行数必须等于 1；`0`（申请不存在或已审批）或 `>1`（键不唯一）时**立即回滚并报错**，不产生任何变更；
- 留痕：每次调用先写本地 `tl_action_log`（拦截=BLOCKED / 演练=DRY_RUN / 真实执行=EXECUTED，含完整 SQL 与参数）；三重闸门（总开关、科室白名单、语句模板白名单）任一不满足时不连库。

## 四、单患者实测步骤（P4；**暂缓执行，待 T9 联调 + DBA 写账号就绪后由人工统一执行**）

### 4.1 前置条件（全部满足才可实测模板 B）

1. DBA 按第二节建好写账号并授最小权限（本阶段只需 `jhmr_monitor_limit_log` UPDATE）；
2. `config.json`：`timeliness.jhemr_write.enabled=true`、写账号/口令就绪、`timeliness.pilot_dept_codes` 含测试科室（当前生产试点四码已同步进模板默认值）；
3. 选定 1 名测试患者（试点科室在院患者），先只读核对其在 `jhmr_monitor_limit_log` 恰好存在 1 条待审批（`flag=1`）申请行：

```sql
-- 只读核对（执行前检查，应恰好返回 1 行）
SELECT patient_id, visit_id, monitor_code, apply_date_time, type, hospital_no, flag
  FROM jhemr.jhmr_monitor_limit_log
 WHERE patient_id = '<测试患者ID>' AND visit_id = '<次数>' AND flag = 1;
```

### 4.2 模板 B 实测步骤

1. 在 `ai_mrzk` 审批界面（T9 已交付）发起"审批通过"（`dry_run=false`），或由你在数据库客户端手工执行模板 B（参数按第三节表格取 4.1 查到的键值）；
2. 执行后核对（只读）：该行 `flag=2`、`approve_user_id/approve_date_time` 已写入；`ai_mrzk` 的 `tl_action_log` 出现 `mode=EXECUTED` 且 `result` 为 `success: rowcount=1`；本地 `tl_approval` 与事件状态同步 APPROVED；
3. 在 JHEMR 客户端确认该申请状态变化、病历可正常编辑；
4. 若返回 0/多行受影响：组件已自动回滚，无需补救；手工执行时请同样回滚并复核键值。

### 4.3 模板 A 实测步骤（**当前阶段不执行**——跨系统节点未对接）

模板 A 仅在后期对接手麻/危急值/抢救医嘱/输血（任务 T12-<系统>）时按该任务的实测计划执行；对 JHEMR 原生已配节点（001/002/011 等）**一律禁止外插**。届时步骤：测试科室 1 例 → 按模板 A 插 1 行（`source_system_identity='AI_MRZK'`）→ 测试机重登 JHEMR 验证锁定弹窗 → 按第五节回滚语句删除 → 结论回填。

## 五、回滚 SQL（人工执行，逐条审批）

```sql
-- 模板 B 回滚：把误审批的行恢复为待审批并清空审批信息（WHERE 键值与误写行一致）
UPDATE jhemr.jhmr_monitor_limit_log SET approve_user_id = NULL, approve_date_time = NULL, flag = 1
 WHERE patient_id = '<患者ID>' AND visit_id = '<次数>' AND monitor_code = '<监控码>'
   AND apply_date_time = '<申请时间>' AND type = <类型> AND hospital_no = '<院区号>' AND flag = 2;

-- 模板 A 回滚（未启用，预留）：删除 AI 外插的监控行（按标记列精准定位，不触碰原生行）
DELETE FROM jhemr.emr_online_monitor
 WHERE patient_id = '<患者ID>' AND visit_id = '<次数>'
   AND source_system_identity = 'AI_MRZK';

-- 回滚后核对（只读）：外插行应为 0 行
SELECT count(*) FROM jhemr.emr_online_monitor
 WHERE patient_id = '<患者ID>' AND visit_id = '<次数>' AND source_system_identity = 'AI_MRZK';
```

> 注意：Oracle 兼容模式下空串等同 NULL，判空一律用 `IS NULL / IS NOT NULL`，勿用 `COALESCE(col,'') <> ''`。

## 六、执行前核对清单

- [ ] 写账号非 `aizk_user`、权限仅限批准的表（第二节）；
- [ ] `pilot_dept_codes` 仅含试点科室（当前模板默认=生产试点四码）；
- [ ] 4.1 只读核对返回恰好 1 行（模板 B）；
- [ ] `ai_mrzk` 容器 `tl_action_log` 可写（留痕先行）；
- [ ] 已明确本批 SQL 的批复口径与执行人；
- [ ] 模板 A：`insert_monitor_enabled` 保持 false（跨系统节点对接前一律不启用）；
- [ ] 待办：T9 approve 链路单患者联调 + DBA 写账号就绪后，由人工统一执行 P4（AI 不执行）。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 T8 JHEMR 写入审批材料包（纯文档，不连库）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出 Markdown 路径")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_markdown(datetime.now())
    out_path.write_text(content, encoding="utf-8", newline="\n")
    print(f"[T8] 审批材料包已生成: {out_path}（{len(content)} 字符）")
    print("[T8] 提醒：本脚本仅生成材料，未连接任何数据库，未执行任何语句。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""生成 JHEMR 受控写入审批材料包（病历时效质控 T8）。

产出 `review/timeliness/T8_approval_package.md`，内容为主设计文档 §15 T8 要求的
审批五要素：目标库、账号要求、参数化语句模板、单患者实测步骤（§15.3）、回滚 SQL。

- 两个可执行语句模板**直接导入** `app.timeliness.jhemr_writer` 的硬编码常量，
  与代码单一事实源一致，本脚本不另行抄写；
- 本脚本只生成 Markdown 材料，不连接任何数据库、不执行任何语句；
- 包内 SQL 仅供用户/DBA 审阅与手工执行，AI 不执行（生产写入须用户逐批复）。

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
    SQL_INSERT_MONITOR_TEMPLATE,
    WRITE_PASSWORD_ENV_VAR,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "review" / "timeliness" / "T8_approval_package.md"

# 模板 A 列清单（自常量解析，避免脚本内再抄一份）。
def _insert_columns() -> list[str]:
    text = SQL_INSERT_MONITOR_TEMPLATE
    inner = text[text.index("(") + 1 : text.index(") VALUES")]
    return [c.strip() for c in inner.split(",")]


def build_markdown(generated_at: datetime) -> str:
    cols = _insert_columns()
    placeholders = ", ".join(["%s"] * len(cols))
    insert_head = SQL_INSERT_MONITOR_TEMPLATE.split(" VALUES")[0]
    approve_params_table = """| 序 | 占位符 | 参数 | 说明 |
| --- | --- | --- | --- |
| 1 | approve_user_id | 审批人账号 | 科室主任/授权审批人在 ai_mrzk 的操作者标识 |
| 2 | approve_date_time | 审批时间 | 缺省取执行时刻 |
| 3 | patient_id | 患者 ID | 与 jhemr.jhmr_monitor_limit_log.patient_id 一致 |
| 4 | visit_id | 住院次数 | 同上 |
| 5 | monitor_code | 监控码 | 如 JH04.02.002（首次病程） |
| 6 | apply_date_time | 申请时间 | 超时解锁申请的提交时间（唯一键之一） |
| 7 | type | 申请类型 | 与源表 type 列一致（数字） |
| 8 | hospital_no | 院区号 | 与源表 hospital_no 列一致 |"""
    return f"""# T8 JHEMR 受控写入审批材料包（病历时效质控）

> 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')}（脚本 `scripts/timeliness/build_write_approval_package.py`）
> 依据：主设计文档 `E:\\嘉和\\JHEMR\\嘉和病历质控\\JHEMR病历时效锁定改造计划及后续质控说明-20261108.md` §15 T8 / §15.3 P4 / §18.1 D3、D8 / §18.3 / 勘误 E6
> 红线：**AI 不执行本包任何写语句**；每条语句的执行均需你对当批 SQL 明确回复“同意执行”或由你本人/DBA 执行；`emr_online_monitor.completed_date` 永不写入（勘误 R1/E4）。

## 一、目标库与影响面

| 项 | 值 |
| --- | --- |
| 目标库 | `10.10.8.177:5432/jhemr`（Vastbase/openGauss，schema `jhemr`） |
| 影响表 1 | `jhemr.emr_online_monitor`（原生监控行；仅模板 A，**当前未启用**） |
| 影响表 2 | `jhemr.jhmr_monitor_limit_log`（超时申请/审批台账；仅模板 B） |
| 不影响 | `goal_setting_table` 原生锁定开关（由 §18.4 单独审批，不在本包）；两表结构与其他数据 |

## 二、写账号要求（与只读账号分离，D2/T8 约束）

1. **专用写账号**：新建独立账号（示例名 `mrzk_timeliness_write`），严禁复用只读账号 `aizk_user`（`ai_mrzk` 代码层面亦直接拒绝同名账号）；
2. **最小权限**：只授予两张目标表的最小写权限，不给 SELECT 之外任何 DDL/管理权限；参考授权 SQL（由 DBA 审阅执行）：

```sql
-- 影响面：仅新增一个最小权限写账号；GRANT INSERT 允许插入监控行（模板 A 未启用前可不授）
GRANT USAGE ON SCHEMA jhemr TO mrzk_timeliness_write;
GRANT INSERT ON jhemr.emr_online_monitor      TO mrzk_timeliness_write;
GRANT UPDATE ON jhemr.jhmr_monitor_limit_log  TO mrzk_timeliness_write;
-- 回退（收回写权限，10 秒内生效）：
-- REVOKE INSERT ON jhemr.emr_online_monitor     FROM mrzk_timeliness_write;
-- REVOKE UPDATE ON jhemr.jhmr_monitor_limit_log FROM mrzk_timeliness_write;
```

3. **口令交付**：口令不写入代码/文档/日志；由你以 Fernet 密文填入 `config.json` 的 `timeliness.jhemr_write.password_enc`，或部署时注入环境变量 `{WRITE_PASSWORD_ENV_VAR}`；
4. **配置段**（`config.json`，模板默认 `enabled:false`）：

```json
"jhemr_write": {{"enabled": false, "host": "10.10.8.177", "port": 5432, "database": "jhemr",
  "username": "mrzk_timeliness_write", "password_enc": "", "statement_timeout_ms": 60000}}
```

## 三、参数化语句模板（硬编码白名单，禁止外部传入 SQL）

### 模板 A：插入监控行 —— **未启用（D3 待嘉和确认）**

遵守 D3 决策（§18.1/§18.3 Q1–Q3）：外插行能否触发 JHEMR 锁定（勘误 E6）、`monitor_no` 取号方式、必填列均未经嘉和确认。确认前 `app/timeliness/jhemr_writer.py` 的 `insert_monitor_row()` **直接抛 `NotImplementedError`**，以下骨架仅供审批预览（列清单 = T1 真实列核对 23 列剔除 `completed_date` 后的 {len(cols)} 列）：

```sql
{insert_head}
VALUES ({placeholders})
```

- 插入时 `source_system_identity` 必须填 `'AI_MRZK'`（回滚按该值精准定位外插行）；
- `completed_date` 永不写入（由 JHEMR 原生维护，勘误 R1/E4）。

### 模板 B：审批通过回写（与原生 IPMCWidgetMRMONITORLIMIT 条件一致 + flag=1 防重复）

```sql
{SQL_APPROVE_LIMIT_LOG_TEMPLATE}
```

{approve_params_table}

- 语义：把一条 `flag=1`（待审批）的超时解锁申请置为 `flag=2`（已通过）并记录审批人/时间；
- 安全约束：受影响行数必须等于 1；`0`（申请不存在或已审批）或 `>1`（键不唯一）时**立即回滚并报错**，不产生任何变更；
- 留痕：`ai_mrzk` 侧每次调用均先写本地 `tl_action_log`（拦截=BLOCKED / 演练=DRY_RUN / 真实执行=EXECUTED，含完整 SQL 与参数），三重闸门（总开关 `jhemr_write.enabled`、试点科室白名单 `pilot_dept_codes`、语句模板白名单）任一不满足时不连库。

## 四、单患者实测步骤（§15.3 P4；模板 B 先行，模板 A 等 D3 答复）

### 4.1 前置条件（全部满足才可实测）

1. DBA 按第二节建好写账号并授最小权限（模板 A 未启用前可只授 `jhmr_monitor_limit_log` 的权限）；
2. `config.json`：`timeliness.jhemr_write.enabled=true`、写账号/口令就绪、`timeliness.pilot_dept_codes` 仅含测试科室代码；
3. 选定 1 名测试患者（测试科室在院患者），先只读核对该患者在 `jhmr_monitor_limit_log` 恰好存在 1 条待审批（`flag=1`）申请行：

```sql
-- 只读核对（执行前检查，应恰好返回 1 行）
SELECT patient_id, visit_id, monitor_code, apply_date_time, type, hospital_no, flag
  FROM jhemr.jhmr_monitor_limit_log
 WHERE patient_id = '<测试患者ID>' AND visit_id = '<次数>' AND flag = 1;
```

### 4.2 模板 B 实测步骤

1. 在 `ai_mrzk` 时效审批界面（T9 交付后）发起“审批通过”，或由你在数据库客户端手工执行模板 B（参数按第三节表格取 4.1 查到的键值）；
2. 执行后核对（只读）：该行 `flag=2`、`approve_user_id/approve_date_time` 已写入；`ai_mrzk` 的 `tl_action_log` 出现 `mode=EXECUTED` 且 `result` 为 `success: rowcount=1`；
3. 在 JHEMR 客户端【超时审批】画布确认该申请状态变化、病历可正常编辑；
4. 若第 1 步返回 0/多行受影响：组件已自动回滚，无需补救；手工执行时请同样回滚并复核键值。

### 4.3 模板 A 实测步骤（**待 D3 答复并回填 §18.3 后方可进行**，对应 §15.3 P4）

1. 在测试科室选 1 例在院患者，按本包模板 A 插入 1 行监控行（`source_system_identity='AI_MRZK'`）；
2. 测试机**重新登录** JHEMR 客户端，打开该患者验证是否弹出锁定框（E6 未证明前的核心验证点）；
3. 验证完成后立即按第五节模板 A 回滚语句删除该行；
4. 结论回填 §18.3（能锁 → 进入 P5 评估；不能锁 → 维持提醒+考核路径）。

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

## 六、执行前核对清单

- [ ] 写账号非 `aizk_user`、权限仅两张表（第二节）；
- [ ] `pilot_dept_codes` 仅含测试科室；
- [ ] 4.1 只读核对返回恰好 1 行（模板 B）；
- [ ] `ai_mrzk` 容器 `tl_action_log` 可写（留痕先行）；
- [ ] 已明确本批 SQL 的批复口径与执行人；
- [ ] 模板 A 相关动作已获 D3 答复（当前一律不做）。
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

# 062 · 病历时效质控执行指针（TIMELINESS_QC_EXECUTION_POINTER）

> 建立：2026-11-10（T0 交付物；编号取 docs/INDEX.md 现最大 061+1=062）。本文件是执行指针：只登记主计划路径、任务包范围与当前状态，不复制主计划正文；设计口径（D1/红线/命名/状态表）统一维护在 [开发起步包/05_病历时效质控设计指针.md](../../开发起步包/05_病历时效质控设计指针.md)。

## 1. 主设计文档（唯一事实来源）

`E:\嘉和\JHEMR\嘉和病历质控\JHEMR病历时效锁定改造计划及后续质控说明-20261108.md`（v3.2，含第〇章勘误 E1–E14 / 实证 R1–R3、第十四章架构评估、第十五章任务包 T0–T11、第十八章用户答复落实 D2/D3/D4/D8）。

执行规则：只按该文档 §15 任务包施工；其第二、三、四、九、十二、十三章旧表名/旧编码/旧 Oracle 语法仅作背景不得照抄；每任务开工重读 §15.0 通用规则；每任务交付代码 + 测试 + `review/timeliness/T{n}_report.md`。

## 2. 任务包范围与当前状态（2026-11-12 终态更新：T0–T11 全部完成）

| 任务 | 内容摘要 | 状态 |
| --- | --- | --- |
| T0 | 启动、基线采集与指针文档登记 | ✅ 已完成（2026-11-10；证据=review/timeliness/T0_baseline.md、T0_report.md、T0_git_status_before.txt；pytest 收集 1538 条 exit 0；run_gates --quick 4/4 PASS exit 0，gate-runs/20261110-083541） |
| T1 | JHEMR 多表只读访问层（jhemr_reader.py，账号固定 aizk_user） | ✅ 已完成 |
| T2 | 本地表 tl_* 七张、迁移与规则种子（D8 红线入种子 note） | ✅ 已完成 |
| T3 | 规则引擎纯函数（危急值/抢救/输血/麻醉=ExternalEventSource 接口桩 NOT_CONFIGURED） | ✅ 已完成 |
| T4 | 影子扫描、台账与原生对账报告（真实扫描 BLOCKED：等 §18.2 GRANT 授权） | ✅ 已完成 |
| T5 | 后端 API、权限与菜单（含 D8 LOCK_EMR 400 拒绝校验） | ✅ 已完成 |
| T6 | 可视化规则配置界面 frontend/src/features/timeliness/ | ✅ 已完成 |
| T7 | 通用通知层与企微提醒（抽 send_signed_relay()；真实发送待 D6） | ✅ 已完成 |
| T8 | JHEMR 写入器（仅代码与演练；插入监控行模板等 D3 答复前 NotImplementedError） | ✅ 已完成（并行会话交付） |
| T9 | 审批同步与扣罚台账 | ✅ 已完成 |
| T10 | 内涵/AI 质控提醒通道抽象（仅接口与本地实现） | ✅ 已完成 |
| T11 | 终态门禁与交付 | ✅ 已完成 |

依赖图与阻塞项见主设计文档 §15.1。**2026-11-12 终态：T0–T11 全部完成；遗留=D3（模板 A）、D6（企微真实发送）、D10（FILEVERIFY 表 DDL）、T8 模板 B hospital_no 疑点裁定、生产部署审批（§15.3 P2–P5）——详 review/timeliness/DELIVERY_REPORT.md §四五。**

## 3. 核心红线（摘要，全文见 05 指针 §3 与主设计文档 §15.0 第 4 条）

1. 生产库默认只读（`JHEMR_WRITE_ENABLED=false`）；真实提交路径任何任务包不得调用。
2. 严禁将任何真实密码明文写入代码、配置文件、测试或文档。
3. `ADM_REC` 与 `CHIEF_FIRST_ROUND` 严禁开启 `LOCK_EMR`（D8；后端 400 拒绝 + 前端禁用，T5/T6 测试覆盖）。
4. 不改 Dify 链路文件、`prearchive_service/`、`app/emr_vastbase_client.py`；不 `git commit/push`（除非用户单批明确授权）；数据库只读调查不启动 `app.main` / `init_db()`；保留他人未提交改动。

## 4. 状态更新约定

每完成一个任务包：更新本文件 §2 状态列 + `开发起步包/02_协作任务板.md` 对应行 + `开发起步包/01_统一修改记录.md` 追加登记行 + `review/timeliness/T{n}_report.md` 留证；同步 `开发起步包/05` 状态表。本文件状态列与 05 指针状态表保持一致。

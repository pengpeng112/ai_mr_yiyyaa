# -*- coding: utf-8 -*-
"""Canonical Field Registry（039 T9 / §10）：预检/医保映射字段的 confirmed|candidate|blocked 注册。

证据分级（039 §10.2）：
- confirmed：本仓库 029/030/034 已实测回填、当前代码正在使用的列（阶段 A 可用于已发布规则）；
- candidate：`F:\\python\\数据资产` 机器资产（08 元数据快照/03 视图登记）中出现、
  尚未经本服务 B1 受控只读核验的表/列——只能进草稿，不得发布；
- blocked：G2/G3/G5 等外部资料未到位（EMR/HIS 接口字段、DRG 年度包等）——
  只留占位与诊断，禁止造假值域。

不复制外仓大文件；每条都注明证据路径与快照日期。阶段 A 零生产活库连接。
"""

from __future__ import annotations

# 数据资产机器资产快照日期（读取时间 2026-09-02，只读文件系统）
DATA_ASSET_SNAPSHOT_DATE = "2026-09-02"
DATA_ASSET_META = "F:\\python\\数据资产\\开发起步包\\08_数据中心元数据快照.json"
DATA_ASSET_VIEW_REGISTRY = "F:\\python\\数据资产\\开发起步包\\03_view_registry.json"

_REPO_DOC = "docs/ACTIVE/{doc}"

CANONICAL_FIELDS = [
    # ---- 住院主键与患者基本信息（confirmed：V_QYBR 实测列，AGENTS/029/030） ----
    {"field": "patient_id", "label": "患者ID", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"患者ID\"", "usable_for_publish": True,
     "evidence": "AGENTS.md Dept Fields 节 + " + _REPO_DOC.format(doc="029")},
    {"field": "visit_number", "label": "住院次数", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"次数\"", "usable_for_publish": True,
     "evidence": "AGENTS.md + " + _REPO_DOC.format(doc="029")},
    {"field": "dept_code", "label": "所在科室编码", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"所在科室编码\"", "usable_for_publish": True,
     "evidence": "AGENTS.md Dept Fields 节"},
    {"field": "dept_name", "label": "所在科室名称", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"所在科室名称\"", "usable_for_publish": True,
     "evidence": "AGENTS.md Dept Fields 节"},
    {"field": "discharge_dept_code", "label": "出院科室编码", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"出院科室编码\"", "usable_for_publish": True,
     "evidence": "AGENTS.md Dept Fields 节"},
    {"field": "discharge_dept_name", "label": "出院科室名称", "status": "confirmed",
     "source": "JHEMR.V_QYBR.\"出院科室名称\"", "usable_for_publish": True,
     "evidence": "AGENTS.md Dept Fields 节"},

    # ---- 文书/首页（confirmed：034 实测回填采集器） ----
    {"field": "documents.report_name", "label": "文书名称", "status": "confirmed",
     "source": "jhemr v_blws REPORTNAME 族", "usable_for_publish": True,
     "evidence": _REPO_DOC.format(doc="029") + " + prearchive/collectors.py"},
    {"field": "documents.template_name", "label": "文书模板名", "status": "confirmed",
     "source": "jhemr v_blws 模板列（progress_template_name 实测）", "usable_for_publish": True,
     "evidence": "AGENTS.md Vastbase Gotchas + " + _REPO_DOC.format(doc="034")},
    {"field": "firstpage.operation", "label": "首页手术信息", "status": "confirmed",
     "source": "his_firstpage_operation（T8-4 手术证据源）", "usable_for_publish": True,
     "evidence": _REPO_DOC.format(doc="034")},
    {"field": "diagnoses", "label": "诊断列表", "status": "confirmed",
     "source": "jhemr v_blws 诊断文书解析（duplicate 判定器在用）", "usable_for_publish": True,
     "evidence": "prearchive/engine.py duplicate 判定器"},

    # ---- 结算/医保（candidate：数据资产快照有对象，未经 B1 核验） ----
    {"field": "settle.total_cost", "label": "住院总费用", "status": "candidate",
     "source": "HIS.INP_SETTLE_MASTER（含 PATIENT_ID/VISIT_ID，共 20 列）",
     "usable_for_publish": False,
     "evidence": f"{DATA_ASSET_META} schemas.HIS.tables（快照 {DATA_ASSET_SNAPSHOT_DATE}）",
     "note": "B1 受控只读核验列名/值域前，只能建草稿规则"},
    {"field": "settle.insurance_amount", "label": "医保结算金额", "status": "candidate",
     "source": "HIS.INP_SETTLE_MASTER_YB（49 列，含 YBFDJE/DESYBX/GWYBZ/DBZYBJSJE）",
     "usable_for_publish": False,
     "evidence": f"{DATA_ASSET_META} schemas.HIS.tables（快照 {DATA_ASSET_SNAPSHOT_DATE}）"},
    {"field": "firstpage.basy", "label": "病案首页字段族", "status": "candidate",
     "source": "ZNT views BASYFY / FXJCPT_BASY；KZL views BASYFY",
     "usable_for_publish": False,
     "evidence": f"{DATA_ASSET_META} schemas.ZNT/KZL.views（快照 {DATA_ASSET_SNAPSHOT_DATE}）",
     "note": "主诊断/主手术 ICD 具体列需 B1 核验后升级 confirmed"},
    {"field": "drg.dict", "label": "DRG 分组字典", "status": "candidate",
     "source": "DBZ views DRGSDICTDEPT / DRGSDICTDOCTOR",
     "usable_for_publish": False,
     "evidence": f"{DATA_ASSET_META} schemas.DBZ.views（快照 {DATA_ASSET_SNAPSHOT_DATE}）",
     "note": "仅说明库内存在字典视图；本院 DRG 分组结果/回写字段是否存在需 B1 核验"},

    # ---- 接口身份（blocked：G2/G3/G4 未确认） ----
    {"field": "emr_api.subject", "label": "EMR 接口患者标识", "status": "blocked",
     "source": "G2 未确认（URL/认证/字段映射缺）",
     "usable_for_publish": False,
     "evidence": "039 §3 G2 行；默认只传 patient_id+visit_number 最小集"},
    {"field": "his_api.subject", "label": "HIS 接口患者标识", "status": "blocked",
     "source": "G3 未确认", "usable_for_publish": False,
     "evidence": "039 §3 G3 行"},
    {"field": "insurance.ruleset", "label": "山东济南 DRG 年度规则包", "status": "blocked",
     "source": "G5 未确认（年度/分组方案/权重未到）",
     "usable_for_publish": False,
     "evidence": "039 §3 G5 行；正式判定保持关闭"},
    {"field": "source.xd", "label": "心电源", "status": "blocked",
     "source": "两库均无 ITF 对象（031 §10 实测）",
     "usable_for_publish": False,
     "evidence": _REPO_DOC.format(doc="031") + " §10"},
]


def fields_by_status(status: str) -> list:
    return [f for f in CANONICAL_FIELDS if f["status"] == status]


def publishable_fields() -> list:
    return [f["field"] for f in CANONICAL_FIELDS if f.get("usable_for_publish")]

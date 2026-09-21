# -*- coding: utf-8 -*-
"""046 T1 覆盖账本：92 条评分项 → 机器可读逐条账本（原子条款级）。

数据来源（不重造结论，逐条给依据）：
- 快照 `rules/paperless_items_snapshot_20260828.json`（92 条原文/分值/分组，FNAME 截断至80字=原文如此）；
- 030 映射表 v1.1（A=23/B=7/C=62 分类、每 FID 方案/数据源依据/严重度、七问拍板）；
- 046 §4.2 对 23 项确定性候选的实施边界（FID55/57 的拆分要求、blocked 条件）；
- `rules/example_rules.json` v2026.08.29-qc-authorized-v1（非空 FID 11 个=已发布规则锚点）。

账本语义：
- 每条含原子条款（一 FID 多条款），条款 method ∈ deterministic/ai_assist/manual/data_blocked；
- coverage ∈ full/partial/none：full=该条款已有可执行判定且数据源证实；partial=部分子句
  或存在已批准候选；none=无自动化覆盖；
- blocked_reason 必须给数据/口径缺口，不得为凑覆盖率把 manual 写成 deterministic。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .closed_loop_models import (
    METHOD_AI_ASSIST,
    METHOD_DATA_BLOCKED,
    METHOD_DETERMINISTIC,
    METHOD_MANUAL,
)

SNAPSHOT_DEFAULT = Path(__file__).resolve().parents[1] / "rules" / \
    "paperless_items_snapshot_20260828.json"
COVERAGE_OUTPUT = Path(__file__).resolve().parents[1] / "rules" / \
    "paperless_coverage_v1.json"

GROUP_NAMES = {
    "1": "总则", "2": "首页", "3": "入院记录", "4": "出院记录",
    "14": "病程/会诊/抢救", "15": "手术/麻醉", "33": "知情同意",
    "34": "医嘱/辅检", "37": "护理",
}

# 026/046 §4.3 历史高频扣分 FID（2026-08-28 样本线索，仅提示优先级不作结论）
HISTORICAL_HIGH_FREQ = {3, 6, 12, 15, 26, 35, 41, 44, 48, 56, 58, 64, 72, 75, 76, 78}

SOURCE_SYSTEM = "paperless_cdms"
DEFAULT_SNAPSHOT_ID = "paperless_items_snapshot_20260828"


def _clause(clause_id: str, text: str, method: str, coverage: str = "none",
            rule_ids=(), fields=(), sources=(), threshold: str = "",
            blocked: str = "", pos: str = "", neg: str = "",
            covered: str = "", uncovered: str = "", tests=(),
            hints: dict | None = None) -> dict:
    return {
        "clause_id": clause_id,
        "clause_text": text,
        "method": method,
        "coverage": coverage,
        "rule_ids": list(rule_ids),
        "covered_clauses": covered or (text if coverage == "full" else ""),
        "uncovered_clauses": uncovered or ("" if coverage == "full" else text),
        "fields": list(fields),
        "sources": list(sources),
        "threshold_source": threshold,
        "blocked_reason": blocked,
        "example_positive": pos,
        "example_negative": neg,
        "linked_tests": list(tests),
        # stub/模型生成候选 DSL 的确定性提示（阈值必须来自 threshold_source 已批准口径）
        "hints": hints or {},
    }


# ---------------------------------------------------------------------------
# 逐 FID curated 数据（A=23 全量条款级；B=7 关联现有六类；C=62 分类理由）
# 依据列 = 030 表行 + 046 §4.2 边界。
# ---------------------------------------------------------------------------
R = {
    14: ("R-TIME-ADMISSION-RECORD-24H",), 34: ("R-TIME-FIRST-PROGRESS-8H",),
    55: ("R-TIME-INVASIVE-OP-24H",), 57: ("R-MISS-SURGERY-PREPOST-DOCS",),
    59: ("R-MISS-ANESTHESIA-PREOP-VISIT",), 61: ("R-MISS-ANESTHESIA-RECORD",),
    63: ("R-MISS-SURGERY-CHECKTABLE",), 65: ("R-TIME-POSTOP-FIRST-PROGRESS-24H",),
    67: ("R-MISS-ANESTHESIA-POSTOP-FOLLOWUP",), 71: ("R-TIME-DISCHARGE-RECORD-24H",),
    88: ("R-MISS-SURGERY-COUNT-RECORD",),
}

A_CURATED: dict[int, dict] = {
    14: {
        "interpretation": "入院记录族（入院/再入院/24h内入出院/24h内入院死亡记录）由执业医师在入院24h内完成",
        "clauses": [
            _clause("FID14-C1", "入院记录族文书存在（有住院事实即应有）",
                    METHOD_DETERMINISTIC, "partial", R[14],
                    fields=["documents.template_name"], sources=["jhemr_blws"],
                    blocked="现规则仅时限判定，缺文书子句在 046 T3 落地（F05 修复后缺文书=缺陷/未知）",
                    pos="v_blws 有模板=入院记录的文书", neg="无任何入院记录族文书（T3 起报缺陷）",
                    tests=["test_pa_rules_fid11.py"]),
            _clause("FID14-C2", "入院起 24h 内完成", METHOD_DETERMINISTIC, "full",
                    R[14], fields=["admit_time", "documents.event_time"],
                    sources=["jhemr_blws", "jhemr.pat_visit"],
                    hints={"kind": "time_limit", "threshold_hours": 24,
                           "event": "admission", "doc_name": "入院记录",
                           "doc_time_source": "blws"},
                    threshold="《病历书写基本规范》+030 七问 Q3（族变体统一 24h）",
                    pos="入院 2026-01-01 08:00，文书完成 2026-01-01 20:00 → pass",
                    neg="入院 2026-01-01 08:00，文书完成 2026-01-02 12:00 → fail",
                    tests=["test_pa_rules_t24.py"]),
            _clause("FID14-C3", "由执业医师书写（签名/资质）", METHOD_MANUAL, "none",
                    blocked="书写者资质与签名链无结构化源（029 P0-6 完成医生字段 177 无数据）"),
            _clause("FID14-C4", "再入院/24h入出院/24h入院死亡记录变体识别",
                    METHOD_DETERMINISTIC, "partial", R[14],
                    fields=["documents.template_name"],
                    covered="046 T3 词表已扩（再入院记录/24小时内入出院记录/24小时内入院死亡记录）",
                    uncovered="变体文书与主文书同时存在时的择优口径（现场校准前不判）"),
        ],
    },
    34: {
        "interpretation": "首次病程记录由经治/值班医师在入院8小时内完成",
        "clauses": [
            _clause("FID34-C1", "首次病程记录存在", METHOD_DETERMINISTIC, "partial",
                    R[34], fields=["documents.template_name"], sources=["jhemr_blws"],
                    blocked="缺文书子句 046 T3 落地",
                    tests=["test_pa_rules_fid11.py"]),
            _clause("FID34-C2", "入院起 8h 内完成", METHOD_DETERMINISTIC, "full",
                    R[34], fields=["admit_time", "documents.event_time"],
                    sources=["jhemr_blws", "jhemr.pat_visit"],
                    hints={"kind": "time_limit", "threshold_hours": 8,
                           "event": "admission", "doc_name": "首次病程记录",
                           "doc_time_source": "blws"},
                    threshold="《病历书写基本规范》首次病程 8h（030 FID34 行）",
                    pos="入院 08:00 首程 14:00 → pass", neg="入院 08:00 首程 17:00 → fail",
                    tests=["test_pa_rules_t24.py"]),
            _clause("FID34-C3", "经治/值班医师书写", METHOD_MANUAL, "none",
                    blocked="责任者字段无结构化源"),
        ],
    },
    55: {
        "interpretation": "有创诊疗操作记录在操作完成后即时书写、不超过24小时（含操作名称/时间/者签名）",
        "clauses": [
            _clause("FID55-C1", "有创操作事件识别（独立于手术事件）",
                    METHOD_DATA_BLOCKED, "none",
                    blocked="无独立有创操作事件源；现规则以手术事件代替（046 F12：不能一律代替）。未证实前该条款 blocked"),
            _clause("FID55-C2", "操作完成起 24h 内记录", METHOD_DETERMINISTIC, "partial",
                    R[55], fields=["surgery_time", "documents.event_time"],
                    sources=["sm_itf", "jhemr_blws"],
                    threshold="030 FID55 行（≤24h）；事件源=手术（partial）",
                    blocked="事件锚=手术时间为过渡口径，非有创操作完成时刻",
                    pos="手术 09:00，操作记录当日 15:00 → pass",
                    neg="手术 09:00，次日 14:00 才有记录 → fail"),
            _clause("FID55-C3", "内容（名称/时间/签名）完整", METHOD_MANUAL, "none",
                    blocked="正文内容级判定需文书原文（二期）"),
        ],
    },
    57: {
        "interpretation": "手术记录由手术者在术后24h内完成（特殊情况一助书写须手术者签名）",
        "clauses": [
            _clause("FID57-C1", "手术记录文书存在", METHOD_DETERMINISTIC, "partial",
                    R[57], fields=["documents.template_name"],
                    sources=["jhemr_blws"],
                    blocked="现为术前术后文书族组合缺文书（046 F12：组合不能代表存在性子句），046 T3 拆分",
                    hints={"kind": "missing_doc", "family": ["手术记录"]},
                    tests=["test_pa_rules_fid11.py"]),
            _clause("FID57-C2", "术后 24h 内完成", METHOD_DETERMINISTIC, "full",
                    ("R-TIME-SURGERY-RECORD-24H",),
                    fields=["surgery_time", "documents.event_time"],
                    sources=["sm_itf", "jhemr_blws"],
                    threshold="《病历书写基本规范》术后24h（030 FID57 行）；046 T3 落地（每手术事件独立配对评估）",
                    pos="手术 09-01 10:00，手术记录 09-01 18:00 → pass",
                    neg="手术 09-01 10:00，手术记录 09-03 09:00 → fail",
                    tests=["test_pa_rules_fid11.py", "test_pa_engine_events.py"],
                    hints={"kind": "time_limit", "threshold_hours": 24,
                           "event": "surgery", "doc_name": "手术记录",
                           "doc_time_source": "blws"}),
            _clause("FID57-C3", "手术者书写/一助代书+签名", METHOD_MANUAL, "none",
                    blocked="签名与责任者链无结构化源"),
        ],
    },
    59: {
        "interpretation": "麻醉术前访视记录由麻醉医师在术前完成",
        "clauses": [
            _clause("FID59-C1", "麻醉术前访视记录存在", METHOD_DETERMINISTIC, "partial",
                    R[59], fields=["documents.report_name"], sources=["sm_itf"],
                    blocked="存在性已可判（手麻实测 4525 条）；多次手术按事件关联 046 T3 补",
                    hints={"kind": "missing_doc", "family": ["术前访视"]},
                    pos="手麻条目含术前访视", neg="手术病例无术前访视条目 → 缺陷"),
            _clause("FID59-C2", "术前完成（时序）", METHOD_DATA_BLOCKED, "none",
                    blocked="访视记录完成时间与手术时间先后无可靠字段（030 FID59 行）"),
            _clause("FID59-C3", "内容由麻醉医师书写", METHOD_MANUAL, "none",
                    blocked="责任者无源"),
        ],
    },
    61: {
        "interpretation": "麻醉记录由麻醉医师完成",
        "clauses": [
            _clause("FID61-C1", "麻醉记录存在", METHOD_DETERMINISTIC, "partial",
                    R[61], fields=["documents.report_name"], sources=["sm_itf"],
                    blocked="存在性已可判（实测 4561 条）；每手术事件独立 046 T3 补",
                    hints={"kind": "missing_doc", "family": ["麻醉单"]},
                    pos="手麻条目含麻醉单", neg="手术病例无麻醉单条目 → 缺陷"),
            _clause("FID61-C2", "麻醉医师完成", METHOD_MANUAL, "none",
                    blocked="责任者无源（030 FID61 行）"),
        ],
    },
    63: {
        "interpretation": "手术安全核查表由手术/麻醉医师和巡回护士三方在麻醉前、手术前、离室前共同核查签署",
        "clauses": [
            _clause("FID63-C1", "安全核查表存在", METHOD_DETERMINISTIC, "partial",
                    R[63], fields=["documents.report_name"], sources=["sm_itf"],
                    blocked="存在性已可判（实测 5435 条；026 高频 57+35）；每手术事件独立 046 T3 补",
                    hints={"kind": "missing_doc", "family": ["安全核查"]}),
            _clause("FID63-C2", "三方签署", METHOD_MANUAL, "none",
                    blocked="签名链无结构化源（030 FID63 行：文书存在≠签署合规）"),
            _clause("FID63-C3", "三个时点核查内容", METHOD_MANUAL, "none",
                    blocked="内容级判定需表单结构化（无源）"),
        ],
    },
    65: {
        "interpretation": "术后首次病程记录由参加手术的医师在术后即时完成（机器口径=术后24h，标题时间源）",
        "clauses": [
            _clause("FID65-C1", "术后首次病程记录存在", METHOD_DETERMINISTIC, "partial",
                    R[65], fields=["documents.template_name", "file_index.topic"],
                    sources=["jhemr_blws", "jhmr_file_index"],
                    blocked="缺文书子句 046 T3 落地"),
            _clause("FID65-C2", "术后 24h 内完成（标题时间判定）",
                    METHOD_DETERMINISTIC, "full", R[65],
                    fields=["surgery_time", "file_index.topic"],
                    sources=["sm_itf", "jhmr_file_index"],
                    threshold="030 七问 Q2 用户拍板：即时→24h，时间源=jhmr_file_index.topic 标题时间戳",
                    pos="手术 03-01 10:00，标题「2026-03-01 18:30 术后首次病程」→ pass",
                    neg="标题时间 2026-03-03 09:00 → fail",
                    tests=["test_pa_rules_t24.py"]),
            _clause("FID65-C3", "多手术匹配各自术后首程", METHOD_DETERMINISTIC, "none",
                    blocked="现取首个匹配文书；046 T3 按事件实例关联（F12）"),
            _clause("FID65-C4", "参加手术的医师书写", METHOD_MANUAL, "none",
                    blocked="责任者无源"),
        ],
    },
    67: {
        "interpretation": "麻醉术后访视记录由麻醉医师在术后完成",
        "clauses": [
            _clause("FID67-C1", "麻醉术后随访记录存在", METHOD_DETERMINISTIC, "partial",
                    R[67], fields=["documents.report_name"], sources=["sm_itf"],
                    blocked="存在性已可判（实测 4471 条）；每手术事件独立 046 T3 补",
                    hints={"kind": "missing_doc", "family": ["术后随访"]}),
            _clause("FID67-C2", "术后时限", METHOD_DATA_BLOCKED, "none",
                    blocked="030 FID67 行未给明确机器时限口径（'术后完成'无小时数），待质控科"),
        ],
    },
    71: {
        "interpretation": "出院记录在出院后24h内完成（复合条款：另含死亡病例讨论一周内完成）",
        "clauses": [
            _clause("FID71-C1", "出院记录存在且出院起 24h 内完成",
                    METHOD_DETERMINISTIC, "full", R[71],
                    fields=["discharge_time", "documents.event_time"],
                    sources=["jhemr_blws", "jhemr.pat_visit"],
                    hints={"kind": "time_limit", "threshold_hours": 24,
                           "event": "discharge", "doc_name": "出院记录",
                           "doc_time_source": "blws"},
                    threshold="《病历书写基本规范》出院记录 24h（030 FID71 行）",
                    pos="出院 03-05 10:00，出院记录 03-05 18:00 → pass",
                    neg="出院记录 03-07 09:00 → fail",
                    tests=["test_pa_rules_t24.py"]),
            _clause("FID71-C2", "死亡病例讨论一周内完成", METHOD_DATA_BLOCKED, "none",
                    blocked="死亡事件+讨论文书事件关联未证实（030 FID71 行）；死亡讨论不能因同 FID 宣称已覆盖（046 §4.2）"),
            _clause("FID71-C3", "内容完整", METHOD_MANUAL, "none",
                    blocked="正文级判定（030 FID72 行同类）"),
        ],
    },
    88: {
        "interpretation": "手术物品清点记录由巡回护士在手术结束后即时完成",
        "clauses": [
            _clause("FID88-C1", "手术清点记录存在", METHOD_DETERMINISTIC, "partial",
                    R[88], fields=["documents.report_name"], sources=["sm_itf"],
                    blocked="存在性已可判（实测合计约 5548 条）；每手术事件独立 046 T3 补",
                    hints={"kind": "missing_doc", "family": ["手术清点记录"]}),
            _clause("FID88-C2", "巡回护士即时完成", METHOD_MANUAL, "none",
                    blocked="责任者+即时性无源（030 FID88 行）"),
        ],
    },
    10: {
        "interpretation": "首页身份证号/新生儿出生体重/其他诊断/其他手术/呼吸机/ICU/费用等填写完整规范",
        "clauses": [
            _clause("FID10-C1", "首页结构化字段完整性", METHOD_DATA_BLOCKED, "none",
                    blocked="029 K4：首页结构化数据四源不存在；pat_visit 首页字段近30天非空率 8.1% 不可判空（030 七问 Q4）——重新检索资产后再评估，不沿用旧'等179'口径（046 §4.2）",
                    fields=["firstpage.basy"]),
        ],
    },
    11: {
        "interpretation": "首页年龄/出入院时间及科别等基本项目填写齐全（含 026 高频'过敏空项'归属组）",
        "clauses": [
            _clause("FID11-C1", "首页基本字段完整性", METHOD_DATA_BLOCKED, "none",
                    blocked="同 FID10（K4 无结构化源）", fields=["firstpage.*"]),
            _clause("FID11-C2", "过敏药物空项（026 高频 211 次）", METHOD_AI_ASSIST,
                    "partial", ("R-EMPTY-FIRSTPAGE-ALLERGY",),
                    fields=["firstpage.allergy_drug"],
                    blocked="现有 empty_field 规则可判，但 alergy_drugs 非空率 8.1% 说明数据面不可靠（030 Q4）；规则 mark_item_fid=null 待质控科确认归属",
                    pos="首页过敏药物=「无」→ pass（A13）", neg="首页过敏药物空 → 缺陷"),
        ],
    },
    12: {
        "interpretation": "首页其他项目填写完整规范",
        "clauses": [
            _clause("FID12-C1", "首页其他项目完整性", METHOD_DATA_BLOCKED, "none",
                    blocked="同 FID10（K4）", fields=["firstpage.*"]),
        ],
    },
    15: {
        "interpretation": "入院记录一般项目填写齐全准确（含 026 高频'出生地空项 52 次'）",
        "clauses": [
            _clause("FID15-C1", "入院记录一般项目齐全", METHOD_DATA_BLOCKED, "none",
                    blocked="文书字段级数据源未证实（030 FID15 行）；出生地等字段在正文非结构化列"),
        ],
    },
    38: {
        "interpretation": "上级医师首次查房记录在入院后48小时内完成",
        "clauses": [
            _clause("FID38-C1", "上级首次查房 48h 时限", METHOD_DETERMINISTIC, "full",
                    ("R-TIME-FIRST-WARD-ROUND-48H",),
                    fields=["admit_time", "documents.event_time"],
                    sources=["jhemr_blws", "jhemr.pat_visit"],
                    hints={"kind": "time_limit", "threshold_hours": 48,
                           "event": "admission", "doc_name": "上级医师查房记录",
                           "doc_time_source": "blws"},
                    threshold="《病历书写基本规范》48h（030 FID38 行）",
                    pos="入院 08-20 08:00，查房记录 08-21 09:00 → pass",
                    neg="入院 08-20 08:00，查房记录 08-23 10:00 → fail",
                    tests=["test_pa_rules_fid11.py"],
                    uncovered="词表=上级/首次查房（029 P0-3⑤ 现场校准前为近似词表）"),
            _clause("FID38-C2", "上级医师身份/职称", METHOD_MANUAL, "none",
                    blocked="责任者层级无源（030 FID38 行）"),
        ],
    },
    41: {
        "interpretation": "日常病程按病情频次书写（病危随时/至少每日一次；病重至少2日一次；稳定至少3日一次）",
        "clauses": [
            _clause("FID41-C1", "病危患者每日病程", METHOD_DATA_BLOCKED, "none",
                    blocked="病危/病重状态需医嘱病情状态源（030 FID41 行）；无状态不得假定稳定患者（046 §4.2）"),
            _clause("FID41-C2", "病重患者隔日病程", METHOD_DATA_BLOCKED, "none",
                    blocked="同上"),
            _clause("FID41-C3", "稳定患者三日病程", METHOD_DATA_BLOCKED, "none",
                    blocked="同上（需先证实病危病重状态可用，否则只能对全部住院日按最宽松间隔提示）"),
        ],
    },
    48: {
        "interpretation": "交接班记录/转科记录/阶段小结在规定时限内完成",
        "clauses": [
            _clause("FID48-C1", "交接班记录时限", METHOD_DETERMINISTIC, "none",
                    blocked="每种事件定义与期限需质控科细化（030 FID48 行；046 §4.2 拆原子规则）"),
            _clause("FID48-C2", "转科记录时限", METHOD_DETERMINISTIC, "none",
                    blocked="同上"),
            _clause("FID48-C3", "阶段小结时限", METHOD_DETERMINISTIC, "none",
                    blocked="同上"),
        ],
    },
    49: {
        "interpretation": "常规会诊24h内完成、急会诊10分钟内到场并即刻完成会诊记录",
        "clauses": [
            _clause("FID49-C1", "常规会诊 24h", METHOD_DATA_BLOCKED, "none",
                    blocked="K2：CONSULTATION_ID 全空（029 P0 实测），会诊申请/到场/结束时间无源"),
            _clause("FID49-C2", "急会诊 10 分钟到场", METHOD_DATA_BLOCKED, "none",
                    blocked="同上"),
        ],
    },
    53: {
        "interpretation": "抢救记录在抢救结束后6小时内完成（参加抢救医师书写、主持者审核签字）",
        "clauses": [
            _clause("FID53-C1", "抢救结束起 6h 内记录", METHOD_DATA_BLOCKED, "none",
                    blocked="抢救结束事件识别无标记源；不能由词频推定结束时间（030 FID53/046 §4.2）"),
            _clause("FID53-C2", "主持抢救医师审核签字", METHOD_MANUAL, "none",
                    blocked="签名链无源"),
        ],
    },
    80: {
        "interpretation": "辅助检查报告单与医嘱内容相符、完整无遗漏",
        "clauses": [
            _clause("FID80-C1", "检查医嘱/申请与报告匹配", METHOD_DATA_BLOCKED, "none",
                    blocked="HIS REPORTNAME 数字编码语义待确认（029 K2 仅 0/1/2 且 0/1 成对相等）；取消/退单/外送状态、订单关联无源（046 §4.2）。已有泛检验配置不算完成"),
        ],
    },
    82: {
        "interpretation": "输血病例应有输血前检查项目报告单和发血记录单",
        "clauses": [
            _clause("FID82-C1", "输血前检查报告单存在", METHOD_DATA_BLOCKED, "none",
                    blocked="输血事件触发源待定（LIS 输血科类别 2995 条可用作候选词表，030 FID82 行）"),
            _clause("FID82-C2", "发血记录单存在", METHOD_DATA_BLOCKED, "none",
                    blocked="同上"),
        ],
    },
    90: {
        "interpretation": "输血护理记录内容完整（含血型/输血史/不良反应等）",
        "clauses": [
            _clause("FID90-C1", "输血护理记录存在/内容", METHOD_DATA_BLOCKED, "none",
                    blocked="手麻词表无对应词（仅'取血单'1条，030 FID90 行）；RPTCOUNT 不能代替（§1.3）"),
        ],
    },
}

B_CURATED: dict[int, dict] = {
    2: {"interpretation": "病历内容客观真实，不得前后矛盾",
        "clauses": [_clause("FID2-C1", "跨文书一致性（客观真实不矛盾）", METHOD_AI_ASSIST,
                            "none", fields=["document_text"],
                            blocked="并入现有六类语义质控的关联候选；需逐类核对输入确有对应证据（046 §4.3），首轮只读关联不生成确定性缺陷")]},
    8: {"interpretation": "主要诊断选择填写正确",
        "clauses": [_clause("FID8-C1", "主要诊断选择正确性", METHOD_AI_ASSIST, "none",
                            blocked="关联 discharge_vs_frontpage 等语义审计；注意该类型名不能证明输入含首页（046 F10/§4.3）——语义缺口待真实 payload 核验")]},
    9: {"interpretation": "主要手术及操作选择填写正确",
        "clauses": [_clause("FID9-C1", "主要手术选择正确性", METHOD_AI_ASSIST, "none",
                            blocked="关联 syssvsscbc 语义审计（首页手术 vs 术后首程）；首页结构化输入未证实（K4）")]},
    13: {"interpretation": "首页填写内容与病历内容一致互为印证",
        "clauses": [_clause("FID13-C1", "首页 vs 病历一致性", METHOD_AI_ASSIST, "none",
                            blocked="跨文书一致性语义；首页输入源未证实（同 FID8 缺口）")]},
    16: {"interpretation": "主诉不超过20字、能导出第一诊断、不用诊断名称代替",
        "clauses": [
            _clause("FID16-C1", "主诉≤20字", METHOD_DETERMINISTIC, "none",
                    fields=["document_text"],
                    blocked="可确定性计算，但需文书正文解析源（030 FID16 行：文本可算→二期）"),
            _clause("FID16-C2", "主诉导出第一诊断/不用诊断名代替", METHOD_AI_ASSIST, "none",
                    blocked="语义判断，需正文+语义审计（二期）"),
        ]},
    17: {"interpretation": "现病史与主诉相符",
        "clauses": [_clause("FID17-C1", "现病史与主诉相符", METHOD_AI_ASSIST, "none",
                            blocked="语义辅助（046 §4.3）；正文源未接")]},
    32: {"interpretation": "初步诊断合理、疾病名称规范、主次分明",
        "clauses": [_clause("FID32-C1", "初步诊断合理性/规范性", METHOD_AI_ASSIST, "none",
                            blocked="语义辅助；诊断规范词表未接")]},
}

# C 类 62 条：分类理由（030 备注）+ 高频标记；全部 manual。
C_NOTES = {
    1: "涂改/模仿签名（内容+签名层）", 3: "签名（历史高频）",
    4: "修改规范（双线划改保留原记录）", 5: "日期格式规范（24小时制；二期PDF层可算）",
    6: "术语/页面/页码（历史高频）", 7: "墨水/打印规范",
    18: "现病史发病情况", 19: "现病史症状特点", 20: "现病史伴随症状",
    21: "现病史诊疗经过", 22: "现病史一般情况", 23: "现病史其他疾病",
    24: "既往史（含过敏史记录，历史高频）", 25: "个人史", 26: "婚育史（历史高频）",
    27: "家族史", 28: "体格检查项目齐全", 29: "查体重点描述", 30: "专科检查",
    31: "辅助检查记录", 33: "入院记录签名", 35: "首程病例特点（历史高频）",
    36: "首程诊断依据", 37: "首程诊疗计划", 39: "上级首查内容", 40: "日常查房内容",
    42: "病情记录内容", 43: "辅检结果记录", 44: "诊疗措施记录（历史高频）",
    45: "告知记录", 46: "输血病程记录", 47: "疑难讨论", 50: "会诊申请记录（会诊数据无源）",
    51: "会诊记录内容（会诊数据无源）", 52: "会诊意见执行（会诊数据无源）",
    54: "抢救记录内容", 56: "术前小结内容（026 C类312次，历史高频）",
    58: "手术记录内容（历史高频）", 60: "麻醉访视内容", 62: "麻醉记录内容",
    64: "核查表内容（历史高频）", 66: "术后首程内容", 68: "术后访视内容",
    69: "医疗器械信息记录", 70: "条形码粘贴", 72: "出院记录内容（历史高频）",
    73: "死亡讨论内容", 74: "知情同意签署", 75: "同意书规范（历史高频；排除词表防误命中）",
    76: "处方办法（历史高频）", 77: "医嘱规范", 78: "医嘱时间签名（历史高频）",
    79: "医嘱取消补录", 81: "外院报告原件", 83: "报告单规范", 84: "签名权限",
    85: "体温单（护理系统无接口，028 已移出一期）", 86: "护理记录连续性",
    87: "护理记录内容", 89: "清点记录内容", 91: "血糖记录（护理，移出一期）",
    92: "血糖谱（护理，移出一期）",
}

# C 类判定缺口分类（用于批量生成条款 method=manual 的理由前缀）
C_GAP_KIND = {
    "签名": "签名/资质链无结构化数据源",
    "内容": "正文内容级语义判定（需文书原文/OCR，二期）",
    "护理": "护理系统无接口（028 一期移出）",
    "会诊": "会诊数据无源（K2 CONSULTATION_ID 全空）",
    "医嘱": "医嘱明细结构化语义未接入",
    "规范": "版式/格式/流程规范属人工裁量",
}


def _c_gap_reason(note: str) -> str:
    for kind, reason in C_GAP_KIND.items():
        if kind in note:
            return f"{reason}（030 备注：{note}）"
    return f"正文/人工裁量级条款，无结构化数据源（030 备注：{note}）"


def build_coverage_records(snapshot_items: list,
                           snapshot_id: str = DEFAULT_SNAPSHOT_ID) -> list[dict]:
    """快照 items（[{fid,ftypeid,fscore,fname}]）→ 92 条账本记录。"""
    records = []
    seen = set()
    for item in snapshot_items or []:
        fid = int(item["fid"])
        seen.add(fid)
        fname = str(item.get("fname") or "")
        group_code = str(item.get("ftypeid") or "")
        fscore = str(item.get("fscore") or "0")

        if fid in A_CURATED:
            base = A_CURATED[fid]
            category = "A"
        elif fid in B_CURATED:
            base = B_CURATED[fid]
            category = "B"
        else:
            note = C_NOTES.get(fid, "纯人工裁量条款")
            base = {"interpretation": note,
                    "clauses": [_clause(f"FID{fid}-C1", note, METHOD_MANUAL, "none",
                                        blocked=_c_gap_reason(note))]}
            category = "C"

        methods = [c["method"] for c in base["clauses"]]
        if METHOD_DETERMINISTIC in methods:
            overall = METHOD_DETERMINISTIC
        elif METHOD_AI_ASSIST in methods:
            overall = METHOD_AI_ASSIST
        elif METHOD_DATA_BLOCKED in methods:
            overall = METHOD_DATA_BLOCKED
        else:
            overall = METHOD_MANUAL

        severity = "high" if float(fscore or 0) >= 5 else (
            "medium" if float(fscore or 0) >= 1 else "low")
        records.append({
            "fid": fid,
            "source_system": SOURCE_SYSTEM,
            "snapshot_id": snapshot_id,
            "original_text": fname,
            "original_text_sha256": hashlib.sha256(
                fname.encode("utf-8")).hexdigest(),
            "score": fscore,
            "group_code": group_code,
            "group_name": GROUP_NAMES.get(group_code, group_code),
            "enabled": int(item.get("fisenable", 1)) == 1,
            "category": category,
            "interpretation": base["interpretation"],
            "overall_method": overall,
            "clauses": base["clauses"],
            "severity_suggestion": severity,
            "historical_high_freq": fid in HISTORICAL_HIGH_FREQ,
            "status": "draft",
            "verified_at": "",
            "rule_version": "",
            "owner": "",
            "next_step": "",
        })
    if len(seen) != len(snapshot_items or []):
        raise ValueError("snapshot contains duplicate fid")
    return records


def coverage_counts(records: list[dict]) -> dict:
    """账本汇总（T5 规则中心页直接复用）。overall_method 缺省时从条款推导。"""
    by_method: dict[str, int] = {}
    full = partial = none = 0

    def _overall(r: dict) -> str:
        if r.get("overall_method"):
            return r["overall_method"]
        methods = [c.get("method") for c in r.get("clauses") or []]
        for m in (METHOD_DETERMINISTIC, METHOD_AI_ASSIST, METHOD_DATA_BLOCKED,
                  METHOD_MANUAL):
            if m in methods:
                return m
        return METHOD_MANUAL

    for r in records or []:
        overall = _overall(r)
        by_method[overall] = by_method.get(overall, 0) + 1
        has_full = any(c.get("coverage") == "full" for c in r.get("clauses") or [])
        has_partial = any(c.get("coverage") == "partial"
                          for c in r.get("clauses") or [])
        if has_full:
            full += 1
        elif has_partial:
            partial += 1
        else:
            none += 1
    return {"catalog_count": len(records or []),
            "by_method": by_method,
            "full_coverage": full, "partial_coverage": partial, "no_coverage": none}


def write_coverage_json(records: list[dict], path=COVERAGE_OUTPUT) -> str:
    payload = {
        "version": "v1-20260910",
        "generated_from": DEFAULT_SNAPSHOT_ID,
        "counts": coverage_counts(records),
        "items": records,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return str(path)


def load_snapshot_items(path=SNAPSHOT_DEFAULT) -> list:
    from .paperless import load_snapshot_items as _load
    return _load(str(path) if path else str(SNAPSHOT_DEFAULT))


def diff_coverage_against_rules(records: list[dict], published_rules: list[dict]) -> dict:
    """已发布规则 mark_item_fid → 账本核对：已关联 FID 数/悬空 FID/未关联规则。"""
    linked = set()
    for rule in published_rules or []:
        fid = rule.get("mark_item_fid")
        if fid is not None:
            linked.add(int(fid))
    known = {r["fid"] for r in records or []}
    return {"published_rules": len(published_rules or []),
            "linked_fids": sorted(linked),
            "dangling_fids": sorted(linked - known),
            "unlinked_rule_ids": [r.get("rule_id") for r in published_rules or []
                                  if r.get("mark_item_fid") is None]}

"""fanout 源 field_mapping 患者身份提取回归（035/RP9-C2）。

背景：jyjc_vs_bcnursing nursing 源 field_mapping 曾因编码损坏写成
patient_id='??ID' / visit_number='??'，正确值应为 loader 注入列 '患者ID'/'次数'。
乱码期间靠 _record_group_values 的「映射键 miss→原键」兜底链休眠存活，
本文件固化：①正确映射直接命中注入列；②兜底链行为不被悄悄移除；
③配置文件不得再出现 '?' 乱码映射值。
"""

import json
from pathlib import Path

import pytest

from app.services.data_source_loader import _record_group_values

_CORRECTED_MAPPING = {"patient_id": "患者ID", "visit_number": "次数"}


def _fanout_record(patient_id: str = "P001", visit_number: str = "1") -> dict:
    """模拟 _oracle_fanout_worker 产出的记录形态：列名小写 + 身份列注入。"""
    return {
        "nursing_patient_id": patient_id,
        "patient_uid": "uid-1",
        "form_id": "f1",
        "event_time": "2026-08-30 08:00:00",
        "record_name": "general_nursing_record",
        "content": "体温平稳",
        "患者ID": patient_id,
        "次数": visit_number,
        "patient_id": patient_id,
        "visit_number": visit_number,
    }


def test_corrected_mapping_hits_injected_identity_columns_directly():
    record = _fanout_record("P1024", "3")
    values = _record_group_values(record, _CORRECTED_MAPPING, ["patient_id", "visit_number"])
    assert values == {"patient_id": "P1024", "visit_number": "3"}


def test_identity_fallback_chain_keeps_broken_mapping_dormant():
    """乱码映射期间为什么没炸：映射键 miss → 回退原键 → 命中注入列。"""
    record = _fanout_record("P7", "2")
    mojibake_mapping = {"patient_id": "??ID", "visit_number": "??"}
    values = _record_group_values(record, mojibake_mapping, ["patient_id", "visit_number"])
    assert values == {"patient_id": "P7", "visit_number": "2"}


def test_fanout_sql_identity_contract_on_local_config():
    """本地 config.json（存在时）jyjc nursing 映射必须为注入列名。"""
    path = Path("config/config.json")
    if not path.exists():
        pytest.skip("本地 config/config.json 不存在")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    jyjc = next(at for at in cfg.get("audit_types", []) if at.get("code") == "jyjc_vs_bcnursing")
    fm = jyjc["sources"]["nursing"]["field_mapping"]
    assert fm.get("patient_id") == "患者ID"
    assert fm.get("visit_number") == "次数"


@pytest.mark.parametrize("config_path", ["config/config.json", "config/config.json.template"])
def test_no_mojibake_question_marks_in_field_mappings(config_path):
    """任何 field_mapping 值不得包含 '?'：编码损坏（GBK→UTF-8 丢字）产物为问号。"""
    path = Path(config_path)
    if not path.exists():
        pytest.skip(f"{config_path} 不存在")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for at in cfg.get("audit_types", []):
        for source_name, source in (at.get("sources") or {}).items():
            for key, value in (source.get("field_mapping") or {}).items():
                assert "?" not in str(value), (
                    f"{at.get('code')}.{source_name}.field_mapping.{key}={value!r} 含 '?' 乱码"
                )

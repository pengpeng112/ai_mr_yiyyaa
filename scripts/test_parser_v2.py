"""
解析器 v2 兼容性验证脚本
验证 parse_dify_structured_output 对 v1/v2/mixed 输入的兼容性

用法:
    python scripts/test_parser_v2.py
"""
import sys
import os
import json

# 强制 UTF-8 输出，兼容 Windows GBK 终端
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.dify_pusher import parse_dify_structured_output

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures")

REQUIRED_6_CODES = {
    "diagnosis_consistency",
    "nursing_level_consistency",
    "vital_sign_consistency",
    "condition_consistency",
    "treatment_measure_consistency",
    "timeline_consistency",
}

VALID_ALERT_LEVELS = {"red", "yellow", "blue", "gray", ""}
VALID_PUSH_STRATEGIES = {"immediate", "batch", "shift_summary", "review_only", ""}
VALID_OUTCOME_BUCKETS = {"primary", "secondary", "none", ""}
VALID_SEVERITIES = {"high", "medium", "low", ""}
VALID_STATUSES = {"pass", "fail", "warn", "unknown"}

passed = 0
failed = 0
errors = []


def assert_true(condition: bool, msg: str):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        errors.append(msg)
        print(f"  ❌ FAIL: {msg}")


def assert_eq(actual, expected, msg: str):
    assert_true(actual == expected, f"{msg}: expected={expected!r}, actual={actual!r}")


def assert_in(value, valid_set: set, msg: str):
    assert_true(value in valid_set, f"{msg}: {value!r} not in {valid_set}")


def load_fixture(name: str) -> dict:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_v1_legacy():
    """测试 v1 旧版输出（中文字段名）能正确解析"""
    print("\n[Test 1] v1 旧版输出兼容性")
    data = load_fixture("v1_legacy_output.json")
    result = parse_dify_structured_output({"result": data})

    assert_true(result["parse_success"], "v1 解析应成功")
    assert_eq(result["patient_name"], "李四", "患者姓名")
    assert_eq(result["patient_id"], "P20260101001", "患者ID")
    assert_eq(result["dept"], "呼吸科", "科室")
    assert_true(len(result["dimensions"]) >= 5, f"维度数应>=5, 实际={len(result['dimensions'])}")

    # v1 输出不含 alert_level，应为空或后处理派生
    # 不强制要求非空，但必须是合法值
    assert_in(result.get("alert_level", ""), VALID_ALERT_LEVELS, "总体 alert_level 合法")
    assert_in(result.get("severity", ""), VALID_SEVERITIES, "总体 severity 合法")

    # v1 不含 overall_qc_summary，应为空
    # (post-process 可能派生，所以只检查类型)
    assert_true(isinstance(result.get("overall_qc_summary", ""), str), "overall_qc_summary 应为字符串")

    # 维度级别检查
    for dim in result["dimensions"]:
        assert_in(dim.get("status", ""), VALID_STATUSES, f"维度 {dim.get('dimension')} status 合法")
        assert_in(dim.get("severity", ""), VALID_SEVERITIES, f"维度 {dim.get('dimension')} severity 合法")
    print(f"  ✅ v1 兼容性测试完成")


def test_v2_full():
    """测试 v2 完整输出（含所有 alert 字段）"""
    print("\n[Test 2] v2 完整输出解析")
    data = load_fixture("v2_full_output.json")
    result = parse_dify_structured_output({"result": data})

    assert_true(result["parse_success"], "v2 解析应成功")
    assert_eq(result["patient_name"], "张三", "患者姓名")
    assert_eq(result["patient_id"], "P202604020001", "患者ID")
    assert_eq(result["dept"], "心内科", "科室")
    assert_eq(result["version"], "2.0", "版本号")

    # 总体 alert 字段
    assert_eq(result["alert_level"], "red", "总体 alert_level")
    assert_eq(result["severity"], "high", "总体 severity")
    assert_eq(result["closure_hours"], 24, "总体 closure_hours")
    assert_eq(result["push_strategy"], "immediate", "总体 push_strategy")
    assert_eq(result["outcome_bucket"], "primary", "总体 outcome_bucket")
    assert_true(bool(result["overall_qc_summary"]), "overall_qc_summary 应非空")
    assert_true(result["inconsistency"], "应检测到不一致")
    assert_eq(result["risk_score"], 78, "风险分值")

    # 维度检查 - 应有 6 个
    assert_eq(len(result["dimensions"]), 6, "维度数量")
    codes = {dim["dimension_code"] for dim in result["dimensions"]}
    assert_eq(codes, REQUIRED_6_CODES, "6 个维度编码完整")

    # 检查各维度 alert 字段
    for dim in result["dimensions"]:
        code = dim["dimension_code"]
        assert_in(dim["alert_level"], VALID_ALERT_LEVELS, f"{code}.alert_level 合法")
        assert_in(dim["push_strategy"], VALID_PUSH_STRATEGIES, f"{code}.push_strategy 合法")
        assert_in(dim["outcome_bucket"], VALID_OUTCOME_BUCKETS, f"{code}.outcome_bucket 合法")
        assert_true(isinstance(dim["closure_hours"], int), f"{code}.closure_hours 应为整数")
        assert_true(0.0 <= dim["confidence"] <= 1.0, f"{code}.confidence 应在 [0,1]")
        assert_in(dim["severity"], VALID_SEVERITIES, f"{code}.severity 合法")

    # 具体维度值检查
    dim_map = {d["dimension_code"]: d for d in result["dimensions"]}
    assert_eq(dim_map["diagnosis_consistency"]["alert_level"], "red", "诊断维度应为红灯")
    assert_eq(dim_map["nursing_level_consistency"]["alert_level"], "yellow", "护理级别维度应为黄灯")
    assert_eq(dim_map["treatment_measure_consistency"]["alert_level"], "gray", "诊疗措施维度应为灰灯")
    assert_eq(dim_map["vital_sign_consistency"]["alert_level"], "blue", "生命体征维度应为蓝灯")
    print(f"  ✅ v2 完整解析测试完成")


def test_v2_all_pass():
    """测试 v2 全部通过场景"""
    print("\n[Test 3] v2 全部通过场景")
    data = load_fixture("v2_all_pass.json")
    result = parse_dify_structured_output({"result": data})

    assert_true(result["parse_success"], "解析应成功")
    assert_eq(result["alert_level"], "blue", "全部通过时总体应为蓝灯")
    assert_eq(result["severity"], "low", "全部通过时 severity 应为 low")
    assert_eq(len(result["dimensions"]), 6, "维度数量")

    for dim in result["dimensions"]:
        assert_eq(dim["status"], "pass", f"{dim['dimension_code']} 应为 pass")
        assert_eq(dim["alert_level"], "blue", f"{dim['dimension_code']} 应为蓝灯")
    print(f"  ✅ 全部通过场景测试完成")


def test_v2_gray_dominant():
    """测试 v2 灰灯主导场景"""
    print("\n[Test 4] v2 灰灯主导场景")
    data = load_fixture("v2_gray_dominant.json")
    result = parse_dify_structured_output({"result": data})

    assert_true(result["parse_success"], "解析应成功")
    assert_eq(result["alert_level"], "gray", "灰灯主导时总体应为灰灯")

    dim_map = {d["dimension_code"]: d for d in result["dimensions"]}
    gray_dims = [code for code, dim in dim_map.items() if dim["alert_level"] == "gray"]
    assert_true(len(gray_dims) >= 3, f"至少 3 个灰灯维度, 实际={len(gray_dims)}")

    # 灰灯维度的置信度应 < 0.6（在 fixture 中设定）
    for code in gray_dims:
        assert_true(dim_map[code]["confidence"] < 0.6, f"{code} 灰灯维度 confidence 应 < 0.6")
    print(f"  ✅ 灰灯主导场景测试完成")


def test_alert_severity_derivation():
    """测试 alert_level → severity 自动派生"""
    print("\n[Test 5] alert_level → severity 派生")
    # 构造一个只有 alert_level 没有 severity 的输入
    data = {
        "version": "2.0",
        "patient_summary": {"patient_id": "TEST001", "patient_name": "测试"},
        "audit_summary": {
            "has_inconsistency": True,
            "alert_level": "yellow",
            "closure_hours": 72,
            "push_strategy": "batch",
            "outcome_bucket": "secondary",
            "overall_conclusion": "测试派生",
        },
        "dimensions": [
            {
                "dimension_code": "diagnosis_consistency",
                "dimension_name": "诊断一致性",
                "status": "warn",
                "confidence": 0.85,
                "alert_level": "yellow",
                "issue_summary": "测试",
            }
        ],
    }
    result = parse_dify_structured_output({"result": data})
    assert_true(result["parse_success"], "解析应成功")
    # severity 应从 alert_level 派生
    assert_eq(result["severity"], "medium", "yellow → medium 派生")
    assert_eq(result["alert_level"], "yellow", "alert_level 保持 yellow")
    print(f"  ✅ 派生逻辑测试完成")


def test_v1_no_alert_fields():
    """测试 v1 输出不包含 alert 字段时，新字段有合理默认值"""
    print("\n[Test 6] v1 缺少 alert 字段时默认值")
    data = load_fixture("v1_legacy_output.json")
    result = parse_dify_structured_output({"result": data})

    # 新字段应有默认值（空或 0），不应报错
    assert_true(isinstance(result.get("closure_hours", 0), int), "closure_hours 应为整数")
    assert_true(isinstance(result.get("push_strategy", ""), str), "push_strategy 应为字符串")
    assert_true(isinstance(result.get("outcome_bucket", ""), str), "outcome_bucket 应为字符串")
    assert_true(isinstance(result.get("overall_qc_summary", ""), str), "overall_qc_summary 应为字符串")
    print(f"  ✅ 默认值测试完成")


def test_chinese_alert_level_normalization():
    """测试中文预警灯号归一化"""
    print("\n[Test 7] 中文预警灯号归一化")
    data = {
        "version": "2.0",
        "patient_summary": {"patient_id": "TEST002", "patient_name": "测试"},
        "audit_summary": {
            "has_inconsistency": True,
            "alert_level": "红灯",
            "severity": "high",
            "overall_conclusion": "测试中文灯号",
        },
        "dimensions": [
            {
                "dimension_code": "diagnosis_consistency",
                "dimension_name": "诊断一致性",
                "status": "fail",
                "severity": "high",
                "confidence": 0.90,
                "alert_level": "红",
                "issue_summary": "测试",
            },
            {
                "dimension_code": "nursing_level_consistency",
                "dimension_name": "护理级别执行",
                "status": "warn",
                "severity": "medium",
                "confidence": 0.80,
                "alert_level": "黄灯",
                "issue_summary": "测试",
            },
        ],
    }
    result = parse_dify_structured_output({"result": data})
    assert_true(result["parse_success"], "解析应成功")
    assert_eq(result["alert_level"], "red", "红灯 → red")

    dim_map = {d["dimension_code"]: d for d in result["dimensions"]}
    assert_eq(dim_map["diagnosis_consistency"]["alert_level"], "red", "红 → red")
    assert_eq(dim_map["nursing_level_consistency"]["alert_level"], "yellow", "黄灯 → yellow")
    print(f"  ✅ 中文灯号归一化测试完成")


def test_markdown_wrapped_json():
    """测试 markdown 代码块包裹的 JSON 能正确解析"""
    print("\n[Test 8] Markdown 代码块包裹兼容")
    v2_data = load_fixture("v2_full_output.json")
    wrapped = "```json\n" + json.dumps(v2_data, ensure_ascii=False) + "\n```"
    result = parse_dify_structured_output({"result": wrapped})

    assert_true(result["parse_success"], "markdown 包裹的 JSON 应能解析")
    assert_eq(result["patient_name"], "张三", "患者姓名")
    assert_eq(result["alert_level"], "red", "alert_level")
    print(f"  ✅ Markdown 包裹兼容测试完成")


def test_fallback_keyword_inference():
    """测试非 JSON 输出时的关键词回退推断"""
    print("\n[Test 9] fallback 关键词推断")
    raw_text = "系统判定存在不一致，属于 high 风险，需要尽快处理。"
    result = parse_dify_structured_output({"result": raw_text})

    assert_true(not result["parse_success"], "fallback 推断时 parse_success 应为 False")
    assert_true(result.get("fallback_inference", False), "应标记 fallback_inference=True")
    assert_true(result["inconsistency"], "应通过关键词识别到不一致")
    assert_eq(result["severity"], "high", "high 关键词应派生高风险")
    assert_true(bool(result["overall_conclusion"]), "fallback 应补充总体结论")
    print(f"  ✅ fallback 关键词推断测试完成")


if __name__ == "__main__":
    print("=" * 60)
    print("  解析器 v2 兼容性验证")
    print("=" * 60)

    test_v1_legacy()
    test_v2_full()
    test_v2_all_pass()
    test_v2_gray_dominant()
    test_alert_severity_derivation()
    test_v1_no_alert_fields()
    test_chinese_alert_level_normalization()
    test_markdown_wrapped_json()
    test_fallback_keyword_inference()

    print("\n" + "=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    if errors:
        print("\n失败详情:")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        sys.exit(1)
    else:
        print("\n✅ 所有测试通过!")
        sys.exit(0)

"""测试 logs 跳过原因标签映射。"""
from app.routers.logs import _SKIP_REASON_LABELS


class TestSkipReasonLabels:
    def test_all_expected_reasons_have_labels(self):
        expected = [
            "empty_lab_exam",
            "empty_progress_nursing",
            "empty_both_sides",
            "empty_primary",
            "empty_frontpage",
            "unreviewed_pending",
            "rectified_suppressed",
            "already_succeeded",
            "cancelled",
        ]
        for reason in expected:
            assert reason in _SKIP_REASON_LABELS, f"缺少跳过原因标签: {reason}"

    def test_labels_are_chinese(self):
        for reason, label in _SKIP_REASON_LABELS.items():
            assert label, f"标签不能为空: {reason}"
            # 至少包含一个中文字符
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), f"标签应包含中文: {reason} -> {label}"

    def test_empty_lab_exam_label_distinct_from_others(self):
        """确保 empty_lab_exam 不再是旧的混合描述。"""
        assert _SKIP_REASON_LABELS["empty_lab_exam"] != "检验检查或病程护理数据为空", "empty_lab_exam 标签应已更新"

    def test_empty_progress_nursing_exists(self):
        assert "empty_progress_nursing" in _SKIP_REASON_LABELS
        assert _SKIP_REASON_LABELS["empty_progress_nursing"] == "病程护理记录为空"

    def test_empty_both_sides_exists(self):
        assert "empty_both_sides" in _SKIP_REASON_LABELS
        assert _SKIP_REASON_LABELS["empty_both_sides"] == "检验检查和病程护理均为空"

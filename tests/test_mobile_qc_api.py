"""
医生端 H5（mobile_qc）接口自动化测试。

覆盖 docs/ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md §4.2.4 / §4.3：
- H5 页面 token 校验各分支（无 token / 配置异常 / 过期 / 不匹配 / 正常）
- 详情接口查看记录写入（viewed_flag / view_count / viewer 来源优先级 / 异常回滚）
- 三种反馈（acknowledged / rectified / other）+ 重复提交 409 + 提交人来源
- verify-token 健康检查
- payload evidence 提取

测试模式沿用 test_qc_feedback_api.py：SimpleNamespace 模拟 ORM 对象，MagicMock 模拟 db，
monkeypatch 替换 _get_token_secret / verify_alert_token，pytest.raises 断言 HTTPException。
"""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers import mobile_qc


# ---------- helpers ----------

def _make_request(headers=None, host="10.0.0.1", ua="Mozilla/5.0"):
    """构造一个最小可用的 Request 替身。

    handler 从 request.headers.get("user-agent") 和 request.client.host 取值，
    因此 ua 必须作为 header 键（而非对象属性）。
    """
    merged = dict(headers or {})
    if "user-agent" not in merged:
        merged["user-agent"] = ua
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        headers=merged,
    )


def _make_alert(**overrides):
    """构造一个 QCRecordAlertLog 替身。"""
    base = dict(
        id=500,
        push_log_id=900,
        dept="心内科",
        alert_level="red",
        severity="high",
        dimension_code="DIM1",
        payload_json=json.dumps({
            "evidence_summary": "护理记录与病程不一致",
            "evidence_titles": {"A": "首次病程"},
            "doctor_name": "李医生",
            "doctor_id": "D001",
        }),
        viewed_flag=0,
        viewed_at=None,
        last_viewed_at=None,
        view_count=0,
        viewer_userid="",
        viewer_name="",
        viewer_ip="",
        viewer_user_agent="",
        created_at=datetime(2026, 7, 10, 8, 30, 0),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_db_with_alert(alert, feedback_existing=None):
    """
    构造 MagicMock db：query().filter().first() 按 model 分流。
    alert = 返回的 QCRecordAlertLog；feedback_existing = 已存在的 QCAlertFeedback（用于 409）。
    """
    db = MagicMock()

    def _query(model):
        chain = MagicMock()
        filt = MagicMock()
        chain.filter.return_value = filt
        chain.filter_by.return_value = filt  # 以防使用 filter_by

        # 默认 first() 返回 None
        filt.first.return_value = None

        # 按 model 分流 first() 返回值
        from app.models import QCRecordAlertLog, QCAlertFeedback
        if model is QCRecordAlertLog:
            filt.first.return_value = alert
        elif model is QCAlertFeedback and feedback_existing is not None:
            filt.first.return_value = feedback_existing
        return chain

    db.query.side_effect = _query
    return db


# ---------- H5 页面 mobile_qc_page ----------

class TestMobileQcPage:
    """GET /mobile/qc/{alert_id} —— H5 页面 token 校验。"""

    def test_no_token_returns_400(self):
        resp = mobile_qc.mobile_qc_page(alert_id=500, token="")
        assert resp.status_code == 400
        assert "缺少访问令牌" in resp.body.decode("utf-8")

    def test_secret_not_configured_returns_401(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "")
        resp = mobile_qc.mobile_qc_page(alert_id=500, token="some")
        assert resp.status_code == 401
        assert "配置异常" in resp.body.decode("utf-8")

    def test_token_invalid_returns_401(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "secret")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: None)
        resp = mobile_qc.mobile_qc_page(alert_id=500, token="bad")
        assert resp.status_code == 401
        assert "过期或无效" in resp.body.decode("utf-8")

    def test_token_mismatch_returns_401(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "secret")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 499)
        resp = mobile_qc.mobile_qc_page(alert_id=500, token="ok")
        assert resp.status_code == 401
        assert "不匹配" in resp.body.decode("utf-8")


# ---------- 详情接口 get_qc_detail ----------

class TestGetQcDetail:
    """GET /api/mobile/qc-detail/{alert_id} —— 查看记录写入与详情组装。"""

    def test_no_token_raises_400(self):
        db = _make_db_with_alert(_make_alert())
        with pytest.raises(HTTPException) as exc:
            mobile_qc.get_qc_detail(
                alert_id=500, request=_make_request(), token="",
                viewer_userid="", viewer_name="", db=db,
            )
        assert exc.value.status_code == 400

    def test_secret_missing_raises_401(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "")
        db = _make_db_with_alert(_make_alert())
        with pytest.raises(HTTPException) as exc:
            mobile_qc.get_qc_detail(
                alert_id=500, request=_make_request(), token="x",
                viewer_userid="", viewer_name="", db=db,
            )
        assert exc.value.status_code == 401
        assert "not configured" in exc.value.detail

    def test_token_mismatch_raises_401(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 499)
        db = _make_db_with_alert(_make_alert())
        with pytest.raises(HTTPException) as exc:
            mobile_qc.get_qc_detail(
                alert_id=500, request=_make_request(), token="x",
                viewer_userid="", viewer_name="", db=db,
            )
        assert exc.value.status_code == 401
        assert "mismatch" in exc.value.detail

    def test_alert_not_found_raises_404(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        db = _make_db_with_alert(None)  # alert 不存在
        with pytest.raises(HTTPException) as exc:
            mobile_qc.get_qc_detail(
                alert_id=500, request=_make_request(), token="x",
                viewer_userid="", viewer_name="", db=db,
            )
        assert exc.value.status_code == 404

    def test_first_view_sets_flag_and_increments_count(self, monkeypatch):
        """§4.3 验收：首次查看置 viewed_flag=1、写 viewed_at、view_count+1。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert(viewed_flag=0, view_count=0)
        db = _make_db_with_alert(alert)

        mobile_qc.get_qc_detail(
            alert_id=500, request=_make_request(), token="x",
            viewer_userid="W001", viewer_name="王护士", db=db,
        )

        assert alert.viewed_flag == 1
        assert alert.viewed_at is not None
        assert alert.view_count == 1
        assert alert.viewer_userid == "W001"
        assert alert.viewer_name == "王护士"
        db.commit.assert_called_once()

    def test_second_view_keeps_first_viewed_at(self, monkeypatch):
        """§4.3：二次访问 viewed_at 不变，last_viewed_at 更新，view_count 再+1。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        first_at = datetime(2026, 7, 9, 10, 0, 0)
        alert = _make_alert(viewed_flag=1, viewed_at=first_at, view_count=1, last_viewed_at=first_at)
        db = _make_db_with_alert(alert)

        mobile_qc.get_qc_detail(
            alert_id=500, request=_make_request(), token="x",
            viewer_userid="", viewer_name="", db=db,
        )

        assert alert.viewed_at == first_at  # 首次时间不变
        assert alert.view_count == 2
        assert alert.last_viewed_at > first_at

    def test_viewer_param_priority_over_header(self, monkeypatch):
        """§4.3：viewer_userid 参数优先于 X-WeCom-UserId header。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        req = _make_request(headers={
            "X-WeCom-UserId": "HEADER_ID",
            "X-WeCom-UserName": "HEADER_NAME",
            "user-agent": "UA",
        })

        mobile_qc.get_qc_detail(
            alert_id=500, request=req, token="x",
            viewer_userid="PARAM_ID", viewer_name="PARAM_NAME", db=db,
        )

        assert alert.viewer_userid == "PARAM_ID"
        assert alert.viewer_name == "PARAM_NAME"

    def test_header_fallback_when_param_empty(self, monkeypatch):
        """参数为空时回退到 header。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        req = _make_request(headers={
            "X-WeCom-UserId": "HEADER_ID",
            "X-WeCom-UserName": "HEADER_NAME",
        })

        mobile_qc.get_qc_detail(
            alert_id=500, request=req, token="x",
            viewer_userid="", viewer_name="", db=db,
        )

        assert alert.viewer_userid == "HEADER_ID"
        assert alert.viewer_name == "HEADER_NAME"

    def test_mark_viewed_failure_rolls_back_and_500(self, monkeypatch):
        """§4.3：查看记录写入异常时回滚并返回 500。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        # 让 commit 抛异常触发 except 分支
        db.commit.side_effect = RuntimeError("db down")

        with pytest.raises(HTTPException) as exc:
            mobile_qc.get_qc_detail(
                alert_id=500, request=_make_request(), token="x",
                viewer_userid="", viewer_name="", db=db,
            )
        assert exc.value.status_code == 500
        assert "查看状态记录失败" in exc.value.detail
        db.rollback.assert_called_once()

    def test_evidence_extracted_from_payload(self, monkeypatch):
        """§4.3：payload_json 的 evidence_summary/evidence_titles 正确提取。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)

        resp = mobile_qc.get_qc_detail(
            alert_id=500, request=_make_request(), token="x",
            viewer_userid="", viewer_name="", db=db,
        )

        assert resp["evidence"]["summary"] == "护理记录与病程不一致"
        assert resp["evidence"]["titles"] == {"A": "首次病程"}

    def test_missing_push_log_does_not_crash(self, monkeypatch):
        """push_log/dimension/conclusion/feedback 缺失时各字段返回空串/None，不抛异常。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)  # push_log/dimension/conclusion/feedback 的 first() 都返回 None

        resp = mobile_qc.get_qc_detail(
            alert_id=500, request=_make_request(), token="x",
            viewer_userid="", viewer_name="", db=db,
        )

        assert resp["alert"]["patient_name"] == ""
        assert resp["feedback"]["action"] is None
        assert resp["dimension_detail"]["issue_summary"] == ""


# ---------- 反馈接口 submit_feedback ----------

class TestSubmitFeedback:
    """POST /api/mobile/qc-feedback —— 三种反馈 + 409 + 提交人来源。"""

    def _make_body(self, **overrides):
        base = dict(
            alert_id=500,
            token="x",
            action="acknowledged",
            reason="",
            rectification_text="",
            viewer_userid="",
            viewer_name="",
        )
        base.update(overrides)
        return mobile_qc.FeedbackRequest(**base)

    def test_invalid_action_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            mobile_qc.submit_feedback(
                self._make_body(action="bogus"), _make_request(), db=object(),
            )
        assert exc.value.status_code == 400
        assert "invalid action" in exc.value.detail

    def test_rectified_without_text_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            mobile_qc.submit_feedback(
                self._make_body(action="rectified", rectification_text="  "), _make_request(), db=object(),
            )
        assert exc.value.status_code == 400
        assert "整改说明" in exc.value.detail

    def test_other_without_reason_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            mobile_qc.submit_feedback(
                self._make_body(action="other", reason=""), _make_request(), db=object(),
            )
        assert exc.value.status_code == 400
        assert "说明" in exc.value.detail

    def test_acknowledged_success(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        req = _make_request(headers={"X-WeCom-UserId": "W001", "X-WeCom-UserName": "王医生"})

        resp = mobile_qc.submit_feedback(
            self._make_body(action="acknowledged", viewer_name="王医生"),
            req, db=db,
        )

        assert resp == {"ok": True, "message": "反馈已提交"}
        db.add.assert_called_once()
        fb = db.add.call_args[0][0]
        assert fb.action == "acknowledged"
        assert fb.status == "submitted"
        assert fb.doctor_id == "W001"
        assert fb.doctor_name == "王医生"
        assert fb.rectification_text == ""  # acknowledged 不写整改
        assert fb.reason == ""

    def test_rectified_with_text_written(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)

        mobile_qc.submit_feedback(
            self._make_body(action="rectified", rectification_text="已补充护理记录"),
            _make_request(), db=db,
        )

        fb = db.add.call_args[0][0]
        assert fb.action == "rectified"
        assert fb.rectification_text == "已补充护理记录"
        assert fb.reason == ""

    def test_other_with_reason_written(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)

        mobile_qc.submit_feedback(
            self._make_body(action="other", reason="患者已出院无法补录"),
            _make_request(), db=db,
        )

        fb = db.add.call_args[0][0]
        assert fb.action == "other"
        assert fb.reason == "患者已出院无法补录"
        assert fb.rectification_text == ""

    def test_duplicate_feedback_raises_409(self, monkeypatch):
        """§4.3：重复提交返回 409，且 db.add 不被调用。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        existing_fb = SimpleNamespace(alert_log_id=500, action="acknowledged")
        alert = _make_alert()
        db = _make_db_with_alert(alert, feedback_existing=existing_fb)

        with pytest.raises(HTTPException) as exc:
            mobile_qc.submit_feedback(
                self._make_body(action="acknowledged"), _make_request(), db=db,
            )
        assert exc.value.status_code == 409
        assert "不可重复提交" in exc.value.detail
        db.add.assert_not_called()

    def test_doctor_name_fallback_to_payload(self, monkeypatch):
        """body 无 viewer_name 且无 header → 走 payload_json 兜底。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()  # payload_json 含 doctor_name=李医生
        db = _make_db_with_alert(alert)

        mobile_qc.submit_feedback(
            self._make_body(action="acknowledged"),  # viewer_name 空
            _make_request(),  # 无 header
            db=db,
        )

        fb = db.add.call_args[0][0]
        assert fb.doctor_name == "李医生"
        assert fb.doctor_id == "D001"

    def test_no_name_anywhere_defaults_unknown(self, monkeypatch):
        """body/header/payload 都无 doctor_name → '未知人员'。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert(payload_json="{}")  # 无 doctor_name
        db = _make_db_with_alert(alert)

        mobile_qc.submit_feedback(
            self._make_body(action="acknowledged"), _make_request(), db=db,
        )

        assert db.add.call_args[0][0].doctor_name == "未知人员"

    def test_dept_from_wecom_header(self, monkeypatch):
        """X-WeCom-DeptName header 透传到 feedback.dept。"""
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        req = _make_request(headers={"X-WeCom-DeptName": "消化内科"})

        mobile_qc.submit_feedback(
            self._make_body(action="acknowledged"), req, db=db,
        )

        assert db.add.call_args[0][0].dept == "消化内科"

    def test_client_ip_and_ua_recorded(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        alert = _make_alert()
        db = _make_db_with_alert(alert)
        req = _make_request(host="192.168.1.1", ua="LongAgent/1.0")

        mobile_qc.submit_feedback(
            self._make_body(action="acknowledged"), req, db=db,
        )

        fb = db.add.call_args[0][0]
        assert fb.client_ip == "192.168.1.1"
        assert fb.user_agent == "LongAgent/1.0"


# ---------- verify-token ----------

class TestVerifyToken:
    """GET /api/mobile/qc-detail/{alert_id}/verify-token。"""

    def test_valid_token(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 500)
        resp = mobile_qc.verify_token(alert_id=500, token="x")
        assert resp == {"valid": True, "alert_id": 500}

    def test_invalid_token(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: None)
        resp = mobile_qc.verify_token(alert_id=500, token="bad")
        assert resp == {"valid": False}

    def test_mismatch_token(self, monkeypatch):
        monkeypatch.setattr(mobile_qc, "_get_token_secret", lambda: "s")
        monkeypatch.setattr(mobile_qc, "verify_alert_token", lambda _t, _s: 499)
        resp = mobile_qc.verify_token(alert_id=500, token="x")
        assert resp == {"valid": False}

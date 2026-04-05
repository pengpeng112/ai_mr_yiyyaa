from app import notifier


class DummyChannel:
    def __init__(self):
        self.calls = []

    def send(self, patient_id, result, config, build_content):
        self.calls.append((patient_id, result, config, build_content(patient_id, result)))


def test_send_notification_dispatches_registry(monkeypatch):
    dummy = DummyChannel()
    monkeypatch.setattr(notifier, "CHANNEL_REGISTRY", {"dummy": dummy})
    logs = []
    monkeypatch.setattr(notifier, "_log_notify", lambda *args: logs.append(args))

    notifier.send_notification(
        "P001",
        {"severity": "low", "result": {"text": "ok"}},
        {"channels": [{"enabled": True, "type": "dummy", "config": {"k": 1}}]},
    )

    assert len(dummy.calls) == 1
    assert any(item[2] == "sent" for item in logs)


def test_send_notification_unknown_channel(monkeypatch):
    monkeypatch.setattr(notifier, "CHANNEL_REGISTRY", {})
    logs = []
    monkeypatch.setattr(notifier, "_log_notify", lambda *args: logs.append(args))

    notifier.send_notification("P001", {"severity": "low", "result": {}}, {"channels": [{"enabled": True, "type": "x", "config": {}}]})
    assert any(item[2] == "failed" for item in logs)


def test_test_notify_channel_success(monkeypatch):
    dummy = DummyChannel()
    monkeypatch.setattr(notifier, "CHANNEL_REGISTRY", {"dummy": dummy})
    result = notifier.test_notify_channel({"type": "dummy", "config": {}})
    assert result["success"] is True


def test_build_notify_content_contains_alert_level():
    text = notifier._build_notify_content(
        "P001",
        {
            "severity": "high",
            "result": {"text": "abc"},
            "parsed_output": {"alert_level": "red"},
        },
    )
    assert "预警级别" in text

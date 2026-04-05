"""
预警通知模块 —— 企微/钉钉/邮件/HTTP回调
"""
import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import NotifyLog
from app.notify_channels import CHANNEL_REGISTRY

logger = logging.getLogger(__name__)


def send_notification(patient_id: str, result: dict, notify_config: dict):
    """根据配置向多个渠道发送通知"""
    channels = notify_config.get("channels", [])
    for channel in channels:
        if not channel.get("enabled", False):
            continue
        ch_type = channel.get("type", "")
        ch_config = channel.get("config", {})
        sender = CHANNEL_REGISTRY.get(ch_type)
        if sender is None:
            logger.warning("未知通知渠道类型: %s", ch_type)
            _log_notify(ch_type, patient_id, "failed", f"未知渠道类型: {ch_type}")
            continue
        try:
            sender.send(patient_id, result, ch_config, _build_notify_content)
            _log_notify(ch_type, patient_id, "sent", "")
        except Exception as e:
            logger.error(f"通知发送失败 [{ch_type}]: {e}", exc_info=True)
            _log_notify(ch_type, patient_id, "failed", str(e))


def _build_notify_content(patient_id: str, result: dict) -> str:
    alert_level = result.get("parsed_output", {}).get("alert_level", "")
    alert_emoji = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "gray": "⚪"}.get(alert_level, "")
    if not alert_emoji:
        severity = result.get("severity", "unknown")
        alert_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
    else:
        severity = result.get("severity", "unknown")
    outputs = result.get("result", {})
    detail = ""
    for key in ("result", "output", "text", "analysis"):
        if key in outputs:
            detail = str(outputs[key])[:500]
            break

    alert_info = ""
    if alert_level:
        alert_label = {"red": "红灯-高风险", "yellow": "黄灯-中风险", "blue": "蓝灯-低风险", "gray": "灰灯-待复核"}.get(alert_level, alert_level)
        alert_info = f"预警级别: {alert_label}\n"

    return (
        f"{alert_emoji} 【医疗记录不一致预警】\n"
        f"患者ID: {patient_id}\n"
        f"{alert_info}"
        f"严重程度: {severity}\n"
        f"发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"分析摘要:\n{detail}\n"
    )


def _log_notify(channel_type: str, patient_id: str, status: str, error_msg: str):
    """记录通知日志"""
    db = None
    try:
        db = SessionLocal()
        log = NotifyLog(
            notify_time=datetime.now(),
            channel_type=channel_type,
            patient_id=patient_id,
            status=status,
            error_msg=error_msg,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"通知日志写入失败: {e}", exc_info=True)
        if db:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db:
            db.close()


def test_notify_channel(channel: dict) -> dict:
    """测试通知渠道"""
    ch_type = channel.get("type", "")
    ch_config = channel.get("config", {})
    sender = CHANNEL_REGISTRY.get(ch_type)
    if sender is None:
        return {"success": False, "message": f"未知渠道类型: {ch_type}"}
    test_result = {
        "severity": "low",
        "result": {"text": "这是一条测试通知，请忽略。"},
    }
    try:
        sender.send("TEST-001", test_result, ch_config, _build_notify_content)
        return {"success": True, "message": "测试通知发送成功"}
    except Exception as e:
        return {"success": False, "message": str(e)}

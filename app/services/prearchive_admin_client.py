"""预检规则中心 BFF 白名单客户端（039 T6 / §9.2）。

- 显式白名单：只允许调用预检服务固定 API 路径，绝不透传任意 URL/path/header；
- 环境开关：PREARCHIVE_ADMIN_ENABLED=false（默认）时全部写/读接口返回
  feature-disabled，主服务启动不探测远端、不因远端不可用失败；
- actor 签名：X-Actor-* + X-Actor-Signature（HMAC-SHA256(signing_secret)），
  预检服务验签落审计，不信任裸 header；
- 超时上限固定，错误响应脱敏（不含 token/患者标识/规则 evidence）；
- 统一 request_id 贯穿两端审计。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

ENV_ENABLED = "PREARCHIVE_ADMIN_ENABLED"
ENV_BASE_URL = "PREARCHIVE_ADMIN_BASE_URL"
ENV_SECRET = "PREARCHIVE_ADMIN_SECRET"
ENV_ADMIN_TOKEN = "PREARCHIVE_ADMIN_TOKEN"

CONNECT_TIMEOUT_SECONDS = 3
READ_TIMEOUT_SECONDS = 10
TOTAL_TIMEOUT_SECONDS = 15   # 上限：任何单请求不得超过

# BFF 允许代理的预检管理 API 白名单（方法, 路径模板）。
# 041 口径=固定 20 目标；046 T1a 起按 046 §T7.1 迁移为「完整获准 (method,path) 集合
# 精确比较 + 逐条权限映射」——集合只增不隐式放行，未知路径/方法/穿越仍拒绝。
ALLOWED_TARGETS = {
    ("GET", "/api/admin/settings"),
    ("GET", "/api/admin/rules"),
    ("POST", "/api/admin/rules"),
    ("GET", "/api/admin/rules/{rule_key}/versions"),
    ("PUT", "/api/admin/rules/{rule_key}/draft"),
    ("POST", "/api/admin/rules/{rule_key}/validate"),
    ("POST", "/api/admin/rules/{rule_key}/dry-run"),
    ("POST", "/api/admin/rules/{rule_key}/approve"),
    ("POST", "/api/admin/rules/{rule_key}/publish"),
    ("POST", "/api/admin/rules/{rule_key}/rollback"),
    ("POST", "/api/admin/rules/{rule_key}/retire"),
    ("GET", "/api/admin/rules/{rule_key}/diff"),
    ("GET", "/api/admin/destinations"),
    ("POST", "/api/admin/destinations"),
    ("POST", "/api/admin/destinations/{code}/contract-test"),
    ("GET", "/api/admin/outbox"),
    ("POST", "/api/admin/outbox/{outbox_id}/retry"),
    ("GET", "/api/admin/fields"),
    ("GET", "/api/admin/audit"),
    ("GET", "/api/admin/delivery-logs"),
    # ---- 046 T1a 新增：覆盖账本 / AI 匹配 / trial ----
    ("GET", "/api/admin/coverage"),
    ("POST", "/api/admin/coverage/import-snapshot"),
    ("POST", "/api/admin/coverage/{fid}/confirm"),
    ("GET", "/api/admin/coverage/export"),
    ("POST", "/api/admin/coverage/generate-file"),
    ("POST", "/api/admin/match/tasks"),
    ("POST", "/api/admin/match/tasks/{task_id}/run"),
    ("GET", "/api/admin/match/tasks/{task_id}"),
    ("POST", "/api/admin/match/tasks/{task_id}/cancel"),
    ("POST", "/api/admin/match/candidates/{candidate_id}/decision"),
    ("POST", "/api/admin/trial/runs"),
    ("GET", "/api/admin/trial/runs"),
    # ---- 046 T5 新增：核查工作台（checks / issues） ----
    ("GET", "/api/admin/checks"),
    ("GET", "/api/admin/checks/{run_id}"),
    ("GET", "/api/admin/issues"),
    ("GET", "/api/admin/issues/{issue_id}"),
    ("POST", "/api/admin/issues/{issue_id}/actions"),
    ("POST", "/api/admin/trial/runs/{trial_run_id}/execute"),
    ("GET", "/api/admin/trial/runs/{trial_run_id}/observations"),
    ("POST", "/api/admin/trial/runs/{trial_run_id}/feedback"),
    # ---- 046 T7 新增：JHEMR 集成内部目标（外部=主服务 /api/integrations/jhemr/*，
    #      JHEMR 签名认证；此处为集成服务账号最小权限，非普通医生 JWT） ----
    ("POST", "/api/integration/jhemr/submission-checks"),
    ("GET", "/api/integration/jhemr/submission-checks/{check_id}"),
    ("POST", "/api/integration/jhemr/view-tickets"),
    ("POST", "/api/integration/jhemr/view-tickets/{nonce}/redeem"),
    ("POST", "/api/integration/jhemr/issues/{issue_id}/feedback"),
    ("POST", "/api/integration/jhemr/rechecks"),
}

# 逐目标权限映射（046 T7.1：获准集合的精确权限矩阵，测试逐条断言；
# 与预检服务 closed_loop_api/admin_api 内部检查双保险一致）
TARGET_PERMISSIONS = {
    ("GET", "/api/admin/settings"): "prearchive_rule_view",
    ("GET", "/api/admin/rules"): "prearchive_rule_view",
    ("POST", "/api/admin/rules"): "prearchive_rule_edit",
    ("GET", "/api/admin/rules/{rule_key}/versions"): "prearchive_rule_view",
    ("PUT", "/api/admin/rules/{rule_key}/draft"): "prearchive_rule_edit",
    ("POST", "/api/admin/rules/{rule_key}/validate"): "prearchive_rule_edit",
    ("POST", "/api/admin/rules/{rule_key}/dry-run"): "prearchive_rule_view",
    ("POST", "/api/admin/rules/{rule_key}/approve"): "prearchive_rule_approve",
    ("POST", "/api/admin/rules/{rule_key}/publish"): "prearchive_rule_publish",
    ("POST", "/api/admin/rules/{rule_key}/rollback"): "prearchive_rule_publish",
    ("POST", "/api/admin/rules/{rule_key}/retire"): "prearchive_rule_publish",
    ("GET", "/api/admin/rules/{rule_key}/diff"): "prearchive_rule_view",
    ("GET", "/api/admin/destinations"): "prearchive_integration_manage",
    ("POST", "/api/admin/destinations"): "prearchive_integration_manage",
    ("POST", "/api/admin/destinations/{code}/contract-test"):
        "prearchive_integration_manage",
    ("GET", "/api/admin/outbox"): "prearchive_rule_view",
    ("POST", "/api/admin/outbox/{outbox_id}/retry"): "prearchive_delivery_retry",
    ("GET", "/api/admin/fields"): "prearchive_rule_view",
    ("GET", "/api/admin/audit"): "prearchive_rule_view",
    ("GET", "/api/admin/delivery-logs"): "prearchive_rule_view",
    ("GET", "/api/admin/coverage"): "prearchive_rule_view",
    ("POST", "/api/admin/coverage/import-snapshot"): "prearchive_rule_edit",
    ("POST", "/api/admin/coverage/{fid}/confirm"): "prearchive_rule_edit",
    ("GET", "/api/admin/coverage/export"): "prearchive_rule_view",
    ("POST", "/api/admin/coverage/generate-file"): "prearchive_rule_edit",
    ("POST", "/api/admin/match/tasks"): "prearchive_match_run",
    ("POST", "/api/admin/match/tasks/{task_id}/run"): "prearchive_match_run",
    ("GET", "/api/admin/match/tasks/{task_id}"): "prearchive_rule_view",
    ("POST", "/api/admin/match/tasks/{task_id}/cancel"): "prearchive_match_run",
    ("POST", "/api/admin/match/candidates/{candidate_id}/decision"):
        "prearchive_match_run",
    ("POST", "/api/admin/trial/runs"): "prearchive_trial_manage",
    ("GET", "/api/admin/trial/runs"): "prearchive_rule_view",
    ("GET", "/api/admin/checks"): "prearchive_check_view",
    ("GET", "/api/admin/checks/{run_id}"): "prearchive_check_view",
    ("GET", "/api/admin/issues"): "prearchive_check_view",
    ("GET", "/api/admin/issues/{issue_id}"): "prearchive_check_view",
    # 任一（feedback/review）即可；终态动作由预检侧再校验 review
    ("POST", "/api/admin/issues/{issue_id}/actions"): "prearchive_issue_feedback",
    ("POST", "/api/admin/trial/runs/{trial_run_id}/execute"):
        "prearchive_trial_manage",
    ("GET", "/api/admin/trial/runs/{trial_run_id}/observations"):
        "prearchive_rule_view",
    ("POST", "/api/admin/trial/runs/{trial_run_id}/feedback"):
        "prearchive_match_run",
    # 046 T7：集成目标权限（集成服务账号最小集；check_view/issue_feedback）
    ("POST", "/api/integration/jhemr/submission-checks"): "prearchive_check_view",
    ("GET", "/api/integration/jhemr/submission-checks/{check_id}"):
        "prearchive_check_view",
    ("POST", "/api/integration/jhemr/view-tickets"): "prearchive_check_view",
    ("POST", "/api/integration/jhemr/view-tickets/{nonce}/redeem"):
        "prearchive_check_view",
    ("POST", "/api/integration/jhemr/issues/{issue_id}/feedback"):
        "prearchive_issue_feedback",
    ("POST", "/api/integration/jhemr/rechecks"): "prearchive_check_view",
}

# 新增内部权限清单（046 §3.2：显式迁移脚本落库，禁止启动钩子 seed）
NEW_PREARCHIVE_PERMISSIONS = (
    "prearchive_match_run",
    "prearchive_trial_manage",
    "prearchive_check_view",
    "prearchive_issue_review",
    "prearchive_issue_feedback",
)


class PrearchiveAdminDisabled(Exception):
    """BFF 开关关闭（默认）——不是远端故障。"""


class PrearchiveAdminUnavailable(Exception):
    """远端不可达/超时/坏响应——fail-open：主服务不受影响。"""


def _match_target(method: str, path_template: str) -> bool:
    return (method.upper(), path_template) in ALLOWED_TARGETS


def permission_for_target(method: str, path_template: str) -> str | None:
    """白名单目标的必需权限（未知目标返回 None——调用方必须拒绝）。"""
    return TARGET_PERMISSIONS.get((method.upper(), path_template))


def render_path(path_template: str, params: dict) -> str:
    """白名单模板 → 实际路径（参数仅做安全编码，不引入新路径段）。"""
    rendered = path_template
    for key, value in (params or {}).items():
        rendered = rendered.replace("{" + key + "}", quote(str(value), safe=""))
    return rendered


class PrearchiveAdminClient:
    def __init__(self, base_url: str = "", admin_token: str = "",
                 signing_secret: str = "", enabled: bool | None = None):
        env = os.environ
        self.enabled = (enabled if enabled is not None
                        else str(env.get(ENV_ENABLED, "false")).strip().lower()
                        in ("1", "true", "yes", "on"))
        self.base_url = (base_url or env.get(ENV_BASE_URL, "")).rstrip("/")
        self.admin_token = admin_token or env.get(ENV_ADMIN_TOKEN, "")
        self.signing_secret = signing_secret or env.get(ENV_SECRET, "")

    def _headers(self, actor, request_id: str, path_params_rendered: str) -> dict:
        actor_id = str(getattr(actor, "id", "") or "")
        actor_name = quote(str(getattr(actor, "username", "") or ""), safe="")
        permissions = ",".join(sorted(set(getattr(actor, "permissions", []) or [])))
        signature = hmac.new(
            self.signing_secret.encode("utf-8"),
            f"{actor_id}|{actor_name}|{permissions}|{request_id}".encode("utf-8"),
            hashlib.sha256).hexdigest()
        return {
            "X-Admin-Token": self.admin_token,
            "X-Actor-Id": actor_id,
            "X-Actor-Name": actor_name,
            "X-Actor-Permissions": permissions,
            "X-Request-Id": request_id,
            "X-Actor-Signature": signature,
        }

    def call(self, method: str, path_template: str, actor, *,
             params: dict | None = None, query: dict | None = None,
             json_body: dict | None = None) -> dict:
        """白名单代理调用。返回 {status, json}；禁用/不可用抛专用异常。"""
        if not self.enabled:
            raise PrearchiveAdminDisabled("prearchive admin BFF is disabled")
        if not _match_target(method, path_template):
            raise ValueError(f"target not in allowlist: {method} {path_template}")
        if not self.base_url or not self.admin_token or not self.signing_secret:
            raise PrearchiveAdminUnavailable("prearchive admin BFF not configured")

        request_id = f"bff-{uuid.uuid4().hex[:16]}"
        path = render_path(path_template, params or {})
        url = f"{self.base_url}{path}"
        headers = self._headers(actor, request_id, path)
        try:
            response = requests.request(
                method.upper(), url, headers=headers,
                params={k: v for k, v in (query or {}).items() if v is not None},
                json=json_body,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.Timeout:
            raise PrearchiveAdminUnavailable("prearchive admin request timeout")
        except requests.RequestException as exc:
            # 脱敏：不回传底层异常细节（可能含内网拓扑）
            logger.warning("prearchive admin call failed (%s %s): %s",
                           method, path_template, type(exc).__name__)
            raise PrearchiveAdminUnavailable("prearchive admin service unreachable")

        try:
            payload = response.json()
        except ValueError:
            payload = {"message": "invalid remote response"}
        return {"status": response.status_code, "json": payload,
                "request_id": request_id}

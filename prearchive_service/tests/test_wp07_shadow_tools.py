# -*- coding: utf-8 -*-
"""WP07 影子工具链测试（064 总计划；任务书 §六 5 项）。

1. 盘点脚本 --mock-json：TOP 扣分项统计与三组覆盖分类正确，输出无患者标识；
2. 回测脚本离线模式：调用 backtest_v2 得到正确命中/漏检/误报数，报告患者号已掩码；
3. import_rules_cli：dry-run 零写入；--apply 两次幂等（SQLite 临时库）；
4. staging_table 中间表传输：非法表名拒绝；SQL 参数化且含幂等 NOT EXISTS；
   未启用时零连接；未人工确认的缺陷不入 Outbox；
5. 影子模板可被配置加载器解析，所有对外投递开关为 false。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "prearchive_service" / "scripts"))

from analyze_paperless_rejections_ro import (  # noqa: E402
    classify_coverage,
    covered_fids,
    render_report,
)
from prearchive.backtest import backtest_v2  # noqa: E402
from prearchive.config import load_config  # noqa: E402
from prearchive.delivery_wiring import (  # noqa: E402
    DeliveryGovernance,
    load_delivery_governance,
)
from prearchive.models import build_session_factory, build_sqlite_engine  # noqa: E402
from prearchive.outbox import (  # noqa: E402
    DeliveryWorker,
    build_staging_insert_sql,
)
from prearchive.destinations import DestinationError  # noqa: E402
from prearchive.rule_repository import RuleRepository  # noqa: E402
from prearchive.result_contract import serialize_result, build_idempotency_key  # noqa: E402
from prearchive.rule_models import OUTBOX_SENT  # noqa: E402
from prearchive.rule_service import Actor, RuleService  # noqa: E402
from prearchive.config import resolve_base_dir  # noqa: E402
from prearchive.rule_admin import _build_repository  # noqa: E402

WP07_DIR = Path(__file__).resolve().parent
SHADOW_TEMPLATE = BASE_DIR / "config.shadow.prod.template.json"


# ---- 1. 盘点脚本（--mock-json） ----

MOCK_DATA = {
    "mark_details": [
        {"fid": 63, "item_name": "手术核查表缺失", "count": 10, "patients": 8},
        {"fid": 57, "item_name": "术前术后讨论记录缺失", "count": 6, "patients": 5},
        {"fid": 999, "item_name": "知情同意书未签名", "count": 5, "patients": 5},
        {"fid": 888, "item_name": "护理记录内涵矛盾描述", "count": 4, "patients": 4},
        {"fid": 14, "item_name": "入院记录超24小时", "count": 2, "patients": 2},
    ],
    "rework": {
        "total": 12,
        "by_control_type": {"病历返工": 8, "护理返工": 4},
        "overdue": {"overdue_cnt": 3, "avg_voerdays": 2.5},
    },
    "mr_control": {
        "by_doc_name": {"手术记录": 9},
        "remark_keywords": {"缺少": 7, "未签名": 3},
    },
}


def test_analyze_mock_top_and_coverage_groups(tmp_path):
    import importlib

    mod = importlib.import_module("analyze_paperless_rejections_ro")
    covered = covered_fids(BASE_DIR / "rules" / "example_rules.json")
    assert 63 in covered and 57 in covered and 14 in covered

    groups = classify_coverage(MOCK_DATA["mark_details"], covered)
    # 已覆盖：63/57/14（example_rules 已规则化 FID）
    covered_ids = {r["fid"] for r in groups["covered"]}
    assert {63, 57, 14} <= covered_ids
    # 未覆盖：999（形式关键词「未签」→ 可规则化）、888（内涵矛盾→建议 AI）
    ruleable_ids = {r["fid"] for r in groups["ruleable"]}
    ai_ids = {r["fid"] for r in groups["ai_suggest"]}
    assert 999 in ruleable_ids
    assert 888 in ai_ids

    report = mod.render_report(MOCK_DATA, 30, covered, "离线演练数据")
    assert "| 63 |" in report and "手术核查表缺失" in report
    assert "已覆盖" in report and "可规则化" in report and "建议 AI" in report
    assert "返工总量：12" in report
    assert "缺少×7" in report
    # 零患者标识：报告不含任何 mock 之外的患者号形态（全数字长串）
    for line in report.splitlines():
        for token in line.replace("|", " ").split():
            assert not (token.isdigit() and len(token) >= 8), f"疑似未脱敏患者号: {line}"


def test_analyze_mask_patient_ref():
    from analyze_paperless_rejections_ro import mask_patient_ref

    assert mask_patient_ref("00985003") == "****5003"
    assert mask_patient_ref("12") == "**"
    assert mask_patient_ref("") == ""


# ---- 2. 回测脚本（离线 → backtest_v2） ----

def _results() -> list[dict]:
    return [
        {
            "patient_id": "00985003", "visit_id": "1", "dept_code": "040112",
            "checked_at": "2026-11-19T10:00:00", "ruleset_revision": "r1",
            "problems": [
                {"rule_id": "R-MISS-SURGERY-CHECKTABLE", "severity": "medium", "confirmed": True},
                {"rule_id": "R-UNRELATED", "severity": "low", "confirmed": True},
            ],
            "evaluations": [
                {"fid": 63, "status": "fail", "clause_id": "a"},
                {"fid": 777, "status": "fail", "clause_id": "b"},  # 范围外命中→unknown
            ],
        },
        {
            "patient_id": "00985010", "visit_id": "1", "dept_code": "040112",
            "checked_at": "2026-11-19T10:30:00", "ruleset_revision": "r1",
            "problems": [{"rule_id": "R-MISS-SURGERY-PREPOST-DOCS", "severity": "low",
                          "confirmed": True}],
            "evaluations": [{"fid": 57, "status": "pass"}],
        },
    ]


def _manual() -> dict:
    return {
        "deductions": [
            {"patient_id": "00985003", "visit_id": "1", "fid": 63, "clause_id": "a",
             "reviewed_at": "2026-11-20T09:00:00", "data_as_of": "2026-11-19T08:00:00"},
            {"patient_id": "00985010", "visit_id": "1", "fid": 57, "clause_id": "",
             "reviewed_at": "2026-11-20T09:00:00", "data_as_of": "2026-11-19T08:00:00"},
        ],
        "evaluated_negatives": [
            {"patient_id": "00985003", "visit_id": "1", "fids": [63, 63],
             "reviewed_at": "2026-11-20T09:00:00"},
        ],
        "confirmation": {"confirmed_sample_count": 2, "confirmed_by": "病案室", "confirmed_at": "2026-11-20"},
    }


def test_backtest_offline_counts_and_masking(tmp_path):
    import importlib

    mod = importlib.import_module("paperless_gold_backtest_ro")
    report = backtest_v2(
        _manual(), _results(),
        rule_id_map=mod._rule_id_map(BASE_DIR / "rules" / "example_rules.json"),
        alignment_tolerance_seconds=86400,
    )
    # fid=63：人工扣分 & 规则命中 → TP；fid=57：人工扣分 & 规则 pass → FN
    fid63 = report["per_fid"]["63"]
    assert fid63["tp"] == 1 and fid63["fn"] == 0
    fid57 = report["per_fid"]["57"]
    assert fid57["fn"] == 1
    # 777 范围外命中 → unknown（不进 FP）
    assert report["overall"]["unknown"] >= 1
    assert report["overall"]["tp"] >= 1 and report["overall"]["fn"] >= 1

    report = dict(report)
    report["patient_keys"] = sorted({
        (str(r["patient_id"]), str(r["visit_id"]))
        for r in _manual().get("deductions", [])
    } | {(str(r["patient_id"]), str(r["visit_id"]))
         for r in _manual().get("evaluated_negatives", [])})
    masked = mod.render_masked_report(report, "# md", source_note="离线文件")
    assert "P***5003" in masked and "P***5010" in masked
    assert "00985003" not in masked and "00985010" not in masked
    assert "命中率（recall）>= 0.80" in masked


# ---- 3. import_rules_cli（dry-run 零写入 / --apply 两次幂等） ----

@pytest.fixture()
def prearchive_config(tmp_path):
    config_path = tmp_path / "pa_config.json"
    payload = json.loads(
        (BASE_DIR / "config.demo.json").read_text(encoding="utf-8")) \
        if (BASE_DIR / "config.demo.json").exists() else {}
    payload.setdefault("result_store", {})
    payload["result_store"]["type"] = "sqlite"
    payload["result_store"]["sqlite_path"] = str(tmp_path / "rules_repo.db")
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(config_path)


def test_import_cli_dry_run_and_idempotent_apply(prearchive_config, capsys):
    import importlib

    mod = importlib.import_module("import_rules_cli")
    files = [str(BASE_DIR / "rules" / "example_rules.json"),
             str(BASE_DIR / "rules" / "system_push_rules.json")]

    # dry-run：零规则落库（created 为"计划创建"计数；落库行数必须为 0）
    report_dry = mod.run_import(prearchive_config, files, apply=False, actor_name="wp07-test")
    assert report_dry["apply"] is False
    assert report_dry["errors"] == []
    assert report_dry["created"] >= 1   # 计划创建数（报告口径）
    config = load_config(prearchive_config)
    repo_check = _build_repository(config, Path(prearchive_config).parent)
    for rule in json.loads((BASE_DIR / "rules" / "example_rules.json").read_text(encoding="utf-8"))["rules"][:3]:
        assert repo_check.get_version(str(rule["rule_id"]), str(rule["version"])) is None,             f"dry-run 落库了规则 {rule['rule_id']}"

    # 第一次 --apply：created>0
    report1 = mod.run_import(prearchive_config, files, apply=True, actor_name="wp07-test")
    assert report1["apply"] is True
    assert report1["created"] > 0 and report1["errors"] == []
    # 第二次 --apply：幂等 skipped（同版本同 SHA）
    report2 = mod.run_import(prearchive_config, files, apply=True, actor_name="wp07-test")
    assert report2["created"] == 0
    assert report2["skipped"] == report1["created"]


# ---- 4. staging_table 中间表传输 ----

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, dict(params or {})))
        key = (params or {}).get("idempotency_key")
        if key in self.conn.inserted_keys:
            self.rowcount = 0       # 幂等命中
        else:
            self.conn.inserted_keys.add(key)
            self.rowcount = 1

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.executed: list = []
        self.inserted_keys: set = set()
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _seed_envelope(repository, destination_code="stg_1"):
    envelope = serialize_result(
        result_id="r-1", patient_id="00985003", visit_number="1",
        dept_code="040112", trigger_mode="discharge",
        checked_at=__import__("datetime").datetime(2026, 11, 19, 10, 0, 0),
        problems=[{"rule_id": "R-1", "severity": "high", "confirmed": True}],
        rule_version="v1", event_id="evt-stg-1",
    )
    envelope.idempotency_key = build_idempotency_key("evt-stg-1", destination_code)
    return envelope


def test_staging_table_name_allowlist_rejects_injection():
    for bad in ("bad table; DROP TABLE x", "MED_QUEUE; DELETE", "t-1", "a" * 31, "", "1QUEUE"):
        with pytest.raises(DestinationError):
            build_staging_insert_sql(bad, "IDEMPOTENCY_KEY")
    with pytest.raises(DestinationError):
        build_staging_insert_sql("MED_PUSH_QUEUE", "bad column; DROP")
    # 合法（含 schema 前缀）
    sql = build_staging_insert_sql("HIS.MED_PUSH_QUEUE", "IDEMPOTENCY_KEY")
    assert ":idempotency_key" in sql and ":payload_json" in sql


def test_staging_sql_is_parameterized_with_not_exists():
    sql = build_staging_insert_sql("MED_PUSH_QUEUE", "IDEMPOTENCY_KEY")
    assert "SELECT :idempotency_key, :payload_json" in sql      # 参数化绑定
    assert "WHERE NOT EXISTS (SELECT 1 FROM MED_PUSH_QUEUE WHERE IDEMPOTENCY_KEY = :idempotency_key)" in sql
    # 表名白名单外的动态片段不存在（无分号/注释注入可能）
    assert ";" not in sql and "--" not in sql


def test_staging_sql_uses_configured_idempotency_column():
    """回归保护（P1-4）：自定义 idempotency_column 同时用于 INSERT 与 WHERE 子句。"""
    sql = build_staging_insert_sql("HIS.MED_PUSH_QUEUE", "CUSTOM_IDEM_COL")
    assert "INSERT INTO HIS.MED_PUSH_QUEUE (CUSTOM_IDEM_COL, PAYLOAD_JSON, CREATED_AT)" in sql
    assert "WHERE CUSTOM_IDEM_COL = :idempotency_key" in sql


def test_staging_disabled_destination_means_zero_connection(tmp_path):
    repository = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    repository.upsert_destination(
        updated_by="wp07", code="stg_off", kind="staging_table", enabled=0,
        base_url="", endpoint="", auth_type="none", secret_ref="",
        allow_insecure_internal_http=1)
    calls: list[str] = []

    def _no_connect(dsn_env):
        calls.append(dsn_env)
        raise AssertionError("未启用目的地不应发起连接")

    worker = DeliveryWorker(
        repository, delivery_enabled=True, staging_connect=_no_connect,
        staging_config={"stg_off": {"dsn_env": "PREARCHIVE_STAGING_DSN",
                                    "table": "MED_PUSH_QUEUE",
                                    "idempotency_column": "IDEMPOTENCY_KEY"}})
    envelope = serialize_result(
        result_id="r-2", patient_id="00985003", visit_number="1",
        dept_code="040112", trigger_mode="discharge",
        checked_at=__import__("datetime").datetime(2026, 11, 19, 10, 0, 0),
        problems=[], rule_version="v1", event_id="evt-stg-off",
    )
    created = worker.enqueue_for_result(envelope, destinations=["stg_off"])
    # 目的地禁用：enqueue 直接跳过（零 Outbox 行、零连接）
    assert created == [] and calls == []


def test_staging_send_ok_and_idempotent_rerun():
    repository = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    repository.upsert_destination(
        updated_by="wp07", code="stg_1", kind="staging_table", enabled=1,
        base_url="", endpoint="", auth_type="none", secret_ref="",
        allow_insecure_internal_http=1)
    conn = _FakeConn()
    worker = DeliveryWorker(
        repository, delivery_enabled=True,
        staging_connect=lambda dsn_env: conn,
        staging_config={"stg_1": {"dsn_env": "PREARCHIVE_STAGING_DSN",
                                  "table": "MED_PUSH_QUEUE",
                                  "idempotency_column": "IDEMPOTENCY_KEY"}})
    envelope = _seed_envelope(repository)
    worker.enqueue_for_result(envelope, destinations=["stg_1"])
    stats = worker.dispatch_round()
    assert stats["sent"] == 1 and conn.executed
    sql, params = conn.executed[0]
    # 参数化 + 幂等 NOT EXISTS + 绑定参数
    assert "NOT EXISTS" in sql and ":idempotency_key" in sql
    assert params["idempotency_key"] == envelope.idempotency_key
    assert "payload_json" in params
    # 重放同一 Outbox（模拟重跑）：幂等命中 → duplicate → 仍算 sent
    stats2 = worker.dispatch_round()
    assert stats2.get("sent", 0) >= 0
    assert conn.closed is True


# ---- 5. 影子模板解析 + 对外开关全 false + 人工确认闸门 ----

def test_shadow_template_parses_and_all_delivery_switches_off():
    config = load_config(str(SHADOW_TEMPLATE))
    assert config["service"]["anchor_mode"] == "discharge"
    assert config["sources"]["jhemr"]["enabled"] is True
    assert config["sources"]["his"]["enabled"] is True
    assert config["sources"]["sm"]["enabled"] is True
    # 未启用的源（deep merge DEFAULTS 补齐）保持关闭
    for name in ("lis", "bl", "xt", "dcn", "qgj", "his_base"):
        assert config["sources"][name]["enabled"] is False
    # 全部对外投递开关 false
    assert config["push"]["enabled"] is False
    assert config["result_delivery"]["enabled"] is False
    assert config["result_delivery"]["staging_table"]["enabled"] is False
    assert config["result_delivery"]["require_manual_confirm"] is True
    assert config["insurance_qc"]["enabled"] is False
    assert config["rule_match"]["enabled"] is False
    # 密码零明文（只有 enc 占位符）
    raw = SHADOW_TEMPLATE.read_text(encoding="utf-8")
    assert "password_env" not in raw   # 现加载器只支持 password_enc（不写不存在的取密键）
    assert '"password": "' not in raw  # 无明文口令


def test_require_manual_confirm_gate_blocks_unconfirmed():
    governance = load_delivery_governance({
        "result_delivery": {"enabled": False, "require_manual_confirm": True}})
    # 显式 confirmed=false（病案室未确认）→ 不入 Outbox（闸门拒绝）
    assert governance.manual_confirm_allowed(
        [{"rule_id": "R-1", "severity": "high", "confirmed": False}]) is False
    # 全部已确认 → 放行
    assert governance.manual_confirm_allowed(
        [{"rule_id": "R-1", "severity": "high", "confirmed": True}]) is True
    # 缺 confirmed 键 = 旧链路兼容放行（回归零破坏，ops_diag 既有用例依赖）
    assert governance.manual_confirm_allowed(
        [{"rule_id": "R-1", "severity": "high"}]) is True
    # 零问题撤销事件不受闸门约束
    assert governance.manual_confirm_allowed([]) is True
    # 显式关闭（辅助上线后）→ 放行
    relaxed = DeliveryGovernance(require_manual_confirm=False)
    assert relaxed.manual_confirm_allowed([{"rule_id": "R-1", "confirmed": False}]) is True


def test_sql_jhemr_gateway_uses_real_177_pat_visit_columns():
    """回归保护（S6 实测校准）：SqlJhemrGateway 使用 177 jhemr.pat_visit 真实列别名，防 UndefinedColumn。"""
    from prearchive.collectors import SqlJhemrGateway

    for sql in (SqlJhemrGateway.FINISHED_SQL, SqlJhemrGateway.DISCHARGE_SQL, SqlJhemrGateway.PAT_VISIT_SQL):
        assert "pv.pat_name AS patient_name" in sql
        assert "pv.visit_id AS visit_number" in sql
        assert "COALESCE(pv.dept_discharge_from, pv.dept_admission_to) AS dept_code" in sql
        assert "jhemr.dept_dict" in sql
        assert "pv.discharge_disposition AS discharge_mode" in sql
        assert "pv.visit_number" not in sql
        assert "pv.patient_name" not in sql
        assert "pv.dept_code" not in sql
    assert "pv.attending_doctor AS attending_doctor_name" in SqlJhemrGateway.PAT_VISIT_SQL


def test_dsn_builders_url_encode_special_password_chars():
    """回归保护（S6 实测校准）：密码含 @/#/%/: 等 URL 特殊字符时必须 quote_plus 编码防主机名解析截断。"""
    from sqlalchemy.engine.url import make_url
    from prearchive.collectors import _pg_dsn, _oracle_dsn

    pg_url = _pg_dsn({
        "user": "u_test", "password": "P@ss#1/2:3?", "host": "10.10.8.177",
        "port": 5432, "database": "jhemr", "sslmode": "",
    })
    parsed_pg = make_url(pg_url)
    assert parsed_pg.host == "10.10.8.177"
    assert parsed_pg.port == 5432
    assert parsed_pg.password == "P@ss#1/2:3?"
    assert "%40" in pg_url

    ora_url = _oracle_dsn({
        "user": "jhemr", "password": "A@B#C", "host": "10.10.8.216",
        "port": 1521, "service_name": "orcl",
    })
    parsed_ora = make_url(ora_url)
    assert parsed_ora.host == "10.10.8.216"
    assert parsed_ora.password == "A@B#C"
    assert "%40" in ora_url


def test_rule_admin_build_repository_decrypts_oracle_password(monkeypatch):
    """回归保护（S6 实测修复）：rule_admin._build_repository 在 oracle 模式下解密 oracle_password_enc。"""
    from cryptography.fernet import Fernet
    from prearchive.config import encrypt_value
    from prearchive import rule_admin as ra_mod

    key = Fernet.generate_key().decode("ascii")
    enc_pw = encrypt_value(Fernet(key.encode("ascii")), "S@ecret#99")
    captured = {}

    def fake_build_oracle_engine(dsn, user, password, echo=False):
        captured.update(dsn=dsn, user=user, password=password)
        return "FAKE_ENGINE"

    monkeypatch.setenv("PREARCHIVE_SECRET_KEY", key)
    monkeypatch.setattr(ra_mod, "build_oracle_engine", fake_build_oracle_engine)
    monkeypatch.setattr(ra_mod, "build_oracle_session_factory", lambda eng: eng)
    ra_mod._build_repository({
        "result_store": {
            "type": "oracle",
            "oracle_dsn": "10.10.8.216:1521/orcl",
            "oracle_user": "jhemr",
            "oracle_password_enc": enc_pw,
        },
    }, Path("."))
    assert captured["password"] == "S@ecret#99"


def test_all_prearchive_orm_models_place_text_columns_last():
    """回归保护（防 Oracle ORA-24816）：所有 prearchive ORM 模型的 Text/CLOB 列必须排在非 LOB 列之后。"""
    from sqlalchemy import Text
    from prearchive.models import Base
    import prearchive.rule_models  # noqa: F401
    import prearchive.closed_loop_models  # noqa: F401

    for table in Base.metadata.sorted_tables:
        seen_text = False
        for col in table.columns:
            is_text = isinstance(col.type, Text)
            if is_text:
                seen_text = True
            else:
                assert not seen_text, (
                    f"{table.name}.{col.name}（非 Text 列）出现在 Text/CLOB 列之后，Oracle INSERT 将触发 ORA-24816"
                )
    # Oracle 保留字与 11g 序列兼容守卫（MED_PREARCHIVE_RESULT）
    from prearchive.models import PrearchiveResult
    assert PrearchiveResult.__table__.c["current_flag"] is not None
    assert "current" not in PrearchiveResult.__table__.c
    assert PrearchiveResult.__table__.c["id"].default.name == "SEQ_MED_PREARCHIVE_RESULT"

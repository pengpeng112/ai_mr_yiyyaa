# -*- coding: utf-8 -*-
"""048 T5 工作台 E2E 造数（demo 隔离）：向 sidecar sqlite 幂等注入正式 run + fail 评估
+ IssueService 物化 open issue（全部走真实代码路径，零真实患者/零生产）。

- Run A：WB-E2E-P001 / 1 / DEMO-D001（听觉植入科）——主链路（列表→详情→人工动作）；
- Run B：WB-E2E-P002 / 1 / DEMO-D002——跨科室隔离断言用（clinician_d001 不可见）。
- 幂等=删除种子行后重建（终态 issue 复位为 open，E2E 可重复执行）。

用法（仓库根）::

    python scripts/seed_workbench_demo_20260915.py           # 造数
    python scripts/seed_workbench_demo_20260915.py --status  # 只读查看种子行状态

安全边界：只写 prearchive_service/data/demo/ 隔离 sqlite（config.demo.json 解析），
只绑本地文件，不触任何真实库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREARCHIVE_DIR = REPO_ROOT / "prearchive_service"
DEMO_CONFIG = PREARCHIVE_DIR / "config.demo.json"

SEED_TAG = "wb-e2e"
RUN_A = {"patient": "WB-E2E-P001", "visit": "1", "dept": "DEMO-D001",
         "dept_name": "听觉植入科"}
RUN_B = {"patient": "WB-E2E-P002", "visit": "1", "dept": "DEMO-D002",
         "dept_name": "帕金森病与头痛头晕专业"}


def _load_prearchive():
    if str(PREARCHIVE_DIR) not in sys.path:
        sys.path.insert(0, str(PREARCHIVE_DIR))
    import prearchive  # noqa: F401


def _resolve_db_path() -> Path:
    from prearchive.config import resolve_base_dir, resolve_path
    config = json.loads(DEMO_CONFIG.read_text(encoding="utf-8"))
    store_cfg = config.get("result_store") or {}
    db_path = resolve_path(resolve_base_dir(str(DEMO_CONFIG)),
                           store_cfg.get("sqlite_path")
                           or "data/demo/prearchive_result.db")
    return db_path


def _seed_specs() -> list[dict]:
    """两个正式 run 的评估载荷：各 1 fail（产生 open issue）+ 1 pass。"""
    def evals(patient_tag: str):
        return [
            {"rule_id": "R-WB-E2E-01", "rule_version": "v1", "fid": 38,
             "status": "fail", "event_instance_id": f"{SEED_TAG}-event-1",
             "reason_code": "required_doc_missing",
             "evidence": {"severity": "medium",
                          "message": "[E2E合成] 入院记录超时限（脱敏合成数据）"}},
            {"rule_id": "R-WB-E2E-02", "rule_version": "v1", "fid": None,
             "status": "pass", "event_instance_id": f"{SEED_TAG}-event-1",
             "reason_code": "within_limit", "evidence": {}},
        ]
    return [
        {**RUN_A, "evals": evals("a")},
        {**RUN_B, "evals": evals("b")},
    ]


def seed() -> dict:
    _load_prearchive()
    from prearchive.closed_loop_models import (
        IssueActionRow, IssueRow, RuleEvalRow, RunRow,
    )
    from prearchive.eval_store import EvalRunStore
    from prearchive.issue_service import IssueService
    from prearchive.models import build_session_factory, build_sqlite_engine
    from sqlalchemy import delete, select

    db_path = _resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    session_factory = build_session_factory(build_sqlite_engine(str(db_path)))

    report = {"db": str(db_path), "runs": [], "issues": []}
    with session_factory() as session:
        # 幂等复位：删旧种子行（run/eval/issue/action）
        seed_patients = [RUN_A["patient"], RUN_B["patient"]]
        old_issues = session.execute(select(IssueRow).where(
            IssueRow.patient_id.in_(seed_patients))).scalars().all()
        for issue in old_issues:
            session.execute(delete(IssueActionRow).where(
                IssueActionRow.issue_id == issue.id))
            session.delete(issue)
        for patient in seed_patients:
            runs = session.execute(select(RunRow).where(
                RunRow.patient_id == patient)).scalars().all()
            for run in runs:
                session.execute(delete(RuleEvalRow).where(
                    RuleEvalRow.run_id == run.id))
                session.delete(run)
        session.commit()

    for spec in _seed_specs():
        store = EvalRunStore(session_factory)
        run = store.start_run(
            patient_id=spec["patient"], visit_number=spec["visit"],
            trigger_type="manual_recheck", ruleset_revision="wb-e2e-seed-v1",
            dept_code=spec["dept"], dept_name=spec["dept_name"])
        store.record_evals(run.id, spec["evals"])
        store.finish_run(run.id, "completed",
                         {"fail_count": 1, "unknown_count": 0, "status": "fail"}, {})
        materialized = IssueService(session_factory).materialize_for_run(run.id)
        report["runs"].append({"run_id": run.id, "patient": spec["patient"],
                               "dept": spec["dept"],
                               "fail_keys": materialized["fail_keys"]})

    with session_factory() as session:
        rows = session.execute(select(IssueRow).where(
            IssueRow.patient_id.in_(
                [RUN_A["patient"], RUN_B["patient"]]))).scalars().all()
        report["issues"] = [{"issue_id": r.id, "patient": r.patient_id,
                             "status": r.status, "version": r.version}
                            for r in rows]
    return report


def status() -> dict:
    _load_prearchive()
    from prearchive.closed_loop_models import IssueRow, RunRow
    from prearchive.models import build_session_factory, build_sqlite_engine
    from sqlalchemy import select

    db_path = _resolve_db_path()
    if not db_path.exists():
        return {"db": str(db_path), "exists": False}
    session_factory = build_session_factory(build_sqlite_engine(str(db_path)))
    with session_factory() as session:
        runs = session.execute(select(RunRow).where(RunRow.patient_id.in_(
            [RUN_A["patient"], RUN_B["patient"]]))).scalars().all()
        issues = session.execute(select(IssueRow).where(IssueRow.patient_id.in_(
            [RUN_A["patient"], RUN_B["patient"]]))).scalars().all()
        return {"db": str(db_path), "exists": True,
                "runs": [{"id": r.id, "patient": r.patient_id, "status": r.status}
                         for r in runs],
                "issues": [{"id": i.id, "patient": i.patient_id,
                            "status": i.status} for i in issues]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="048 工作台 E2E 造数（demo 隔离）")
    parser.add_argument("--status", action="store_true", help="只读查看种子行状态")
    args = parser.parse_args(argv)
    result = status() if args.status else seed()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.status:
        assert len(result["runs"]) == 2 and len(result["issues"]) == 2, \
            f"种子行数量异常: {result}"
        assert all(i["status"] == "open" for i in result["issues"]), \
            f"种子 issue 未复位为 open: {result['issues']}"
    return 0


if __name__ == "__main__":
    sys.exit(main())

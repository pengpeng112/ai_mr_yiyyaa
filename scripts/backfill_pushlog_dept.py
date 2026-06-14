"""回填 PushLog 空科室字段。

用法：python scripts/backfill_pushlog_dept.py [limit]
"""
import json
import os
import sys

sys.path.insert(0, os.environ.get("APP_ROOT", "/app"))

from app.database import SessionLocal
from app.models import PushLog
from app.utils.patient_dept_query import query_patient_dept


def _load_json(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    db = SessionLocal()
    updated = 0
    scanned = 0
    try:
        rows = (
            db.query(PushLog)
            .filter((PushLog.dept.is_(None)) | (PushLog.dept == ""))
            .order_by(PushLog.id.desc())
            .limit(limit)
            .all()
        )
        for log in rows:
            scanned += 1
            info = query_patient_dept(str(log.patient_id or ""), str(log.visit_number or ""))
            dept = info.get("dept_name") or ""
            if not dept:
                continue
            log.dept = dept
            payload = _load_json(log.request_json)
            patient_info = payload.get("patient_info") if isinstance(payload.get("patient_info"), dict) else {}
            patient_info.setdefault("dept", dept)
            patient_info.setdefault("department", dept)
            patient_info.setdefault("dept_code", info.get("dept_code") or "")
            patient_info.setdefault("inpatient_dept_name", info.get("inpatient_dept_name") or "")
            patient_info.setdefault("inpatient_dept_code", info.get("inpatient_dept_code") or "")
            patient_info.setdefault("admission_dept_name", info.get("admission_dept_name") or "")
            patient_info.setdefault("discharge_dept_name", info.get("discharge_dept_name") or "")
            patient_info.setdefault("discharge_dept_code", info.get("discharge_dept_code") or "")
            payload["patient_info"] = patient_info
            log.request_json = json.dumps(payload, ensure_ascii=False)
            updated += 1
            if updated % 100 == 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    print(f"scanned={scanned} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

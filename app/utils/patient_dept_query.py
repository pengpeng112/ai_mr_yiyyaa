"""患者科室信息查询 — 从 JHEMR.V_QYBR 获取科室编码/名称，供 PushLog 写入和 relay_alert 复用。"""
import logging

logger = logging.getLogger(__name__)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_oracle_data_source() -> bool:
    from app.config import load_config
    cfg = load_config()
    return ((cfg.get("data_source") or {}).get("type") or "oracle") == "oracle"


def _get_oracle_connection():
    from app.config import load_config
    from app.services.config_parser import ConfigParser
    from app.oracle_client import get_oracle_connection as _get_ora
    cfg = ConfigParser.parse_oracle_config(load_config())
    return _get_ora(cfg)


def query_patient_dept(patient_id: str, visit_number: str = "") -> dict:
    """查询患者科室信息。

    V_QYBR 当前使用“所在科室名称/编码”和“出院科室名称/编码”。dept_name 优先取
    所在科室名称，缺失时回退出院科室名称，便于 PushLog.dept 做统一科室筛选。
    """
    if not patient_id or not _is_oracle_data_source():
        return {}
    visit_num = str(visit_number or "").strip()
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection()
        cur = conn.cursor()
        if visit_num:
            cur.execute(
                'SELECT * FROM (SELECT "所在科室编码", "所在科室名称", "出院科室编码", "出院科室名称", "入院科室名称" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid AND "次数" = :vn ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id, "vn": visit_num},
            )
        else:
            cur.execute(
                'SELECT * FROM (SELECT "所在科室编码", "所在科室名称", "出院科室编码", "出院科室名称", "入院科室名称" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id},
            )
        row = cur.fetchone()
        if row:
            inpatient_code = _as_text(row[0])
            inpatient_name = _as_text(row[1])
            discharge_code = _as_text(row[2])
            discharge_name = _as_text(row[3])
            return {
                "dept_code": inpatient_code or discharge_code,
                "dept_name": inpatient_name or discharge_name,
                "inpatient_dept_code": inpatient_code,
                "inpatient_dept_name": inpatient_name,
                "discharge_dept_code": discharge_code,
                "discharge_dept_name": discharge_name,
                "admission_dept_name": _as_text(row[4]),
            }
    except Exception as e:
        logger.warning("query_patient_dept patient=%s visit=%s err=%s", patient_id, visit_num, e)
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return {}

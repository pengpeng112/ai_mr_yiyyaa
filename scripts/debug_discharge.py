"""诊断出院记录查询问题"""
import sys
sys.path.insert(0, ".")

from app.config import load_config
from app.services.config_parser import ConfigParser
from app.oracle_client import get_oracle_connection
from app.services.patient_visit_export_service import _safe_text, _format_dt

cfg = load_config()
oracle_cfg = ConfigParser.parse_oracle_config(cfg)
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)
conn = get_oracle_connection(oracle_cfg)

patient_id = "00018069"

try:
    cursor = conn.cursor()

    # 1. 检查 TEMP_PAT_VISIT_LIST
    cursor.execute("SELECT 患者ID, 住院号, 住院次数 FROM TEMP_PAT_VISIT_LIST WHERE 患者ID=:p", {"p": patient_id})
    print("=== TEMP_PAT_VISIT_LIST ===")
    for row in cursor.fetchall():
        print(f"  患者ID={row[0]}, 住院号={row[1]}, 住院次数={row[2]} (type={type(row[2]).__name__})")

    # 2. 检查 V_cyJL 出院记录
    cursor.execute("SELECT 患者ID, 次数, 病历名称, RN FROM jhemr.V_cyJL WHERE 患者ID=:p AND 病历名称 LIKE '%出院记录%'", {"p": patient_id})
    print("\n=== V_cyJL 出院记录 ===")
    rows = cursor.fetchall()
    if not rows:
        print("  无数据!")
    for row in rows:
        print(f"  患者ID={row[0]}, 次数={row[1]} (type={type(row[1]).__name__}), 病历名称={row[2]}, RN={row[3]}")

    # 3. 检查 v_blws 出院记录
    cursor.execute("SELECT patient_id, visit_id, progress_type_name, progress_title_name FROM jhemr.v_blws WHERE patient_id=:p AND (progress_type_name LIKE '%出院%' OR progress_title_name LIKE '%出院%')", {"p": patient_id})
    print("\n=== v_blws 出院相关记录 ===")
    rows = cursor.fetchall()
    if not rows:
        print("  无数据!")
    for row in rows:
        print(f"  patient_id={row[0]}, visit_id={row[1]} (type={type(row[1]).__name__}), type={row[2]}, title={row[3]}")

    # 4. 检查 emr_cfg 是否启用
    print(f"\n=== 海量库配置 ===")
    print(f"  enabled: {emr_cfg.get('enabled')}")
    print(f"  host: {emr_cfg.get('host')}")
    print(f"  use_for_export_discharge: {emr_cfg.get('use_for_export_discharge')}")

    # 5. 模拟导出查询
    from app.services.patient_visit_export_service import _query_discharge_records
    patient_ids = [_safe_text(patient_id)]
    discharge = _query_discharge_records(conn, patient_ids)
    print(f"\n=== _query_discharge_records 结果 ===")
    print(f"  keys: {list(discharge.keys())}")
    for k, v in discharge.items():
        print(f"  {k}: {len(v)} records")
        for r in v:
            print(f"    {r}")

    # 6. 检查 visit_number 类型匹配问题
    print(f"\n=== 类型匹配检查 ===")
    cursor.execute("SELECT 患者ID, 住院次数 FROM TEMP_PAT_VISIT_LIST WHERE 患者ID=:p", {"p": patient_id})
    temp_row = cursor.fetchone()
    if temp_row:
        vn_temp = _safe_text(temp_row[1])
        print(f"  TEMP_TABLE visit_number: '{vn_temp}' (原始: {temp_row[1]}, type: {type(temp_row[1]).__name__})")
    
    cursor.execute("SELECT 患者ID, 次数 FROM jhemr.V_cyJL WHERE 患者ID=:p AND 病历名称 LIKE '%出院记录%' AND RN=1", {"p": patient_id})
    cyjl_row = cursor.fetchone()
    if cyjl_row:
        vn_cyjl = _safe_text(cyjl_row[1])
        print(f"  V_cyJL visit_number: '{vn_cyjl}' (原始: {cyjl_row[1]}, type: {type(cyjl_row[1]).__name__})")
        print(f"  匹配: {vn_temp == vn_cyjl}")

finally:
    conn.close()

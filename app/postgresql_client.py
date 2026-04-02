"""
PostgreSQL 数据库连接与查询模块
支持可配置 SQL 和字段映射，与 oracle_client.py 保持相同接口风格
"""
import logging
import re
import time
from typing import List, Dict, Any

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit.postgresql")

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    logger.warning("psycopg2 未安装，PostgreSQL 查询功能不可用（开发环境可忽略）")

# SQL 标识符校验正则（允许中文字母数字下划线）
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z\u4e00-\u9fff_][a-zA-Z0-9\u4e00-\u9fff_]*$")

# SQL 危险关键字
_DANGEROUS_SQL_RE = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|EXEC|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)


def _validate_sql_identifier(name: str, label: str = "字段名") -> str:
    """校验 SQL 标识符（字段名/表名），防止 SQL 注入"""
    name = (name or "").strip()
    if not name:
        raise ValueError(f"{label}不能为空")
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"{label} '{name}' 包含非法字符，仅允许字母、数字、中文和下划线")
    return name


def _validate_configurable_sql(sql: str, label: str = "SQL") -> str:
    """校验可配置的 SQL 语句，仅允许 SELECT"""
    sql = (sql or "").strip()
    if not sql:
        return sql
    if not sql.upper().lstrip().startswith("SELECT"):
        raise ValueError(f"{label} 必须以 SELECT 开头")
    match = _DANGEROUS_SQL_RE.search(sql.split("WHERE")[0] if "WHERE" in sql.upper() else sql)
    if match:
        raise ValueError(f"{label} 中包含禁止的关键字: {match.group()}")
    return sql


_DEFAULT_FIELD_MAPPING = {
    "patient_id": "患者ID",
    "visit_number": "次数",
    "patient_name": "患者姓名",
    "dept": "所在科室名称",
    "admission_no": "住院号",
}

_DEFAULT_QUERY_SQL = """SELECT
    序号, 患者ID, 次数, 住院号, 患者姓名,
    性别, 出生日期, 入院日期, 床号,
    入院诊断, 入院病情, 医嘱护理级别, 所在科室名称, 管床医生,
    病历标题时间, 病历名称, 病历创建人, 病历内容,
    护理记录时间, 护理单类型, 护理记录人,
    体温, 心率脉搏, 呼吸, 血压, 血氧饱和度, 血糖, 意识神志,
    氧疗_鼻导管, 氧疗_面罩,
    入量_名称, 入量_途径, 入量_量,
    出量_名称, 出量_量, 尿量,
    皮肤情况, 刀口情况, 管道护理, 高危风险,
    病情观察及护理措施, 护士签名
FROM ai_mr.patient_records
WHERE {dept_filter}
  AND DATE(护理记录时间) = %s
ORDER BY 患者ID, 次数, 病历标题时间, 护理记录时间"""

_DEFAULT_DEPT_SQL = (
    "SELECT DISTINCT \u6240\u5728\u79d1\u5ba4\u540d\u79f0 FROM ai_mr.patient_records "
    "WHERE \u6240\u5728\u79d1\u5ba4\u540d\u79f0 IS NOT NULL ORDER BY \u6240\u5728\u79d1\u5ba4\u540d\u79f0"
)


def get_pg_connection(config: dict):
    """创建 PostgreSQL 数据库连接"""
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 未安装，请执行: pip install psycopg2-binary")
    conn = psycopg2.connect(
        host=config["host"],
        port=int(config.get("port", 5432)),
        dbname=config["database"],
        user=config["username"],
        password=config["password"],
        connect_timeout=10,
    )
    return conn


def test_pg_connection(config: dict) -> dict:
    """测试 PostgreSQL 连接，返回延迟及诊断信息"""
    if not HAS_PSYCOPG2:
        return {
            "status": "down",
            "message": "psycopg2 未安装。请执行: pip install psycopg2-binary",
            "fix": "install_psycopg2",
        }
    start = time.time()
    conn = None
    try:
        conn = get_pg_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        latency = int((time.time() - start) * 1000)
        audit_logger.info(f"PostgreSQL 连接测试成功, 延迟={latency}ms, host={config.get('host')}")
        return {"status": "up", "latency_ms": latency}
    except Exception as e:
        err = str(e)
        audit_logger.error(f"PostgreSQL 连接测试失败: {err}")
        fix = None
        hint = err
        if "password authentication failed" in err or "role" in err.lower():
            fix = "check_credentials"
            hint = f"用户名或密码错误，请检查账号信息。原始错误: {err}"
        elif "could not connect" in err or "Connection refused" in err:
            fix = "check_network"
            hint = f"无法连接到 {config.get('host')}:{config.get('port')}，请确认服务已启动且端口可达。原始错误: {err}"
        elif "database" in err.lower() and "does not exist" in err.lower():
            fix = "check_database"
            hint = f"数据库 '{config.get('database')}' 不存在，请确认数据库名。原始错误: {err}"
        elif "timeout" in err.lower():
            fix = "check_network"
            hint = f"连接超时，请确认 {config.get('host')} 可达。原始错误: {err}"
        return {"status": "down", "message": hint, "raw_error": err, "fix": fix}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def fetch_pg_department_list(config: dict) -> List[str]:
    """从 PostgreSQL 动态获取科室列表"""
    conn = get_pg_connection(config)
    dept_sql = (config.get("dept_sql") or "").strip() or _DEFAULT_DEPT_SQL
    if dept_sql != _DEFAULT_DEPT_SQL:
        dept_sql = _validate_configurable_sql(dept_sql, "PG科室查询SQL")
    audit_logger.info(f"[PG科室查询] SQL: {dept_sql[:200]}")
    try:
        cursor = conn.cursor()
        cursor.execute(dept_sql)
        depts = [row[0] for row in cursor.fetchall() if row[0]]
        cursor.close()
        audit_logger.info(f"[PG科室查询] 返回 {len(depts)} 个科室")
        return depts
    finally:
        conn.close()


def _get_field_mapping(config: dict) -> dict:
    mapping = config.get("field_mapping") or {}
    result = _DEFAULT_FIELD_MAPPING.copy()
    if isinstance(mapping, dict):
        result.update({k: v for k, v in mapping.items() if v})
    return result


def fetch_pg_records(config: dict, dept_list: List[str], query_date: str) -> List[dict]:
    """
    从 PostgreSQL 查询病程记录（使用可配置 SQL）
    SQL 须包含 {dept_filter} 占位符和 %(query_date)s 参数
    """
    conn = get_pg_connection(config)
    field_mapping = _get_field_mapping(config)
    dept_field = field_mapping.get("dept", "所在科室名称")
    dept_field = _validate_sql_identifier(dept_field, "PG科室字段名")

    try:
        # 校验自定义 SQL
        query_sql_raw = (config.get("query_sql") or "").strip()
        if query_sql_raw:
            _validate_configurable_sql(query_sql_raw, "PG病历查询SQL")

        if dept_list:
            placeholders = ",".join(["%s"] * len(dept_list))
            dept_filter = f"\"{dept_field}\" IN ({placeholders})"
            params = list(dept_list) + [query_date]
        else:
            dept_filter = "1=1"
            params = [query_date]

        query_sql = (config.get("query_sql") or "").strip() or _DEFAULT_QUERY_SQL
        sql = query_sql.format(dept_filter=dept_filter)

        audit_logger.info(f"[PG病历查询] 日期={query_date}, 科室={dept_list}")
        audit_logger.debug(f"[PG病历查询] SQL: {sql[:500]}")

        start = time.time()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        elapsed = int((time.time() - start) * 1000)

        records = [dict(row) for row in rows]
        
        # 安全上限告警
        MAX_SAFE_RECORDS = int(config.get("max_records", 50000))
        if len(records) > MAX_SAFE_RECORDS:
            logger.warning(
                f"PG 查询结果 {len(records)} 条超过安全上限 {MAX_SAFE_RECORDS}，"
                f"已截断。请检查 query_sql 或科室/日期筛选条件。"
            )
            records = records[:MAX_SAFE_RECORDS]
        
        audit_logger.info(f"[PG病历查询] 返回 {len(records)} 条记录, 耗时={elapsed}ms")
        logger.info(f"PostgreSQL 查询到 {len(records)} 条记录 (日期={query_date}, 科室={dept_list})")
        return records
    except Exception as e:
        audit_logger.error(f"[PG病历查询] 异常: {e}")
        raise
    finally:
        conn.close()

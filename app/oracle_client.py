"""
Oracle 数据库连接与查询模块
支持可配置 SQL 和字段映射，查询日志记录到本地文件
"""
import logging
import re
import time
from typing import List, Optional, Dict, Any

from app.config import validate_oracle_instant_client_dir

logger = logging.getLogger(__name__)

# 专用审计日志器：记录详细的数据库查询信息
audit_logger = logging.getLogger("audit.oracle")

# 尝试导入 cx_Oracle，开发环境可能未安装
try:
    import cx_Oracle
    HAS_CX_ORACLE = True
except ImportError:
    HAS_CX_ORACLE = False
    logger.warning("cx_Oracle 未安装，Oracle 查询功能不可用（开发环境可忽略）")


# 全局只初始化一次 Instant Client（按路径缓存）
_oracle_client_init_path = None

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


def _init_oracle_client(instant_client_dir: str = ""):
    """初始化 Oracle Instant Client。路径变化时自动重新初始化。"""
    global _oracle_client_init_path
    if not HAS_CX_ORACLE:
        return
    dir_clean = (instant_client_dir or "").strip()
    if _oracle_client_init_path == dir_clean:
        return  # 路径未变，跳过
    if dir_clean:
        try:
            cx_Oracle.init_oracle_client(lib_dir=dir_clean)
            _oracle_client_init_path = dir_clean
            audit_logger.info(f"Oracle Instant Client 初始化成功: {dir_clean}")
        except Exception as e:
            err = str(e)
            # cx_Oracle 已初始化过（不同路径）时会报错，记录警告但继续
            if "already" in err.lower() or "re-initialize" in err.lower():
                _oracle_client_init_path = dir_clean
                audit_logger.warning(f"Oracle Instant Client 已初始化，无法切换路径（需重启服务生效）: {err}")
            else:
                audit_logger.error(f"Oracle Instant Client 初始化失败: {err}")
                raise RuntimeError(f"Instant Client 初始化失败: {err}")
    else:
        # 不指定路径，让 cx_Oracle 自动搜索系统 PATH
        try:
            cx_Oracle.init_oracle_client()
            _oracle_client_init_path = ""
            audit_logger.info("Oracle Instant Client 使用系统 PATH 初始化")
        except Exception as e:
            err = str(e)
            if "already" in err.lower() or "re-initialize" in err.lower():
                _oracle_client_init_path = ""
            else:
                audit_logger.warning(f"Oracle Instant Client 自动初始化: {err}")


# ---- 默认 SQL（当 config 中未配置时使用） ----
_DEFAULT_QUERY_SQL = """SELECT
    a.患者ID, a.次数, a.住院号, a.患者姓名, a.性别, a.出生日期, a.入院日期,
    a.BED_NO AS 床号, a.入院诊断, a.入院病情,
    a.护理级别 AS 医嘱护理级别, a.所在科室名称, a.管床医生,
    b.病历标题时间 AS 病历文书_完成时间,
    b.病历名称 AS 病历文书_名称,
    b.创建人 AS 病历文书_签名医师,
    b.病历内容 AS 病历文书_内容,
    c.护理记录时间 AS 护理记录_创建时间,
    c.护理单类型 AS 护理记录_文书类型,
    c.病情观察及护理措施 AS 护理记录_内容,
    c.记录人 AS 护理记录_记录人,
    c.体温 AS 护理记录_体温,
    c.心率脉搏 AS 护理记录_心率脉搏,
    c.呼吸 AS 护理记录_呼吸,
    c.血压 AS 护理记录_血压,
    c.血氧饱和度 AS 护理记录_血氧饱和度,
    c.血糖 AS 护理记录_血糖,
    c.意识神志 AS 护理记录_意识神志,
    c.氧疗_鼻导管 AS 护理记录_氧疗_鼻导管,
    c.氧疗_面罩 AS 护理记录_氧疗_面罩,
    c.入量_名称 AS 护理记录_入量_名称,
    c.入量_途径 AS 护理记录_入量_途径,
    c.入量_量 AS 护理记录_入量_量,
    c.出量_名称 AS 护理记录_出量_名称,
    c.出量_量 AS 护理记录_出量_量,
    c.尿量 AS 护理记录_尿量,
    c.皮肤情况 AS 护理记录_皮肤情况,
    c.刀口情况 AS 护理记录_刀口情况,
    c.管道护理 AS 护理记录_管道护理,
    c.高危风险 AS 护理记录_高危风险,
    c.护士签名 AS 护理记录_护士签名
FROM jhemr.v_zybr a
LEFT JOIN jhemr.v_bcjl b ON a.患者ID = b.患者ID AND a.次数 = b.次数
LEFT JOIN ydhl.v_hljl c ON c.患者ID = b.患者ID || '_' || b.次数
    AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = TO_CHAR(c.护理记录时间, 'yyyy-mm-dd')
WHERE {dept_filter}
  AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = :query_date
ORDER BY a.患者ID, a.次数, b.病历标题时间, c.护理记录时间"""

_DEFAULT_DEPT_SQL = "SELECT DISTINCT 所在科室名称 FROM jhemr.v_zybr WHERE 所在科室名称 IS NOT NULL ORDER BY 所在科室名称"

_DEFAULT_FIELD_MAPPING = {
    "patient_id": "患者ID",
    "visit_number": "次数",
    "patient_name": "患者姓名",
    "dept": "所在科室名称",
    "admission_no": "住院号",
}


def get_oracle_connection(config: dict):
    """创建 Oracle 数据库连接"""
    if not HAS_CX_ORACLE:
        raise RuntimeError("cx_Oracle 未安装，请安装 cx_Oracle 和 Oracle Instant Client")

    # 每次连接前确保 Instant Client 已初始化
    instant_client_dir = validate_oracle_instant_client_dir(
        config.get("instant_client_dir", "") or "",
        require_exists=bool(config.get("instant_client_dir", "")),
    )
    _init_oracle_client(instant_client_dir)

    dsn = cx_Oracle.makedsn(
        config["host"],
        config["port"],
        service_name=config["service_name"],
    )
    conn = cx_Oracle.connect(
        user=config["username"],
        password=config["password"],
        dsn=dsn,
        encoding="UTF-8",
    )
    return conn


def test_oracle_connection(config: dict) -> dict:
    """测试 Oracle 连接，返回延迟及详细诊断信息"""
    if not HAS_CX_ORACLE:
        return {
            "status": "down",
            "message": "cx_Oracle 未安装。请执行: pip install cx_Oracle",
            "fix": "install_cx_oracle",
        }
    start = time.time()
    conn = None
    try:
        conn = get_oracle_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        latency = int((time.time() - start) * 1000)
        audit_logger.info(f"Oracle 连接测试成功, 延迟={latency}ms, host={config.get('host')}")
        return {"status": "up", "latency_ms": latency}
    except Exception as e:
        err = str(e)
        audit_logger.error(f"Oracle 连接测试失败: {err}, host={config.get('host')}")
        # 诊断提示
        fix = None
        hint = err
        if "DPI-1047" in err or "locate" in err.lower():
            fix = "install_instant_client"
            hint = (
                "找不到 Oracle Instant Client DLL。"
                "请下载 Oracle Instant Client Basic 包（与数据库位数一致），"
                "解压后将目录路径填入下方 'Instant Client 目录' 字段。"
                "下载地址：https://www.oracle.com/database/technologies/instant-client/downloads.html"
            )
        elif "ORA-01017" in err or "logon denied" in err.lower():
            fix = "check_credentials"
            hint = "用户名或密码错误（ORA-01017），请检查 Oracle 配置中的用户名/密码。"
        elif "ORA-12541" in err or "no listener" in err.lower():
            fix = "check_network"
            hint = f"无法连接到 {config.get('host')}:{config.get('port')}，Oracle 监听器未启动或网络不通。"
        elif "ORA-12514" in err:
            fix = "check_service_name"
            hint = f"服务名 '{config.get('service_name')}' 不存在，请确认 Oracle 服务名配置正确。"
        elif "timed out" in err.lower() or "timeout" in err.lower():
            fix = "check_network"
            hint = f"连接超时，请确认 {config.get('host')} 在内网可达，防火墙已放行 {config.get('port')} 端口。"
        return {"status": "down", "message": hint, "raw_error": err, "fix": fix}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _get_field_mapping(config: dict) -> dict:
    """获取字段映射配置"""
    mapping = config.get("field_mapping", {})
    result = _DEFAULT_FIELD_MAPPING.copy()
    if isinstance(mapping, dict):
        result.update(mapping)
    return result


def fetch_department_list(config: dict) -> List[str]:
    """从 Oracle 动态获取科室列表（使用可配置 SQL）"""
    conn = get_oracle_connection(config)
    dept_sql = config.get("dept_sql", "").strip()
    if not dept_sql:
        dept_sql = _DEFAULT_DEPT_SQL
    else:
        dept_sql = _validate_configurable_sql(dept_sql, "科室查询SQL")

    audit_logger.info(f"[科室查询] SQL: {dept_sql[:200]}")
    try:
        cursor = conn.cursor()
        cursor.execute(dept_sql)
        depts = [row[0] for row in cursor.fetchall() if row[0]]
        cursor.close()
        audit_logger.info(f"[科室查询] 返回 {len(depts)} 个科室")
        return depts
    finally:
        conn.close()


def fetch_records(config: dict, dept_list: List[str], query_date: str) -> List[dict]:
    """
    从 Oracle 查询病程记录与护理记录（使用可配置 SQL）

    config 中可包含:
    - query_sql: 自定义查询 SQL，必须包含 {dept_filter} 和 :query_date 占位符
    - field_mapping: 字段映射配置
    """
    conn = get_oracle_connection(config)
    field_mapping = _get_field_mapping(config)
    dept_field = field_mapping.get("dept", "所在科室名称")
    dept_field = _validate_sql_identifier(dept_field, "科室字段名")

    try:
        # 校验自定义 SQL
        query_sql_raw = config.get("query_sql", "").strip()
        if query_sql_raw:
            _validate_configurable_sql(query_sql_raw, "病历查询SQL")

        if dept_list:
            placeholders = ",".join([f":d{i}" for i in range(len(dept_list))])
            dept_filter = f"a.{dept_field} IN ({placeholders})"
            params = {f"d{i}": d for i, d in enumerate(dept_list)}
        else:
            dept_filter = "1=1"
            params = {}

        params["query_date"] = query_date

        # 使用可配置 SQL，fallback 到默认
        query_sql = config.get("query_sql", "").strip()
        if not query_sql:
            query_sql = _DEFAULT_QUERY_SQL

        sql = query_sql.format(dept_filter=dept_filter)

        audit_logger.info(f"[病历查询] 日期={query_date}, 科室={dept_list}")
        audit_logger.debug(f"[病历查询] SQL: {sql[:500]}")
        audit_logger.debug(f"[病历查询] Params: {params}")

        start = time.time()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        elapsed = int((time.time() - start) * 1000)

        records = [dict(zip(columns, row)) for row in rows]
        
        # 安全上限告警
        MAX_SAFE_RECORDS = int(config.get("max_records", 50000))
        if len(records) > MAX_SAFE_RECORDS:
            logger.warning(
                f"查询结果 {len(records)} 条超过安全上限 {MAX_SAFE_RECORDS}，"
                f"已截断。请检查 query_sql 或科室/日期筛选条件。"
            )
            records = records[:MAX_SAFE_RECORDS]
        
        audit_logger.info(
            f"[病历查询] 返回 {len(records)} 条记录, 耗时={elapsed}ms, "
            f"列名={columns[:10]}{'...' if len(columns) > 10 else ''}"
        )
        logger.info(f"查询到 {len(records)} 条记录 (日期={query_date}, 科室={dept_list})")
        return records
    except Exception as e:
        audit_logger.error(f"[病历查询] 异常: {e}, 日期={query_date}, 科室={dept_list}")
        raise
    finally:
        conn.close()


def group_by_patient(records: List[dict], field_mapping: dict = None) -> dict:
    """按 患者ID + 次数 分组（支持可配置字段名）"""
    if field_mapping is None:
        field_mapping = _DEFAULT_FIELD_MAPPING

    pid_field = field_mapping.get("patient_id", "患者ID")
    visit_field = field_mapping.get("visit_number", "次数")

    grouped = {}
    for r in records:
        pid = str(r.get(pid_field, "unknown"))
        visit = str(r.get(visit_field, "1"))
        key = f"{pid}_{visit}"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)
    return grouped


def build_mr_text(record: dict) -> str:
    """将单条记录组装为结构化文本（自动适配所有列）"""
    return _build_record_section(record, 1)


def build_mr_text_combined(patient_records: List[dict], field_mapping: dict = None) -> str:
    """
    将同一患者的多条记录合并为结构化文本

    自动从记录字段中提取信息，支持可配置的字段映射
    """
    if not patient_records:
        return ""

    if field_mapping is None:
        field_mapping = _DEFAULT_FIELD_MAPPING

    first = patient_records[0]

    # ---- 患者信息头 ----
    name_field = field_mapping.get("patient_name", "患者姓名")
    dept_field = field_mapping.get("dept", "所在科室名称")
    admission_field = field_mapping.get("admission_no", "住院号")
    visit_field = field_mapping.get("visit_number", "次数")

    header = f"""【患者信息】
姓名：{_v(first, name_field)} | 性别：{_v(first, '性别')} | 出生日期：{_v(first, '出生日期')}
住院号：{_v(first, admission_field)} | 次数：{_v(first, visit_field)}
科室：{_v(first, dept_field)} | 床号：{_v(first, '床号')} | 管床医生：{_v(first, '管床医生')}
入院日期：{_v(first, '入院日期')} | 入院诊断：{_v(first, '入院诊断')} | 入院病情：{_v(first, '入院病情')}
医嘱护理级别：{_v(first, '医嘱护理级别')}"""

    # ---- 逐条记录 ----
    sections = []
    for i, r in enumerate(patient_records, 1):
        section = _build_record_section(r, i)
        sections.append(section)

    return header + "\n\n" + "\n\n".join(sections)


def _build_record_section(r: dict, index: int) -> str:
    """构建单条记录的文本段落"""
    lines = [f"--- 第 {index} 条记录 ---"]

    # 病程记录
    lines.append(f"【病程记录】（时间：{_v(r, '病历标题时间')} | 名称：{_v(r, '病历名称')} | 创建人：{_v(r, '病历创建人')}）")
    content = _v(r, '病历内容')
    if not content:
        content = _v(r, '病程记录内容', '（无）')
    lines.append(content)

    # 护理记录
    lines.append(f"\n【护理记录】（时间：{_v(r, '护理记录时间')} | 类型：{_v(r, '护理单类型')} | 记录人：{_v(r, '护理记录人')}）")

    # 生命体征
    vitals = []
    for key in ['体温', '心率脉搏', '呼吸', '血压', '血氧饱和度', '血糖', '意识神志']:
        val = _v(r, key)
        if val:
            vitals.append(f"{key}：{val}")
    if vitals:
        lines.append("生命体征：" + "  ".join(vitals))

    # 氧疗
    oxy_parts = []
    for key in ['氧疗_鼻导管', '氧疗_面罩']:
        val = _v(r, key)
        if val:
            oxy_parts.append(f"{key.replace('氧疗_', '')}：{val}")
    if oxy_parts:
        lines.append("氧疗：" + "  ".join(oxy_parts))

    # 出入量
    io_parts = []
    for prefix, keys in [("入量", ['入量_名称', '入量_途径', '入量_量']), ("出量", ['出量_名称', '出量_量'])]:
        vals = [f"{k.split('_')[-1]}：{_v(r, k)}" for k in keys if _v(r, k)]
        if vals:
            io_parts.append(f"{prefix}({' '.join(vals)})")
    urine = _v(r, '尿量')
    if urine:
        io_parts.append(f"尿量：{urine}")
    if io_parts:
        lines.append("出入量：" + "  ".join(io_parts))

    # 专科评估
    assess_parts = []
    for key in ['皮肤情况', '刀口情况', '管道护理', '高危风险']:
        val = _v(r, key)
        if val:
            assess_parts.append(f"{key}：{val}")
    if assess_parts:
        lines.append("专科评估：" + " | ".join(assess_parts))

    # 护理观察
    obs = _v(r, '病情观察及护理措施')
    if obs:
        lines.append(f"护理观察：{obs}")

    # 护士签名
    nurse = _v(r, '护士签名')
    if nurse:
        lines.append(f"护士签名：{nurse}")

    return "\n".join(lines)


def _v(record: dict, key: str, default: str = "") -> str:
    """安全取值，返回字符串"""
    val = record.get(key)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    return str(val).strip()

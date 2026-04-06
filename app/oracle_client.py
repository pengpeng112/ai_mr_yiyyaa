"""
Oracle 数据库连接与查询模块
支持可配置 SQL 和字段映射，查询日志记录到本地文件
"""
import logging
import time
import threading
from typing import List, Optional, Dict, Any

from app.config import validate_oracle_instant_client_dir
from app.services.config_parser import ConfigParser
from app.db_client_base import (
    validate_sql_identifier as _validate_sql_identifier,
    validate_configurable_sql as _validate_configurable_sql,
    normalize_sql as _normalize_oracle_sql,
    inject_condition_into_sql as _inject_condition_into_sql,
    build_oracle_execute_params as _build_execute_params,
)

logger = logging.getLogger(__name__)

# 专用审计日志器：记录详细的数据库查询信息
audit_logger = logging.getLogger("audit.oracle")

# 尝试导入 cx_Oracle，开发环境可能未安装
try:
    import cx_Oracle
    HAS_CX_ORACLE = True
except ImportError:
    cx_Oracle = None
    HAS_CX_ORACLE = False
    logger.warning("cx_Oracle 未安装，Oracle 查询功能不可用（开发环境可忽略）")


# 全局只初始化一次 Instant Client（按路径缓存）
_oracle_client_init_path = None
_oracle_pool = None
_oracle_pool_key = None
_pool_failed_keys: set = set()   # 记录连接池初始化失败的配置 key，避免重复尝试
_pool_lock = threading.Lock()

def _init_oracle_client(instant_client_dir: str = ""):
    """初始化 Oracle Instant Client。路径变化时自动重新初始化。

    优先使用 instant_client_dir 指定路径；
    若为空，则优先使用环境变量 ORACLE_HOME 指定的路径（容器内为 /opt/oracle），
    避免 cx_Oracle 自动搜索时拾到宿主机的旧版 Oracle Client。
    """
    import os
    global _oracle_client_init_path
    if not HAS_CX_ORACLE:
        return
    dir_clean = (instant_client_dir or "").strip()

    # 若未显式配置路径，尝试从环境变量 ORACLE_HOME 获取（Docker 内已设置为 /opt/oracle）
    if not dir_clean:
        oracle_home = os.environ.get("ORACLE_HOME", "").strip()
        if oracle_home and os.path.isdir(oracle_home):
            dir_clean = oracle_home

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


def _parse_int_config(config: dict, key: str, default: int, minimum: int) -> int:
    """解析整数配置，异常时回退默认值并记录告警。"""
    raw = config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Oracle 配置项 %s 非法(%s)，回退默认值 %s", key, raw, default)
        value = default
    return max(minimum, value)


def _parse_bool_config(config: dict, key: str, default: bool) -> bool:
    """解析布尔配置，兼容 true/false/1/0/yes/no 字符串。"""
    raw = config.get(key, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning("Oracle 配置项 %s 非法布尔值(%s)，回退默认值 %s", key, raw, default)
    return default


def _resolve_oracle_pool_settings(config: dict) -> dict:
    """解析并归一化 Oracle 连接池相关配置。"""
    pool_min = _parse_int_config(config, "pool_min", 1, 1)
    pool_max = _parse_int_config(config, "pool_max", 8, pool_min)
    pool_increment = _parse_int_config(config, "pool_increment", 1, 1)
    pool_timeout_seconds = _parse_int_config(config, "pool_timeout_seconds", 60, 10)
    acquire_timeout_seconds = _parse_int_config(config, "acquire_timeout_seconds", 15, 1)
    fallback_direct_connect = _parse_bool_config(config, "pool_fallback_direct", False)

    timed_wait_mode = getattr(cx_Oracle, "SPOOL_ATTRVAL_TIMEDWAIT", None)
    wait_mode = getattr(cx_Oracle, "SPOOL_ATTRVAL_WAIT", None)
    getmode = timed_wait_mode if timed_wait_mode is not None else wait_mode
    use_timed_wait = timed_wait_mode is not None and getmode == timed_wait_mode

    return {
        "pool_min": pool_min,
        "pool_max": pool_max,
        "pool_increment": pool_increment,
        "pool_timeout_seconds": pool_timeout_seconds,
        "acquire_timeout_seconds": acquire_timeout_seconds,
        "fallback_direct_connect": fallback_direct_connect,
        "getmode": getmode,
        "use_timed_wait": use_timed_wait,
    }


def get_oracle_connection(config: dict):
    """创建 Oracle 数据库连接"""
    import hashlib
    global _oracle_pool, _oracle_pool_key

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

    settings = _resolve_oracle_pool_settings(config)
    pool_min = settings["pool_min"]
    pool_max = settings["pool_max"]
    pool_increment = settings["pool_increment"]
    pool_timeout = settings["pool_timeout_seconds"]
    acquire_timeout_seconds = settings["acquire_timeout_seconds"]
    fallback_direct_connect = settings["fallback_direct_connect"]
    getmode = settings["getmode"]
    use_timed_wait = settings["use_timed_wait"]

    # 使用密码哈希而非明文，避免每次配置加载后密码对象不同导致连接池重建
    password_hash = hashlib.sha256((config.get("password", "") or "").encode("utf-8")).hexdigest()

    pool_key = (
        config.get("host", ""),
        int(config.get("port", 1521) or 1521),
        config.get("service_name", ""),
        config.get("username", ""),
        password_hash,  # 使用哈希值而非明文
        instant_client_dir,
        pool_min,
        pool_max,
        pool_increment,
        pool_timeout,
        acquire_timeout_seconds,
        fallback_direct_connect,
        use_timed_wait,
    )

    with _pool_lock:
        # 如果配置变更，关闭旧连接池
        if _oracle_pool is not None and _oracle_pool_key != pool_key:
            try:
                _oracle_pool.close(force=True)
                audit_logger.info("Oracle 连接池配置变更，已关闭旧连接池")
            except Exception as e:
                audit_logger.warning("关闭旧 Oracle 连接池失败: %s", e)
            finally:
                _oracle_pool = None
                _oracle_pool_key = None

        # 如果当前配置已知连接池初始化失败，直接使用直连，避免重复尝试
        if pool_key in _pool_failed_keys:
            audit_logger.debug("Oracle 连接池已知失败配置，使用直连模式")
            return cx_Oracle.connect(
                user=config["username"],
                password=config["password"],
                dsn=dsn,
                encoding="UTF-8",
            )

        if _oracle_pool is None:
            try:
                # 记录 Oracle Client 版本信息，帮助诊断 DPI-1050 错误
                try:
                    client_version = cx_Oracle.clientversion()
                    client_version_str = ".".join(map(str, client_version))
                    audit_logger.info(f"Oracle Client 版本: {client_version_str}")
                except Exception as ve:
                    audit_logger.warning(f"无法获取 Oracle Client 版本: {ve}")

                _oracle_pool = cx_Oracle.SessionPool(
                    user=config["username"],
                    password=config["password"],
                    dsn=dsn,
                    min=pool_min,
                    max=pool_max,
                    increment=pool_increment,
                    timeout=pool_timeout,
                    threaded=True,
                    getmode=getmode,
                    encoding="UTF-8",
                )
                if use_timed_wait and hasattr(_oracle_pool, "wait_timeout"):
                    _oracle_pool.wait_timeout = acquire_timeout_seconds
                _oracle_pool_key = pool_key
                audit_logger.info(
                    "Oracle 连接池初始化成功 host=%s service=%s min=%s max=%s inc=%s timeout=%ss acquire_timeout=%ss timedwait=%s fallback_direct=%s",
                    config.get("host"),
                    config.get("service_name"),
                    pool_min,
                    pool_max,
                    pool_increment,
                    pool_timeout,
                    acquire_timeout_seconds,
                    use_timed_wait,
                    fallback_direct_connect,
                )
            except Exception as e:
                err_msg = str(e)
                # 将失败的配置加入缓存，避免重复尝试
                _pool_failed_keys.add(pool_key)
                # 特殊处理 DPI-1050 错误，提供更明确的诊断信息
                if "DPI-1050" in err_msg:
                    try:
                        client_version = cx_Oracle.clientversion()
                        client_version_str = ".".join(map(str, client_version))
                        audit_logger.error(
                            "Oracle 连接池初始化失败: Oracle Client 版本 %s 不支持连接池（需要 12.2+），已回退直连。"
                            "建议升级 Oracle Instant Client 到 19c 或更高版本。当前加载路径: %s",
                            client_version_str,
                            _oracle_client_init_path or "系统 PATH",
                        )
                    except Exception:
                        audit_logger.error("Oracle 连接池初始化失败，回退直连: %s", e)
                else:
                    audit_logger.error("Oracle 连接池初始化失败，回退直连: %s", e)
                return cx_Oracle.connect(
                    user=config["username"],
                    password=config["password"],
                    dsn=dsn,
                    encoding="UTF-8",
                )

    try:
        return _oracle_pool.acquire()
    except Exception as e:
        audit_logger.error("从 Oracle 连接池获取连接失败: %s", e)
        if not fallback_direct_connect:
            raise RuntimeError(
                "Oracle 连接池获取连接失败，已禁用直连回退。"
                "可检查连接池配置或将 oracle.pool_fallback_direct 设为 true。"
            ) from e
        audit_logger.warning("连接池获取失败，启用直连回退（pool_fallback_direct=true）")
        return cx_Oracle.connect(
            user=config["username"],
            password=config["password"],
            dsn=dsn,
            encoding="UTF-8",
        )


def reset_oracle_pool() -> None:
    """重置 Oracle 连接池（配置变更后调用）。"""
    global _oracle_pool, _oracle_pool_key
    with _pool_lock:
        _pool_failed_keys.clear()  # 清除失败缓存，允许下次重新尝试连接池
        if _oracle_pool is None:
            _oracle_pool_key = None
            return
        try:
            _oracle_pool.close(force=True)
            audit_logger.info("Oracle 连接池已重置")
        except Exception as e:
            audit_logger.warning("重置 Oracle 连接池失败: %s", e)
        finally:
            _oracle_pool = None
            _oracle_pool_key = None


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
        elif "连接池获取连接失败" in err:
            fix = "check_pool_limit"
            hint = (
                "连接池获取超时/失败，请检查 pool_max 与并发设置；"
                "必要时可临时开启 pool_fallback_direct=true 进行应急。"
            )
        return {"status": "down", "message": hint, "raw_error": err, "fix": fix}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _get_field_mapping(config: dict) -> dict:
    """获取字段映射配置"""
    result = ConfigParser.get_field_mapping({"oracle": config}, "oracle")
    for key, default_value in _DEFAULT_FIELD_MAPPING.items():
        if not str(result.get(key, "") or "").strip():
            result[key] = default_value
    return result


def fetch_department_list(config: dict) -> List[str]:
    """从 Oracle 动态获取科室列表（使用可配置 SQL）"""
    dept_sql = _normalize_oracle_sql(config.get("dept_sql", ""))
    if not dept_sql:
        dept_sql = _DEFAULT_DEPT_SQL
    else:
        dept_sql = _validate_configurable_sql(dept_sql, "科室查询SQL")

    audit_logger.info(f"[科室查询] SQL: {dept_sql[:200]}")
    conn = get_oracle_connection(config)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(dept_sql)
        depts = [row[0] for row in cursor.fetchall() if row[0]]
        audit_logger.info(f"[科室查询] 返回 {len(depts)} 个科室")
        return depts
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass


def fetch_records(config: dict, dept_list: List[str], query_date: str) -> List[dict]:
    """
    从 Oracle 查询病程记录与护理记录（使用可配置 SQL）

    config 中可包含:
    - query_sql: 自定义查询 SQL（建议包含 {dept_filter} 和 :query_date 占位符）
    - field_mapping: 字段映射配置
    """
    field_mapping = _get_field_mapping(config)
    dept_field = field_mapping.get("dept", "所在科室名称")
    dept_field = _validate_sql_identifier(dept_field, "科室字段名")

    # 校验 SQL 与参数前，不先占用连接
    query_sql_raw = _normalize_oracle_sql(config.get("query_sql", ""))
    if query_sql_raw:
        _validate_configurable_sql(query_sql_raw, "病历查询SQL")

    conn = get_oracle_connection(config)
    cursor = None
    try:
        if dept_list:
            placeholders = ",".join([f":d{i}" for i in range(len(dept_list))])
            dept_filter = f"a.{dept_field} IN ({placeholders})"
            dept_filter_fallback = f"{dept_field} IN ({placeholders})"
            candidate_params = {f"d{i}": d for i, d in enumerate(dept_list)}
        else:
            dept_filter = "1=1"
            dept_filter_fallback = "1=1"
            candidate_params = {}

        candidate_params["query_date"] = query_date

        # 使用可配置 SQL，fallback 到默认
        query_sql = _normalize_oracle_sql(config.get("query_sql", ""))
        if not query_sql:
            query_sql = _DEFAULT_QUERY_SQL

        try:
            if "{dept_filter}" in query_sql:
                sql = query_sql.format(dept_filter=dept_filter)
            elif dept_list:
                sql = _inject_condition_into_sql(query_sql, dept_filter_fallback)
            else:
                sql = query_sql
        except KeyError as e:
            raise ValueError(f"自定义病历查询SQL包含未支持的模板变量: {e}") from e

        sql = _normalize_oracle_sql(sql)

        params = _build_execute_params(sql, candidate_params)

        audit_logger.info(f"[病历查询] 日期={query_date}, 科室={dept_list}")
        audit_logger.debug(f"[病历查询] SQL: {sql}")
        audit_logger.debug(f"[病历查询] Params: {params}")

        start = time.time()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
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
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass


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

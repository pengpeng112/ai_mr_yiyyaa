"""
数据库客户端公共工具函数（Oracle/PostgreSQL 复用）。
"""
import re
from typing import Any, Dict


# SQL 标识符校验正则（允许中文字母数字下划线）
IDENTIFIER_RE = re.compile(r"^[a-zA-Z\u4e00-\u9fff_][a-zA-Z0-9\u4e00-\u9fff_]*$")

# SQL 危险关键字
DANGEROUS_SQL_RE = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|EXEC|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)

# Oracle 命名绑定参数（如 :query_date / :d0）
ORACLE_BIND_NAME_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")
SQL_TAIL_TRIM_CHARS = ";；/"
SQL_CLAUSE_SPLIT_RE = re.compile(r"\b(group\s+by|having|order\s+by)\b", re.IGNORECASE)
SQL_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")


def validate_sql_identifier(name: str, label: str = "字段名") -> str:
    """校验 SQL 标识符（字段名/表名），防止 SQL 注入。"""
    value = (name or "").strip()
    if not value:
        raise ValueError(f"{label}不能为空")
    if not IDENTIFIER_RE.match(value):
        raise ValueError(f"{label} '{value}' 包含非法字符，仅允许字母、数字、中文和下划线")
    return value


def validate_configurable_sql(sql: str, label: str = "SQL") -> str:
    """校验可配置 SQL，仅允许 SELECT。"""
    value = (sql or "").strip()
    if not value:
        return value
    if not value.upper().lstrip().startswith("SELECT"):
        raise ValueError(f"{label} 必须以 SELECT 开头")
    match = DANGEROUS_SQL_RE.search(value.split("WHERE")[0] if "WHERE" in value.upper() else value)
    if match:
        raise ValueError(f"{label} 中包含禁止的关键字: {match.group()}")
    return value


def normalize_sql(sql: str) -> str:
    """归一化 SQL 文本，处理 BOM 和尾部分隔符。"""
    normalized = (sql or "").replace("\ufeff", "").strip()
    while normalized.endswith(tuple(SQL_TAIL_TRIM_CHARS)):
        normalized = normalized[:-1].rstrip()
    return normalized


def inject_condition_into_sql(sql: str, condition: str) -> str:
    """将条件注入 SQL（优先插入在 GROUP/HAVING/ORDER 之前）。"""
    condition_value = (condition or "").strip()
    if not condition_value:
        return sql

    stripped_sql = (sql or "").strip()
    split_match = SQL_CLAUSE_SPLIT_RE.search(stripped_sql)
    if split_match:
        body = stripped_sql[:split_match.start()].rstrip()
        tail = stripped_sql[split_match.start():].lstrip()
    else:
        body = stripped_sql
        tail = ""

    if re.search(r"\bwhere\b", body, re.IGNORECASE):
        merged = f"{body} AND {condition_value}"
    else:
        merged = f"{body} WHERE {condition_value}"

    return f"{merged} {tail}".strip() if tail else merged


def build_oracle_execute_params(sql: str, candidate_params: Dict[str, Any]) -> Dict[str, Any]:
    """按 SQL 中出现的 Oracle 绑定变量裁剪参数，并校验缺失项。"""
    sql_without_literals = SQL_STRING_LITERAL_RE.sub("''", sql or "")
    bind_names = set(ORACLE_BIND_NAME_RE.findall(sql_without_literals))
    missing = sorted(name for name in bind_names if name not in candidate_params)
    if missing:
        raise ValueError(f"SQL 绑定变量缺失: {', '.join(missing)}")
    return {name: candidate_params[name] for name in sorted(bind_names)}

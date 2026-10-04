# -*- coding: utf-8 -*-
"""数据库只读探索工具（057 D0，2026-09-25 计划 / 2026-09-28 实现）

红线（与 057 §5-D0 一致）：
- 只执行本文件内人工审查过的固定 SELECT 模板；不接受任意 SQL；
- 连接后先设只读保护并回验，未确认前不执行任何业务查询；
- 禁止 DML/DDL/CALL/EXEC/SELECT INTO/FOR UPDATE/nextval/用户函数/DBLink/EXPLAIN；
- 预算：连接 10s、语句 15s、锁等待 2s、单源单轮 <=20 条、元数据每页 100 行、
  对象上限 1000/源；默认不做全表 count、不取患者级明细；
- 凭据只从环境变量或既有配置（经 app.config 解密单键）读取，绝不写入输出；
- 事务最终 rollback 并 close；错误输出清理 DSN/口令/参数；
- PostgreSQL/Vastbase 本机缺 psycopg2 时经 84 容器转运（docker exec -i，零文件写入）。

用法：
  python scripts/explore_databases_readonly_20260925.py --list-sources
  python scripts/explore_databases_readonly_20260925.py --dry-run --source ods_oracle_216 --group identity
  python scripts/explore_databases_readonly_20260925.py --source ods_oracle_216 --group identity
离线测试：python -m pytest tests/test_database_readonly_explorer_20260925.py -q
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REGISTRY_PATH = os.path.join(REPO_ROOT, 'review', 'db-discovery-20260925', 'source-registry.json')
OUT_DIR = os.path.join(REPO_ROOT, 'review', 'db-discovery-20260925')

CONNECT_TIMEOUT_S = 10
STATEMENT_TIMEOUT_MS = 15000
LOCK_TIMEOUT_MS = 2000
MAX_QUERIES_PER_RUN = 20
METADATA_PAGE = 100
MAX_OBJECTS_PER_SOURCE = 1000

# 患者级敏感列 token（命中即整格脱敏；技术列名如 table_name 不在列）
SENSITIVE_COLUMN_TOKENS = ('patient_name', '姓名', '证件', 'idcard', 'id_no', 'phone', 'mobile',
                           '电话', '出生', 'birth', '正文', 'address', '地址', '内容', 'content')

# 只允许标识符类参数（schema/table/user），拒绝任何空白/引号/分号
IDENT_RE = re.compile(r'^[A-Za-z0-9_$#\u4e00-\u9fff]{1,60}$')

# SQL 白名单守卫（防线二；模板注册时的静态校验是防线一）
_FORBIDDEN_RE = re.compile(
    r'(?i)\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|call|exec|execute|'
    r'into|for\s+update|nextval|currval|savepoint|commit|lock\s+table|'
    r'explain|dblink|database\s+link|copy|vacuum|analyze|reindex|comment)\b')
_ALLOWED_HEAD_RE = re.compile(r'(?is)^\s*(select|with)\b')


class GuardError(RuntimeError):
    """只读保护未满足 / SQL 未过白名单 / 源未启用——一律中止，不重试。"""


def validate_template_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(';').strip()
    if ';' in stripped:
        raise GuardError('模板含多语句（分号）: %s' % sql[:60])
    if not _ALLOWED_HEAD_RE.match(stripped):
        raise GuardError('模板非 SELECT/WITH 开头: %s' % sql[:60])
    m = _FORBIDDEN_RE.search(stripped)
    if m:
        raise GuardError('模板命中禁止关键字 %s: %s' % (m.group(0), sql[:60]))


def validate_param(name: str, value: str) -> str:
    if not IDENT_RE.match(value or ''):
        raise GuardError('参数 %s=%r 不在标识符白名单内' % (name, value))
    return value


# ---------------------------------------------------------------- 模板注册表
TEMPLATES: dict[str, dict] = {}


def _tpl(key: str, dialects: tuple[str, ...], sql: str, params: tuple[str, ...] = (), desc: str = ''):
    validate_template_sql(sql)
    if key in TEMPLATES:
        raise GuardError('模板重名: %s' % key)
    TEMPLATES[key] = {'dialects': dialects, 'sql': sql, 'params': params, 'desc': desc}


# ---- PostgreSQL / Vastbase（openGauss 兼容 information_schema/pg_catalog） ----
_tpl('pg.identity', ('postgresql',),
     'select current_database(), current_schema(), session_user, '
     'coalesce(inet_server_addr()::text, chr(45)), inet_server_port(), pg_is_in_recovery(), version()',
     desc='实例身份/是否恢复库/版本')
_tpl('pg.txn_state', ('postgresql',),
     "select current_setting('transaction_read_only') as transaction_read_only",
     desc='回验会话只读状态')
_tpl('pg.objects', ('postgresql',),
     'select table_schema, table_name, table_type from information_schema.tables '
     'where table_schema = %(schema)s order by table_schema, table_name limit %(cap)s',
     params=('schema', 'cap'), desc='schema 对象清单（分页）')
_tpl('pg.columns', ('postgresql',),
     'select table_schema, table_name, column_name, ordinal_position, data_type, '
     'character_maximum_length, numeric_precision, is_nullable, udt_name from information_schema.columns '
     'where table_schema = %(schema)s and table_name = %(table)s order by ordinal_position',
     params=('schema', 'table'), desc='表字段结构')
_tpl('pg.view_def', ('postgresql',),
     'select pg_get_viewdef(c.oid, true) as viewdef from pg_class c '
     'join pg_namespace n on n.oid = c.relnamespace where n.nspname = %(schema)s and c.relname = %(table)s '
     "and c.relkind = 'v'", params=('schema', 'table'), desc='视图定义（无权限则失败，如实记录）')
_tpl('pg.indexes', ('postgresql',),
     'select schemaname, tablename, indexname, indexdef from pg_indexes '
     'where schemaname = %(schema)s order by tablename, indexname limit %(cap)s',
     params=('schema', 'cap'), desc='索引清单')
_tpl('pg.table_estimates', ('postgresql',),
     'select n.nspname as schema_name, c.relname as table_name, c.reltuples::bigint as est_rows '
     'from pg_class c join pg_namespace n on n.oid = c.relnamespace '
     "where n.nspname = %(schema)s and c.relkind = 'r' order by c.reltuples desc nulls last limit %(cap)s",
     params=('schema', 'cap'), desc='规划器行数估计（不做全表 count）')

# ---- Oracle ----
_tpl('ora.identity', ('oracle',),
     "select user as session_user, sys_context('USERENV', 'CURRENT_SCHEMA') as cur_schema, "
     "sys_context('USERENV', 'SERVER_HOST') as db_host, sys_context('USERENV', 'INSTANCE_NAME') as instance "
     'from dual', desc='会话身份/实例')
_tpl('ora.banner', ('oracle',), 'select banner from v$version where rownum <= 3',
     desc='数据库版本（无权限则失败）')
_tpl('ora.objects', ('oracle',),
     'select * from (select owner, object_name, object_type from all_objects where owner = :owner '
     'order by object_name) where rownum <= :cap', params=('owner', 'cap'),
     desc='schema 对象清单（11.2 ROWNUM 分页，现场版本 2026-09-28 实测）')
_tpl('ora.tables', ('oracle',),
     'select * from (select owner, table_name, num_rows, last_analyzed from all_tables where owner = :owner '
     'order by table_name) where rownum <= :cap', params=('owner', 'cap'),
     desc='表与统计行数（统计值非现算；11.2 ROWNUM 分页）')
_tpl('ora.columns', ('oracle',),
     'select owner, table_name, column_name, column_id, data_type, data_length, data_precision, nullable '
     'from all_tab_columns where owner = :owner and table_name = :tab order by column_id',
     params=('owner', 'tab'), desc='表字段结构（:table 为保留字，绑定名用 tab）')
_tpl('ora.view_def', ('oracle',),
     'select text length_only_marker from all_views where owner = :owner and view_name = :vw',
     params=('owner', 'vw'), desc='视图定义（:view 为保留字，绑定名用 vw；TEXT 长值输出截断）')
_tpl('ora.indexes', ('oracle',),
     'select index_name, uniqueness from all_indexes where owner = :owner and table_name = :tab '
     'order by index_name', params=('owner', 'tab'), desc='表索引')

# ---- MySQL ----
_tpl('my.identity', ('mysql',), 'select database(), user(), version()', desc='会话身份与版本')
_tpl('my.objects', ('mysql',),
     'select table_schema, table_name, table_type from information_schema.tables '
     'where table_schema = %(schema)s order by table_name limit %(cap)s', params=('schema', 'cap'),
     desc='schema 对象清单')
_tpl('my.columns', ('mysql',),
     'select table_schema, table_name, column_name, ordinal_position, column_type, is_nullable, column_key '
     'from information_schema.columns where table_schema = %(schema)s and table_name = %(table)s '
     'order by ordinal_position', params=('schema', 'table'), desc='表字段结构')

# ---- SQL Server（仅当台账证明 SELECT-only 账号才允许登记启用） ----
_tpl('ms.identity', ('mssql',),
     'select @@servername as server_name, suser_sname() as login, @@version as version',
     desc='会话身份与版本')
_tpl('ms.objects', ('mssql',),
     'select s.name as schema_name, o.name as object_name, o.type_desc from sys.objects o '
     'join sys.schemas s on s.schema_id = o.schema_id where s.name = ? '
     'order by o.name offset 0 rows fetch next ? rows only', params=('schema', 'cap'),
     desc='schema 对象清单')
_tpl('ms.columns', ('mssql',),
     'select s.name as schema_name, t.name as table_name, c.name as column_name, c.column_id, '
     'ty.name as type_name, c.max_length, c.is_nullable from sys.columns c '
     'join sys.tables t on t.object_id = c.object_id join sys.schemas s on s.schema_id = t.schema_id '
     'join sys.types ty on ty.user_type_id = c.user_type_id '
     'where s.name = ? and t.name = ? order by c.column_id', params=('schema', 'table'),
     desc='表字段结构')

# ---- SQLite ----
_tpl('lite.identity', ('sqlite',), 'select sqlite_version()', desc='SQLite 版本')
_tpl('lite.objects', ('sqlite',),
     "select type, name from sqlite_master where name not like 'sqlite_%' order by type, name limit ?",
     params=('cap',), desc='对象清单')
_tpl('lite.columns', ('sqlite',),
     'select name as column_name, type, "notnull" as not_null, pk from pragma_table_info(?) order by cid',
     params=('table',), desc='表字段结构')

GROUPS: dict[str, list[str]] = {
    'identity': ('pg.identity', 'pg.txn_state', 'ora.identity', 'ora.banner', 'my.identity',
                 'ms.identity', 'lite.identity'),
    'objects': ('pg.objects', 'pg.indexes', 'pg.table_estimates', 'ora.objects', 'ora.tables',
                'my.objects', 'ms.objects', 'lite.objects'),
    'columns': ('pg.columns', 'pg.view_def', 'ora.columns', 'ora.view_def', 'ora.indexes',
                'my.columns', 'ms.columns', 'lite.columns'),
    # FILEVERIFY 目标表现状（056 §6.1 只读口径复刻；仅聚合与四固定 ID，无患者数据）
    'fileverify': ('pg.fileverify_history', 'pg.fileverify_targets'),
}

_tpl('pg.fileverify_history', ('postgresql',),
     'select check_type, enable, count(*) as cnt from jhemr.jhmr_file_cum_fileverify '
     'group by check_type, enable order by check_type, enable',
     desc='FILEVERIFY 按 check_type/enable 聚合')
_tpl('pg.fileverify_targets', ('postgresql',),
     "select id, check_type, enable from jhemr.jhmr_file_cum_fileverify "
     "where id = any(array['20260922AIQC01','20260922AIQC02','20260922AIQC03','20260922AIQC04']) "
     "order by id",
     desc='四目标 ID 现值（056 第一批候选；仅 ID/类型/开关）')


# ---------------------------------------------------------------- 脱敏与凭据
def sanitize_text(value: str, keep: int = 80) -> str:
    return value if len(value) <= keep else value[:keep] + '...<truncated>'


def sanitize_cell(column_label: str, value):
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    low = column_label.lower()
    if any(tok in low for tok in SENSITIVE_COLUMN_TOKENS):
        return '<redacted len=%d>' % len(text)
    if 'viewdef' in low or low == 'text' or 'length_only_marker' in low:
        return sanitize_text(text, keep=2000)  # DDL 文本，非 PHI
    return sanitize_text(text)


def scrub_error(text: str, secrets) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, '<redacted>')
    out = re.sub(r'(?i)(password|passwd|pwd)\s*[=:]\s*[^\s;,)]+', r'\1=<redacted>', out)
    return out[:800]


def _ssh84_exec(cmd: str, timeout: int = 20) -> str:
    import paramiko
    ssh_pw = os.environ.get('MED_AUDIT_SSH_PASSWORD', '')
    if not ssh_pw:
        raise GuardError('MED_AUDIT_SSH_PASSWORD 未设置，84 通道不可用')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('10.10.8.84', port=40022, username='root', password=ssh_pw, timeout=CONNECT_TIMEOUT_S)
    try:
        _, out, err = ssh.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        text = out.read().decode(errors='ignore')
        if rc:
            raise GuardError('84 只读命令失败 rc=%d: %s' % (rc, scrub_error(err.read().decode(errors='ignore'), [ssh_pw])))
        return text
    finally:
        ssh.close()


def resolve_credential(spec: dict) -> tuple[str, bool]:
    """返回 (口令或占位, 是否需远端解析)。绝不打印。
    kind=env / app_config / container_env（本地取回后用）/ container_config（仅 ssh84，容器内解密，口令不出容器）。"""
    kind = spec.get('type')
    if kind == 'env':
        var = spec.get('name', '')
        val = os.environ.get(var, '')
        if not val:
            raise GuardError('凭据缺失：环境变量 %s 未设置（BLOCKED，不穷举）' % var)
        return val, False
    if kind == 'app_config':
        sys.path.insert(0, REPO_ROOT)
        from app.config import decrypt_value  # 延迟导入，仅解密单一键，不触发 load_config
        cfg = json.load(open(os.path.join(REPO_ROOT, 'config', 'config.json'), encoding='utf-8'))
        node = cfg
        for part in spec['section'].split('.'):
            node = node[part]
        return decrypt_value(node[spec.get('key', 'password_enc')]), False
    if kind == 'container_env':
        # 从 84 容器环境取回既有口令（只读 docker exec env；不回显、不落盘）
        var = spec.get('name', '')
        text = _ssh84_exec("docker exec med-audit sh -c 'printf %%s \"$%s\"'" % var)
        val = text.strip('\r\n')
        if not val:
            raise GuardError('容器环境变量 %s 为空/不存在（BLOCKED）' % var)
        return val, False
    if kind == 'container_config':
        if spec.get('section') != 'emr_vastbase':
            raise GuardError('container_config 目前仅允许 emr_vastbase 段（最小授权）')
        return '<resolved-in-container>', True
    if kind == 'container_env_oracle':
        # 216 Oracle：本机直连被 ORA-12537 关闭（2026-09-28 实测），容器内 cx_Oracle 为既有通道；
        # 口令在容器 env 内解析，不出容器
        return '<resolved-in-container>', True
    if kind == 'none':
        return '', False  # sqlite 等无凭据源
    if kind == 'literal':
        raise GuardError('registry 禁止存明文口令（kind=literal 被拒绝）')
    raise GuardError('未知凭据类型: %r' % kind)


# ---------------------------------------------------------------- 本地连接（带保护链）
def connect_postgresql_local(src: dict, password: str):
    import psycopg2  # 本机可能缺 DLL；由调用方决定走 ssh84 转运
    conn = psycopg2.connect(host=src['host'], port=int(src['port']), dbname=src['database'],
                            user=src['user'], password=password, connect_timeout=CONNECT_TIMEOUT_S,
                            options='-c default_transaction_read_only=on')
    cur = conn.cursor()
    cur.execute('SET statement_timeout = %d' % STATEMENT_TIMEOUT_MS)
    cur.execute('SET lock_timeout = %d' % LOCK_TIMEOUT_MS)
    cur.execute('show transaction_read_only')
    state = cur.fetchone()[0]
    if str(state).lower() != 'on':
        raise GuardError('transaction_read_only 未确认（得到 %r），拒绝继续' % state)
    return conn, ['default_transaction_read_only=on(connect-options)', 'statement_timeout=15s',
                  'lock_timeout=2s', 'show transaction_read_only=on']


def connect_mysql_local(src: dict, password: str):
    import pymysql
    conn = pymysql.connect(host=src['host'], port=int(src['port']), user=src['user'],
                           password=password, database=src.get('database') or None,
                           connect_timeout=CONNECT_TIMEOUT_S,
                           read_timeout=STATEMENT_TIMEOUT_MS // 1000 + 5,
                           write_timeout=STATEMENT_TIMEOUT_MS // 1000 + 5)
    cur = conn.cursor()
    cur.execute('SET SESSION TRANSACTION READ ONLY')
    cur.execute('SELECT @@session.transaction_read_only')
    state = cur.fetchone()[0]
    if int(state) != 1:
        raise GuardError('MySQL 事务只读未确认（得到 %r）' % state)
    guards = ['SET SESSION TRANSACTION READ ONLY', 'SELECT @@session.transaction_read_only=1']
    try:
        cur.execute('SET SESSION max_execution_time = %d' % STATEMENT_TIMEOUT_MS)
        guards.append('max_execution_time=15000(8.0+)')
    except Exception:
        guards.append('max_execution_time 不支持（仅 read_timeout 兜底）')
    return conn, guards


def _stage_oracle_client_ascii(lib_dir_rel: str) -> str:
    """oracledb init_oracle_client 在 Windows 非 ASCII 路径下报 UnicodeDecodeError；
    将捆绑 Instant Client 复制到 %TEMP% ASCII 目录后初始化（本机实测修正，仅一次）。"""
    src = os.path.abspath(os.path.join(REPO_ROOT, lib_dir_rel))
    dst = os.path.join(os.environ.get('TEMP', '/tmp'), 'oraclient_ascii_staged')
    if not os.path.isdir(dst) or not any(f.endswith('.dll') for f in os.listdir(dst)):
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(src):
            if f.lower().endswith(('.dll', '.sym', '.lis')):
                try:
                    shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
                except OSError:
                    pass
    return dst


def connect_oracle_local(src: dict, password: str):
    import oracledb
    if src.get('oracle_thick_client_dir'):
        try:
            oracledb.init_oracle_client(
                lib_dir=_stage_oracle_client_ascii(src['oracle_thick_client_dir']))
        except Exception as exc:  # 已初始化（重复调用）可忽略
            if 'DPI-1047' in str(exc) or 'already' not in str(exc).lower():
                if 'already' not in str(exc).lower():
                    raise GuardError('Instant Client 初始化失败: %s' % scrub_error(str(exc), []))
    dsn = oracledb.makedsn(src['host'], int(src['port']),
                           service_name=src.get('service_name') or src.get('database'))
    conn = oracledb.connect(user=src['user'], password=password, dsn=dsn,
                            tcp_connect_timeout=CONNECT_TIMEOUT_S)
    conn.call_timeout = STATEMENT_TIMEOUT_MS  # 驱动级调用超时（毫秒，连接属性而非 connect 参数）
    cur = conn.cursor()
    cur.execute('SET TRANSACTION READ ONLY')  # 事务首语句，锁定只读（驱动 call_timeout 同时生效）
    return conn, ['SET TRANSACTION READ ONLY(事务首语句)', 'call_timeout=15000ms']


def connect_mssql_local(src: dict, password: str):
    import pyodbc
    # ApplicationIntent=ReadOnly 不作为权限隔离（057 D0 口径）；仅查询超时+模板白名单防护，
    # 台账未证明 SELECT-only 账号的源必须在 registry 保持 enabled=false。
    cs = ('DRIVER={ODBC Driver 17 for SQL Server};SERVER=%s,%s;DATABASE=%s;UID=%s;PWD=%s;'
          'TrustServerCertificate=yes;' % (src['host'], src['port'], src.get('database') or 'master',
                                           src['user'], password))
    conn = pyodbc.connect(cs, timeout=CONNECT_TIMEOUT_S)
    conn.timeout = STATEMENT_TIMEOUT_MS // 1000  # 查询超时（秒）
    cur = conn.cursor()
    cur.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
    return conn, ['pyodbc query timeout=15s', 'READ COMMITTED（注：非只读事务，依赖账号 SELECT-only 证明）']


def connect_sqlite_local(src: dict, password: str):
    import sqlite3
    path = os.path.abspath(os.path.join(REPO_ROOT, src['path']))
    if not os.path.isfile(path):
        raise GuardError('SQLite 文件不存在: %s' % src['path'])
    conn = sqlite3.connect('file:%s?mode=ro' % path.replace('?', '%3f').replace('#', '%23'),
                           uri=True, timeout=LOCK_TIMEOUT_MS / 1000.0)
    cur = conn.cursor()
    cur.execute('pragma query_only = on')
    cur.execute('pragma query_only')
    if cur.fetchone()[0] != 1:
        raise GuardError('sqlite query_only 未确认')
    return conn, ['uri mode=ro', 'pragma query_only=on']


LOCAL_FACTORIES = {'postgresql': connect_postgresql_local, 'mysql': connect_mysql_local,
                   'oracle': connect_oracle_local, 'mssql': connect_mssql_local,
                   'sqlite': connect_sqlite_local}


# ---------------------------------------------------------------- 84 容器转运（PostgreSQL/Vastbase）
REMOTE_RUNNER_TEMPLATE = r'''
import sys, json
payload = json.loads(sys.stdin.read())
cred = payload.get("credential") or {}
if cred.get("type") == "container_config":
    sys.path.insert(0, "/app")
    import json as _json
    from app.config import decrypt_value
    cfg = _json.load(open("/app/config/config.json"))
    password = decrypt_value(cfg[cred["section"]][cred.get("key", "password_enc")])
elif cred.get("type") == "env":
    import os
    password = os.environ.get(cred.get("name", ""), "")
    if not password:
        raise RuntimeError("container env " + cred.get("name", "") + " empty")
else:
    password = payload["password"]
guards = []
c = payload["connect"]
if payload.get("dialect") == "oracle":
    import cx_Oracle
    dsn = cx_Oracle.makedsn(c["host"], int(c["port"]), service_name=c.get("service_name") or c["database"])
    conn = cx_Oracle.connect(user=c["user"], password=password, dsn=dsn)
    conn.callTimeout = %d
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    guards = ["SET TRANSACTION READ ONLY(事务首语句)", "callTimeout=15000ms"]
    class _Cur:
        def __init__(self, c):
            self._c = c
        def execute(self, sql, params=None):
            self._c.execute(sql, params or {})
        @property
        def description(self):
            return self._c.description
        def fetchmany(self, n):
            return self._c.fetchmany(numRows=n)
    cur = _Cur(cur)
else:
    import psycopg2
    conn = psycopg2.connect(host=c["host"], port=c["port"], dbname=c["database"], user=c["user"],
                            password=password, connect_timeout=10,
                            options="-c default_transaction_read_only=on")
    cur = conn.cursor()
    cur.execute("SAVEPOINT guard_timeouts")
    try:
        cur.execute("SET statement_timeout = %d")
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT guard_timeouts")
        st = "statement_timeout 不支持"
    else:
        st = "statement_timeout=15s"
    try:
        cur.execute("SET lock_timeout = %d")
        lt = "lock_timeout=2s"
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT guard_timeouts")
        try:
            cur.execute("SET lockwait_timeout = %d")
            lt = "lockwait_timeout=2s(openGauss)"
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT guard_timeouts")
            lt = "lock等待超时不支持（statement_timeout 兜底）"
    cur.execute("show transaction_read_only")
    state = cur.fetchone()[0]
    if str(state).lower() != "on":
        raise RuntimeError("transaction_read_only=" + str(state) + " not confirmed")
    guards = ["default_transaction_read_only=on", st, lt, "show transaction_read_only=on"]
out = []
try:
    cur_ = cur
    for q in payload["queries"]:
        try:
            cur_.execute("SAVEPOINT q_guard")
            cur_.execute(q["sql"], q.get("params") or None)
            cols = [d[0] for d in cur_.description] if cur_.description else []
            cap = int((q.get("params") or {}).get("cap", %d))
            rows = []
            while len(rows) < cap:
                page = cur_.fetchmany(%d)
                if not page:
                    break
                rows.extend(page)
            rows = rows[:cap]
            out.append({"name": q["name"], "ok": True, "columns": cols,
                        "rows": [[str(v) for v in r] for r in rows]})
        except Exception as exc:
            out.append({"name": q["name"], "ok": False, "error": str(exc).splitlines()[0][:300]})
            try:
                cur_.execute("ROLLBACK TO SAVEPOINT q_guard")
            except Exception:
                pass
finally:
    try:
        conn.rollback()
    finally:
        conn.close()
print(json.dumps({"guards": guards + ["rollback+close"], "results": out}, ensure_ascii=False))
'''
REMOTE_RUNNER = (REMOTE_RUNNER_TEMPLATE
                 % (STATEMENT_TIMEOUT_MS, STATEMENT_TIMEOUT_MS, LOCK_TIMEOUT_MS, LOCK_TIMEOUT_MS, METADATA_PAGE, METADATA_PAGE))


def run_via_ssh84(src: dict, password: str, queries: list[dict], credential: dict | None = None,
                  dialect: str = 'postgresql'):
    import base64
    import paramiko
    import shlex
    ssh_pw = os.environ.get('MED_AUDIT_SSH_PASSWORD', '')
    if not ssh_pw:
        raise GuardError('MED_AUDIT_SSH_PASSWORD 未设置，84 转运不可用')
    payload = {'connect': {'host': src['host'], 'port': int(src['port']), 'database': src['database'],
                           'service_name': src.get('service_name') or src.get('database'),
                           'user': src['user']},
               'password': password,
               'queries': queries,
               'dialect': dialect,
               'credential': credential or {'type': 'inline'}}
    if credential and credential.get('type') == 'container_env_oracle':
        # 远端以容器 env 解析（口令不出容器）
        payload['credential'] = {'type': 'env', 'name': 'APP_ORACLE_PASSWORD'}
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('10.10.8.84', port=40022, username='root', password=ssh_pw, timeout=CONNECT_TIMEOUT_S)
    try:
        code = 'import base64;exec(base64.b64decode(%r))' % base64.b64encode(
            REMOTE_RUNNER.encode()).decode()
        cmd = 'docker exec -i med-audit python -B -c ' + shlex.quote(code)
        stdin, stdout, stderr = ssh.exec_command(
            cmd, timeout=60 + STATEMENT_TIMEOUT_MS // 1000 * max(1, len(queries)))
        stdin.write(json.dumps(payload, ensure_ascii=False))
        stdin.flush()
        stdin.channel.shutdown_write()
        err = stderr.read().decode(errors='ignore')
        text = stdout.read().decode(errors='ignore')
        rc = stdout.channel.recv_exit_status()
        if rc:
            raise GuardError('84 容器执行失败 rc=%d: %s' % (rc, scrub_error(err, [password, ssh_pw])))
        return json.loads(text.strip().splitlines()[-1])
    finally:
        ssh.close()


# ---------------------------------------------------------------- 执行器
def build_queries(src: dict, group: str, params: dict) -> list[dict]:
    keys = GROUPS.get(group)
    if not keys:
        raise GuardError('未知查询组: %s（可用 %s）' % (group, sorted(GROUPS)))
    applicable = [(key, TEMPLATES[key]) for key in keys if src['dialect'] in TEMPLATES[key]['dialects']]
    if not applicable:
        raise GuardError('组 %s 在方言 %s 下无模板' % (group, src['dialect']))
    if len(applicable) > MAX_QUERIES_PER_RUN:
        raise GuardError('单轮查询数 %d 超预算 %d' % (len(applicable), MAX_QUERIES_PER_RUN))
    out = []
    for key, tpl in applicable:
        bind = {}
        for p in tpl['params']:
            if p == 'cap':
                bind[p] = min(int(params.get('cap', METADATA_PAGE)), MAX_OBJECTS_PER_SOURCE)
            elif p in params:
                bind[p] = validate_param(p, str(params[p]))
            else:
                raise GuardError('模板 %s 缺参数 %s' % (key, p))
        out.append({'name': key, 'sql': tpl['sql'], 'params': bind,
                    'param_order': list(tpl['params'])})
    return out


def run_local(src: dict, password: str, queries: list[dict], conn_factory=None):
    factory = conn_factory or LOCAL_FACTORIES.get(src['dialect'])
    if not factory:
        raise GuardError('方言 %s 无本地工厂' % src['dialect'])
    conn = None
    guards: list[str] = []
    results = []
    try:
        conn, guards = factory(src, password)
        cur = conn.cursor()
        for q in queries:
            t0 = time.time()
            try:
                if src['dialect'] == 'oracle':  # noqa: SIM108（本地路径仅备用，现网走 ssh84）
                    bind = {k: v for k, v in q['params'].items()}
                    cur.execute(q['sql'], bind if bind else None)
                elif src['dialect'] in ('postgresql', 'mysql'):
                    cur.execute(q['sql'], q['params'] or None)
                else:  # mssql / sqlite：按注册参数序位置绑定
                    ordered = [q['params'][p] for p in q['param_order']]
                    if ordered:
                        cur.execute(q['sql'], ordered)
                    else:
                        cur.execute(q['sql'])
                cols = [d[0] for d in cur.description] if cur.description else []
                cap = int(q['params'].get('cap', METADATA_PAGE))
                rows = []
                while len(rows) < cap:
                    page = cur.fetchmany(METADATA_PAGE)
                    if not page:
                        break
                    rows.extend(page)
                rows = rows[:cap]
                results.append({'name': q['name'], 'ok': True, 'ms': int((time.time() - t0) * 1000),
                                'columns': cols,
                                'rows': [[sanitize_cell(c, v) for c, v in zip(cols, r)] for r in rows]})
            except Exception as exc:  # 单条失败不掩盖其余；不自动重试
                results.append({'name': q['name'], 'ok': False, 'ms': int((time.time() - t0) * 1000),
                                'error': scrub_error(str(exc), [password])})
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    return {'guards': guards + ['rollback+close'], 'results': results}


def _sanitize_remote(result: dict) -> dict:
    """远端容器返回的行未过本地脱敏；落盘前统一套用本地列级脱敏/截断。"""
    if not result.get('ok'):
        return result
    cols = result.get('columns') or []
    rows = result.get('rows') or []
    result['rows'] = [[sanitize_cell(c, v) for c, v in zip(cols, row)] for row in rows]
    return result


def load_registry() -> dict:
    if not os.path.isfile(REGISTRY_PATH):
        raise GuardError('registry 不存在: %s（先执行 D1 生成）' % REGISTRY_PATH)
    return json.load(open(REGISTRY_PATH, encoding='utf-8'))


def main(argv=None):
    ap = argparse.ArgumentParser(description='数据库只读探索工具（057 D0）')
    ap.add_argument('--list-sources', action='store_true', help='列出 registry 中的源')
    ap.add_argument('--show-source', metavar='ID')
    ap.add_argument('--dry-run', action='store_true', help='不连接，打印将执行的模板与参数')
    ap.add_argument('--source', metavar='ID')
    ap.add_argument('--group', choices=sorted(GROUPS))
    ap.add_argument('--param', action='append', default=[], help='k=v 模板参数（仅标识符白名单）')
    ap.add_argument('--transport', choices=('auto', 'local', 'ssh84'), default='auto')
    args = ap.parse_args(argv)

    if args.list_sources or args.show_source:
        reg = load_registry()
        for s in reg.get('sources', []):
            if args.list_sources:
                print('%-18s %-11s %-34s %s' % (
                    s['source_id'], s['dialect'],
                    '%s:%s/%s' % (s.get('host', s.get('path', '')), s.get('port', ''),
                                  s.get('database', '')), s.get('status', '')))
            elif args.show_source == s['source_id']:
                print(json.dumps({k: v for k, v in s.items() if 'password' not in k.lower()},
                                 ensure_ascii=False, indent=1))
        return 0

    if not args.source or not args.group:
        ap.error('--source 与 --group 必填（或使用 --list-sources / --dry-run）')
    reg = load_registry()
    src = next((s for s in reg.get('sources', []) if s['source_id'] == args.source), None)
    if src is None:
        raise GuardError('未知源: %s' % args.source)
    if not src.get('enabled', False):
        raise GuardError('源 %s 未启用（状态 %s）——按 D0 规则拒绝连接' % (args.source, src.get('status', '')))

    params = {}
    for kv in args.param:
        k, _, v = kv.partition('=')
        params[k] = v
    queries = build_queries(src, args.group, params)

    if args.dry_run:
        print(json.dumps({'source': args.source, 'dialect': src['dialect'], 'group': args.group,
                          'queries': [{'name': q['name'], 'params': q['params'], 'sql': q['sql']}
                                      for q in queries]}, ensure_ascii=False, indent=1))
        return 0

    cred_spec = src.get('credential') or {}
    password, remote_resolve = resolve_credential(cred_spec)
    transport = args.transport
    if transport == 'auto':
        transport = 'ssh84' if src.get('ssh84_transport', True) and src['dialect'] in (
            'postgresql', 'oracle') else 'local'
    if transport == 'ssh84':
        def _binds_for(q):
            # 只传 SQL 中实际出现的绑定名（多余键在 cx_Oracle 会 ORA-01745/ORA-01036）
            used = set(re.findall(r'(?<!:):([A-Za-z_][A-Za-z0-9_]*)', q['sql']))
            if src['dialect'] == 'oracle':
                return {k: v for k, v in q['params'].items() if k in used}
            return q['params'] or None
        payload = run_via_ssh84(src, password, [{'name': q['name'], 'sql': q['sql'],
                                                 'params': _binds_for(q)} for q in queries],
                                credential=cred_spec if remote_resolve else None,
                                dialect=src['dialect'])
    else:
        payload = run_local(src, password, queries)

    stamp = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    out_path = os.path.join(OUT_DIR, args.source, '%s-%s.json' % (args.group, stamp))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = {'source_id': args.source, 'dialect': src['dialect'], 'group': args.group,
           'transport': transport, 'ts': stamp, 'guards': payload.get('guards', []),
           'results': [_sanitize_remote(r) for r in payload.get('results', [])],
           'budgets': {'statement_ms': STATEMENT_TIMEOUT_MS, 'lock_ms': LOCK_TIMEOUT_MS,
                       'page': METADATA_PAGE, 'queries': len(queries)}}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in doc['results'] if r.get('ok'))
    print('%s: %d/%d 模板成功 -> %s' % (args.source, ok, len(doc['results']), out_path))
    for r in doc['results']:
        print('  [%s] %s %s' % ('OK' if r.get('ok') else 'FAIL', r['name'], r.get('error', '')[:120]))
    return 0


if __name__ == '__main__':
    sys.exit(main())

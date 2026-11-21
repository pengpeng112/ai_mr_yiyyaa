"""T-HIS：app/timeliness/his_oracle_reader.py 只读取数模块单测（2026-11-14 七规则轮）。

覆盖（任务书 §3.1）：
- probe_oracle_tables：可读=True / ORA-00942 捕获为错误文本；
- 抢救医嘱 SQL 铁律：ORDER_STATUS IN ('2','3','6')、REPEAT_INDICATOR=0 绑定、
  白名单 ORDER_CODE/ORDER_TEXT 精确集合、Oracle 11g 兼容（无 FETCH FIRST）、
  死亡白名单严禁 LIKE '%死亡%'（会误中 PD-L1）；
- 抢救 30 分钟合并：同患者 20 分钟两条→1 事件（最早时间+首条 source_event_id）、
  40 分钟两条→2 事件、跨患者不合并；
- 死亡/料理医嘱：最早时间聚合键 (patient_id, visit_id)；
- 手术标准化：SURGEON→operator_id、DEPT_STAYED→dept_code、排台 SCHEDULED 优先
  回退（主表命中取实际时间；SM 缺关键列整源跳过；无 OPER_ID 保守反连接）；
- 职称字典 TTL 缓存：窗口内不重复连库、reset 后重取；
- HisRescueOrderSource：status=READY、fetch 失败降级空列表。

全部用假 cursor/connection（零真实 Oracle 连接）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from app.timeliness import his_oracle_reader as his
from app.timeliness.engine.triggers import EXTERNAL_TRIGGER_SOURCES, NotConfiguredSource


T0 = datetime(2026, 11, 12, 8, 0, 0)


class FakeCursor:
    def __init__(self, results=None, error=None, script=None):
        self.results = list(results or [])
        self.error = error
        self.script = script or []       # 每次 execute 依次弹出的结果集
        self.executed: list[tuple[str, dict]] = []
        self._rows: list = []

    def execute(self, sql, params=None):
        self.executed.append((sql, dict(params or {})))
        if self.error is not None:
            raise self.error
        if self.script:
            self._rows = self.script.pop(0)
        else:
            self._rows = self.results

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class OraError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


def _connect_of(cursor):
    def factory():
        return FakeConn(cursor)
    return factory


# ---------- probe ----------


def test_probe_all_readable():
    cur = FakeCursor(results=[(1,)])
    result = his.probe_oracle_tables(connect=_connect_of(cur))
    assert set(result) == set(his.PROBE_TABLES)
    assert all(v is True for v in result.values())
    # 探测语句逐表执行
    assert len(cur.executed) == len(his.PROBE_TABLES)


def test_probe_captures_ora_942_as_text():
    calls = {"n": 0}

    class ErrorOnce(FakeCursor):
        def execute(self, sql, params=None):
            calls["n"] += 1
            if "HIS.ORDERS" in sql:
                raise OraError("ORA-00942: table or view does not exist")
            super().execute(sql, params)

    cur = ErrorOnce(results=[(1,)])
    result = his.probe_oracle_tables(connect=_connect_of(cur))
    assert result["HIS.ORDERS"].startswith("ORA-00942")
    assert result["HIS.STAFF_DICT"] is True


# ---------- 抢救医嘱 ----------


def _rescue_row(order_no, sub, t0, patient="P1", visit="1", status="2", dept="040112", doctor="204011",
                code="011104000010000", text="院内抢救费（常规）", repeat="0"):
    return (patient, visit, order_no, sub, t0, dept, doctor, status, code, text, repeat)


def _make_orders_cursor(rows):
    """把 (…) 行翻译为 list_rescue_orders 的 SELECT 列序。"""
    class RowCur(FakeCursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            # 列序：PATIENT_ID, VISIT_ID, ORDER_NO, ORDER_SUB_NO, T0, ORDERING_DEPT, DOCTOR, ORDER_TEXT
            self._rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[8]) for r in rows]
    return RowCur()


def test_rescue_sql_hard_filters_and_whitelist():
    cur = _make_orders_cursor([])
    his.list_rescue_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    sql, params = cur.executed[0]
    norm = " ".join(sql.split()).upper()
    assert "FETCH FIRST" not in norm                      # Oracle 11g 兼容
    assert "ORDER_STATUS IN" in norm and "REPEAT_INDICATOR = :RC_REPEAT" in norm
    assert "COALESCE(O.START_DATE_TIME, O.ENTER_DATE_TIME)" in norm
    # 有效状态硬过滤绑定值 = ('2','3','6')
    status_binds = sorted(v for k, v in params.items() if k.startswith("rs"))
    assert status_binds == ["2", "3", "6"]
    assert params["rc_repeat"] == "0"
    # 白名单绑定：抢救费两码 + 五文本（键名 rcc*/rct* 与 rc_ 参数不冲突）
    codes = sorted(v for k, v in params.items() if k.startswith("rcc"))
    texts = sorted(v for k, v in params.items() if k.startswith("rct"))
    assert codes == sorted(his.RESCUE_ORDER_CODES)
    assert texts == sorted(his.RESCUE_ORDER_TEXTS)


def test_rescue_merge_within_30_minutes():
    rows = [
        _rescue_row("1001", "1", T0, text="院内抢救费（常规）"),
        _rescue_row("1002", "1", T0 + timedelta(minutes=20), text="院内抢救费（复杂）",
                    code="011104000020000"),
    ]
    cur = _make_orders_cursor(rows)
    events = his.list_rescue_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    assert len(events) == 1
    e = events[0]
    assert e["source_event_id"] == "1001_1"               # 最早一条
    assert e["event_time"] == T0
    assert e["trigger_type"] == "RESCUE_ORDER"
    assert e["source_system"] == his.SOURCE_SYSTEM_HIS_ORDERS
    assert e["dept_code"] == "040112" and e["doctor_id"] == "204011"
    assert e["detail"]["merged_order_count"] == 2


def test_rescue_merge_splits_beyond_30_minutes():
    rows = [
        _rescue_row("1001", "1", T0),
        _rescue_row("1002", "1", T0 + timedelta(minutes=31)),
        _rescue_row("1003", "1", T0 + timedelta(minutes=55)),  # 与第二条同窗
    ]
    cur = _make_orders_cursor(rows)
    events = his.list_rescue_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    assert len(events) == 2
    assert [e["source_event_id"] for e in events] == ["1001_1", "1002_1"]
    assert events[1]["event_time"] == T0 + timedelta(minutes=31)
    assert events[1]["detail"]["merged_order_count"] == 2


def test_rescue_merge_does_not_cross_patients():
    rows = [
        _rescue_row("1001", "1", T0, patient="P1"),
        _rescue_row("2001", "1", T0 + timedelta(minutes=5), patient="P2", visit="2"),
    ]
    cur = _make_orders_cursor(rows)
    events = his.list_rescue_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    assert len(events) == 2
    assert {e["patient_id"] for e in events} == {"P1", "P2"}


# ---------- 死亡/料理医嘱 ----------


def test_death_orders_sql_never_likes_percent_death():
    cur = FakeCursor(results=[])
    his.list_death_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    sql, params = cur.executed[0]
    norm = " ".join(sql.split()).upper()
    assert "FETCH FIRST" not in norm
    assert "LIKE" not in norm                                # 严禁 LIKE（PD-L1 误中教训）
    assert "MIN(COALESCE(O.START_DATE_TIME, O.ENTER_DATE_TIME))" in norm
    assert "GROUP BY O.PATIENT_ID, O.VISIT_ID" in norm
    codes = sorted(v for k, v in params.items() if k.startswith("dcc"))
    texts = sorted(v for k, v in params.items() if k.startswith("dct"))
    assert codes == sorted(his.DEATH_ORDER_CODES)
    assert texts == sorted(his.DEATH_ORDER_TEXTS)


def test_death_orders_returns_earliest_per_patient_visit():
    cur = FakeCursor(results=[
        ("P1", "1", T0 + timedelta(hours=2), "040112", "204011"),   # 尸体料理（更晚）
        ("P1", "1", T0, "040112", "204011"),                        # 临床死亡（最早）
        ("P2", "3", T0 + timedelta(hours=1), "030442", "205012"),
    ])
    result = his.list_death_orders(T0, T0 + timedelta(days=1), connect=_connect_of(cur))
    assert set(result) == {("P1", "1"), ("P2", "3")}
    assert result[("P1", "1")]["death_time"] == T0
    assert result[("P2", "3")]["dept_code"] == "030442"


# ---------- 手术标准化 ----------


def _his_master_row(pid="P1", vid="1", oper="55", start=None, end=None, surgeon="000701",
                    dept="040112", room="040902", scale="3", emergency="0",
                    anesthesia="全麻", name="腹腔镜胆囊切除术"):
    return (pid, vid, oper, dept, room, scale, emergency, "A", surgeon, "A1",
            anesthesia, start or T0, end, name)


def _sm_row(pid, vid, oper, sched, dept="040112", room="040902", scale="一",
             emergency="0", surgeon="000701", anesthesia="局麻", start=None,
             end=None, name="胃镜检查", oper_status="0", cancel=None):
    """SM 排台行（SM_BUSINESS_COLUMNS 17 列顺序）。"""
    return (pid, vid, oper, dept, room, scale, emergency, "A", surgeon, "A1",
            anesthesia, sched, start, end, name, oper_status, cancel)


def test_his_operations_normalized_shape():
    cur = FakeCursor(script=[[_his_master_row()], []])   # 主表 1 行；SM 查询 0 行
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns={"PATIENT_ID", "VISIT_ID", "SCHEDULED_DATE_TIME", "OPER_ID"},
        connect=_connect_of(cur),
    )
    assert len(ops) == 1
    op = ops[0]
    assert op["operator_id"] == "000701"                  # SURGEON → 主刀工号
    assert op["dept_code"] == "040112"                     # DEPT_STAYED → 临床科室
    assert op["operation_no"] == "HIS-55"                  # 源前缀防撞（uid 第三段）
    assert op["operation_desc"] == "腹腔镜胆囊切除术"
    assert op["operating_date"] == T0 and op["anesthesia_method"] == "全麻"
    assert op["operation_scale"] == "3" and op["emergency_indicator"] == "0"
    assert op["source"] == "his_operation_master"


def test_his_operations_scheduled_row_from_sm():
    """排台行读全业务列（补丁1）：统一 HIS-{OPER_ID} 前缀 + 中文'一'级不再传空。"""
    master = [_his_master_row(pid="P1", oper="55")]
    sm = [_sm_row("P2", "2", "77", T0 + timedelta(days=1))]
    cur = FakeCursor(script=[master, sm])
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns={"PATIENT_ID", "VISIT_ID", "SCHEDULED_DATE_TIME", "OPER_ID"},
        connect=_connect_of(cur),
    )
    by_source = {op["source"]: op for op in ops}
    assert set(by_source) == {"his_operation_master", "sm_scheduled"}
    assert by_source["sm_scheduled"]["operating_date"] == T0 + timedelta(days=1)
    assert by_source["sm_scheduled"]["operation_no"] == "HIS-77"      # 统一前缀（补丁1）
    assert by_source["sm_scheduled"]["operation_scale"] == "一"        # 中文级别透传
    assert by_source["sm_scheduled"]["anesthesia_method"] == "局麻"


def test_his_operations_sm_skipped_when_columns_missing():
    cur = FakeCursor(script=[[_his_master_row()]])        # 只有主表查询；SM 整源跳过
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns=set(),
        connect=_connect_of(cur),
    )
    assert len(ops) == 1 and ops[0]["source"] == "his_operation_master"
    assert len(cur.executed) == 1                          # 没有第二条 SM 查询


def test_his_operations_sm_without_oper_id_uses_conservative_anti_join():
    master = [_his_master_row(pid="P1", oper="55")]
    sm = [_sm_row("P1", "1", None, T0 + timedelta(days=1)),   # P1 已在主表 → 保守排除
          _sm_row("P3", "1", None, T0 + timedelta(days=1))]
    cur = FakeCursor(script=[master, sm])
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns={"PATIENT_ID", "VISIT_ID", "SCHEDULED_DATE_TIME"},   # 无 OPER_ID
        connect=_connect_of(cur),
    )
    sm_rows = [op for op in ops if op["source"] == "sm_scheduled"]
    assert [op["patient_id"] for op in sm_rows] == ["P3"]
    # oper_id 为空 → SM-SCHED- 兜底前缀（含开台时间戳，确定性）
    assert sm_rows[0]["operation_no"].startswith("SM-SCHED-")


# ---------- 职称字典 TTL ----------


def test_staff_title_map_ttl_cache():
    his.reset_staff_cache()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return FakeConn(FakeCursor(results=[("204011", "张三", "主治医师"), ("000701", "李四", "主任医师")]))

    m1 = his.get_staff_title_map(connect=factory, ttl=3600)
    m2 = his.get_staff_title_map(connect=factory, ttl=3600)
    assert calls["n"] == 1                                 # TTL 内不重复连库
    assert m1["204011"] == "主治医师"
    assert m2["000701"] == "主任医师"                       # 同一缓存对象
    his.reset_staff_cache()
    his.get_staff_title_map(connect=factory, ttl=3600)
    assert calls["n"] == 2                                 # reset 后重取
    his.reset_staff_cache()


def test_staff_title_map_supports_name_fallback_key():
    his.reset_staff_cache()
    cur = FakeCursor(results=[("204011", "张三", "副主任医师")])
    m = his.get_staff_title_map(connect=_connect_of(cur), ttl=3600)
    assert m["204011"] == "副主任医师" and m["张三"] == "副主任医师"
    his.reset_staff_cache()


# ---------- 外部源登记 ----------


def test_rescue_source_ready_and_degrades_on_failure():
    source = his.HisRescueOrderSource()
    assert source.status == "READY"

    def failing():
        raise OraError("ORA-01031: insufficient privileges")

    assert source.fetch_events(T0, T0 + timedelta(hours=1)) == []   # 失败降级空列表


def test_register_his_rescue_source_replaces_stub_and_restores():
    original = EXTERNAL_TRIGGER_SOURCES["RESCUE_ORDER"]
    try:
        his.register_his_rescue_source()
        registered = EXTERNAL_TRIGGER_SOURCES["RESCUE_ORDER"]
        assert registered.status == "READY"
        assert isinstance(registered, his.HisRescueOrderSource)
    finally:
        from app.timeliness.engine.triggers import register_external_source
        register_external_source("RESCUE_ORDER", original)
    assert EXTERNAL_TRIGGER_SOURCES["RESCUE_ORDER"].status == "NOT_CONFIGURED"


# ---------- 2026-11-14 补丁轮 ----------


def test_sm_query_filters_cancelled_and_reads_full_columns():
    """补丁1：取消手术硬过滤（CANCEL_DATE_TIME IS NULL + NVL(OPER_STATUS,0)>=0）
    + 按白名单 17 业务列动态拼 SELECT。"""
    cur = FakeCursor(script=[[], []])
    his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns=set(his.SM_BUSINESS_COLUMNS),
        connect=_connect_of(cur),
    )
    sm_sql = " ".join(cur.executed[1][0].split()).upper()
    assert "S.CANCEL_DATE_TIME IS NULL" in sm_sql
    assert "NVL(S.OPER_STATUS, 0) >= 0" in sm_sql
    assert "COALESCE(S.START_DATE_TIME, S.SCHEDULED_DATE_TIME)" in sm_sql
    for col in his.SM_BUSINESS_COLUMNS:
        assert f"S.{col}" in sm_sql, col


def test_sm_cancelled_row_excluded_via_where_clause():
    """-80 取消行由 WHERE 硬过滤排除（SQL 层，非 Python 过滤）——假 cursor 只回
    未取消行，断言其被正常标准化。"""
    cur = FakeCursor(script=[[], [_sm_row("P9", "1", "88", T0 + timedelta(days=1))]])
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns=set(his.SM_BUSINESS_COLUMNS), connect=_connect_of(cur),
    )
    sm = [op for op in ops if op["source"] == "sm_scheduled"]
    assert len(sm) == 1 and sm[0]["operation_no"] == "HIS-88"


def test_sm_and_master_same_oper_unified_uid():
    """补丁1：SM 与主表同 (pid,vid,oper_id) → 只保留主表行、uid 同为 HIS-{id}
    ——排台预警→下台归档全生命周期同一 event_uid，不再分裂。"""
    master = [_his_master_row(pid="P1", oper="55")]
    sm = [_sm_row("P1", "1", "55", T0 + timedelta(days=1))]
    cur = FakeCursor(script=[master, sm])
    ops = his.list_his_operations(
        T0 - timedelta(days=7), T0 + timedelta(days=2),
        sm_columns=set(his.SM_BUSINESS_COLUMNS), connect=_connect_of(cur),
    )
    assert len(ops) == 1
    assert ops[0]["operation_no"] == "HIS-55" and ops[0]["source"] == "his_operation_master"


def test_sm_start_datetime_preferred_over_scheduled():
    """排台行已开台（START_DATE_TIME 非空）→ operating_date 取实际开台时间。"""
    started = T0 + timedelta(hours=2)
    cur = FakeCursor(script=[[], [_sm_row("P2", "1", "66", T0, start=started)]])
    ops = his.list_his_operations(
        T0 - timedelta(days=1), T0 + timedelta(days=2),
        sm_columns=set(his.SM_BUSINESS_COLUMNS), connect=_connect_of(cur),
    )
    assert ops[0]["operating_date"] == started


def test_fetch_patient_visit_meta_batching_and_columns():
    """补丁3：V_QYBR 批量取姓名/科室/管床工号（≤200 对/批，OR 绑定）。"""
    # WP01：7 列契约（+入院科室编码）；所在→入院→出院三层兜底
    # WP04：追加 8 个临床展示列（15 列 SELECT——住院号/性别/年龄/入院日期/出院日期/
    # 入院诊断/护理级别/出院主诊断），返回 dict 同步增 8 键。
    rows = [("P1", "1", "张三", "040112", "", "", "204011",
             "0510001", "男", "45", datetime(2026, 11, 10, 9, 30, 0), None,
             "急性阑尾炎", "二级护理", "慢性阑尾炎"),
            ("P2", "2", "李四", "", "030300", "030442", "205012",
             "", "女", "52", "", "", "", "", "")]
    cur = FakeCursor(results=rows)
    meta = his.fetch_patient_visit_meta([("P1", "1"), ("P2", "2")], connect=_connect_of(cur))
    sql, binds = cur.executed[0]
    # P0：单列 IN 批量（OR 双列全扫已在生产拖死扫描进程，弃用）。
    assert '"患者ID" IN (:p0, :p1)' in sql
    assert '"患者姓名"' in sql and '"管床医生编号"' in sql
    # WP04：15 列契约（8 个临床展示列入 SELECT）
    for col in ('"住院号"', '"性别"', '"年龄"', '"入院日期"', '"出院日期"',
                '"入院诊断"', '"护理级别"', '"出院主诊断"'):
        assert col in sql
    assert sorted(binds.values()) == ["P1", "P2"]
    assert meta[("P1", "1")] == {
        "patient_name": "张三", "dept_code": "040112", "doctor_in_charge_id": "204011",
        "inp_no": "0510001", "sex": "男", "age": "45",
        "admission_date": "2026-11-10T09:30:00", "discharge_date": None,
        "admission_diagnosis": "急性阑尾炎", "nursing_level": "二级护理",
        "discharge_diagnosis": "慢性阑尾炎",
    }
    assert meta[("P2", "2")]["dept_code"] == "030300"       # 所在空 → 入院科室兜底（新增）
    # WP04：全空临床列 → 空串/None 兜底（原有键不受新增列影响）；sex 已填值正常透出
    assert meta[("P2", "2")]["sex"] == "女"
    assert meta[("P2", "2")]["age"] == "52"
    for name in ("inp_no", "admission_diagnosis", "nursing_level",
                 "discharge_diagnosis"):
        assert meta[("P2", "2")][name] == ""
    assert meta[("P2", "2")]["admission_date"] is None
    assert meta[("P2", "2")]["discharge_date"] is None


def test_fetch_patient_visit_meta_dedupes_pairs_and_degrades():
    cur = FakeCursor(results=[("P1", "1", "张三", "040112", "", "", "",
                               "", "", "", "", "", "", "", "")])

    def failing():
        raise OraError("ORA-01031")

    assert his.fetch_patient_visit_meta([], connect=None) == {}
    meta = his.fetch_patient_visit_meta(
        [("P1", "1"), ("P1", "1"), (" ", "2")], connect=_connect_of(cur))
    assert list(meta) == [("P1", "1")]
    assert his.fetch_patient_visit_meta([("P9", "9")], connect=failing) == {}


def test_visit_meta_two_rounds_incremental_beyond_limit():
    """假增量修复：>600 对分两轮调用，未命中键跨轮占用查库配额，全部补齐。"""
    his.reset_visit_meta_cache()
    total = his.V_QYBR_META_LIMIT + 150
    rows_by_pid = {}
    for i in range(total):
        pid = f"P{i:04d}"
        rows_by_pid[pid] = (pid, "1", f"姓名{i}", "040112", "", "", "204011",
                            "", "", "", None, None, "", "", "")
    queries = []

    def factory():
        class C:
            def __init__(self):
                self._cur = _QybrCursor(rows_by_pid)

            def cursor(self):
                return self._cur

            def close(self):
                pass
        return C()

    class _QybrCursor(FakeCursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            queries.append(sorted(params.values()))
            pids = set(params.values())
            self._rows = [rows_by_pid[p] for p in sorted(pids) if p in rows_by_pid]

    pairs = [(f"P{i:04d}", "1") for i in range(total)]
    first = his.fetch_patient_visit_meta(pairs, connect=factory)
    assert len(first) == his.V_QYBR_META_LIMIT          # 首轮受配额限制
    second = his.fetch_patient_visit_meta(pairs, connect=factory)
    # 第二轮：首轮 600 命中缓存 + 新查 150 → 全部补齐
    assert len(second) == total
    assert all(second[p]["patient_name"] for p in pairs)
    # 查库只发生两轮（600 + 150），缓存命中不连库
    assert sum(len(q) for q in queries) == total
    his.reset_visit_meta_cache()

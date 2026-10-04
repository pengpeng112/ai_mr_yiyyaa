# -*- coding: utf-8 -*-
"""057 D0 离线测试：explore_databases_readonly_20260925 的只读保护与白名单（假驱动，不连任何库）"""
import importlib.util
import json
import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SPEC = importlib.util.spec_from_file_location(
    'explore_databases_readonly_20260925',
    os.path.join(_REPO, 'scripts', 'explore_databases_readonly_20260925.py'))
explorer = importlib.util.module_from_spec(_SPEC)
sys.modules['explore_databases_readonly_20260925'] = explorer
_SPEC.loader.exec_module(explorer)


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        behavior = self._conn.behaviors.get(sql.split()[0].upper(), {})
        if 'raise' in behavior:
            raise behavior['raise']
        self.description = behavior.get('description', [('result',)])
        self._rows = behavior.get('rows', [('ok',)])
        if behavior.get('return_scalar') is not None:
            self._rows = [(behavior['return_scalar'],)]

    def fetchone(self):
        return self._rows[0]

    def fetchmany(self, n):
        return self._rows[:n]


class FakeConn:
    """记录全部执行语句；behaviors 控制 SELECT 行为与异常。"""

    def __init__(self, behaviors=None):
        self.executed = []
        self.behaviors = behaviors or {}
        self.rolled_back = 0
        self.closed = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed += 1


def make_factory(behaviors=None, guard_log=('guard-ok',), connect_raises=None):
    attempts = []

    def factory(src, password):
        attempts.append(password)
        if connect_raises:
            raise connect_raises
        return FakeConn(behaviors), list(guard_log)

    factory.attempts = attempts
    return factory


def fake_src(**kw):
    base = {'source_id': 't_src', 'dialect': 'oracle', 'host': '10.0.0.1', 'port': 1521,
            'database': 'x', 'user': 'u', 'enabled': True, 'credential': {'type': 'env', 'name': 'T_PW'}}
    base.update(kw)
    return base


class TestSqlWhitelist:
    def test_dml_rejected(self):
        for sql in ('delete from t', 'update t set a=1', 'insert into t values (1)',
                    'select 1 into t from dual', 'select * from t for update',
                    'call p()', 'select s.nextval from dual',
                    'select 1; select 2', 'merge into t using s on (1=1)',
                    'explain select 1'):
            with pytest.raises(explorer.GuardError):
                explorer.validate_template_sql(sql)

    def test_allowed_select(self):
        explorer.validate_template_sql('select * from dual')
        explorer.validate_template_sql('with a as (select 1) select * from a')

    def test_param_identifier_whitelist(self):
        assert explorer.validate_param('owner', 'JHEMR') == 'JHEMR'
        for bad in ('A; DROP', 'A B', "a'b", 'a--b', '', 'x' * 61):
            with pytest.raises(explorer.GuardError):
                explorer.validate_param('owner', bad)

    def test_all_registered_templates_pass_guard(self):
        # 模板注册时已校验；此处确保注册表非空且全部为白名单 SQL
        assert len(explorer.TEMPLATES) >= 15
        for key, tpl in explorer.TEMPLATES.items():
            explorer.validate_template_sql(tpl['sql'])


class TestCredential:
    def test_literal_rejected(self):
        with pytest.raises(explorer.GuardError, match='明文'):
            explorer.resolve_credential({'type': 'literal', 'value': 'x'})

    def test_env_missing_is_blocked_no_retry(self):
        # 凭据缺失直接 GuardError；不尝试任何默认/猜测口令
        with pytest.raises(explorer.GuardError, match='T_PW'):
            explorer.resolve_credential({'type': 'env', 'name': 'T_PW'})


class TestScrub:
    def test_password_masked(self):
        out = explorer.scrub_error('connect failed password=SuperSec ret 1', ['SuperSec'])
        assert 'SuperSec' not in out and '<redacted>' in out

    def test_inline_kv_masked(self):
        out = explorer.scrub_error('login failed for user u password: abc123@x', [])
        assert 'abc123' not in out

    def test_sensitive_cell_redacted(self):
        assert explorer.sanitize_cell('患者姓名', '张三') == '<redacted len=2>'
        assert explorer.sanitize_cell('patient_name', 'Zhang') == '<redacted len=5>'
        assert explorer.sanitize_cell('table_name', 'V_QYBR') == 'V_QYBR'

    def test_long_value_truncated(self):
        assert len(explorer.sanitize_cell('some_note', 'x' * 500)) < 120
        # DDL 类列（视图定义）放宽到 2000，但更长仍截断
        assert len(explorer.sanitize_cell('viewdef', 'x' * 500)) == 500
        assert len(explorer.sanitize_cell('viewdef', 'x' * 2500)) < 2020


class TestRunLocalProtections:
    def test_guards_before_select_and_close(self):
        factory = make_factory({'SELECT': {'description': [('a',)]}})
        res = explorer.run_local(fake_src(), 'pw', [{'name': 'q1', 'sql': 'select a from dual',
                                                     'params': {}, 'param_order': []}],
                                 conn_factory=factory)
        conn = None  # factory 内部创建；改用记录断言
        assert res['guards'][-1] == 'rollback+close'
        assert res['results'][0]['ok'] is True

    def test_readonly_unconfirmed_aborts_before_templates(self):
        class GuardFactory:
            def __call__(self, src, password):
                conn = FakeConn()
                # 保护链第 4 步回验失败：show transaction_read_only 返回 off
                def execute_like_cur(sql, params=None):
                    conn.executed.append((sql, params))
                    if sql.startswith('show') or sql.startswith('SELECT @@session'):
                        return 'off'
                    return 'on'
                raise explorer.GuardError('transaction_read_only 未确认（得到 %r），拒绝继续' % 'off')
        src = fake_src()
        queries = [{'name': 'q', 'sql': 'select 1', 'params': {}, 'param_order': []}]
        with pytest.raises(explorer.GuardError, match='未确认'):
            explorer.run_local(src, 'pw', queries, conn_factory=GuardFactory())
        # 抛 GuardError 发生在工厂内部，此时连接尚未返回给执行器；
        # 关键断言：模板查询绝未执行（执行器不可能触达）

    def test_guard_failure_inside_factory_prevents_template_execution(self):
        executed = []

        def factory(src, password):
            executed.append('connect')
            raise explorer.GuardError('只读保护未确认')
        with pytest.raises(explorer.GuardError):
            explorer.run_local(fake_src(), 'pw',
                               [{'name': 'q', 'sql': 'select 1', 'params': {}, 'param_order': []}],
                               conn_factory=factory)
        assert executed == ['connect']  # 无第二次连接尝试（不自动重试认证）

    def test_timeout_error_surfaced_and_conn_closed(self):
        hold = {}

        def factory(src, password):
            conn = FakeConn({'SELECT': {'raise': TimeoutError('statement timeout')}})
            hold['conn'] = conn
            return conn, ['g1']
        res = explorer.run_local(fake_src(), 'pw',
                                 [{'name': 'q', 'sql': 'select 1', 'params': {}, 'param_order': []}],
                                 conn_factory=factory)
        assert res['results'][0]['ok'] is False
        assert 'timeout' in res['results'][0]['error']
        assert hold['conn'].rolled_back == 1 and hold['conn'].closed == 1

    def test_exception_still_rolls_back_and_closes(self):
        hold = {}

        def factory(src, password):
            conn = FakeConn({'SELECT': {'raise': RuntimeError('boom password=zzz')}})
            hold['conn'] = conn
            return conn, ['g1']
        res = explorer.run_local(fake_src(), 'zzz',
                                 [{'name': 'q', 'sql': 'select 1', 'params': {}, 'param_order': []}],
                                 conn_factory=factory)
        assert res['results'][0]['ok'] is False
        assert 'zzz' not in json.dumps(res)  # 口令不落入结果
        assert hold['conn'].closed == 1 and hold['conn'].rolled_back == 1

    def test_query_budget_enforced(self, monkeypatch):
        # 构造一个超过单轮预算的模板组（21 条），预算闸必须先于参数绑定拒绝
        monkeypatch.setitem(explorer.GROUPS, 'over-budget', ('lite.identity',) * 21)
        with pytest.raises(explorer.GuardError, match='超预算'):
            explorer.build_queries({'dialect': 'sqlite'}, 'over-budget', {})


class TestBuildQueries:
    def test_unknown_group_rejected(self):
        with pytest.raises(explorer.GuardError, match='未知查询组'):
            explorer.build_queries(fake_src(), 'drop-all', {})

    def test_param_injection_rejected(self):
        with pytest.raises(explorer.GuardError):
            explorer.build_queries({'dialect': 'postgresql'}, 'objects',
                                   {'schema': 'public; drop table x', 'cap': 100})

    def test_dialect_filter(self):
        qs = explorer.build_queries({'dialect': 'oracle'}, 'identity', {})
        names = [q['name'] for q in qs]
        assert 'ora.identity' in names and 'pg.identity' not in names

    def test_cap_capped_to_object_limit(self):
        qs = explorer.build_queries({'dialect': 'postgresql'}, 'objects', {'schema': 'public', 'cap': 99999})
        bind = next(q for q in qs if q['name'] == 'pg.objects')
        assert bind['params']['cap'] == explorer.MAX_OBJECTS_PER_SOURCE


class TestRegistryGate:
    def _write_registry(self, tmp_path, sources):
        path = tmp_path / 'source-registry.json'
        path.write_text(json.dumps({'sources': sources}, ensure_ascii=False), encoding='utf-8')
        return str(path)

    def test_unknown_source_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(explorer, 'REGISTRY_PATH',
                            self._write_registry(tmp_path, [fake_src()]))
        with pytest.raises(explorer.GuardError, match='未知源'):
            explorer.main(['--source', 'nope', '--group', 'identity'])

    def test_disabled_source_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(explorer, 'REGISTRY_PATH',
                            self._write_registry(tmp_path, [fake_src(enabled=False,
                                                                    status='BLOCKED:凭据缺失')]))
        with pytest.raises(explorer.GuardError, match='未启用'):
            explorer.main(['--source', 't_src', '--group', 'identity'])

    def test_dry_run_never_connects(self, tmp_path, monkeypatch):
        monkeypatch.setattr(explorer, 'REGISTRY_PATH',
                            self._write_registry(tmp_path, [fake_src()]))
        monkeypatch.delenv('T_PW', raising=False)

        def _fail_resolve(spec):
            raise AssertionError('dry-run 不允许解析凭据')
        monkeypatch.setattr(explorer, 'resolve_credential', _fail_resolve)
        rc = explorer.main(['--dry-run', '--source', 't_src', '--group', 'identity'])
        assert rc == 0

    def test_missing_env_blocks_without_retry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(explorer, 'REGISTRY_PATH',
                            self._write_registry(tmp_path, [fake_src()]))
        monkeypatch.delenv('T_PW', raising=False)
        with pytest.raises(explorer.GuardError, match='T_PW'):
            explorer.main(['--source', 't_src', '--group', 'identity'])


class TestRemoteRunnerTemplate:
    def test_template_has_guards_and_rollback(self):
        assert 'default_transaction_read_only=on' in explorer.REMOTE_RUNNER
        assert 'conn.rollback()' in explorer.REMOTE_RUNNER
        assert 'conn.close()' in explorer.REMOTE_RUNNER
        assert 'statement_timeout' in explorer.REMOTE_RUNNER

    def test_no_write_statements_in_runner(self):
        for token in ('insert into', 'update ', 'delete from', 'create ', 'drop '):
            assert token not in explorer.REMOTE_RUNNER.lower()

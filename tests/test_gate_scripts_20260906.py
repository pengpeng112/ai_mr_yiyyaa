"""R2 静态与单元测试：run_gates / clean_demo_ports / update_gate_anchor + 首版锚 json（043 §4 R2）。

全部为纯函数/monkeypatch 单测：不真机跑门禁命令（真机验证由 R2 验收的 `--quick` 冒烟与 R5 `--full` 承担）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_gates_20260906 as run_gates
from scripts import clean_demo_ports_20260906 as clean_ports
from scripts import update_gate_anchor_20260906 as update_anchor

ROOT = Path(__file__).resolve().parents[1]


def test_external_sidecar_does_not_claim_complete_dual_round(monkeypatch, tmp_path):
    monkeypatch.setattr(run_gates, "is_port_listening", lambda *args: True)
    calls = []
    def run_positive(name, *args, **kwargs):
        calls.append(name)
        return run_gates.GateResult(name, "playwright", "PASS", counts={"passed": 1})
    monkeypatch.setattr(run_gates, "run_command", run_positive)
    monkeypatch.setattr(run_gates, "_kill_process_tree",
                        lambda *args: pytest.fail("不得终止外部 sidecar"))
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "SKIPPED"
    assert "external-sidecar" in result.note
    assert calls == ["legacy_rule_center_e2e_正向"]


def test_owned_sidecar_runs_both_rounds_before_pass(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(run_gates, "is_port_listening",
                        lambda host, port: port == run_gates.DEMO_MAIN_PORT)
    monkeypatch.setattr(run_gates, "_spawn_sidecar", lambda path: SimpleNamespace(pid=123))
    monkeypatch.setattr(run_gates, "_wait_port", lambda *args, **kwargs: True)
    killed, calls = [], []
    monkeypatch.setattr(run_gates, "_kill_process_tree", killed.append)
    def run_round(name, *args, **kwargs):
        calls.append((name, kwargs["env"]))
        return run_gates.GateResult(name, "playwright", "PASS", counts={"passed": 1})
    monkeypatch.setattr(run_gates, "run_command", run_round)
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "PASS"
    assert killed == [123]
    assert [name for name, _ in calls] == ["legacy_rule_center_e2e_正向", "legacy_rule_center_e2e_降级"]
    assert calls[1][1]["RULE_CENTER_SIDECAR"] == "0"


# ---------------------------------------------------------------- 046 T9a 新增：045 D1/D2 修复断言


def _t9a_owned_sidecar_env(monkeypatch):
    """公共环境：demo 主服务在听 + 自建 sidecar（PID 可控）。"""
    from types import SimpleNamespace
    monkeypatch.setattr(run_gates, "is_port_listening",
                        lambda host, port: port == run_gates.DEMO_MAIN_PORT)
    monkeypatch.setattr(run_gates, "_spawn_sidecar",
                        lambda path: SimpleNamespace(pid=321))
    monkeypatch.setattr(run_gates, "_wait_port", lambda *a, **k: True)
    return monkeypatch


def test_t9a_d1_dual_round_pass_duration_accumulates(monkeypatch, tmp_path):
    """045 D1：双轮全 PASS 的耗时=正向+降级（非 0 确定值，不再显示 0s）。"""
    _t9a_owned_sidecar_env(monkeypatch)
    killed = []
    monkeypatch.setattr(run_gates, "_kill_process_tree", killed.append)

    def run_round(name, *args, **kwargs):
        gate = run_gates.GateResult(name, "playwright", "PASS", counts={"passed": 1})
        gate.duration = 12.5 if "正向" in name else 7.5
        return gate

    monkeypatch.setattr(run_gates, "run_command", run_round)
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "PASS"
    assert result.duration == pytest.approx(20.0)


def test_t9a_d1_external_sidecar_skipped_keeps_positive_duration(monkeypatch, tmp_path):
    """045 D1 附：外部 sidecar SKIPPED 路径也带正向轮真实耗时。"""
    monkeypatch.setattr(run_gates, "is_port_listening", lambda *a: True)
    positive = run_gates.GateResult("legacy_rule_center_e2e_正向", "pw", "PASS",
                                    counts={"passed": 1})
    positive.duration = 9.0
    monkeypatch.setattr(run_gates, "run_command", lambda name, *a, **k: positive)
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "SKIPPED" and "external-sidecar" in result.note
    assert result.duration == pytest.approx(9.0)


def test_t9a_d2_sidecar_spawn_wait_failure_kills_owned_tree(monkeypatch, tmp_path):
    """045 D2：拉起失败（端口等待超时）必须回收自建进程树，不留孤儿。"""
    _t9a_owned_sidecar_env(monkeypatch)
    monkeypatch.setattr(run_gates, "_spawn_sidecar",
                        lambda path: type("P", (), {"pid": 999})())
    monkeypatch.setattr(run_gates, "_wait_port", lambda *a, **k: False)   # 拉起失败
    killed = []
    monkeypatch.setattr(run_gates, "_kill_process_tree",
                        lambda pid: killed.append(pid))
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "FAIL" and "拉起失败" in result.note
    assert killed == [999]


def test_t9a_d2_positive_round_failure_still_cleans_owned_tree(monkeypatch, tmp_path):
    """045 D2：正向轮 FAIL 也清理自建进程树（且不重复杀）。"""
    _t9a_owned_sidecar_env(monkeypatch)
    killed = []
    monkeypatch.setattr(run_gates, "_kill_process_tree",
                        lambda pid: killed.append(pid))
    failed = run_gates.GateResult("legacy_rule_center_e2e_正向", "pw", "FAIL")
    failed.duration = 1.0
    monkeypatch.setattr(run_gates, "run_command", lambda name, *a, **k: failed)
    result = run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert result.status == "FAIL"
    assert killed == [321]


def test_t9a_d2_unexpected_exception_cleans_owned_tree(monkeypatch, tmp_path):
    """045 D2：异常抛出路径 finally 兜底回收自建进程树。"""
    _t9a_owned_sidecar_env(monkeypatch)
    killed = []
    monkeypatch.setattr(run_gates, "_kill_process_tree",
                        lambda pid: killed.append(pid))

    def boom(name, *a, **k):
        raise RuntimeError("unexpected crash in spec run")

    monkeypatch.setattr(run_gates, "run_command", boom)
    with pytest.raises(RuntimeError):
        run_gates.run_legacy_rule_center_e2e(tmp_path)
    assert killed == [321]


# ---------------------------------------------------------------- run_gates：参数与摘要解析


def test_build_parser_anchor_defaults_to_none():
    args = run_gates.build_parser().parse_args(["--quick"])
    assert args.anchor_file is None
    assert args.quick is True and args.full is False
    assert args.strict_ports is False


def test_main_rejects_both_or_neither_mode():
    # quick/full 互斥在 main() 内 parser.error（SystemExit）
    with pytest.raises(SystemExit):
        run_gates.main(["--quick", "--full"])
    with pytest.raises(SystemExit):
        run_gates.main([])


def test_decode_stream_and_parse_counts_binary_safe():
    # 模拟 Windows 后台任务管道：UTF-8 摘要 + 非法字节（二进制安全要求）
    raw = "1272 passed, 1 skipped in 12.3s\n".encode("utf-8") + b"\xd0\xffgarbage"
    text = run_gates.decode_stream(raw)
    counts = run_gates.parse_counts(text)
    assert counts["passed"] == 1272
    assert counts["skipped"] == 1
    assert counts["failed"] == 0

    playwright = run_gates.parse_counts("  52 passed (24.0s)\n  17 skipped\n  2 failed")
    assert playwright == {"passed": 52, "skipped": 17, "failed": 2, "error": 0}


def test_compare_with_anchors_below_anchor_reports_problem():
    anchors = {"main_pytest": {"passed": 1295, "skipped": 0}, "sidecar_check": {"status": "PASS"}}
    below = {"main_pytest": {"status": "PASS", "counts": {"passed": 1200}},
             "sidecar_check": {"status": "PASS"}}
    problems = run_gates.compare_with_anchors(below, anchors)
    assert any("1295" in p for p in problems)

    ok = {"main_pytest": {"status": "PASS", "counts": {"passed": 1296}},
          "sidecar_check": {"status": "PASS"}}
    assert run_gates.compare_with_anchors(ok, anchors) == []

    sidecar_fail = {"main_pytest": {"status": "PASS", "counts": {"passed": 1300}},
                    "sidecar_check": {"status": "FAIL"}}
    assert any("sidecar" in p for p in run_gates.compare_with_anchors(sidecar_fail, anchors))


def test_compare_with_anchors_skips_gates_not_run():
    # quick 模式没跑 pytest：即使传锚也不比 pytest（只比实际跑过的门）
    anchors = {"main_pytest": {"passed": 1295}}
    quick_only = {"compileall": {"status": "PASS"}}
    assert run_gates.compare_with_anchors(quick_only, anchors) == []


def test_main_quick_without_anchor_exits_zero(monkeypatch, tmp_path, capsys):
    """未传 --anchor-file 时不比锚也退出 0（043 §4 R2 验收原文）。门禁执行全部 mock 为 PASS。"""
    monkeypatch.setattr(run_gates, "RUNS_DIR", tmp_path / "gate-runs")

    def fake_run_command(name, cmd, cwd, run_dir, **kwargs):
        return run_gates.GateResult(name, " ".join(cmd), "PASS", duration=0.0)

    monkeypatch.setattr(run_gates, "run_command", fake_run_command)
    assert run_gates.main(["--quick"]) == 0
    out = capsys.readouterr().out
    assert "未比锚（未传 --anchor-file）" in out
    assert "| compileall | PASS |" in out


def test_main_anchor_missing_file_only_tables(monkeypatch, tmp_path, capsys):
    """传了 --anchor-file 但文件不存在 → 只出表不比锚，退出 0。"""
    monkeypatch.setattr(run_gates, "RUNS_DIR", tmp_path / "gate-runs")

    def fake_run_command(name, cmd, cwd, run_dir, **kwargs):
        return run_gates.GateResult(name, " ".join(cmd), "PASS", duration=0.0)

    monkeypatch.setattr(run_gates, "run_command", fake_run_command)
    missing = tmp_path / "no_such_anchor.json"
    assert run_gates.main(["--quick", "--anchor-file", str(missing)]) == 0
    assert "不存在，只出表" in capsys.readouterr().out


def test_main_below_anchor_exits_nonzero(monkeypatch, tmp_path):
    """传锚且低于锚 → 非零（043 §4 R2 验收原文）。"""
    monkeypatch.setattr(run_gates, "RUNS_DIR", tmp_path / "gate-runs")

    def fake_run_command(name, cmd, cwd, run_dir, **kwargs):
        counts = {"passed": 100} if name == "main_pytest" else {}
        return run_gates.GateResult(name, " ".join(cmd), "PASS", counts=counts, duration=0.0)

    monkeypatch.setattr(run_gates, "run_command", fake_run_command)

    def fake_specs(mode):
        return [{"name": "main_pytest", "cmd": ["x"], "cwd": tmp_path, "counts": True}]

    monkeypatch.setattr(run_gates, "build_gate_specs", fake_specs)
    monkeypatch.setattr(run_gates, "should_run_legacy_demo_e2e", lambda *a, **k: (False, "no-demo(test)"))

    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"anchors": {"main_pytest": {"passed": 1295}}}), encoding="utf-8")
    assert run_gates.main(["--quick", "--anchor-file", str(anchor)]) == 1


# ---------------------------------------------------------------- 首版锚 json


def test_first_version_anchor_file_schema():
    path = ROOT / "docs" / "reference" / "gate_anchors.json"
    assert path.exists(), "首版 gate_anchors.json 必须随 R2 落地"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    anchors = data["anchors"]
    # 054 U6：锚数值经 update_gate_anchor_20260906.py 演进（050 已 1295→1379、283→455、
    # 57→62、17→23），冻结首版数字会在下次升锚后假失败——改为结构/类型/非负校验，
    # 具体数值由 run_gates --anchor-file 的"不低于锚"比较负责。
    for key in ("main_pytest", "prearchive_pytest", "frontend_unit", "frontend_e2e"):
        entry = anchors[key]
        for field in ("passed", "skipped"):
            if field in entry:
                assert isinstance(entry[field], int) and entry[field] >= 0, (key, field)
        assert entry["passed"] > 0, key
    assert anchors["sidecar_check"]["status"] == "PASS"
    # load_anchor_file 通过 schema 校验且读数一致
    loaded = run_gates.load_anchor_file(path)
    assert loaded["main_pytest"]["passed"] == anchors["main_pytest"]["passed"]


# ---------------------------------------------------------------- clean_demo_ports


def test_parse_netstat_english_and_chinese_listening():
    sample_en = (
        "  TCP    127.0.0.1:18080     0.0.0.0:0              LISTENING       12345\n"
        "  TCP    127.0.0.1:9999      127.0.0.1:80           ESTABLISHED     111\n"
    )
    sample_zh = (
        "  TCP    127.0.0.1:18600     0.0.0.0:0              侦听            6789\r\n"
        "  TCP    127.0.0.1:4173      0.0.0.0:0              侦听            999\r\n"
    )
    entries = clean_ports.parse_netstat_output(sample_en + sample_zh)
    by_port = {e.port: e for e in entries}
    assert set(by_port) == {18080, 18600, 4173}  # ESTABLISHED 不收
    assert by_port[18080].pid == 12345
    assert by_port[18600].pid == 6789


def test_classify_port_semantics():
    assert clean_ports.classify_port(18080) == "killable"
    assert clean_ports.classify_port(18081) == "killable"
    assert clean_ports.classify_port(18082) == "killable"
    assert clean_ports.classify_port(18600) == "killable"
    assert clean_ports.classify_port(4173) == "report-only"
    assert clean_ports.classify_port(8000) == "ignored"


def test_clean_ports_dry_run_report_only_and_none(monkeypatch, capsys):
    # 场景一：无残留 → none
    monkeypatch.setattr(clean_ports, "collect_entries", lambda killable=(): [])
    assert clean_ports.main([]) == 0
    assert "none" in capsys.readouterr().out

    # 场景二：18600 残留 + 4173 占用 → would-kill + REPORT-ONLY（默认 dry-run 不真杀）
    residue = [clean_ports.PortEntry(18600, 4242, "侦听"), clean_ports.PortEntry(4173, 777, "LISTENING")]
    monkeypatch.setattr(clean_ports, "collect_entries", lambda killable=(): residue)
    killed: list[int] = []
    monkeypatch.setattr(clean_ports, "kill_pid_tree", lambda pid: killed.append(pid) or True)
    assert clean_ports.main([]) == 0
    out = capsys.readouterr().out
    assert "would-kill 端口 18600 pid=4242" in out
    assert "REPORT-ONLY 端口 4173" in out and "不杀" in out
    assert killed == []  # dry-run 不执行


def test_clean_ports_yes_executes_kill(monkeypatch, capsys):
    residue = [clean_ports.PortEntry(18080, 111, "LISTENING")]
    monkeypatch.setattr(clean_ports, "collect_entries", lambda killable=(): residue)
    killed: list[int] = []
    monkeypatch.setattr(clean_ports, "kill_pid_tree", lambda pid: killed.append(pid) or True)
    assert clean_ports.main(["--yes"]) == 0
    assert killed == [111]
    assert "KILL 端口 18080 pid=111" in capsys.readouterr().out


# ---------------------------------------------------------------- update_gate_anchor


def _write_result(tmp_path: Path, passed: int) -> Path:
    result = {
        "mode": "full",
        "timestamp": "test",
        "results": {
            "main_pytest": {"status": "PASS", "counts": {"passed": passed, "skipped": 0, "failed": 0}},
            "prearchive_pytest": {"status": "PASS", "counts": {"passed": 283, "skipped": 1, "failed": 0}},
            "frontend_unit": {"status": "PASS", "counts": {"passed": 57, "skipped": 0, "failed": 0}},
            "frontend_e2e": {"status": "PASS", "counts": {"passed": 52, "skipped": 17, "failed": 0}},
            "sidecar_check": {"status": "PASS", "counts": {}},
            "compileall": {"status": "PASS", "counts": {}},
        },
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def test_update_anchor_writes_then_idempotent(tmp_path, capsys):
    result_path = _write_result(tmp_path, passed=1301)
    anchor_path = tmp_path / "gate_anchors.json"
    assert update_anchor.main([str(result_path), "--anchor-file", str(anchor_path)]) == 0
    data = json.loads(anchor_path.read_text(encoding="utf-8"))
    assert data["anchors"]["main_pytest"]["passed"] == 1301
    first_bytes = anchor_path.read_bytes()

    # 幂等：跑第二次 json 一致（不重写）
    assert update_anchor.main([str(result_path), "--anchor-file", str(anchor_path)]) == 0
    assert anchor_path.read_bytes() == first_bytes
    assert "幂等" in capsys.readouterr().out


def test_update_anchor_rejects_result_without_pass_gates(tmp_path):
    path = tmp_path / "empty_result.json"
    path.write_text(json.dumps({"results": {"main_pytest": {"status": "FAIL"}}}), encoding="utf-8")
    assert update_anchor.main([str(path), "--anchor-file", str(tmp_path / "a.json")]) == 2


def test_child_env_forces_local_no_proxy(monkeypatch):
    """044 卡点 F：Windows 系统代理劫持 127.0.0.1（urllib 走注册表代理回 502）→ 门禁子进程强制注入本地回环 no_proxy。"""
    # 注意：Windows 的 os.environ 键不区分大小写，NO_PROXY/no_proxy 是同一变量
    monkeypatch.setenv("NO_PROXY", "corp.example.com")
    env = run_gates.child_env_with_local_no_proxy({"LEGACY_E2E": "true"})
    assert "127.0.0.1" in env["NO_PROXY"] and "localhost" in env["NO_PROXY"]
    assert "corp.example.com" in env["NO_PROXY"]  # 保留既有条目
    assert env["LEGACY_E2E"] == "true"
    # 空环境场景：仅本地回环
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    env2 = run_gates.child_env_with_local_no_proxy()
    assert set(env2["NO_PROXY"].split(",")) == {"127.0.0.1", "localhost"}


def test_update_anchor_missing_input_returns_error(tmp_path):
    assert update_anchor.main([str(tmp_path / "nope.json")]) == 2

import main
from config.main_config import geometry_config


def test_headless_run_improves_standard(capsys):
    best, score = main.main(["--geometry", "generic_105_alpha", "--iterations", "300", "--seed", "1"])
    out = capsys.readouterr().out
    start = float(out.split("штраф ")[1].split(" ->")[0])
    assert score < start
    assert len(best.keys) == len(geometry_config("generic_105_alpha")["positions"])


def test_docstring_recommends_cgroup_quota():
    """QA 2026-11-26: докстрінг радив cpulimit, який CLAUDE.md забороняє."""
    from pathlib import Path
    assert "cpulimit" not in Path(main.__file__).read_text(encoding="utf-8")
    assert "systemd-run --user --scope -q -p CPUQuota=60% nice -n 10" in main.__doc__


def test_zero_iterations_clear_error():
    """QA 2026-11-26: --iterations 0 давав сирий traceback ValueError з run_optimization."""
    import pytest
    with pytest.raises(SystemExit) as exit_info:
        main.main(["--geometry", "generic_105_alpha", "--iterations", "0"])
    assert str(exit_info.value.code).startswith("помилка: --iterations")

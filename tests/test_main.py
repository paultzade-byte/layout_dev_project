import main
from config.main_config import geometry_config


def test_headless_run_improves_standard(capsys):
    best, score = main.main(["--geometry", "generic_105_alpha", "--iterations", "300", "--seed", "1"])
    out = capsys.readouterr().out
    start = float(out.split("штраф ")[1].split(" ->")[0])
    assert score < start
    assert len(best.keys) == len(geometry_config("generic_105_alpha")["positions"])

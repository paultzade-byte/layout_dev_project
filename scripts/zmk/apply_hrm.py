"""Дамп клавіатури -> той самий дамп з `&mt` -> `&hml`/`&hmr` на HRM-позиціях.

Після прошивки з новими behavior keymap у Studio лишається старий (`&mt`).
Цей скрипт готує цільовий файл; записує його `studio.py write` по шарах:

    python scripts/zmk/studio.py dump /dev/ttyACM2 /tmp/now.json
    python scripts/zmk/apply_hrm.py /tmp/now.json /tmp/hrm.json
    python scripts/zmk/studio.py write /dev/ttyACM2 /tmp/hrm.json --layer GRAPH [--yes]
    python scripts/zmk/studio.py write /dev/ttyACM2 /tmp/hrm.json --layer CYR [--yes]
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from keymap_from_dump import HRM_LAYERS, HRM_POSITIONS  # noqa: E402
from studio import _norm  # noqa: E402

DISPLAY_NAMES = {"hml": "HRM Left", "hmr": "HRM Right"}  # display-name у .keymap


def apply_hrm(dump):
    result = copy.deepcopy(dump)
    ids = {name: bid for bid, name in result["behaviors"].items()}
    missing = [n for n in DISPLAY_NAMES.values() if n not in ids]
    if missing:
        raise SystemExit(f"у прошивці немає behavior {missing} — спершу прошити нову збірку")
    for layer in result["layers"]:
        if layer["name"] not in HRM_LAYERS:
            continue
        for pos, behavior in HRM_POSITIONS.items():
            b = layer["bindings"][pos]
            if result["behaviors"][b[0]] != "Mod-Tap":
                raise SystemExit(f"{layer['name']}[{pos}]: очікувався Mod-Tap, а там "
                                 f"{result['behaviors'][b[0]]}")
            b[0] = ids[DISPLAY_NAMES[behavior]]
    return result


def main():
    dump = _norm(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(sys.argv[2]).write_text(json.dumps(apply_hrm(dump), ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(f"записано {sys.argv[2]}")


if __name__ == "__main__":
    main()

"""Дамп клавіатури (studio.py dump) -> config/eyelash_corne.keymap для форку.

Шари — у порядку id (індекс у devicetree = id шару в Studio): Studio
зберігає біндинги в налаштуваннях за id, тож параметри шарів (&lt, &tog,
макроси) мусять бути саме id. Порядок шарів зі Studio (CYR під DIGITS тощо)
живе в налаштуваннях клавіатури, devicetree його не задає. Кейкоди без надійного ZMK-імені
(consumer, &bt, &rgb_ug, &mkp) пишуться числами — так вони гарантовано
збігаються з тим, що зараз на клавіатурі.

Home-row mods (сесія 2026-10-29): `&mt` на позиціях HRM_POSITIONS у шарах
HRM_LAYERS замінюються на `&hml`/`&hmr` — холд лише якщо наступна клавіша на
іншій руці або тхамбі, і лише після паузи в друці (require-prior-idle).

    python scripts/zmk/keymap_from_dump.py DUMP.json OUT.keymap
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio import KEY_NAMES, MOD_NAMES, ROWS, _norm  # noqa: E402

LEFT = [*range(0, 6), *range(13, 19), *range(28, 34)]
RIGHT = [*range(7, 13), *range(22, 28), *range(36, 42)]
THUMBS = list(range(42, 48))
# 16/24 — шифти на середніх пальцях, 31/32 — Ctrl+C / Ctrl+V
HRM_POSITIONS = {16: "hml", 31: "hml", 32: "hml", 24: "hmr"}
HRM_LAYERS = {"GRAPH", "CYR"}

BEHAVIORS = """\
        /* Tap = ESC, Hold = FN layer */
        esc_fn: esc_fn {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            tapping-term-ms = <200>;
            flavor = "balanced";
            bindings = <&kp>, <&mo>;
        };

        /* Home-row mods: холд лише якщо наступна клавіша на іншій руці / тхамбі
         * (перекат однією рукою = завжди тап) і лише після паузи в друці. */
        hml: home_row_mod_left {
            compatible = "zmk,behavior-hold-tap";
            display-name = "HRM Left";
            #binding-cells = <2>;
            flavor = "balanced";
            tapping-term-ms = <280>;
            quick-tap-ms = <175>;
            require-prior-idle-ms = <150>;
            hold-trigger-key-positions = <RIGHT_POS THUMB_POS>;
            hold-trigger-on-release;
            bindings = <&kp>, <&kp>;
        };

        hmr: home_row_mod_right {
            compatible = "zmk,behavior-hold-tap";
            display-name = "HRM Right";
            #binding-cells = <2>;
            flavor = "balanced";
            tapping-term-ms = <280>;
            quick-tap-ms = <175>;
            require-prior-idle-ms = <150>;
            hold-trigger-key-positions = <LEFT_POS THUMB_POS>;
            hold-trigger-on-release;
            bindings = <&kp>, <&kp>;
        };
""".replace("LEFT_POS", " ".join(map(str, LEFT))).replace(
    "RIGHT_POS", " ".join(map(str, RIGHT))).replace("THUMB_POS", " ".join(map(str, THUMBS)))

# Перемикач мови: шар CYR і розкладка ОС (us,ua з grp:alt_space_toggle)
# разом, щоб не розходились. Сесія 2026-10-29.
MACROS = """\
        lang_tog: lang_toggle {{
            compatible = "zmk,behavior-macro";
            display-name = "Lang Toggle";
            #binding-cells = <0>;
            bindings
                = <&tog {cyr}>
                , <&macro_press &kp LALT>
                , <&macro_tap &kp SPACE>
                , <&macro_release &kp LALT>
                ;
        }};
"""


def keycode(p):
    mods, page, uid = p >> 24, (p >> 16) & 0xFF, p & 0xFFFF
    if page != 0x07 or uid not in KEY_NAMES:
        return f"{p:#010x}"
    name = KEY_NAMES[uid]
    if name.isdigit():
        name = "N" + name
    for i, m in enumerate(MOD_NAMES):
        if mods & (1 << i):
            name = f"{m}({name})"
    return name


def binding(b, behaviors, layer, override=None):
    bid, p1, p2 = b
    name = behaviors[bid]
    if override and name == "Mod-Tap":
        return f"&{override} {keycode(p1)} {keycode(p2)}"
    return {
        "Key Press": lambda: f"&kp {keycode(p1)}",
        "Transparent": lambda: "&trans",
        "None": lambda: "&none",
        "Mod-Tap": lambda: f"&mt {keycode(p1)} {keycode(p2)}",
        "HRM Left": lambda: f"&hml {keycode(p1)} {keycode(p2)}",
        "HRM Right": lambda: f"&hmr {keycode(p1)} {keycode(p2)}",
        "Layer-Tap": lambda: f"&lt {layer[p1]} {keycode(p2)}",
        "Momentary Layer": lambda: f"&mo {layer[p1]}",
        "To Layer": lambda: f"&to {layer[p1]}",
        "Toggle Layer": lambda: f"&tog {layer[p1]}",
        "Sticky Layer": lambda: f"&sl {layer[p1]}",
        "Sticky Key": lambda: f"&sk {keycode(p1)}",
        "Mouse Key Press": lambda: f"&mkp {p1}",
        "Bluetooth": lambda: f"&bt {p1} {p2}",
        "Underglow": lambda: f"&rgb_ug {p1} {p2}",
        "esc_fn": lambda: f"&esc_fn {keycode(p1)} {layer[p2]}",
        "Lang Toggle": lambda: "&lang_tog",
    }[name]()


def generate(dump):
    behaviors = dump["behaviors"]
    layers = sorted(dump["layers"], key=lambda l: l["id"])
    if [l["id"] for l in layers] != list(range(len(layers))):
        raise SystemExit("id шарів не 0..N-1 — devicetree так не задати")
    defines = {l["id"]: f"L_{l['name']}" for l in layers}
    out = ["/*",
           " * Згенеровано layout_dev_project/scripts/zmk/keymap_from_dump.py з дампу",
           " * клавіатури (ZMK Studio). Шари в порядку id; порядок Studio — у",
           " * налаштуваннях клавіатури.",
           " */", "",
           "#include <behaviors.dtsi>",
           "#include <dt-bindings/zmk/keys.h>",
           "#include <dt-bindings/zmk/bt.h>", ""]
    out += [f"#define {defines[l['id']]:12} {l['id']}" for l in layers]
    out += ["", "/ {", "    behaviors {", BEHAVIORS, "    };", "",
            "    macros {", MACROS.format(cyr=defines[next(l["id"] for l in layers if l["name"] == "CYR")]),
            "    };", "",
            "    keymap {", '        compatible = "zmk,keymap";']
    for l in layers:
        hrm = HRM_POSITIONS if l["name"] in HRM_LAYERS else {}
        texts = [binding(b, behaviors, defines, hrm.get(i)) for i, b in enumerate(l["bindings"])]
        out += ["", f"        layer_{l['name'].lower()} {{", f'            display-name = "{l["name"]}";',
                "            bindings = <"]
        for row, left, right, mid in ROWS:
            positions = sorted([*left, *mid, *right])  # ліва рука, центр, права
            out.append(f"                /* {row} */ " + "  ".join(texts[i] for i in positions))
        out += ["            >;", "        };"]
    out += ["    };", "};", ""]
    return "\n".join(out)


def main():
    dump = _norm(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(sys.argv[2]).write_text(generate(dump), encoding="utf-8")
    print(f"записано {sys.argv[2]}")


if __name__ == "__main__":
    main()

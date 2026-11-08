"""HTML-схема шарів клавіатури з дампу studio.py (для артефакту).

    python scripts/zmk/layers_html.py DUMP.json OUT.html [--mark SYMBOL:11,30,36]
        [--variant "k|найкраща за моделлю|165.31|dump_k.json" --variant ...]

Підписи — ті самі, що в draw_layers.py (кожен шар у мові, в якій він
працює; у спільних шарах — латиниця, а кириличний варіант окремо, де він
інший). «Як увімкнути» рахується з біндингів, тож після зміни keymap досить
перезгенерувати сторінку. --mark підсвічує клавіші (наприклад, тимчасові).
"""

import argparse
import html
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import draw_layers as dl  # noqa: E402
from studio import keycode_name  # noqa: E402

ORDER = ["GRAPH", "CYR", "GRAPH_ALT", "CYR_S", "DIGITS", "SYMBOL", "FN", "FN_C"]
ABOUT = {
    "GRAPH": "База, латиниця.",
    "CYR": "База, кирилиця (розкладка з оптимізатора).",
    "GRAPH_ALT": "Символи й навігація для латиниці: тап — одна наступна клавіша, утримання — шар.",
    "CYR_S": "Символи для кирилиці (RAlt-символи xkb ua / Option на маку).",
    "DIGITS": "Цифри, стрілки, Home/End. Спільний для обох мов.",
    "SYMBOL": "Пунктуація. Спільний: де кирилиця друкує інше, воно показане в кутку.",
    "FN": "Медіа, F-клавіші, мишка, мова, Bluetooth.",
    "FN_C": "Умовний: вмикається сам, коли CYR + FN. Перекриває FN у кирилиці.",
}
LANG = {"GRAPH": "us", "GRAPH_ALT": "us", "CYR": "ua", "CYR_S": "ua"}
ROWS = [list(range(0, 6)) + [None] + list(range(7, 13)),
        list(range(13, 19)) + [None] + list(range(22, 28)),
        list(range(28, 34)) + [None] + list(range(36, 42))]
THUMBS = [42, 43, 44, None, 45, 46, 47]
FINGER_L = ["зовн. мізинець", "мізинець", "безіменний", "середній", "вказівний", "вказівний (внутр.)"]
ROW_NAME = ["верхній ряд", "домашній ряд", "нижній ряд"]
THUMB_NAME = {42: "лівий зовн. тхамб", 43: "лівий середній тхамб", 44: "лівий внутр. тхамб",
              45: "правий внутр. тхамб", 46: "правий середній тхамб", 47: "правий зовн. тхамб"}
MODS = {"LSHFT": "Shift", "RSHFT": "Shift", "LCTRL": "Ctrl", "RCTRL": "Ctrl", "LALT": "Alt",
        "RALT": "AltGr", "LGUI": "Win/Cmd", "RGUI": "Win/Cmd"}


def pos_name(i):
    if i in THUMB_NAME:
        return THUMB_NAME[i]
    for r, row in enumerate(ROWS):
        if i in row:
            c = row.index(i)
            side, f = ("лівий", FINGER_L[c]) if c < 6 else ("правий", FINGER_L[12 - c])
            return f"{side} {f}, {ROW_NAME[r]}"
    return f"#{i}"


def lab(p, lang):
    mods = p >> 24
    if mods & 0x9D:  # Ctrl / Alt / Gui (RAlt+Shift — це AltGr-символ, не шорткат)
        pre = ("⌃" if mods & 0x11 else "") + ("⌥" if mods & 0x04 else "") + \
              ("◆" if mods & 0x88 else "") + ("⇧" if mods & 0x22 else "")
        return pre + dl.ch(p & 0xFFFFFF, "us")
    return dl.ch(p, lang)


def hold_lab(p):
    return MODS.get(keycode_name(p)) or {"LC(C)": "Ctrl+C", "LC(V)": "Ctrl+V"}.get(
        keycode_name(p)) or lab(p, "us")


def key(b, lang):
    """-> dict(tap, hold, kind, layer) для одного біндингу."""
    bid, p1, p2 = b
    n = dl.beh[bid]
    L = dl.lname.get(p1)
    if n == "Key Press":
        return dict(tap=lab(p1, lang), kind="key")
    if n == "Transparent":
        return dict(tap="", kind="trans")
    if n == "None":
        return dict(tap="", kind="none")
    if n in ("Mod-Tap", "HRM Left", "HRM Right"):
        return dict(tap=lab(p2, lang), hold=hold_lab(p1), kind="ht")
    if n == "Layer-Tap":
        return dict(tap=lab(p2, lang), hold=L, kind="lt", layer=L)
    if n == "LT Comma/Dot":
        return dict(tap=", ⇧.", hold=L, kind="lt", layer=L)
    if n == "Momentary Layer":
        return dict(tap="", hold=L, kind="lt", layer=L)
    if n == "Sticky Layer":
        return dict(tap="1×", hold=L, kind="lt", layer=L)
    if n == "To Layer":
        return dict(tap="→ " + L, kind="to", layer=L)
    if n == "Toggle Layer":
        return dict(tap="⇄ " + L, kind="to", layer=L)
    if n == "Sticky Key":
        return dict(tap="1× " + hold_lab(p1), kind="key")
    if n == "esc_fn":
        return dict(tap="Esc", hold="FN", kind="lt", layer="FN")
    if n == "Underglow":
        return dict(tap=dl.RGB_LABELS.get(p1, f"RGB{p1}"), kind="key")
    simple = {"Colon/Semi": ": ⇧;", "Lang CYR": "→ КИР", "Lang LAT": "→ LAT",
              "Lang Toggle": "мова ⇄", "Underglow": "RGB", "Caps Word": "CapsWord",
              "Bootloader": "Boot", "Reset": "Reset", "Key Repeat": "Repeat"}
    if n in simple:
        return dict(tap=simple[n], kind="lang" if n.startswith("Lang") else "key")
    return dict(tap=dl.cell(b, lang), kind="key")


def esc(s):
    return html.escape(s or "")


def key_html(b, layer, i, marks):
    lang = LANG.get(layer)
    k = key(b, lang or "us")
    alt = None
    if lang is None and k["kind"] in ("key", "ht", "lt"):
        ua = key(b, "ua")
        if ua["tap"] != k["tap"]:
            alt = ua["tap"]
    cls = ["k", k["kind"]]
    if i in marks:
        cls.append("mark")
    style = f' style="--lc: var(--l-{k["layer"].lower().replace("_", "-")})"' if k.get("layer") else ""
    tap = esc(k["tap"]) if k["kind"] != "trans" else "▽"
    title = pos_name(i)
    parts = [f'<div class="{" ".join(cls)}"{style} title="{esc(title)}">']
    if k["tap"] or k["kind"] == "trans":
        long_ = " long" if len(k["tap"]) > 4 else ""
        parts.append(f'<span class="tap{long_}">{tap}</span>')
    if k.get("hold"):
        parts.append(f'<span class="hold">{esc(k["hold"])}</span>')
    if alt:
        parts.append(f'<span class="alt" title="кирилиця">{esc(alt)}</span>')
    if i in marks:
        parts.append('<span class="flag">тест</span>')
    parts.append("</div>")
    return "".join(parts)


def activators(name, d):
    lid = next(l["id"] for l in d["layers"] if l["name"] == name)
    out = []
    for l in d["layers"]:
        for i, b in enumerate(l["bindings"]):
            n = dl.beh[b[0]]
            if b[1] != lid or n not in ("Layer-Tap", "LT Comma/Dot", "Momentary Layer",
                                        "Sticky Layer", "To Layer", "Toggle Layer"):
                continue
            how = {"Sticky Layer": "тап — 1 клавіша, утримання",
                   "To Layer": "перемкнути", "Toggle Layer": "увімк./вимк."}.get(n, "утримання")
            out.append(f"{how}: {pos_name(i)} на {l['name']}")
        if name == "FN" and l["name"] != "FN":
            for i, b in enumerate(l["bindings"]):
                if dl.beh[b[0]] == "esc_fn":
                    out.append(f"утримання: {pos_name(i)} на {l['name']}")
    if name == "FN_C":
        out.append("автоматично: CYR + FN разом")
    return out


def layer_html(l, d, marks):
    name = l["name"]
    bb = l["bindings"]
    m = marks.get(name, set())
    rows = []
    for row in ROWS:
        cells = ['<div class="gap"></div>' if i is None else key_html(bb[i], name, i, m) for i in row]
        rows.append('<div class="row">' + "".join(cells) + "</div>")
    th = ['<div class="gap"></div>' if i is None else key_html(bb[i], name, i, m) for i in THUMBS]
    rows.append('<div class="row thumbs"><div class="pad"></div><div class="pad"></div><div class="pad"></div>'
                + "".join(th) + '<div class="pad"></div><div class="pad"></div><div class="pad"></div></div>')
    acts = activators(name, d)
    act = "".join(f"<li>{esc(a)}</li>" for a in acts) or "<li>базовий шар</li>"
    anchor = name.lower().replace("_", "-")
    lc = f"var(--l-{anchor})"
    return f'''<section class="layer" id="{anchor}" style="--lc: {lc}">
  <header><h2><span class="dot"></span>{esc(name)}</h2><p>{esc(ABOUT.get(name, ""))}</p>
  <ul class="acts">{act}</ul></header>
  <div class="scroll"><div class="board">{"".join(rows)}</div></div>
</section>'''


CSS = """
/* Layout: one column of layers; each layer is a split board (6 + gap + 6, thumbs centered) */
:root {
  --bg: #f4f5f7; --panel: #ffffff; --fg: #1c2230; --muted: #626b7d; --line: #d8dce4;
  --key: #ffffff; --key-edge: #c9ced8; --faint: #b7bdc9; --mark: #d9480f;
  --l-graph: #3b6fd8; --l-cyr: #c2410c; --l-graph-alt: #0f8a7e; --l-cyr-s: #b45309;
  --l-digits: #7c3aed; --l-symbol: #be185d; --l-fn: #4b5563; --l-fn-c: #6b7280;
  --sans: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141a; --panel: #181c24; --fg: #e4e8f0; --muted: #9aa3b5; --line: #2a303c;
  --key: #1f2430; --key-edge: #343b4a; --faint: #4a5263; --mark: #ff8a4c;
  --l-graph: #7ea2ff; --l-cyr: #ff9a6b; --l-graph-alt: #4fd1c0; --l-cyr-s: #f6b45a;
  --l-digits: #b69cff; --l-symbol: #f47fb4; --l-fn: #a3acbd; --l-fn-c: #8b94a6; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #11141a; --panel: #181c24; --fg: #e4e8f0; --muted: #9aa3b5; --line: #2a303c;
  --key: #1f2430; --key-edge: #343b4a; --faint: #4a5263; --mark: #ff8a4c;
  --l-graph: #7ea2ff; --l-cyr: #ff9a6b; --l-graph-alt: #4fd1c0; --l-cyr-s: #f6b45a;
  --l-digits: #b69cff; --l-symbol: #f47fb4; --l-fn: #a3acbd; --l-fn-c: #8b94a6; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 15px; line-height: 1.5;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main { max-width: 980px; margin: 0 auto; padding-block: 28px 64px; display: grid; gap: 22px; }
h1 { font-size: 1.6rem; margin: 0; text-wrap: balance; }
h2 { font-size: 1.05rem; margin: 0; display: flex; align-items: center; gap: 8px; font-family: var(--mono); letter-spacing: .02em; }
p { margin: 0; }
.lead { color: var(--muted); max-width: 70ch; }
nav { display: flex; flex-wrap: wrap; gap: 6px; position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5;
  background: var(--bg); padding-block: 8px; }
nav a { font: 500 .85rem var(--mono); color: var(--fg); text-decoration: none; border: 1px solid var(--line);
  border-radius: 999px; padding: 3px 10px; display: inline-flex; align-items: center; gap: 6px; background: var(--panel); }
nav a:focus-visible { outline: 2px solid var(--l-graph); outline-offset: 2px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--lc); flex: none; display: inline-block; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--muted); font-size: .85rem; align-items: center; }
.legend .k { width: 46px; height: 40px; font-size: .8rem; }
.legend span.item { display: inline-flex; align-items: center; gap: 8px; }
.layer { background: var(--panel); border: 1px solid var(--line); border-top: 3px solid var(--lc); border-radius: 10px;
  padding: 16px 18px 18px; display: grid; gap: 12px; min-width: 0; scroll-margin-top: 56px; }
.layer header { display: grid; gap: 4px; }
.layer header p { color: var(--muted); }
.acts { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: .82rem; color: var(--muted); }
.acts li::before { content: "↳ "; color: var(--lc); }
.scroll { overflow-x: auto; }
.board { min-width: 640px; display: grid; gap: 6px; }
.row { display: grid; grid-template-columns: repeat(6, 1fr) .55fr repeat(6, 1fr); gap: 6px; }
.k { position: relative; aspect-ratio: 1 / .86; background: var(--key); border: 1px solid var(--key-edge);
  border-bottom-width: 3px; border-radius: 7px; display: grid; place-items: center; align-content: center; gap: 1px;
  padding: 2px; min-width: 0; }
.tap { font-size: 1.15rem; line-height: 1.1; text-align: center; overflow-wrap: anywhere; }
.tap.long { font-size: .78rem; }
.hold { font: 600 .66rem var(--mono); color: var(--muted); text-transform: none; letter-spacing: .02em; }
.lt { border-bottom-color: var(--lc); }
.lt .hold { color: var(--lc); }
.ht .hold { color: var(--muted); }
.to, .lang { border-color: var(--lc, var(--l-fn)); }
.to .tap, .lang .tap { font: 600 .78rem var(--mono); color: var(--lc, var(--fg)); }
.trans { background: transparent; border-style: dashed; border-bottom-width: 1px; }
.trans .tap { color: var(--faint); font-size: .8rem; }
.none { background: transparent; border-color: transparent; }
.none::after { content: ""; width: 30%; height: 1px; background: var(--line); }
.alt { position: absolute; top: 2px; right: 4px; font-size: .72rem; color: var(--l-cyr); }
.mark { outline: 2px dashed var(--mark); outline-offset: 1px; }
.flag { position: absolute; bottom: 2px; left: 4px; font: 600 .55rem var(--mono); color: var(--mark); text-transform: uppercase; }
.legend .alt { position: static; }
.pad { visibility: hidden; }
footer { color: var(--muted); font-size: .82rem; }
.variants .tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.variants input { position: absolute; opacity: 0; pointer-events: none; }
.variants label { font: 600 .9rem var(--mono); border: 1px solid var(--line); border-radius: 8px; padding: 6px 12px;
  cursor: pointer; background: var(--bg); display: inline-flex; gap: 8px; align-items: baseline; }
.variants label small { font: 500 .75rem var(--mono); color: var(--muted); }
.variants .panel { display: none; gap: 10px; }
.variants .panel p { color: var(--muted); font-size: .88rem; }
code { font-family: var(--mono); font-size: .9em; }
"""


def variants_html(variants, d):
    """variants: [(код, опис, штраф, шлях_дампу)] -> секція з вкладками шару CYR.
    Відкрита за замовчуванням остання; клавіші, що відрізняються від першої, обведені."""
    if not variants:
        return ""
    import json
    cyr = []
    for code, about, score, path in variants:
        raw = json.load(open(path, encoding="utf-8"))
        cyr.append(next(l for l in raw["layers"] if l["name"] == "CYR")["bindings"])
    first = cyr[0]
    inputs, labels, panels, css = [], [], [], []
    for n, ((code, about, score, path), bb) in enumerate(zip(variants, cyr)):
        vid = f"v-{n}"
        diff = {i for i, b in enumerate(bb) if list(b) != list(first[i])} if n else set()
        rows = []
        for row in ROWS:
            rows.append('<div class="row">' + "".join(
                '<div class="gap"></div>' if i is None else key_html(bb[i], "CYR", i, diff) for i in row) + "</div>")
        th = ['<div class="gap"></div>' if i is None else key_html(bb[i], "CYR", i, diff) for i in THUMBS]
        rows.append('<div class="row thumbs"><div class="pad"></div><div class="pad"></div><div class="pad"></div>'
                    + "".join(th) + '<div class="pad"></div><div class="pad"></div><div class="pad"></div></div>')
        note = f"{esc(about)} · штраф {esc(score)} · <code>{esc(os.path.basename(path))}</code>"
        if n:
            note += f" · обведено {len(diff)} клавіш, що відрізняються від {esc(variants[0][0])}"
        checked = " checked" if n == len(variants) - 1 else ""
        inputs.append(f'<input type="radio" name="variant" id="{vid}"{checked}>')
        labels.append(f'<label for="{vid}">{esc(code)} <small>{esc(score)}</small></label>')
        panels.append(f'<div class="panel" id="p-{n}"><p>{note}</p>'
                      f'<div class="scroll"><div class="board">{"".join(rows)}</div></div></div>')
        css.append(f'#{vid}:checked ~ .panels #p-{n} {{ display: grid; }}'
                   f'#{vid}:checked ~ .tabs label[for="{vid}"] {{ border-color: var(--lc); background: var(--panel); box-shadow: inset 0 -2px 0 var(--lc); }}'
                   f'#{vid}:focus-visible ~ .tabs label[for="{vid}"] {{ outline: 2px solid var(--lc); outline-offset: 2px; }}')
    return f'''<style>{"".join(css)}</style>
<section class="layer variants" id="variants" style="--lc: var(--l-cyr)">
  <header><h2><span class="dot"></span>Розкладки CYR</h2><p>Варіанти кириличного шару для порівняння. Щоб повернутись на якийсь, скажи Claude його літеру.</p></header>
  {"".join(inputs)}
  <div class="tabs" role="tablist">{"".join(labels)}</div>
  <div class="panels">{"".join(panels)}</div>
</section>'''


def render(dump_path, marks=None, variants=None):
    """Дамп studio.py (файл) -> HTML-сторінка схеми шарів."""
    d = dl.load(dump_path)
    marks = marks or {}
    layers = {l["name"]: l for l in d["layers"]}
    order = [n for n in ORDER if n in layers] + [n for n in layers if n not in ORDER]
    nav = ('<a href="#variants" style="--lc: var(--l-cyr)"><span class="dot"></span>' + " / ".join(esc(v[0]) for v in variants) + '</a>' if variants else "") + "".join(f'<a href="#{n.lower().replace("_", "-")}" style="--lc: var(--l-{n.lower().replace("_", "-")})">'
                  f'<span class="dot"></span>{n}</a>' for n in order)
    secs = "\n".join(layer_html(layers[n], d, marks) for n in order)
    legend = ('<div class="legend">'
              '<span class="item"><div class="k key"><span class="tap">a</span></div>клавіша</span>'
              '<span class="item"><div class="k ht"><span class="tap">t</span><span class="hold">Shift</span></div>тап / утримання</span>'
              '<span class="item"><div class="k lt" style="--lc: var(--l-symbol)"><span class="tap">_</span><span class="hold">SYMBOL</span></div>утримання вмикає шар</span>'
              '<span class="item"><div class="k trans"><span class="tap">▽</span></div>прозора (як шар нижче)</span>'
              '<span class="item"><div class="k none"></div>порожня</span>'
              '<span class="item"><div class="k key"><span class="tap">?</span><span class="alt">,</span></div>у кутку — що в кирилиці</span>'
              '</div>')
    src = os.path.basename(str(dump_path))
    page = f"""<title>Corne Layers</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<main>
  <header style="display:grid;gap:6px">
    <h1>Шари Corne</h1>
    <p class="lead">Усі шари клавіатури: кожен підписаний символами своєї мови. Наведи курсор на клавішу, щоб побачити її назву. Позначення: ⌃ Ctrl, ⌥ Alt/Option, ◆ Win/Cmd, ⇧ Shift.</p>
  </header>
  <nav aria-label="Шари">{nav}</nav>
  {legend}
  {variants_html(variants, d)}
  {secs}
  <footer>Згенеровано з <code>{esc(src)}</code> скриптом <code>scripts/zmk/layers_html.py</code>.</footer>
</main>
"""
    return page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("out")
    ap.add_argument("--mark", action="append", default=[], help="ШАР:поз,поз")
    ap.add_argument("--variant", action="append", default=[], help="код|опис|штраф|дамп.json")
    a = ap.parse_args()
    marks = {}
    for m in a.mark:
        L, ps = m.split(":")
        marks[L] = {int(x) for x in ps.split(",")}
    page = render(a.dump, marks, [tuple(v.split("|", 3)) for v in a.variant])
    open(a.out, "w", encoding="utf-8").write(page)
    print("записано", a.out, len(page), "байт")


if __name__ == "__main__":
    main()

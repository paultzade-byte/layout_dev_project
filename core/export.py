"""Експорт розкладки в ОС: Windows (.klc для MSKLC), Linux (xkb), macOS (.keylayout).

Одна таблиця на всі формати — `keymap()`: {xkb-назва фізичної клавіші:
[без модифікатора, Shift, AltGr, Shift+AltGr]}. Літерні клавіші — з розкладки
(позиції з полем `key` у geometry.json), AltGr-символи — `altgr` геометрії
(ї на і, ґ на г, апостроф); цифровий ряд — як у ЙЦУКЕН (Ukrainian Enhanced).
Модуль без залежностей від GUI і libxkbcommon — працює і в exe під Windows.

    python -m core.export LAYOUT.json OUT_DIR [--geometry generic_105_alpha] [--name ...]
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date
from pathlib import Path
from xml.sax.saxutils import quoteattr

DEFAULT_NAME = "Ukrainian Optimized"

# Цифровий ряд — як у Windows Ukrainian (Enhanced) / xkb ua: [base, shift, altgr]
NUMBER_ROW = {
    "AE01": ["1", "!"], "AE02": ["2", '"'], "AE03": ["3", "№"],
    "AE04": ["4", ";", "₴"], "AE05": ["5", "%"], "AE06": ["6", ":"],
    "AE07": ["7", "?"], "AE08": ["8", "*"], "AE09": ["9", "("],
    "AE10": ["0", ")"], "AE11": ["-", "_"], "AE12": ["=", "+"],
}

# Shift для розділових знаків, що мають власну клавішу (у ЙЦУКЕН . і , на одній)
PUNCT_SHIFT = {",": ";", ".": ":", "'": "ʼ", "/": "?", "\\": "/"}

# Shift+AltGr для AltGr-символу: велика літера, а для апострофа — ʼ (U+02BC,
# «правильний» український апостроф; простий ' — на AltGr)
ALTGR_SHIFT = {"'": "ʼ"}


_BREAKING = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


def _one_line_name(name: str) -> str:
    """Назва розкладки (CLI --name) одним рядком: керівні символи (переноси,
    таби…, U+2028/2029) -> пробіл. Порожня -> DEFAULT_NAME."""
    name = "".join(" " if unicodedata.category(c) in _BREAKING else c for c in str(name)).strip()
    return name or DEFAULT_NAME


def _quoted_name(name: str) -> str:
    """Назва для рядка в лапках .klc / xkb: екранування там нема (klc) або
    воно своє (xkb, \\), тож лапки -> ', зворотна похила -> /."""
    return _one_line_name(name).replace('"', "'").replace("\\", "/")


def _upper(ch: str) -> str:
    up = ch.upper()
    return up if len(up) == 1 else ch


def _shifted(ch: str) -> str:
    if ch.isalpha():
        return _upper(ch)
    return PUNCT_SHIFT.get(ch, ch)


def keymap(chars: dict[int, str], geometry: dict) -> dict[str, list]:
    """{xkb-клавіша: [l1, l2, l3, l4]} (None — рівня нема).

    chars — {position_id: символ} розкладки; geometry — конфіг геометрії з
    полями `key` у позиціях і (необов'язково) `altgr`.
    """
    altgr = geometry.get("altgr", {})
    out = {name: (levels + [None] * 4)[:4] for name, levels in NUMBER_ROW.items()}
    seen = {}
    for pos in geometry["positions"]:
        name = pos.get("key")
        if not name:
            continue
        ch = chars.get(pos["id"])
        if not ch or len(ch) != 1:
            raise ValueError(f"клавіша {name} (позиція {pos['id']}) без символу: {ch!r}")
        if ch in seen:
            raise ValueError(f"символ {ch!r} двічі: {seen[ch]} і {name}")
        seen[ch] = name
        third = altgr.get(ch)
        fourth = (ALTGR_SHIFT.get(third) or _upper(third)) if third else None
        out[name] = [ch, _shifted(ch), third, fourth]
    missing = set(altgr) - set(seen)
    if missing:
        raise ValueError(f"AltGr-символи для літер, яких нема на розкладці: {sorted(missing)}")
    return out


def load_chars(path) -> dict[int, str]:
    with open(path, "r", encoding="utf-8") as file:
        return {d["position_id"]: d["char"] for d in json.load(file)}


def chars_from_keys(keys) -> dict[int, str]:
    return {k.position_id: k.char for k in keys}


# ----------------------------------------------------------------------
# Windows: .klc (Microsoft Keyboard Layout Creator 1.4)
# ----------------------------------------------------------------------
# xkb -> (скан-код, VK). VK — позиційні, як у штатній українській розкладці:
# Ctrl+C / Ctrl+V лишаються на фізичних C / V.
_WIN_ROWS = [
    ("AE", 1, ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "OEM_MINUS", "OEM_PLUS"], 0x02),
    ("AD", 1, ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "OEM_4", "OEM_6"], 0x10),
    ("AC", 1, ["A", "S", "D", "F", "G", "H", "J", "K", "L", "OEM_1", "OEM_7"], 0x1E),
    ("AB", 1, ["Z", "X", "C", "V", "B", "N", "M", "OEM_COMMA", "OEM_PERIOD", "OEM_2"], 0x2C),
]
WIN_KEYS = {"TLDE": (0x29, "OEM_3"), "BKSL": (0x2B, "OEM_5")}
for _prefix, _first, _vks, _sc in _WIN_ROWS:
    for _i, _vk in enumerate(_vks):
        WIN_KEYS[f"{_prefix}{_i + _first:02d}"] = (_sc + _i, _vk)

# Ctrl+клавіша, що дає керівний символ (як у штатних розкладках)
_WIN_CTRL = {"OEM_4": 0x1B, "OEM_6": 0x1D, "OEM_5": 0x1C, "OEM_102": 0x1C,
             "6": 0x1E, "OEM_MINUS": 0x1F}

_KLC_KEYNAME = """KEYNAME

01\tEsc
0e\tBackspace
0f\tTab
1c\tEnter
1d\tCtrl
2a\tShift
36\t"Right Shift"
37\t"Num *"
38\tAlt
39\tSpace
3a\t"Caps Lock"
3b\tF1
3c\tF2
3d\tF3
3e\tF4
3f\tF5
40\tF6
41\tF7
42\tF8
43\tF9
44\tF10
45\tPause
46\t"Scroll Lock"
47\t"Num 7"
48\t"Num 8"
49\t"Num 9"
4a\t"Num -"
4b\t"Num 4"
4c\t"Num 5"
4d\t"Num 6"
4e\t"Num +"
4f\t"Num 1"
50\t"Num 2"
51\t"Num 3"
52\t"Num 0"
53\t"Num Del"
54\t"Sys Req"
57\tF11
58\tF12
7c\tF13
7d\tF14
7e\tF15
7f\tF16
80\tF17
81\tF18
82\tF19
83\tF20
84\tF21
85\tF22
86\tF23
87\tF24

KEYNAME_EXT

1c\t"Num Enter"
1d\t"Right Ctrl"
35\t"Num /"
37\t"Prnt Scrn"
38\t"Right Alt"
45\t"Num Lock"
46\tBreak
47\tHome
48\tUp
49\t"Page Up"
4b\tLeft
4d\tRight
4f\tEnd
50\tDown
51\t"Page Down"
52\tInsert
53\tDelete
54\t<00>
56\tHelp
5b\t"Left Windows"
5c\t"Right Windows"
5d\tApplication
"""


def _klc_char(ch) -> str:
    return "-1" if ch is None else f"{ord(ch):04x}"


def _klc_comment(levels) -> str:
    shown = [c if c and unicodedata.category(c)[0] not in "CZ" else "" for c in levels]
    return " // " + ", ".join(c for c in shown if c)


def klc_text(km: dict[str, list], name: str = DEFAULT_NAME, kbd_id: str = "ukropt") -> str:
    """Вміст .klc (писати в UTF-16 з BOM — `write_klc`)."""
    rows = []
    for xname, (sc, vk) in sorted(WIN_KEYS.items(), key=lambda kv: kv[1][0]):
        l1, l2, l3, l4 = km[xname]
        caps = 0
        if l1.isalpha():
            caps = 1 | (4 if l3 and l3.isalpha() else 0)  # 4: Caps діє і на AltGr (ї -> Ї)
        ctrl = _WIN_CTRL.get(vk)
        cols = [_klc_char(l1), _klc_char(l2), "-1" if ctrl is None else f"{ctrl:04x}",
                _klc_char(l3), _klc_char(l4)]
        rows.append(f"{sc:02x}\t{vk}\t\t{caps}\t" + "\t".join(cols) + _klc_comment([l1, l2, l3, l4]))
    # ISO-клавіша між лівим Shift і Z (на ANSI нема) — як \ у штатній розкладці
    rows.append("56\tOEM_102\t\t0\t005c\t007c\t001c\t-1\t-1 // \\, |")
    rows.append("39\tSPACE\t\t0\t0020\t0020\t0020\t-1\t-1")
    rows.append("53\tDECIMAL\t\t0\t002c\t002c\t-1\t-1\t-1 // ,")
    name = _quoted_name(name)
    return f"""KBD\t{kbd_id}\t"{name}"

COPYRIGHT\t"(c) {date.today().year}"

COMPANY\t"ukr-layout"

LOCALENAME\t"uk-UA"

LOCALEID\t"00000422"

VERSION\t1.0

SHIFTSTATE

0\t//Column 4
1\t//Column 5 : Shft
2\t//Column 6 :       Ctrl
6\t//Column 7 :       Ctrl Alt
7\t//Column 8 : Shft  Ctrl Alt

LAYOUT\t\t;an extra '@' at the end is a dead key

//SC\tVK_\t\tCap\t0\t1\t2\t6\t7
//--\t----\t\t----\t----\t----\t----\t----\t----

""" + "\n".join(rows) + f"""


{_KLC_KEYNAME}
DESCRIPTIONS

0409\t{name}
0422\t{name}

LANGUAGENAMES

0409\tUkrainian (Ukraine)
0422\tУкраїнська (Україна)

ENDKBD
"""


def write_klc(path, km, name=DEFAULT_NAME) -> Path:
    path = Path(path)
    # MSKLC читає UTF-16 LE з BOM і CRLF
    path.write_bytes(b"\xff\xfe" + klc_text(km, name).replace("\n", "\r\n").encode("utf-16-le"))
    return path


# ----------------------------------------------------------------------
# Linux: xkb symbols
# ----------------------------------------------------------------------
_CYR_NAMES = {
    "а": "a", "б": "be", "в": "ve", "г": "ghe", "д": "de", "е": "ie", "ж": "zhe",
    "з": "ze", "и": "i", "й": "shorti", "к": "ka", "л": "el", "м": "em", "н": "en",
    "о": "o", "п": "pe", "р": "er", "с": "es", "т": "te", "у": "u", "ф": "ef",
    "х": "ha", "ц": "tse", "ч": "che", "ш": "sha", "щ": "shcha", "ь": "softsign",
    "ю": "yu", "я": "ya",
}
XKB_KEYSYMS = {}
for _ch, _n in _CYR_NAMES.items():
    XKB_KEYSYMS[_ch] = f"Cyrillic_{_n}"
    XKB_KEYSYMS[_ch.upper()] = f"Cyrillic_{_n.upper()}"
XKB_KEYSYMS.update({
    "є": "Ukrainian_ie", "Є": "Ukrainian_IE", "і": "Ukrainian_i", "І": "Ukrainian_I",
    "ї": "Ukrainian_yi", "Ї": "Ukrainian_YI",
    "ґ": "Ukrainian_ghe_with_upturn", "Ґ": "Ukrainian_GHE_WITH_UPTURN",
    ",": "comma", ".": "period", ";": "semicolon", ":": "colon", "'": "apostrophe",
    '"': "quotedbl", "!": "exclam", "?": "question", "%": "percent", "*": "asterisk",
    "(": "parenleft", ")": "parenright", "-": "minus", "_": "underscore",
    "=": "equal", "+": "plus", "/": "slash", "\\": "backslash", "|": "bar",
    "№": "numerosign",
})


def xkb_keysym(ch) -> str:
    if ch is None:
        return "NoSymbol"
    if ch in XKB_KEYSYMS:
        return XKB_KEYSYMS[ch]
    if "0" <= ch <= "9":
        return ch
    return f"U{ord(ch):04X}"


def _xkb_type(levels) -> str | None:
    l1, l2, l3, _ = levels
    if l3 is None:
        return "ALPHABETIC" if l1.isalpha() else "TWO_LEVEL"
    if l1.isalpha() and l3.isalpha():
        return "FOUR_LEVEL_ALPHABETIC"
    return "FOUR_LEVEL_SEMIALPHABETIC" if l1.isalpha() else "FOUR_LEVEL"


def xkb_text(km: dict[str, list], name: str = DEFAULT_NAME, variant: str = "basic") -> str:
    order = (["TLDE"] + [f"AE{i:02d}" for i in range(1, 13)] + [f"AD{i:02d}" for i in range(1, 13)]
             + ["BKSL"] + [f"AC{i:02d}" for i in range(1, 12)] + [f"AB{i:02d}" for i in range(1, 11)])
    rows = []
    for xname in order:
        levels = km[xname]
        used = [l for l in levels if l is not None] if levels[2] else levels[:2]
        syms = ", ".join(xkb_keysym(c) for c in used)
        shown = " ".join(c for c in used if c)
        rows.append(f'    key <{xname}> {{ type[Group1] = "{_xkb_type(levels)}", '
                    f"[ {syms} ] }};  // {shown}")
    body = "\n".join(rows)
    name = _quoted_name(name)
    return f"""// {name} — згенеровано оптимізатором розкладки (core/export.py)
// AltGr = правий Alt (level3(ralt_switch)).
default partial alphanumeric_keys
xkb_symbols "{variant}" {{
    name[Group1] = "{name}";

{body}

    include "level3(ralt_switch)"
}};
"""


# ----------------------------------------------------------------------
# macOS: .keylayout (Option = AltGr)
# ----------------------------------------------------------------------
# xkb-назва -> віртуальний код macOS (kVK_*, ANSI)
MAC_VK = {
    "TLDE": 50, "LSGT": 10, "BKSL": 42, "SPCE": 49,
    **dict(zip([f"AE{i:02d}" for i in range(1, 13)],
               [18, 19, 20, 21, 23, 22, 26, 28, 25, 29, 27, 24])),
    **dict(zip([f"AD{i:02d}" for i in range(1, 13)],
               [12, 13, 14, 15, 17, 16, 32, 34, 31, 35, 33, 30])),
    **dict(zip([f"AC{i:02d}" for i in range(1, 12)],
               [0, 1, 2, 3, 5, 4, 38, 40, 37, 41, 39])),
    **dict(zip([f"AB{i:02d}" for i in range(1, 11)],
               [6, 7, 8, 9, 11, 45, 46, 43, 47, 44])),
}

# Службові клавіші: однакові в усіх мапах (як у стандартних розкладках Apple)
MAC_SPECIAL = {
    36: "\r", 48: "\t", 51: "\b", 53: "\x1b", 52: "\x03", 76: "\x03",
    71: "\x1b", 114: "\x05", 115: "\x01", 116: "\x0b", 117: "\x7f",
    119: "\x04", 121: "\x0c", 123: "\x1c", 124: "\x1d", 125: "\x1f",
    126: "\x1e",
    **{vk: "\x10" for vk in (122, 120, 99, 118, 96, 97, 98, 100, 101, 109,
                             103, 111, 105, 107, 113, 106, 64, 79, 80, 90)},
    65: ".", 67: "*", 69: "+", 75: "/", 78: "-", 81: "=",
    **dict(zip([82, 83, 84, 85, 86, 87, 88, 89, 91, 92], "0123456789")),
}

# Латиниця QWERTY для Cmd-шорткатів і Control (за фізичною клавішею)
_US = dict(zip(
    ["TLDE"] + [f"AE{i:02d}" for i in range(1, 13)] + [f"AD{i:02d}" for i in range(1, 13)]
    + ["BKSL"] + [f"AC{i:02d}" for i in range(1, 12)] + [f"AB{i:02d}" for i in range(1, 11)],
    zip("`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./",
        '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?')))
_US["LSGT"] = ("§", "±")
_US["SPCE"] = (" ", " ")


def mac_control_char(c):
    if c and "a" <= c <= "z":
        return chr(ord(c) - 96)
    return {"[": "\x1b", "\\": "\x1c", "]": "\x1d"}.get(c, c)


def mac_esc(c: str) -> str:
    """Видимі знаки — як є (щоб файл можна було прочитати очима), решта — &#x..;"""
    def one(ch):
        cat = unicodedata.category(ch)
        if ch in '&<>"\'' or cat[0] in "CZM" or ch == "":
            return f"&#x{ord(ch):04X};"
        return ch
    return "".join(one(ch) for ch in c)


def mac_keymap_xml(index, mapping):
    rows = [f'      <keyMap index="{index}">']
    for vk in sorted(set(mapping) | set(MAC_SPECIAL)):
        c = MAC_SPECIAL.get(vk, mapping.get(vk))
        if c:
            rows.append(f'        <key code="{vk}" output="{mac_esc(c)}"/>')
    rows.append("      </keyMap>")
    return "\n".join(rows)


def mac_keylayout_xml(name, group, kid, maps):
    """maps — 8 мап {vk: символ}: без модифікатора, Shift, Caps, Option,
    Shift+Option, Cmd, Cmd+Shift, Control."""
    sel = [
        "",                                       # 0 без модифікаторів
        "anyShift caps?",                         # 1 Shift
        "caps",                                   # 2 Caps Lock
        "anyOption caps?",                        # 3 Option
        "anyShift anyOption caps?",               # 4 Shift+Option
        "command caps? anyOption?",               # 5 Cmd (шорткати)
        "command anyShift caps? anyOption?",      # 6 Cmd+Shift
        "anyControl anyShift? caps? anyOption? command?",  # 7 Control
    ]
    mm = "\n".join(
        f'    <keyMapSelect mapIndex="{i}"><modifier keys="{k}"/></keyMapSelect>'
        for i, k in enumerate(sel))
    km = "\n".join(mac_keymap_xml(i, m) for i, m in enumerate(maps))
    return f"""<?xml version="1.1" encoding="UTF-8"?>
<!DOCTYPE keyboard SYSTEM "file://localhost/System/Library/DTDs/KeyboardLayout.dtd">
<keyboard group="{group}" id="{kid}" name={quoteattr(_one_line_name(name))} maxout="1">
  <layouts>
    <layout first="0" last="255" modifiers="mods" mapSet="maps"/>
  </layouts>
  <modifierMap id="mods" defaultIndex="0">
{mm}
  </modifierMap>
  <keyMapSet id="maps">
{km}
  </keyMapSet>
</keyboard>
"""


def keylayout_text(km: dict[str, list], name: str = DEFAULT_NAME) -> str:
    full = dict(km)
    full.setdefault("LSGT", ["\\", "|", None, None])
    full["SPCE"] = [" ", " ", " ", " "]
    vk = {x: MAC_VK[x] for x in full}
    base = {vk[x]: l[0] for x, l in full.items()}
    shift = {vk[x]: l[1] or l[0] for x, l in full.items()}
    caps = {vk[x]: (l[1] if l[0].isalpha() else l[0]) for x, l in full.items()}
    opt = {vk[x]: l[2] or l[0] for x, l in full.items()}
    shopt = {vk[x]: l[3] or l[2] or l[1] or l[0] for x, l in full.items()}
    us_base = {MAC_VK[x]: u[0] for x, u in _US.items()}
    us_shift = {MAC_VK[x]: u[1] for x, u in _US.items()}
    ctrl = {v: mac_control_char(c) for v, c in us_base.items()}
    return mac_keylayout_xml(name, 7, -27481,
                             [base, shift, caps, opt, shopt, us_base, us_shift, ctrl])


# ----------------------------------------------------------------------
# Усе разом + інструкція
# ----------------------------------------------------------------------
FILE_STEM = "ukr_optimized"

README = """{name} — як встановити
{line}

Розкладка: AltGr (правий Alt; на маку — Option) + {altgr}.
Shift+AltGr над апострофом — ʼ (U+02BC). Цифровий ряд — як у звичайній
українській (Shift+4 = ;, Shift+6 = :, Shift+7 = ?), AltGr+4 = ₴.

Windows — {stem}.klc
  1. Встановіть Microsoft Keyboard Layout Creator 1.4 (безкоштовно, з сайту
     Microsoft).
  2. MSKLC: File → Load Source File… → {stem}.klc.
  3. Project → Build DLL and Setup Package. MSKLC збере інсталятор
     (setup.exe) у теці Документи\\{kbd}.
  4. Запустіть setup.exe, перезайдіть у систему (або перезавантажтесь).
  5. Параметри → Час і мова → Мова → Українська → Параметри мови →
     Додати клавіатуру → «{name}». Штатну українську можна прибрати.

Linux (X11) — {stem}.xkb
  Без root, лише на поточну сесію:
    mkdir -p ~/.config/xkb/symbols
    cp {stem}.xkb ~/.config/xkb/symbols/{stem}
    setxkbmap -I ~/.config/xkb -layout us,{stem} -option grp:alt_shift_toggle -print \\
      | xkbcomp -I$HOME/.config/xkb - $DISPLAY
  (us,{stem} — латиниця і ця розкладка, перемикання Alt+Shift; підставте
  свій перемикач.) Щоб діяло після входу — додайте ці два рядки в автозапуск.
  Wayland (GNOME/KDE): libxkbcommon читає ~/.config/xkb/symbols/, але щоб
  розкладка з'явилась у налаштуваннях, її треба ще описати в
  ~/.config/xkb/rules/evdev.xml — інструкція середовища; не перевірено.

macOS — {stem}.keylayout
  1. Скопіюйте {stem}.keylayout у ~/Library/Keyboard Layouts/
     (Finder → Перехід → Перейти до теки…).
  2. Вийдіть із системи й увійдіть знову.
  3. Системні параметри → Клавіатура → Джерела вводу → «+» → Інші →
     «{name}».
  Cmd-шорткати (Cmd+C/V…) — за латиницею QWERTY на тих самих клавішах.
"""


def export_all(chars: dict[int, str], geometry: dict, out_dir, name: str = DEFAULT_NAME) -> list[Path]:
    """Записує .klc, .xkb, .keylayout і README в out_dir; повертає шляхи."""
    km = keymap(chars, geometry)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [write_klc(out / f"{FILE_STEM}.klc", km, name)]
    for suffix, text in ((".xkb", xkb_text(km, name)), (".keylayout", keylayout_text(km, name))):
        path = out / f"{FILE_STEM}{suffix}"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    altgr = ", ".join(f"{k} → {v}" for k, v in geometry.get("altgr", {}).items()) or "—"
    readme = out / "README.txt"
    readme.write_text(README.format(name=name, line="=" * (len(name) + 18), altgr=altgr,
                                    stem=FILE_STEM, kbd="ukropt"), encoding="utf-8")
    paths.append(readme)
    return paths


def main(argv=None):
    from config.main_config import geometry_config
    parser = argparse.ArgumentParser(description="Експорт розкладки в .klc / xkb / .keylayout")
    parser.add_argument("layout", help="JSON розкладки (формат «Зберегти»)")
    parser.add_argument("out_dir")
    parser.add_argument("--geometry", default="generic_105_alpha")
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args(argv)
    for path in export_all(load_chars(args.layout), geometry_config(args.geometry), args.out_dir, args.name):
        print("записано", path)


if __name__ == "__main__":
    main()

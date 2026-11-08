"""Генерує macOS-розкладки (.keylayout), що друкують те саме, що Linux xkb.

Мета: однакова поведінка клавіатури (Corne, ZMK) на Linux і на маку без
змін у прошивці. RAlt на Linux (lv3:ralt_switch) = Option на маку.

    python scripts/macos_keylayout.py KEYMAP.xkb OUT_DIR

KEYMAP.xkb — `xkbcomp -xkb $DISPLAY KEYMAP.xkb` з layout us,ua (група 1 — us,
група 2 — ua). Результат:
- `Ukrainian Corne.keylayout` — копія xkb ua(unicode): рівні 1-4 = без
  модифікатора / Shift / Option / Shift+Option; де рівня 3-4 немає — те саме,
  що без Option. Cmd-шорткати — латиниця QWERTY.
- `US Corne.keylayout` — копія xkb us (рівні 1-2) + Option-символи
  маківської ABC без мертвих клавіш (акценти друкуються як окремі знаки);
  єдина зміна проти ABC: Shift+Option+\\ = | (як Shift+RAlt+\\ на Linux).
Віртуальні коди маку — ANSI (перевірено тестом автора 2026-11-02:
HID 0x35 -> `, HID 0x64 -> §).
"""

import ctypes
import re
import sys
from pathlib import Path

# xkb-назва клавіші -> віртуальний код macOS (kVK_*)
XKB_TO_VK = {
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
SPECIAL = {
    36: "\r", 48: "\t", 51: "\b", 53: "\x1b", 52: "\x03", 76: "\x03",
    71: "\x1b", 114: "\x05", 115: "\x01", 116: "\x0b", 117: "\x7f",
    119: "\x04", 121: "\x0c", 123: "\x1c", 124: "\x1d", 125: "\x1f",
    126: "\x1e",
    **{vk: "\x10" for vk in (122, 120, 99, 118, 96, 97, 98, 100, 101, 109,
                             103, 111, 105, 107, 113, 106, 64, 79, 80, 90)},
    65: ".", 67: "*", 69: "+", 75: "/", 78: "-", 81: "=",
    **dict(zip([82, 83, 84, 85, 86, 87, 88, 89, 91, 92], "0123456789")),
}

# Option / Shift+Option маківської ABC (мертві клавіші -> окремий знак)
US_KEYS = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
ABC_OPT = "`¡™£¢∞§¶•ªº–≠œ∑´®†¥¨ˆøπ“‘«åß∂ƒ©˙∆˚¬…æΩ≈ç√∫˜µ≤≥÷"
ABC_SHOPT = "`⁄€‹›ﬁﬂ‡°·‚—±Œ„´‰ˇÁ¨ˆØ∏”’|ÅÍÎÏ˝ÓÔÒÚÆ¸˛Ç◊ı˜Â¯˘¿"
assert len(US_KEYS) == len(ABC_OPT) == len(ABC_SHOPT)

_xkb = ctypes.CDLL("libxkbcommon.so.0")
_xkb.xkb_keysym_from_name.restype = ctypes.c_uint32
_xkb.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
_xkb.xkb_keysym_to_utf32.restype = ctypes.c_uint32
_xkb.xkb_keysym_to_utf32.argtypes = [ctypes.c_uint32]


def keysym_char(name):
    if name in ("NoSymbol", "VoidSymbol"):
        return None
    cp = _xkb.xkb_keysym_to_utf32(_xkb.xkb_keysym_from_name(name.encode(), 0))
    return chr(cp) if cp else None


def parse_xkb(path):
    """{xkb-клавіша: {група: [символи рівнів]}} із дампу xkbcomp."""
    text = Path(path).read_text()
    body = text[text.index("xkb_symbols"):]
    keys = {}
    for m in re.finditer(r"key <(\w+)> \{(.*?)\};", body, re.S):
        name, inner = m.groups()
        groups = {}
        for g, syms in re.findall(r"symbols\[Group(\d)\]\s*=\s*\[(.*?)\]", inner):
            groups[int(g)] = [s.strip() for s in syms.split(",")]
        if not groups:
            plain = re.search(r"\[(.*?)\]", inner)
            if plain:
                groups[1] = [s.strip() for s in plain.group(1).split(",")]
        keys[name] = groups
    return keys


def levels(keys, group):
    """{vk: [l1, l2, l3, l4]} — символи; група 2 без визначення -> група 1."""
    out = {}
    for xname, vk in XKB_TO_VK.items():
        g = keys.get(xname, {})
        syms = g.get(group) or g.get(1) or []
        chars = [keysym_char(s) for s in syms] + [None] * 4
        out[vk] = chars[:4]
    return out


def control_char(c):
    if c and "a" <= c <= "z":
        return chr(ord(c) - 96)
    return {"[": "\x1b", "\\": "\x1c", "]": "\x1d"}.get(c, c)


def esc(c):
    """Видимі знаки — як є (щоб файл можна було прочитати очима), решта — &#x..;"""
    import unicodedata
    def one(ch):
        cat = unicodedata.category(ch)
        if ch in '&<>"\'' or cat[0] in "CZM" or ch == "\uf8ff":
            return f"&#x{ord(ch):04X};"
        return ch
    return "".join(one(ch) for ch in c)


def keymap_xml(index, mapping):
    rows = [f'      <keyMap index="{index}">']
    for vk in sorted(set(mapping) | set(SPECIAL)):
        c = SPECIAL.get(vk, mapping.get(vk))
        if c:
            rows.append(f'        <key code="{vk}" output="{esc(c)}"/>')
    rows.append("      </keyMap>")
    return "\n".join(rows)


def build(name, group, kid, maps):
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
    km = "\n".join(keymap_xml(i, m) for i, m in enumerate(maps))
    return f"""<?xml version="1.1" encoding="UTF-8"?>
<!DOCTYPE keyboard SYSTEM "file://localhost/System/Library/DTDs/KeyboardLayout.dtd">
<keyboard group="{group}" id="{kid}" name="{name}" maxout="1">
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


def main(xkb_path, out_dir):
    keys = parse_xkb(xkb_path)
    us, ua = levels(keys, 1), levels(keys, 2)
    us_base = {vk: l[0] for vk, l in us.items()}
    us_shift = {vk: l[1] or l[0] for vk, l in us.items()}
    ctrl = {vk: control_char(c) for vk, c in us_base.items()}
    caps = lambda lv: {vk: (l[1] if l[0] and l[0].isalpha() and l[1] else l[0])
                       for vk, l in lv.items()}

    by_char = {c: vk for vk, c in us_base.items()}
    us_opt = dict(us_base)
    us_shopt = dict(us_shift)
    for k, o, so in zip(US_KEYS, ABC_OPT, ABC_SHOPT):
        us_opt[by_char[k]] = o
        us_shopt[by_char[k]] = so
    us_opt[49] = us_shopt[49] = " "

    ua_base = {vk: l[0] for vk, l in ua.items()}
    ua_shift = {vk: l[1] or l[0] for vk, l in ua.items()}
    ua_opt = {vk: l[2] or l[0] for vk, l in ua.items()}
    ua_shopt = {vk: l[3] or l[2] or l[1] or l[0] for vk, l in ua.items()}

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "Ukrainian Corne.keylayout": build(
            "Ukrainian Corne", 7, -27471,
            [ua_base, ua_shift, caps(ua), ua_opt, ua_shopt, us_base, us_shift, ctrl]),
        "US Corne.keylayout": build(
            "US Corne", 0, -27472,
            [us_base, us_shift, caps(us), us_opt, us_shopt, us_base, us_shift, ctrl]),
    }
    for fname, xml in files.items():
        (out / fname).write_text(xml, encoding="utf-8")
        print("записано", out / fname, len(xml), "байт")


if __name__ == "__main__":
    main(*sys.argv[1:3])

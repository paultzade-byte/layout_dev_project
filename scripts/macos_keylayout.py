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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.export import (  # noqa: E402  спільне з експортом ANSI-розкладки
    MAC_VK as XKB_TO_VK,
    mac_control_char as control_char,
    mac_keylayout_xml as build,
)

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

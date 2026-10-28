"""Клієнт протоколу ZMK Studio: читання, порівняння і запис keymap без браузера.

Ліва половина Eyelash Corne зібрана з CONFIG_ZMK_STUDIO=y і по USB дає
послідовний порт. Протокол: protobuf-повідомлення (zmkfirmware/zmk-studio-
messages) у рамках SOF 0xAB … EOF 0xAD, байти SOF/ESC/EOF екрануються 0xAC.
Блокування вимкнене (CONFIG_ZMK_STUDIO_LOCKING=n). Вкладку zmk.studio треба
закрити — порт приймає одне з'єднання.

    python scripts/zmk/studio.py dump  /dev/ttyACM2 config/zmk/keymap.json
    python scripts/zmk/studio.py show  config/zmk/keymap.json [--layer CYR]
    python scripts/zmk/studio.py diff  /dev/ttyACM2 target.json [--layer CYR]
    python scripts/zmk/studio.py write /dev/ttyACM2 target.json --layer CYR [--yes]

`write` без --yes лише показує зміни. З --yes: записує біндинги, перечитує
шар, і лише якщо він збігся з файлом — зберігає у флеш (save_changes); при
будь-якій помилці — discard_changes. Відкат — write з попереднім дампом.

Формат дампу: {"behaviors": {id: назва}, "layers": [{id, name, bindings:
[[behavior_id, param1, param2] × 48]}]}. Id behavior залежать від прошивки,
тому при записі вони зіставляються за назвою.
"""

import argparse
import json
import sys
import time

import serial

SOF, ESC, EOF = 0xAB, 0xAC, 0xAD

# --- protobuf wire format (вручну, без protoc) ---------------------------------


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, payload):
    """int -> varint-поле, bytes -> length-delimited."""
    if isinstance(payload, int):
        return _varint(num << 3) + _varint(payload)
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _zigzag(n):
    return (n << 1) ^ (n >> 31)


def _unzigzag(n):
    return (n >> 1) ^ -(n & 1)


def _decode(buf):
    """-> [(field, value)], value = int (varint) або bytes."""
    i, res = 0, []

    def rv():
        nonlocal i
        s = n = 0
        while True:
            b = buf[i]
            i += 1
            n |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                return n

    while i < len(buf):
        key = rv()
        num, wt = key >> 3, key & 7
        if wt == 0:
            res.append((num, rv()))
        elif wt == 2:
            length = rv()
            res.append((num, buf[i:i + length]))
            i += length
        elif wt in (1, 5):
            size = 8 if wt == 1 else 4
            res.append((num, buf[i:i + size]))
            i += size
        else:
            raise ValueError(f"wire type {wt}")
    return res


def _get(msg, num, default=None):
    for f, v in msg:
        if f == num:
            return v
    return default


def _getall(msg, num):
    return [v for f, v in msg if f == num]


def _unpack_varints(b):
    vals, i = [], 0
    while i < len(b):
        s = n = 0
        while True:
            x = b[i]
            i += 1
            n |= (x & 0x7F) << s
            s += 7
            if not x & 0x80:
                break
        vals.append(n)
    return vals


# --- RPC ----------------------------------------------------------------------

CORE, BEHAVIORS, KEYMAP = 3, 4, 5  # поля підсистем у zmk.studio.Request


class Studio:
    def __init__(self, port):
        self.port = serial.Serial(port, 115200, timeout=0.2)
        self.port.reset_input_buffer()
        self.request_id = 0
        self.buf = bytearray()

    def call(self, subsystem, inner, timeout=5.0):
        self.request_id += 1
        body = _field(1, self.request_id) + _field(subsystem, inner)
        frame = bytearray([SOF])
        for x in body:
            if x in (SOF, ESC, EOF):
                frame.append(ESC)
            frame.append(x)
        frame.append(EOF)
        self.port.write(frame)

        deadline = time.time() + timeout
        while time.time() < deadline:
            self.buf += self.port.read(4096)
            while (msg := self._next_frame()) is not None:
                response = _decode(msg)
                rr = _get(response, 1)  # 2 = notification, пропускаємо
                if rr is None:
                    continue
                rr = _decode(rr)
                if _get(rr, 1) != self.request_id:
                    continue
                meta = _get(rr, 2)
                if meta is not None:
                    raise RuntimeError(f"Studio meta error: {_decode(meta)}")
                return _decode(_get(rr, subsystem, b""))
        raise TimeoutError("немає відповіді від клавіатури")

    def _next_frame(self):
        if SOF not in self.buf:
            self.buf.clear()
            return None
        start = self.buf.index(SOF)
        body, j = bytearray(), start + 1
        while j < len(self.buf):
            x = self.buf[j]
            if x == EOF:
                del self.buf[:j + 1]
                return bytes(body)
            if x == ESC:
                j += 1
                if j >= len(self.buf):
                    return None
                x = self.buf[j]
            body.append(x)
            j += 1
        return None

    def behaviors(self):
        ids = _unpack_varints(_get(self.call(BEHAVIORS, _field(1, 1)), 1, b""))
        names = {}
        for bid in ids:
            details = _decode(_get(self.call(BEHAVIORS, _field(2, _field(1, bid))), 2))
            names[bid] = _get(details, 2, b"").decode()
        return names

    def keymap(self):
        km = _decode(_get(self.call(KEYMAP, _field(1, 1)), 1))
        layers = []
        for raw in _getall(km, 1):
            layer = _decode(raw)
            bindings = []
            for rb in _getall(layer, 3):
                b = _decode(rb)
                bindings.append([_unzigzag(_get(b, 1, 0)), _get(b, 2, 0), _get(b, 3, 0)])
            layers.append({"id": _get(layer, 1, 0), "name": _get(layer, 2, b"").decode(),
                           "bindings": bindings})
        return layers

    def dump(self):
        return {"behaviors": self.behaviors(), "layers": self.keymap()}

    def unsaved_changes(self):
        return bool(_get(self.call(KEYMAP, _field(3, 1)), 3, 0))

    def set_binding(self, layer_id, position, binding):
        bid, p1, p2 = binding
        b = _field(1, _zigzag(bid)) + _field(2, p1) + _field(3, p2)
        req = _field(1, layer_id) + _field(2, position) + _field(3, b)
        code = _get(self.call(KEYMAP, _field(2, req)), 2, 0)
        if code != 0:
            raise RuntimeError(f"set_layer_binding({layer_id}, {position}) -> код {code}")

    def save(self):
        # запис у флеш займає > 5 с (перевірено 2026-10-29)
        res = _decode(_get(self.call(KEYMAP, _field(4, 1), timeout=30), 4, b""))
        if not _get(res, 1, 0):
            raise RuntimeError(f"save_changes -> помилка {_get(res, 2)}")

    def discard(self):
        self.call(KEYMAP, _field(5, 1))


# --- кейкоди і підписи --------------------------------------------------------

KEY_NAMES = {0x04 + i: chr(ord("A") + i) for i in range(26)}
KEY_NAMES.update({0x1E + i: str((i + 1) % 10) for i in range(10)})
KEY_NAMES.update({0x3A + i: f"F{i + 1}" for i in range(12)})
KEY_NAMES.update({
    0x28: "RET", 0x29: "ESC", 0x2A: "BSPC", 0x2B: "TAB", 0x2C: "SPACE", 0x2D: "MINUS",
    0x2E: "EQUAL", 0x2F: "LBKT", 0x30: "RBKT", 0x31: "BSLH", 0x32: "NUHS", 0x33: "SEMI",
    0x34: "SQT", 0x35: "GRAVE", 0x36: "COMMA", 0x37: "DOT", 0x38: "FSLH", 0x39: "CAPS",
    0x46: "PSCRN", 0x47: "SCROLL", 0x48: "PAUSE", 0x49: "INS", 0x4A: "HOME", 0x4B: "PG_UP",
    0x4C: "DEL", 0x4D: "END", 0x4E: "PG_DN", 0x4F: "RIGHT", 0x50: "LEFT", 0x51: "DOWN",
    0x52: "UP", 0x54: "KP_SLASH", 0x64: "NUBS", 0x65: "K_APP",
    0xE0: "LCTRL", 0xE1: "LSHFT", 0xE2: "LALT", 0xE3: "LGUI",
    0xE4: "RCTRL", 0xE5: "RSHFT", 0xE6: "RALT", 0xE7: "RGUI",
})
CONSUMER_NAMES = {
    0xB5: "C_NEXT", 0xB6: "C_PREV", 0xB7: "C_STOP", 0xCD: "C_PP", 0xE2: "C_MUTE",
    0xE9: "C_VOL_UP", 0xEA: "C_VOL_DN", 0x6F: "C_BRI_UP", 0x70: "C_BRI_DN",
    0x221: "C_AC_SEARCH", 0x29F: "C_AC_DESKTOP_SHOW_ALL_WINDOWS",
}
MOD_NAMES = ["LC", "LS", "LA", "LG", "RC", "RS", "RA", "RG"]
_BY_NAME = {v: k for k, v in KEY_NAMES.items()}
LS = 0x02  # біт LShift у старшому байті кейкоду


def keycode(name, mods=0):
    """ZMK-кейкод: модифікатори << 24 | сторінка HID << 16 | код."""
    return (mods << 24) | (0x07 << 16) | _BY_NAME[name]


# Українська розкладка xkb `ua` (варіант за замовчуванням, unicode/winkeys):
# літера -> кейкод ЙЦУКЕН. Перевірено на /usr/share/X11/xkb/symbols/ua.
UA_KEYCODES = {
    "й": keycode("Q"), "ц": keycode("W"), "у": keycode("E"), "к": keycode("R"),
    "е": keycode("T"), "н": keycode("Y"), "г": keycode("U"), "ш": keycode("I"),
    "щ": keycode("O"), "з": keycode("P"), "х": keycode("LBKT"), "ї": keycode("RBKT"),
    "ф": keycode("A"), "і": keycode("S"), "в": keycode("D"), "а": keycode("F"),
    "п": keycode("G"), "р": keycode("H"), "о": keycode("J"), "л": keycode("K"),
    "д": keycode("L"), "ж": keycode("SEMI"), "є": keycode("SQT"), "я": keycode("Z"),
    "ч": keycode("X"), "с": keycode("C"), "м": keycode("V"), "и": keycode("B"),
    "т": keycode("N"), "ь": keycode("M"), "б": keycode("COMMA"), "ю": keycode("DOT"),
    "ґ": keycode("BSLH"), ".": keycode("FSLH"), ",": keycode("FSLH", LS),
    "'": keycode("GRAVE"),
}
UA_CHARS = {v: k for k, v in UA_KEYCODES.items()}


def keycode_name(p, ua=False):
    if ua and p in UA_CHARS:
        return UA_CHARS[p]
    mods, page, uid = p >> 24, (p >> 16) & 0xFF, p & 0xFFFF
    table = KEY_NAMES if page == 0x07 else CONSUMER_NAMES if page == 0x0C else {}
    name = table.get(uid, f"p{page:x}:{uid:#x}")
    for i, m in enumerate(MOD_NAMES):
        if mods & (1 << i):
            name = f"{m}({name})"
    return name


# Біндинги, у яких «тап» — це кейкод, і в якому параметрі він лежить.
TAP_PARAM = {"Key Press": 1, "Mod-Tap": 2, "Layer-Tap": 2, "HRM Left": 2, "HRM Right": 2}


def binding_text(binding, behaviors, layer_names, ua=False):
    bid, p1, p2 = binding
    name = behaviors.get(bid, f"?{bid}")
    k = lambda p: keycode_name(p, ua)  # noqa: E731
    layer = lambda p: layer_names.get(p, p)  # noqa: E731
    formats = {
        "Key Press": lambda: f"&kp {k(p1)}",
        "Transparent": lambda: "&trans",
        "None": lambda: "&none",
        "Mod-Tap": lambda: f"&mt {keycode_name(p1)} {k(p2)}",
        "HRM Left": lambda: f"&hml {keycode_name(p1)} {k(p2)}",
        "HRM Right": lambda: f"&hmr {keycode_name(p1)} {k(p2)}",
        "Layer-Tap": lambda: f"&lt {layer(p1)} {k(p2)}",
        "Momentary Layer": lambda: f"&mo {layer(p1)}",
        "To Layer": lambda: f"&to {layer(p1)}",
        "Toggle Layer": lambda: f"&tog {layer(p1)}",
        "Sticky Layer": lambda: f"&sl {layer(p1)}",
        "Sticky Key": lambda: f"&sk {keycode_name(p1)}",
        "Mouse Key Press": lambda: f"&mkp MB{p1.bit_length()}",
        "esc_fn": lambda: f"&esc_fn {keycode_name(p1)} {layer(p2)}",
        "Bluetooth": lambda: f"&bt {p1} {p2}",
    }
    return formats.get(name, lambda: f"<{name} {p1:#x} {p2:#x}>")()


# Ряди Eyelash Corne: 13/15/14 позицій + 6 тхамбів; у центрі енкодер/джойстик.
ROWS = [("верх", range(0, 6), range(7, 13), [6]),
        ("дім", range(13, 19), range(22, 28), [19, 20, 21]),
        ("низ", range(28, 34), range(36, 42), [34, 35]),
        ("тхамби", range(42, 45), range(45, 48), [])]


def _norm(dump):
    """JSON зберігає ключі як рядки — повертаємо int."""
    return {"behaviors": {int(k): v for k, v in dump["behaviors"].items()},
            "layers": dump["layers"]}


def format_layer(dump, layer):
    layer_names = {l["id"]: l["name"] for l in dump["layers"]}
    ua = layer["name"].startswith("CYR")
    texts = [binding_text(b, dump["behaviors"], layer_names, ua) for b in layer["bindings"]]
    lines = [f"### {layer['name']} (id {layer['id']})"]
    for name, left, right, mid in ROWS:
        line = (f"{name:7}| " + " | ".join(texts[i] for i in left) + "  ||  "
                + " | ".join(texts[i] for i in right))
        if any(texts[i] != "&trans" for i in mid):
            line += "   [центр: " + ", ".join(texts[i] for i in mid) + "]"
        lines.append(line)
    return "\n".join(lines)


def find_layer(dump, name):
    for layer in dump["layers"]:
        if layer["name"] == name:
            return layer
    raise SystemExit(f"шару {name!r} немає: {[l['name'] for l in dump['layers']]}")


def translate(binding, src_behaviors, dst_ids):
    """Біндинг з дампу -> id behavior на пристрої (за назвою)."""
    name = src_behaviors[binding[0]]
    if name not in dst_ids:
        raise SystemExit(f"behavior {name!r} відсутній у прошивці")
    return [dst_ids[name], binding[1], binding[2]]


def layer_diff(current, target, layer_name):
    """-> [(позиція, поточний біндинг, цільовий біндинг у id пристрою)]."""
    dst_ids = {v: k for k, v in current["behaviors"].items()}
    cur = find_layer(current, layer_name)["bindings"]
    tgt = [translate(b, target["behaviors"], dst_ids)
           for b in find_layer(target, layer_name)["bindings"]]
    return [(i, cur[i], tgt[i]) for i in range(len(tgt)) if cur[i] != tgt[i]]


def print_diff(current, changes, layer_name):
    layer_names = {l["id"]: l["name"] for l in current["layers"]}
    ua = layer_name.startswith("CYR")
    txt = lambda b: binding_text(b, current["behaviors"], layer_names, ua)  # noqa: E731
    if not changes:
        print(f"{layer_name}: клавіатура вже збігається з файлом")
    for pos, old, new in changes:
        print(f"  {layer_name}[{pos:2}]  {txt(old):28} -> {txt(new)}")
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump")
    p.add_argument("port")
    p.add_argument("out")
    p = sub.add_parser("show")
    p.add_argument("file")
    p.add_argument("--layer")
    for cmd in ("diff", "write"):
        p = sub.add_parser(cmd)
        p.add_argument("port")
        p.add_argument("file")
        p.add_argument("--layer", required=(cmd == "write"))
        if cmd == "write":
            p.add_argument("--yes", action="store_true", help="справді записати і зберегти")
    args = parser.parse_args()

    if args.cmd == "show":
        dump = _norm(json.load(open(args.file, encoding="utf-8")))
        layers = [find_layer(dump, args.layer)] if args.layer else dump["layers"]
        print("\n\n".join(format_layer(dump, l) for l in layers))
        return

    studio = Studio(args.port)
    current = studio.dump()
    if args.cmd == "dump":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=1)
        print(f"записано {args.out}: " + ", ".join(l["name"] for l in current["layers"]))
        return

    target = _norm(json.load(open(args.file, encoding="utf-8")))
    names = [args.layer] if args.layer else [l["name"] for l in target["layers"]]
    changes = {name: print_diff(current, layer_diff(current, target, name), name)
               for name in names}
    if args.cmd == "diff" or not args.yes or not changes[args.layer]:
        if args.cmd == "write" and not args.yes and changes[args.layer]:
            print("\n(пробний прогін; щоб записати — додай --yes)")
        return

    if studio.unsaved_changes():
        sys.exit("на клавіатурі вже є незбережені зміни — збережи або скасуй їх у Studio")
    layer_id = find_layer(current, args.layer)["id"]
    try:
        for pos, _, new in changes[args.layer]:
            studio.set_binding(layer_id, pos, new)
        after = find_layer({"layers": studio.keymap()}, args.layer)["bindings"]
        expected = find_layer(current, args.layer)["bindings"][:]
        for pos, _, new in changes[args.layer]:
            expected[pos] = new
        if after != expected:
            raise RuntimeError("після запису шар не збігся з очікуваним")
        studio.save()
    except Exception:
        studio.discard()
        print("помилка — незбережені зміни скасовано (discard_changes)")
        raise
    print(f"записано і збережено: {len(changes[args.layer])} клавіш у {args.layer}")


if __name__ == "__main__":
    main()

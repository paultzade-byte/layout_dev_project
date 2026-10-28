"""Читання keymap з клавіатури через протокол ZMK Studio (лише читання).

Ліва половина Eyelash Corne зібрана з CONFIG_ZMK_STUDIO=y і по USB дає
послідовний порт. Протокол: protobuf-повідомлення (zmkfirmware/zmk-studio-
messages) у рамках SOF 0xAB … EOF 0xAD, байти SOF/ESC/EOF екрануються 0xAC.
Блокування вимкнене (CONFIG_ZMK_STUDIO_LOCKING=n). Вкладку zmk.studio треба
закрити — порт приймає одне з'єднання.

    python scripts/zmk/studio_read.py /dev/ttyACM2 config/zmk/studio_keymap.json
    python scripts/zmk/studio_decode.py config/zmk/studio_keymap.json
"""
import json, sys, time, serial
SOF, ESC, EOF = 0xAB, 0xAC, 0xAD

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n: return bytes(out)
def field(num, wt, payload):
    key = varint((num << 3) | wt)
    return key + (varint(payload) if wt == 0 else varint(len(payload)) + payload)
def frame(b):
    out = bytearray([SOF])
    for x in b:
        if x in (SOF, ESC, EOF): out.append(ESC)
        out.append(x)
    out.append(EOF); return bytes(out)

def decode(buf):
    """-> list of (field, wiretype, value) ; value = int or bytes"""
    i, res = 0, []
    def rv():
        nonlocal i
        s = n = 0
        while True:
            b = buf[i]; i += 1; n |= (b & 0x7F) << s; s += 7
            if not b & 0x80: return n
    while i < len(buf):
        k = rv(); f, wt = k >> 3, k & 7
        if wt == 0: res.append((f, 0, rv()))
        elif wt == 2:
            l = rv(); res.append((f, 2, buf[i:i+l])); i += l
        elif wt == 5: res.append((f, 5, buf[i:i+4])); i += 4
        elif wt == 1: res.append((f, 1, buf[i:i+8])); i += 8
        else: raise ValueError(wt)
    return res
def get(msg, f, default=None):
    for ff, wt, v in msg:
        if ff == f: return v
    return default
def getall(msg, f): return [v for ff, wt, v in msg if ff == f]
def zz(n): return (n >> 1) ^ -(n & 1)

class Client:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0.2); self.rid = 0; self.buf = bytearray()
        self.s.reset_input_buffer()
    def call(self, subsys_field, inner):
        self.rid += 1
        self.s.write(frame(field(1, 0, self.rid) + field(subsys_field, 2, inner)))
        deadline = time.time() + 5
        while time.time() < deadline:
            self.buf += self.s.read(4096)
            while SOF in self.buf and EOF in self.buf[self.buf.index(SOF):]:
                st = self.buf.index(SOF); j = st + 1; body = bytearray()
                while j < len(self.buf) and self.buf[j] != EOF:
                    if self.buf[j] == ESC: j += 1
                    body.append(self.buf[j]); j += 1
                if j >= len(self.buf): break
                del self.buf[:j + 1]
                resp = decode(bytes(body))
                rr = get(resp, 1)
                if rr is None: continue  # notification
                rr = decode(rr)
                if get(rr, 1) != self.rid: continue
                for ff, wt, v in rr:
                    if ff == 2: raise RuntimeError(f"meta error {decode(v)}")
                    if ff == subsys_field: return decode(v)
        raise TimeoutError

port = sys.argv[1]; out = sys.argv[2]
c = Client(port)
lock = c.call(3, field(2, 0, 1)); print("lock state:", get(lock, 2, 0), "(1=unlocked)")
info = decode(get(c.call(3, field(1, 0, 1)), 1)); print("device:", get(info, 1).decode())
ids = get(c.call(4, field(1, 0, 1)), 1)
# packed repeated uint32
def unpack(b):
    vals, i = [], 0
    while i < len(b):
        s = n = 0
        while True:
            x = b[i]; i += 1; n |= (x & 0x7F) << s; s += 7
            if not x & 0x80: break
        vals.append(n)
    return vals
beh_ids = unpack(ids)
behaviors = {}
for bid in beh_ids:
    d = decode(get(c.call(4, field(2, 2, field(1, 0, bid))), 2))
    behaviors[bid] = get(d, 2, b"").decode()
print("behaviors:", behaviors)
km = decode(get(c.call(5, field(1, 0, 1)), 1))
layers = []
for lb in getall(km, 1):
    L = decode(lb)
    binds = []
    for bb in getall(L, 3):
        B = decode(bb)
        binds.append([zz(get(B, 1, 0)), get(B, 2, 0), get(B, 3, 0)])
    layers.append({"id": get(L, 1, 0), "name": get(L, 2, b"").decode(), "bindings": binds})
unsaved = get(c.call(5, field(3, 0, 1)), 3, 0)
json.dump({"behaviors": behaviors, "layers": layers, "unsaved_changes": unsaved,
           "available_layers": get(km, 2, 0)}, open(out, "w"), ensure_ascii=False, indent=1)
print("layers:", [(l["id"], l["name"], len(l["bindings"])) for l in layers], "unsaved:", unsaved)

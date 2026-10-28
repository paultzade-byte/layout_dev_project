"""Дамп studio_read.py → читабельні біндинги ZMK по рядах Eyelash Corne.

Параметри шарів (&mo, &lt, &to…) у Studio — id шару, не індекс (у дампі
CYR має id 6, CYR_S — id 5).
"""
import json, sys
d = json.load(open(sys.argv[1]))
B = {int(k): v for k, v in d["behaviors"].items()}
lid = {l["id"]: l["name"] for l in d["layers"]}
K = {0x04+i: chr(ord('A')+i) for i in range(26)}
K.update({0x1E+i: str((i+1) % 10) for i in range(10)})
K.update({0x28:'RET',0x29:'ESC',0x2A:'BSPC',0x2B:'TAB',0x2C:'SPACE',0x2D:'MINUS',0x2E:'EQUAL',0x2F:'LBKT',0x30:'RBKT',
 0x31:'BSLH',0x32:'NUHS',0x33:'SEMI',0x34:'SQT',0x35:'GRAVE',0x36:'COMMA',0x37:'DOT',0x38:'FSLH',0x39:'CAPS',
 0x46:'PSCRN',0x47:'SCROLL',0x48:'PAUSE',0x49:'INS',0x4A:'HOME',0x4B:'PG_UP',0x4C:'DEL',0x4D:'END',0x4E:'PG_DN',
 0x54:'KP_SLASH',0x4F:'RIGHT',0x50:'LEFT',0x51:'DOWN',0x52:'UP',0x64:'NUBS',0x65:'K_APP',
 0xE0:'LCTRL',0xE1:'LSHFT',0xE2:'LALT',0xE3:'LGUI',0xE4:'RCTRL',0xE5:'RSHFT',0xE6:'RALT',0xE7:'RGUI'})
K.update({0x3A+i: f'F{i+1}' for i in range(12)})
C = {0xB5:'C_NEXT',0xB6:'C_PREV',0xB7:'C_STOP',0xCD:'C_PP',0xE2:'C_MUTE',0xE9:'C_VOL_UP',0xEA:'C_VOL_DN',
     0x6F:'C_BRI_UP',0x70:'C_BRI_DN',0x221:'C_AC_SEARCH',0x29F:'C_AC_DESKTOP_SHOW_ALL_WINDOWS'}
MODS = ['LC','LS','LA','LG','RC','RS','RA','RG']
def kc(p):
    mods, page, uid = p >> 24, (p >> 16) & 0xFF, p & 0xFFFF
    name = (K if page == 7 else C if page == 12 else {}).get(uid, f'p{page:x}:{uid:#x}')
    for i, m in enumerate(MODS):
        if mods & (1 << i): name = f'{m}({name})'
    return name
def fmt(b):
    bid, p1, p2 = b; n = B.get(bid, f'?{bid}')
    return {'Key Press': lambda: f'&kp {kc(p1)}', 'Transparent': lambda: '&trans', 'None': lambda: '&none',
            'Mod-Tap': lambda: f'&mt {kc(p1)} {kc(p2)}', 'Layer-Tap': lambda: f'&lt {lid.get(p1,p1)} {kc(p2)}',
            'Momentary Layer': lambda: f'&mo {lid.get(p1,p1)}', 'To Layer': lambda: f'&to {lid.get(p1,p1)}',
            'Toggle Layer': lambda: f'&tog {lid.get(p1,p1)}', 'Sticky Layer': lambda: f'&sl {lid.get(p1,p1)}',
            'Sticky Key': lambda: f'&sk {kc(p1)}', 'Mouse Key Press': lambda: f'&mkp MB{p1.bit_length()}',
            'esc_fn': lambda: f'&esc_fn {kc(p1)} {lid.get(p2,p2)}', 'Bluetooth': lambda: f'&bt {p1} {p2}',
           }.get(n, lambda: f'<{n} {p1:#x} {p2:#x}>')()
rows = [('верх', range(0, 6), range(7, 13), [6]), ('дім', range(13, 19), range(22, 28), [19, 20, 21]),
        ('низ', range(28, 34), range(36, 42), [34, 35]), ('тхамби', range(42, 45), range(45, 48), [])]
for l in d["layers"]:
    bs = [fmt(b) for b in l["bindings"]]
    print(f'\n### {l["name"]} (id {l["id"]})')
    for name, L, R, mid in rows:
        print(f'{name:7}| ' + ' | '.join(bs[i] for i in L) + '  ||  ' + ' | '.join(bs[i] for i in R)
              + ('   [центр: ' + ', '.join(bs[i] for i in mid) + ']' if any(bs[i] != '&trans' for i in mid) else ''))

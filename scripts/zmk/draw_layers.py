"""ASCII-схема шарів із дампу studio.py: кожна клавіша розшифрована в символ
своєї мови (GRAPH/GRAPH_ALT — us, CYR/CYR_S — ua, спільні — «us|ua», де різне).

    python scripts/zmk/draw_layers.py DUMP.json GRAPH,CYR,GRAPH_ALT,CYR_S,DIGITS,SYMBOL,FN
"""
import json, sys, unicodedata
sys.path.insert(0, __import__('os').path.dirname(__file__))
from studio import KEY_NAMES, UA_CHARS, keycode_name
d, beh, lname = None, {}, {}


def load(path):
    """Читає дамп; ch()/cell() беруть з нього назви behavior і шарів."""
    return use(json.load(open(path)))


def use(dump):
    """Те саме, що load, але для дампу в пам'яті (напр. щойно з клавіатури)."""
    global d
    d = dump
    beh.clear(); beh.update({int(k): v for k, v in d['behaviors'].items()})
    lname.clear(); lname.update({l['id']: l['name'] for l in d['layers']})
    return d
SHORT = {'DIGITS': 'DIG', 'SYMBOL': 'SYM', 'FN': 'FN', 'CYR_S': 'CYS', 'GRAPH_ALT': 'GA', 'CYR': 'CYR', 'GRAPH': 'GR'}
US = {'MINUS': '-', 'EQUAL': '=', 'LBKT': '[', 'RBKT': ']', 'BSLH': '\\', 'SEMI': ';', 'SQT': "'", 'GRAVE': '`',
      'COMMA': ',', 'DOT': '.', 'FSLH': '/', 'NUBS': '<', 'KP_SLASH': '/', 'KP_DOT': '.', 'KP_PLUS': '+', 'KP_MINUS': '-', 'KP_MULTIPLY': '*', 'SPACE': '␣',
      'RET': '⏎', 'BSPC': '⌫', 'DEL': '⌦', 'TAB': '⇥', 'ESC': 'Esc', 'LEFT': '←', 'RIGHT': '→', 'UP': '↑',
      'DOWN': '↓', 'HOME': 'Home', 'END': 'End', 'PG_UP': 'PgUp', 'PG_DN': 'PgDn', 'CAPS': 'Caps',
      'K_APP': 'Menu', 'PSCRN': 'PrSc', 'LSHFT': '⇧', 'RSHFT': '⇧', 'LCTRL': 'Ctl', 'LALT': 'Alt',
      'RALT': 'AltG', 'LGUI': 'Win'}
US_S = dict(zip("1234567890-=[]\;',./`", '!@#$%^&*()_+{}|:"<>?~')); US_S['<'] = '>'
UA_S = dict(zip('1234567890-=', '!"№;%:?*()_+'))
UA_N = {'FSLH': '.', 'GRAVE': "'", 'NUBS': '/', 'BSLH': 'ґ'}
UA_SH = {'FSLH': ',', 'GRAVE': 'ʼ', 'NUBS': '|'}
UA_3 = {'6': '<', '7': '>', '9': '[', '0': ']', 'COMMA': '«', 'DOT': '»', 'MINUS': '—', 'BSLH': '\\', 'FSLH': '/'}
UA_4 = {'9': '{', '0': '}', 'COMMA': '„', 'DOT': '“', 'MINUS': '–', 'BSLH': '|', 'GRAVE': '~', '3': '₴'}
def ch(p, lang):
    mods, uid = p >> 24, p & 0xFFFF
    if (p >> 16) & 0xFF == 0x0C: return {0xB5:'Next',0xB6:'Prev',0xB7:'Stop',0xCD:'Play',0xE9:'Vol+',0xEA:'Vol-',0x6F:'Bri+',0x70:'Bri-',0x221:'Srch',0x29F:'Wins'}.get(uid,'?')
    n = KEY_NAMES.get(uid, '?'); sh = bool(mods & 0x22); ra = bool(mods & 0x40)
    ctl, alt, gui = bool(mods & 0x11), bool(mods & 0x04), bool(mods & 0x08)
    if ctl or alt or gui:
        pre = ('C' if ctl else '') + ('A' if alt else '') + ('G' if gui else '') + ('S' if sh else '')
        base = US.get(n, n)
        return f"{pre}{base}" if len(base) == 1 else f"{pre}-{base}"
    if lang == 'ua':
        if ra: return (UA_4 if sh else UA_3).get(n, '?')
        if p in UA_CHARS and not sh: return UA_CHARS[p]
        if sh and (p & ~0x22000000) in UA_CHARS and n not in UA_SH:
            return UA_CHARS[p & ~0x22000000].upper()
        if n in UA_N: return (UA_SH if sh else UA_N)[n]
        if sh and n in UA_S: return UA_S[n]
    if n in KEY_NAMES.values() and len(n) == 1 and n.isalpha(): return n.upper() if sh else n.lower()
    c = US.get(n, n)
    if sh: c = US_S.get(c, US_S.get(n, '⇧' + c))
    return c
def cell(b, lang):
    bid, p1, p2 = b; name = beh[bid]
    hold = lambda h: {'LSHFT':'⇧','RSHFT':'⇧','LCTRL':'⌃','LALT':'⌥','LGUI':'◆','RALT':'AG'}.get(keycode_name(h), ch(h, 'us'))
    if name == 'Key Press': return ch(p1, lang)
    if name == 'Transparent': return '·'
    if name == 'None': return ''
    if name in ('Mod-Tap', 'HRM Left', 'HRM Right'):
        h = keycode_name(p1)
        hs = {'LC(C)':'^C','LC(V)':'^V'}.get(h) or hold(p1)
        return f"{ch(p2, lang)}/{hs}"
    if name == 'Layer-Tap': return f"{ch(p2, lang)}/{SHORT[lname[p1]]}"
    if name == 'esc_fn': return f"Esc/FN"
    if name == 'Sticky Layer': return f"1×{SHORT[lname[p1]]}"
    if name == 'Sticky Key': return f"1×{hold(p1)}"
    if name == 'LT Comma/Dot': return f",⇧./{SHORT[lname[p1]]}"
    if name == 'Colon/Semi': return ':⇧;'
    if name == 'Lang CYR': return '→КИР'
    if name == 'Lang LAT': return '→LAT'
    if name == 'Lang Toggle': return 'LangT'
    if name == 'To Layer': return {'GRAPH':'=LAT','CYR':'=КИР'}.get(lname[p1], '=' + lname[p1])
    if name == 'Mouse Key Press': return f"M{p1.bit_length()}"
    if name == 'Bluetooth': return {4:'BTclr'}.get(p1, f'BT{p1}')
    if name == 'Underglow': return RGB_LABELS.get(p1, f'RGB{p1}')
    return name[:5]
# ZMK dt-bindings/zmk/rgb.h: TOG 0, BRI 7, BRD 8, EFF 11, EFR 12
RGB_LABELS = {0: 'RGB ⏻', 1: 'RGB on', 2: 'RGB off', 7: 'RGB ☀+', 8: 'RGB ☀−', 11: 'RGB ▸', 12: 'RGB ◂'}
def w(s): return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)
def pad(s, n=6):
    s = s if w(s) <= n else s[:n]
    return s + ' ' * (n - w(s))
CTX = {'GRAPH':'us','GRAPH_ALT':'us','CYR':'ua','CYR_S':'ua'}


def main():
    load(sys.argv[1])
    order = sys.argv[2].split(',')
    for name in order:
        l = next(x for x in d['layers'] if x['name'] == name)
        for lang in [CTX.get(name, 'both')]:
            title = name + ('' if name in CTX else '  (спільний; латиниця|кирилиця, де різне)')
            print(f"── {title} " + '─' * (88 - len(title)))
            bb = l['bindings']
            def c(i):
                if lang != 'both': return pad(cell(bb[i], lang))
                a, b = cell(bb[i], 'us'), cell(bb[i], 'ua')
                return pad(a if a == b else f"{a}|{b}")
            line = lambda L, R: '│'.join(c(i) for i in L) + '  ║  ' + '│'.join(c(i) for i in R)
            print(line(range(0, 6), range(7, 13)))
            print(line(range(13, 19), range(22, 28)))
            print(line(range(28, 34), range(36, 42)))
            print(' ' * 21 + '│'.join(c(i) for i in range(42, 45)) + '  ║  ' + '│'.join(c(i) for i in range(45, 48)))
            print()


if __name__ == '__main__':
    main()

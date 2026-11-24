# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: GUI оптимізатора + міні-апка статистики одним каталогом (onedir).

Два exe в одній теці (спільні бібліотеки): ukr-layout.exe (оптимізатор) і
ukr-stats.exe (статистика текстів, ukr_stats.py; воркери — multiprocessing).

    pyinstaller --noconfirm --distpath dist --workpath build packaging/ukr_layout.spec

onedir, а не onefile: швидший старт (нічого не розпаковується в TEMP при
кожному запуску) і менше хибних спрацювань антивірусів.

Ресурси — лише те, що читає config/main_config.py (+ стартові розкладки з
geometry.json). Особисті розкладки автора, дампи клавіатури, корпус — ні.
ZMK-скрипти потрапляють як модулі (їх імпортує uiux/layer_view.py), але
тека scripts/zmk у збірці відсутня, тож GUI ховає все, що пов'язано з
клавіатурою (`_zmk_mode()`).
"""
import json
from pathlib import Path

ROOT = Path(SPECPATH).parent
CONFIG = ROOT / "config"

geometry = json.loads((CONFIG / "geometry.json").read_text(encoding="utf-8"))
start_layouts = sorted({g["start_layout"] for g in geometry["layouts"].values() if g.get("start_layout")})

resources = ["geometry.json", "moves.yaml", "moves_standard.yaml", "statistic.json",
             "word_stats.json", "mutator_config.json", *start_layouts]
datas = [(str(CONFIG / name), "config") for name in resources]
# іконки: .ico — у сам exe (Провідник, ярлики), .png — у вікно Tk (uiux.theme.set_window_icon);
# згенеровані scripts/make_icons.py і лежать у git
ICONS = ROOT / "packaging" / "icons"
datas += [(str(ICONS / "ukr-layout.png"), "icons")]

a = Analysis(
    [str(ROOT / "ukr_layout.py")],
    pathex=[str(ROOT), str(ROOT / "scripts" / "zmk")],
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["pytest", "playwright", "greenlet", "pyee", "pygments", "dotenv",
              "matplotlib", "scipy", "pandas", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ukr-layout",
    icon=str(ICONS / "ukr-layout.ico"),
    console=False,          # віконний застосунок; помилки — error.log + вікно
    upx=False,              # UPX частіше насторожує антивіруси
)

s_a = Analysis(
    [str(ROOT / "ukr_stats.py")],
    pathex=[str(ROOT)],
    datas=[(str(ICONS / "ukr-stats.png"), "icons")],
    hiddenimports=[],
    excludes=["pytest", "playwright", "greenlet", "pyee", "pygments", "dotenv",
              "matplotlib", "scipy", "pandas", "IPython", "numba", "llvmlite", "PIL", "yaml"],
    noarchive=False,
)
s_exe = EXE(
    PYZ(s_a.pure),
    s_a.scripts,
    [],
    exclude_binaries=True,
    name="ukr-stats",
    icon=str(ICONS / "ukr-stats.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, s_exe, s_a.binaries, s_a.datas, name="ukr-layout", upx=False)

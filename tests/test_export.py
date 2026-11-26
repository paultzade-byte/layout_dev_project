"""Експорт розкладки в ОС (core/export.py): .klc, xkb, .keylayout."""
import re
import shutil
import subprocess

import pytest

from config.main_config import CONFIG_DIR, geometry_config
from core import export

GEOMETRY = "generic_105_alpha"


@pytest.fixture(scope="module")
def chars():
    return export.load_chars(CONFIG_DIR / "layout_standard_A.json")


@pytest.fixture(scope="module")
def km(chars):
    return export.keymap(chars, geometry_config(GEOMETRY))


def test_keymap_has_every_symbol_once(km):
    letters = set("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя") | {",", "."}
    base = [levels[0] for name, levels in km.items() if not name.startswith("AE")]
    assert sorted(base) == sorted(letters)
    assert len(km) == 35 + 12                              # слоти + цифровий ряд


def test_altgr_and_case(km):
    by_base = {levels[0]: levels for levels in km.values()}
    assert by_base["і"] == ["і", "І", "ї", "Ї"]
    assert by_base["г"] == ["г", "Г", "ґ", "Ґ"]
    assert by_base["о"] == ["о", "О", "'", "ʼ"]
    assert by_base["ю"] == ["ю", "Ю", None, None]
    assert by_base[","][:2] == [",", ";"]


def test_keymap_rejects_duplicates(chars):
    bad = dict(chars)
    bad[0] = bad[1]
    with pytest.raises(ValueError, match="двічі"):
        export.keymap(bad, geometry_config(GEOMETRY))


def test_klc_is_utf16_and_complete(km, tmp_path):
    path = export.write_klc(tmp_path / "x.klc", km)
    raw = path.read_bytes()
    assert raw[:2] == b"\xff\xfe"
    text = raw[2:].decode("utf-16-le")
    assert "\r\n" in text and text.rstrip().endswith("ENDKBD")
    rows = re.findall(r"^([0-9a-f]{2})\t(\w+)\t\t(\d)\t(\S+)\t(\S+)\t(\S+)\t(\S+)\t(\S+)",
                      text, re.M)
    by_vk = {r[1]: r for r in rows}
    assert len(rows) == 47 + 3                              # + OEM_102, SPACE, DECIMAL
    sc, vk = export.WIN_KEYS[next(n for n, l in km.items() if l[0] == "і")]
    assert by_vk[vk][2] == "5" and by_vk[vk][3:] == (
        "0456", "0406", "-1", "0457", "0407")               # Caps діє і на ї
    assert by_vk["Q"][0] == "10" and by_vk["OEM_3"][0] == "29"


@pytest.mark.skipif(not (shutil.which("xkbcomp") and shutil.which("setxkbmap")),
                    reason="нема xkbcomp/setxkbmap")
def test_xkb_compiles(km, tmp_path):
    symbols = tmp_path / "xkb" / "symbols"
    symbols.mkdir(parents=True)
    (symbols / "ukr_optimized").write_text(export.xkb_text(km), encoding="utf-8")
    keymap = subprocess.run(
        ["setxkbmap", "-I", str(tmp_path / "xkb"), "-layout", "us,ukr_optimized", "-print"],
        capture_output=True, text=True, check=True).stdout
    result = subprocess.run(
        ["xkbcomp", "-w", "1", f"-I{tmp_path / 'xkb'}", "-", str(tmp_path / "out.xkm")],
        input=keymap, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "NoSymbol" not in export.xkb_text(km).split("key <AE01>")[0]


def test_keylayout_well_formed(km):
    import xml.dom.minidom
    xml_text = export.keylayout_text(km)
    # керівні символи (&#x0008; тощо) легальні лише в XML 1.1 — для expat приберемо
    plain = re.sub(r"&#x00[01][0-9A-F];", "X", xml_text.replace('version="1.1"', 'version="1.0"', 1))
    doc = xml.dom.minidom.parseString(plain.encode())
    maps = doc.getElementsByTagName("keyMap")
    assert len(maps) == 8
    base = {k.getAttribute("code"): k.getAttribute("output") for k in maps[0].getElementsByTagName("key")}
    opt = {k.getAttribute("code"): k.getAttribute("output") for k in maps[3].getElementsByTagName("key")}
    vk_i = str(export.MAC_VK[next(n for n, l in km.items() if l[0] == "і")])
    assert base[vk_i] == "і" and opt[vk_i] == "ї"
    cmd = {k.getAttribute("code"): k.getAttribute("output") for k in maps[5].getElementsByTagName("key")}
    assert cmd["8"] == "c"                                  # Cmd+C — фізична C


def test_export_all_writes_files(chars, tmp_path):
    paths = export.export_all(chars, geometry_config(GEOMETRY), tmp_path / "out")
    assert sorted(p.name for p in paths) == sorted(
        ["ukr_optimized.klc", "ukr_optimized.xkb", "ukr_optimized.keylayout", "README.txt"])
    assert "MSKLC" in (tmp_path / "out" / "README.txt").read_text(encoding="utf-8")


NASTY_NAME = 'A & <B> "C" \\ \'D\'\nE F'


def test_name_is_escaped_in_every_format(km, tmp_path):
    """QA 2026-11-26: назва (--name) з & < " ламала .keylayout (невалідний XML),
    а лапки / переноси — рядок у лапках .klc і xkb."""
    import xml.dom.minidom
    xml_text = export.keylayout_text(km, NASTY_NAME)
    plain = re.sub(r"&#x00[01][0-9A-F];", "X", xml_text.replace('version="1.1"', 'version="1.0"', 1))
    doc = xml.dom.minidom.parseString(plain.encode())
    assert doc.documentElement.getAttribute("name") == 'A & <B> "C" \\ \'D\' E F'

    klc = export.klc_text(km, NASTY_NAME)
    assert klc.splitlines()[0] == "KBD\tukropt\t\"A & <B> 'C' / 'D' E F\""
    assert "0409\tA & <B> 'C' / 'D' E F\n" in klc

    xkb = export.xkb_text(km, NASTY_NAME)
    assert xkb.splitlines()[0].startswith("// A & <B> 'C' / 'D' E F — ")
    assert "    name[Group1] = \"A & <B> 'C' / 'D' E F\";\n" in xkb
    assert export.xkb_text(km, "\n") == export.xkb_text(km)   # порожня -> типова назва


def test_readme_underline_matches_title(chars, tmp_path):
    """QA 2026-11-26: підкреслення заголовка README було на 2 символи довше за заголовок."""
    export.export_all(chars, geometry_config(GEOMETRY), tmp_path, name="Моя")
    title, line = (tmp_path / "README.txt").read_text(encoding="utf-8").splitlines()[:2]
    assert title == "Моя — як встановити"
    assert line == "=" * len(title)
    export.export_all(chars, geometry_config(GEOMETRY), tmp_path, name="Моя\nдруга")
    title, line = (tmp_path / "README.txt").read_text(encoding="utf-8").splitlines()[:2]
    assert title == "Моя друга — як встановити"
    assert line == "=" * len(title)

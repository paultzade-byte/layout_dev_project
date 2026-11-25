import xml.etree.ElementTree as ET

from PIL import Image

from config.main_config import geometry_config
from core.layout_factory import build_layout
from uiux import render


def test_png_every_geometry(geometry_name, tmp_path):
    geometry = geometry_config(geometry_name)
    layout = build_layout(geometry)
    path = render.save(layout.keys, geometry, geometry_name, tmp_path / "l.png", "заголовок", "дата")
    with Image.open(path) as image:
        width, height = image.size
    cells = render.key_cells(geometry, geometry_name)
    span = max(x + w for _, x, _, w in cells)
    assert width == (span + 2 * render.MARGIN) * 2          # scale=2
    assert height > geometry["key_height"] * 3


def test_svg_is_valid_and_has_every_letter(geometry_name, tmp_path):
    geometry = geometry_config(geometry_name)
    layout = build_layout(geometry)
    path = render.save(layout.keys, geometry, geometry_name, tmp_path / "l.svg", "a & b", "")
    root = ET.parse(path).getroot()
    texts = {t.text for t in root.iter("{http://www.w3.org/2000/svg}text")}
    letters = {k.char for k in layout.keys if len(k.char) == 1}
    assert letters <= texts
    assert "a & b" in texts


def test_cli_default_layout(tmp_path, capsys):
    render.main(["-", str(tmp_path / "x.png"), "--geometry", "generic_105_alpha", "--title", "t", "--subtitle", "s"])
    assert (tmp_path / "x.png").exists()


def test_altgr_legends_in_svg():
    from config.main_config import geometry_config, start_layout
    from uiux import render
    name = "generic_105_alpha"
    svg = render.render_svg(start_layout(name).keys, geometry_config(name), name)
    for extra in geometry_config(name)["altgr"].values():
        assert f">{render.escape(extra)}</text>" in svg


def test_key_cells_scale_for_hidpi():
    """GUI на екрані з масштабом Windows 150%: клавіші й проміжки — у 1.5 раза більші."""
    from config.main_config import geometry_config
    from uiux.render import key_cells
    g = geometry_config("generic_105_alpha")
    plain, big = key_cells(g, "generic_105_alpha"), key_cells(g, "generic_105_alpha", 1.5)
    for (_, x, y, w), (_, bx, by, bw) in zip(plain, big):
        assert abs(bx - 1.5 * x) <= 1 and abs(by - 1.5 * y) <= 1 and abs(bw - 1.5 * w) <= 1

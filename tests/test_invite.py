"""Інвітейшн при вході: фраза за номером запуску, лічильник, вікно закривається кліком."""
import os

import pytest

from uiux import invite as I


def test_phrases_by_launch():
    assert I.phrase(1) == I.phrase(10) == ("Етап I. Знайомство та дисципліна", "«Пізнай себе, друкуй».")
    assert "восьминіг» 🐙" in I.phrase(11)[1] and I.phrase(13) == I.phrase(11)
    assert "мокрий принтер" in I.phrase(41)[1] and "стеногр@фіст" in I.phrase(44)[1]
    assert I.phrase(53) == I.phrase(1000) == ("Етап VI. Постійна просвітленість", "«Пізнай себе».")
    starts = [s for s, _, _ in I.PHRASES]
    assert starts == sorted(starts) and starts[0] == 1


def test_launch_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    assert [I.next_launch() for _ in range(3)] == [1, 2, 3]


tk = pytest.importorskip("tkinter")


@pytest.mark.skipif(not os.environ.get("DISPLAY") and os.name != "nt", reason="немає дисплея (xvfb-run)")
def test_invite_closes_on_click():
    root = tk.Tk()
    root.withdraw()
    try:
        inv = I.Invite(root, 44)
        assert inv.alive and inv.win.winfo_viewable()
        inv.win.event_generate("<Button-1>", x=5, y=5)
        root.update()
        assert not inv.alive
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY") and os.name != "nt", reason="немає дисплея (xvfb-run)")
def test_invite_closes_itself_unless_hovered(monkeypatch):
    """Не закрили кліком — зникає сама за CLOSE_MS; поки над нею курсор — ні."""
    import time
    from uiux import toast
    monkeypatch.setattr(I, "CLOSE_MS", 50)
    monkeypatch.setattr(toast, "AFTER_HOVER_MS", 50)
    hovered = {"on": True}
    monkeypatch.setattr(toast, "_hovered", lambda w: hovered["on"])
    root = tk.Tk()
    root.withdraw()

    def spin(sec):
        end = time.time() + sec
        while time.time() < end:
            root.update()
            time.sleep(0.01)
    try:
        inv = I.Invite(root, 1)
        spin(0.4)
        assert inv.alive                  # курсор над плашкою — тримається
        hovered["on"] = False
        spin(0.6)
        assert not inv.alive
    finally:
        root.destroy()

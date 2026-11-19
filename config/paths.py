"""Шляхи застосунку: ресурси (лише читання) і дані юзера (запис).

Ресурси — конфіги з репозиторію (`config/*.json|yaml`). У зібраному exe
(PyInstaller) вони лежать у `sys._MEIPASS`, тож шлях береться звідти.

Дані юзера — пресети, вибраний режим (налаштування). Вони ніколи не
пишуться в теку проєкту (у exe вона може бути лише для читання):
  Windows: %APPDATA%\\ukr-layout
  macOS:   ~/Library/Application Support/ukr-layout
  інше:    $XDG_CONFIG_HOME/ukr-layout (типово ~/.config/ukr-layout)
Змінна середовища LAYOUT_USER_DIR перекриває все (тести, портативний режим).

Розкладки й картинки юзер зберігає сам через діалоги («Зберегти як…»,
«Скрін»); типова тека — layouts_dir(): Документи/ukr-layout.
"""

import os
import sys
from pathlib import Path

APP_NAME = "ukr-layout"

PROJ_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
CONFIG_DIR = PROJ_DIR / "config"


def user_data_dir() -> Path:
    override = os.environ.get("LAYOUT_USER_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def layouts_dir() -> Path:
    """Типова тека для «Зберегти як…», «Відкрити…» і «Скрін»: Документи/ukr-layout
    (на Windows — «Документи» юзера; немає Documents — домашня тека)."""
    documents = Path.home() / "Documents"
    base = (documents if documents.is_dir() else Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base

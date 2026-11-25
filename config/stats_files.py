"""Файли статистики для оптимізатора: вбудована (config/statistic.json +
word_stats.json, корпус UberText) і ті, що порахувала міні-апка статистики
(uiux/stats_app.py) у stats_dir() — по файлу на корпус, мова в назві:
ukr_<корпус>_<дата>.json (див. core/corpus.write_statistic_file).

Вибір запам'ятовується в settings.json ("statistic_file"; None — вбудована).
"""

from __future__ import annotations

import json
from pathlib import Path

from config.paths import layouts_dir

BUILTIN = None          # «вбудована» у налаштуваннях і меню
NGRAM_KEYS = ("unigrams", "bigrams", "trigrams", "skipgrams")
LANG_NAMES = {"uk": "українська", "be": "білоруська", "pl": "польська"}
OPTIMIZER_LANGS = {"uk"}   # розкладки й модель поки лише українські


def stats_dir() -> Path:
    """Документи/ukr-layout/статистика — сюди пише міні-апка статистики."""
    return layouts_dir() / "статистика"


def read_meta(path) -> dict | None:
    """meta файлу статистики або None, якщо це не файл статистики."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in NGRAM_KEYS) or "meta" not in data:
        return None
    return data["meta"]


def list_files(folder: Path | None = None) -> list[tuple[Path, dict]]:
    """Файли статистики в теці, найновіші першими."""
    folder = folder or stats_dir()
    if not folder.is_dir():
        return []
    found = [(p, m) for p in folder.glob("*.json") if (m := read_meta(p)) is not None]
    return sorted(found, key=lambda pm: (pm[1].get("created", ""), pm[0].name), reverse=True)


def load(path) -> dict:
    """Статистика у форматі STATISTIC (n-грами + words, масштабовані до корпусу)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in NGRAM_KEYS if k not in data]
    if missing:
        raise ValueError(f"це не файл статистики (немає {', '.join(missing)})")
    stat = {k: data[k] for k in NGRAM_KEYS}
    meta = data.get("meta") or {}
    if data.get("words"):
        scale = 1.0 / (meta.get("sample_fraction") or 1.0)
        stat["words"] = {w: n * scale for w, n in data["words"].items()}
    return stat


def language(path) -> str | None:
    meta = read_meta(path)
    return meta.get("language") if meta else None


def label(path, meta: dict | None = None) -> str:
    """Підпис у меню: «ukr_новини_2026-11-24 — українська, 1.2 ГБ»."""
    meta = meta if meta is not None else (read_meta(path) or {})
    lang = LANG_NAMES.get(meta.get("language"), meta.get("language") or "?")
    size = meta.get("bytes")
    size_txt = ""
    if size:
        size_txt = f", {size / 2**30:.1f} ГБ" if size >= 2**30 else f", {size / 2**20:.0f} МБ"
    return f"{Path(path).stem} — {lang}{size_txt}"

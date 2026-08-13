# config/white_ist.py

import re

UKR_LETTERS = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
DIGITS = "0123456789"
PUNCTUATION = " .,!?;:()-—«»\"'\n\t"

ALLOWED_CHARS = UKR_LETTERS + DIGITS + PUNCTUATION

# Компілюється один раз при старті: "все, що НЕ в ALLOWED_CHARS" -> пробіл
_junk_pattern = re.compile(f"[^{re.escape(ALLOWED_CHARS)}]")


def clean_text(text: str) -> str:
    """Заміняє все поза білим списком на пробіл (regex в C, швидко)."""
    return _junk_pattern.sub(' ', text)
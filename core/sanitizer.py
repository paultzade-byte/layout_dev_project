import re
from pathlib import Path
import logging

# Імпортуємо наші конфіги (шляхи відносно кореня проекту)
from config.main_config import ALPHABET, LOWERING_ENABLED, STRICT_LETTERS_ONLY

# Підтягуємо налаштований логер (або створюємо локальний, якщо імпорт інший)
logger = logging.getLogger(__name__)


class DataSanitizer:
    def __init__(self):
        # 1. Формуємо базовий алфавіт
        self.base_alphabet = ALPHABET.lower()
        if not LOWERING_ENABLED:
            # Якщо аперкейс враховується, додаємо великі літери до дозволених
            self.base_alphabet += ALPHABET.upper()

        # 2. Формуємо набір (set) дозволених символів для швидкого пошуку в циклі
        if STRICT_LETTERS_ONLY:
            # Тільки літери та мінімум пунктуації
            self.allowed_chars = set(self.base_alphabet + " .,")
        else:
            # Літери + розширена пунктуація
            self.allowed_chars = set(self.base_alphabet + " .,!?:;-")

    def clean_line(self, line: str) -> str:
        """Очищає один рядок тексту згідно з правилами конфігу."""
        if LOWERING_ENABLED:
            line = line.lower()

        # Проходимо циклом по кожному символу. Якщо він є у множині дозволених — залишаємо.
        # Це працює швидше за регулярки для посимвольної фільтрації.
        cleaned = "".join(char for char in line if char in self.allowed_chars)

        # Окремо згортаємо множинні пробіли в один, щоб не було "дірок" у текстах
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def process_file(self, input_path: Path, output_path: Path):
        """Читає файл, чистить його і записує в нове місце."""
        try:
            # Відкриваємо одразу два файли: на читання і на запис
            with open(input_path, 'r', encoding='utf-8') as infile, \
                    open(output_path, 'w', encoding='utf-8') as outfile:

                # Читаємо файл по рядках (не вантажить оперативну пам'ять)
                for line in infile:
                    cleaned_line = self.clean_line(line)
                    if cleaned_line:  # Записуємо тільки якщо рядок не став пустим після чистки
                        outfile.write(cleaned_line + "\n")

            logger.info(f"Успішно очищено: {input_path.name}")

        except Exception as e:
            logger.error(f"Помилка обробки файлу {input_path.name}: {e}")

    def run(self, input_dir_str: str, output_dir_str: str):
        """Головний метод, який проходить по всіх файлах у папці скрапера."""
        input_dir = Path(input_dir_str)
        output_dir = Path(output_dir_str)

        # Створюємо папку для чистих даних, якщо її ще немає (це - не в папці скрапера)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Початок пакетного очищення файлів. Джерело: {input_dir}")

        # Шукаємо всі .txt файли у папці скрапера (включно з підпапками articles, vocabularies)
        for file_path in input_dir.rglob("*.txt"):
            # Формуємо шлях для збереження (наприклад, clean_data/clean_letters.txt)
            out_file_path = output_dir / f"clean_{file_path.name}"
            self.process_file(file_path, out_file_path)


# --- Приклад запуску (може бути винесено в core/builder.py або окремий скрипт) ---
if __name__ == "__main__":
    sanitizer = DataSanitizer()
    # Беремо брудні дані зі скрапера
    source_folder = "scrapper/data"
    # Кладемо чисті дані в абсолютно нову незалежну папку в корені
    target_folder = "clean_data"

    sanitizer.run(source_folder, target_folder)
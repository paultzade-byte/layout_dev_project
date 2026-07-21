import os
import logging.config
from datetime import datetime

# get current date for logs sorting
now = datetime.now()
year = now.strftime("%Y")
month = now.strftime("%m")


# atterting that the log folder is already exists
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(f"{LOG_DIR}/{year}/{month}", exist_ok=True)

# Словник з конфігурацією
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # Важливо: не вимикає логери сторонніх ліб

    # 1. Форматери: як саме виглядає текст логу
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)-8s [%(name)s:%(lineno)d] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "simple": {
            "format": "%(levelname)-8s [%(name)s] %(message)s"
        },
    },

    # 2. Хендлери: куди відправляються логи
    "handlers": {
        "console": {
            "level": "INFO",  # У консоль виводимо тільки INFO і вище (без спаму DEBUG)
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "stream": "ext://sys.stdout",
        },
        "file_app": {
            "level": "DEBUG",  # У файл пишемо абсолютно все, включаючи DEBUG
            "class": "logging.handlers.RotatingFileHandler",  # Автоматично робить бекап файлу, коли він стає завеликим
            "formatter": "standard",
            "filename": os.path.join(LOG_DIR, "app.log"),
            "maxBytes": 5 * 1024 * 1024,  # 5 МБ
            "backupCount": 3,  # Зберігати 3 старих файли
            "encoding": "utf8"
        },
        "file_errors": {
            "level": "ERROR",  # Окремий файл ТІЛЬКИ для помилок
            "class": "logging.FileHandler",
            "formatter": "standard",
            "filename": os.path.join(LOG_DIR, "errors.log"),
            "encoding": "utf8"
        },
    },

    # 3. Логгери: налаштування для різних частин проєкту
    "loggers": {
        # Базовий логер (якщо ім'я не вказано)
        "": {
            "handlers": ["console", "file_app", "file_errors"],
            "level": "DEBUG",
            "propagate": True
        },
        # Можемо зробити окремі рівні для різних модулів
        "scrapper": {
            "handlers": ["console", "file_app", "file_errors"],
            "level": "INFO",
            "propagate": False
        },
        "core.optimizer": {
            "handlers": ["console", "file_app", "file_errors"],
            "level": "DEBUG",  # Тут нам цікавий кожен крок алгоритму
            "propagate": False
        }
    }
}


def setup_logging():
    """Функція, яку треба викликати один раз при старті програми."""
    logging.config.dictConfig(LOGGING_CONFIG)
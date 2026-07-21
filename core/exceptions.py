"""
Документація модуля exceptions.py

Цей модуль містить кастомні класи винятків для проєкту оптимізатора розкладки.
Всі винятки успадковуються від базового класу LayoutProjectError. Це дозволяє
перехоплювати будь-які специфічні помилки проєкту одним блоком except,
відділяючи їх від стандартних системних помилок Python (KeyError, ValueError тощо).

Ієрархія винятків:
LayoutProjectError
 ├── SanitizerError    (Помилки очищення: пустий текст після фільтрації, невідомі символи)
 ├── BuilderError      (Помилки побудови: відсутні словники, некоректні дані частотності)
 ├── ScoringError      (Помилки оцінки: відсутні координати в geometry.json, ділення на нуль)
 ├── OptimizerError    (Помилки алгоритму: неможливість знайти рішення, конфлікт constraints)
 ├── DatabaseError     (Помилки БД: блокування файлу sqlite3, відсутні таблиці/поля)
 ├── UIStartupError   (Неможливість ініціалізувати графіку, конфлікт X11/Wayland)
 └── UIDragDropError  (Невалідна зона відпускання, конфлікт заморожених літер)
"""

class LayoutProjectError(Exception):
    """Базовий клас для всіх специфічних винятків проєкту."""
    def __init__(self, message: str, *args):
        super().__init__(message, *args)
        self.message = message

# --- CORE LOGIC EXCEPTIONS ---

class SanitizerError(LayoutProjectError):
    """Викликається при проблемах з очищенням та нормалізацією тексту."""
    pass

class BuilderError(LayoutProjectError):
    """Викликається, коли білдер не може згенерувати початковий стан або завантажити дані."""
    pass

class ScoringError(LayoutProjectError):
    """Викликається при математичних помилках або відсутності координат для підрахунку штрафів."""
    pass

class OptimizerError(LayoutProjectError):
    """Викликається при логічних збоях у роботі алгоритму оптимізації."""
    pass

# --- DATA STORAGE EXCEPTIONS ---

class DatabaseError(LayoutProjectError):
    """Кастомна обгортка для помилок доступу та читання бази даних статистики або словників."""
    pass


# --- UI EXCEPTIONS ---

class UIStartupError(LayoutProjectError):
    """Викликається, якщо графічний рушій не може запуститися через системні обмеження."""
    pass

class UIDragDropError(LayoutProjectError):
    """Викликається для штатного скасування некоректної дії перетягування об'єктів на матриці."""
    pass
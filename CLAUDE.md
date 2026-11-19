# layout_dev_project

Оптимізатор української розкладки для спліт-клавіатури Corne 42 (є також
`generic_105_alpha`). Мова спілкування з автором — українська.

## Продовження роботи

Якщо користувач каже «продовжуємо роботу над оптимізатором» (або подібне):
1. Прочитай `docs/WORKLOG.md` — там стан, ухвалені рішення, відкриті питання
   і наступні кроки з попередніх сесій.
2. Перевір гілку і останні коміти: `git branch`, `git log --oneline -15`.
3. Коротко підсумуй користувачу, де зупинились, і запропонуй наступний крок
   зі списку «Наступні кроки».

В кінці кожної робочої сесії (або коли користувач просить зафіксувати
контекст) — онови `docs/WORKLOG.md`: новий розділ сесії з датою, оновлені
«Відкриті питання» і «Наступні кроки». Закоміть разом з роботою.

## Структура

- `core/scorer.py` — `MovementScoringEngine`: `prepare_statistics()` (дорого,
  раз на запуск) → `update_layout()` (дешево, після мутації) → `score()`
  (NumPy, розбивка по компонентах). Менше = краще. Для SA — delta-оцінка:
  `load()` → `try_layout()` (лише n-грами з переміщеними літерами) →
  `accept()`. Штрафи бі/три/скіп-грам — з таблиць за кортежами позицій,
  побудованих у `__init__` тими ж `_*_terms`; `moves` після створення
  engine не змінювати. Після зміни моделі — `scripts/check_delta.py`.
- `core/mutator.py` — `LayoutOptimizerSA`: simulated annealing + tabu +
  драбина мутацій (swap → 3-цикл → подвійний swap) + рестарт з best/reheat.
  Мутації — на місці з undo-списком (без клонування розкладки).
  Температура калібрується за реальними delta на першому прогоні
  (`_calibrate`); параметри — імовірності прийняття в `mutator_config.json`.
- `core/models.py` — `Key`, `Layout`, `ScoreMetrics`.
- `core/layout_factory.py` — `build_layout(geometry)`.
- `uiux/app.py` — Tkinter: drag&drop, freeze (ПКМ), Start/Stop, Reheat,
  Rec>>/Rec<<. Слайдерів ваг немає (прибрані за рішенням автора) — ваги
  лише в `moves.yaml`. `uiux/processors.py` — оптимізація в окремому потоці.
- `config/moves.yaml` — усі ваги штрафів (з коментарями).
- `config/geometry.json` — фізичні позиції (`active_layout`).
- `config/statistic.json` — уні/бі/три/скіп-грами корпусу UberText.
- `config/word_stats.json` — частоти слів (для `hand_runs`), генерує
  `scripts/word_counter.py`.
- `config/main_config.py` — завантажує конфіги, домішує `words` у `STATISTIC`.
- `scripts/compare_reference.py` — оптимізатор vs еталон автора
  (`config/reference_layout.json`); `scripts/sa_bench.py` — параметри SA на
  кількох seed (дивись середнє: розкид між seed 3–4 пункти);
  `scripts/multistart.py` — N стартів, найкраща розкладка (`--out` у
  форматі Rec>>, `--from` — старт із замороженими клавішами);
  `scripts/check_delta.py` — delta-оцінка == повний `score()`.
- `.ignore*` — локальні файли автора (корпус ~16 ГБ у `.ignore_storage/`,
  нотатки, старі тести). У git не потрапляють.

## Запуск

```bash
source .venv/bin/activate
python -m uiux.app            # GUI (з кореня проєкту)
```

`main.py` наразі зламаний (див. WORKLOG). Тести в `.ignore_tests/` не
запускаються (`pytest.ini` вказує на неіснуючу `tests/`).

## Правила роботи

- Один коміт на один пункт/виправлення. Не пушити без дозволу.
- Важкі обчислення (корпус, довгі прогони оптимізатора) — під обмеженням CPU:
  `cpulimit -l 60 -f -m -q -- python script.py` (60% — побажання автора; ця версія cpulimit не має `-i`).
  Воркери multiprocessing — з `os.nice()`.
- Згенеровані текстові файли (статистика, звіти) — не більше 50 МБ.
- Нові ваги — у `moves.yaml` з коментарем, що вони означають; схема
  обов'язкових ключів — `_REQUIRED_MOVES_SCHEMA` у `core/scorer.py`.

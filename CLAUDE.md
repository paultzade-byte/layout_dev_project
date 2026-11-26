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

Опис для людей і переваги — `README.md`.

Поточний великий напрям (з 2026-11-14) — звичайна ANSI-клавіатура, тогл
режиму, скрін, повзунки, exe: план і рішення в `docs/PLAN_standard.md`.

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
- `core/mutator.py` — `LayoutOptimizerSA`: simulated annealing із сумішшю
  мутацій (`mutation_mix`: 85% swap / 15% 3-цикл; `null` — стара драбина
  swap → 3-цикл → подвійний swap) + рестарт з best/reheat + фінальне
  дотюнювання `_polish` (усі swap, потім 3-цикли, до локального оптимуму).
  Tabu за станом вимкнено (`tabu_size: 0`, див. WORKLOG 2026-11-19).
  Мутації — на місці з undo-списком (без клонування розкладки).
  Температура калібрується за реальними delta на першому прогоні
  (`_calibrate`); параметри — імовірності прийняття в `mutator_config.json`.
  Частка CPU — `core/throttle.py` (`cpu_share`, паузи між шматками роботи;
  GUI-меню «CPU: 25% ▾», запам'ятовується в settings.json, типово 25%).
- `core/heat.py` — теплові мапи: частота натискань і «незручність» (частка штрафу
  на клавішу — `MovementScoringEngine.per_char_penalty()`), кольори шкал. GUI: кнопки
  «Частота» / «Незручність» біля штрафу (затиснути — поки тримаєш, клік — лишити);
  «Скрін» зберігає те, що на дошці (`render.save(..., heat=, footer=)`).
- `core/models.py` — `Key`, `Layout`, `ScoreMetrics`.
- `core/layout_factory.py` — `build_layout(geometry)`.
- `uiux/app.py` — Tkinter: drag&drop, freeze (ПКМ), Start/Stop, Reheat,
  «Відкрити… / Зберегти / Зберегти як…», «Скрін»; `set_geometry(name)` перемикає геометрію в рантаймі.
  Збережений файл стає стартовим для режиму наступного запуску (settings `start_files`,
  `_session_start_layout`); «↺ За замовчуванням» — завжди вбудована `start_layout`.
  Пресети повзунків — всередині панелі «Детальніше» (видалення — підменю «Видалити пресет ▸»).
- `core/export.py` — експорт розкладки в ОС: `.klc` (MSKLC), xkb, `.keylayout`
  + README; кнопка «Експорт…» (лише «Звичайна»), CLI
  `python -m core.export LAYOUT.json OUT_DIR`. Фізичні клавіші — `key` у geometry.json.
- `uiux/render.py` — картинка розкладки (PNG через Pillow / SVG) для будь-якої
  геометрії; `key_cells()` — сітка, спільна з GUI. Для картинок у чат —
  `python -m uiux.render LAYOUT.json OUT.png [--geometry ...]` (той самий код,
  що й кнопка «Скрін» і «На клаву»). Кольори — `uiux/theme.py`. Окремих слайдерів ваг немає — є 5 повзунків
  впливу (`core/knobs.py`, панель «Детальніше ▸»), що множать групи ваг з
  moves-файлу. Інфо-повідомлення — `uiux/toast.py` (жовті плашки, не модальні). Інвітейшн при вході
  (кампанія «Пізнай себе», одна фраза на день: лічильник — дні з запуском, `next_launch`) — `uiux/invite.py`, з `main()`. Кольори груп
  нижніх кнопок — `theme.GROUP_COLORS`. `uiux/processors.py` — оптимізація в окремому потоці
  (`on_error` — якщо воркер упав; tkinter з потоку не чіпати — опитування з головного, як `_watch_failure`).
  Поки фоном перераховуються ваги (`_weights_busy`), Start/Reheat вимкнені.
- `config/moves.yaml` — усі ваги штрафів (з коментарями) для спліта
  (`corne_42`); `config/moves_standard.yaml` — для звичайної клавіатури
  (`generic_105_alpha`). Відповідність — `MOVES_FILES` у `main_config.py`.
  `column_multiplier`: `col_index` / `col_pinky` — дотичні колонки вказівного
  і мізинця окремо.
- `config/geometry.json` — фізичні позиції (`active_layout`).
- `config/statistic.json` — уні/бі/три/скіп-грами корпусу UberText.
- `config/word_stats.json` — частоти слів (для `hand_runs`); генерується разом
  зі `statistic.json` (див. `core/corpus.py`).
- `config/main_config.py` — завантажує конфіги, домішує `words` у `STATISTIC`;
  `geometry_config(name)` / `load_moves(name)`; активна геометрія —
  `active_layout` або змінна `LAYOUT_GEOMETRY` (для скриптів).
- `config/settings.py` — налаштування юзера між запусками (режим GUI),
  `user_data_dir()/settings.json`; `initial_mode()`: LAYOUT_GEOMETRY >
  запам'ятований > типовий («Звичайна» в exe).
- `config/paths.py` — ресурси (з урахуванням PyInstaller), тека налаштувань
  юзера (`~/.config/ukr-layout`, `%APPDATA%\ukr-layout`; перекриває
  `LAYOUT_USER_DIR`) і `layouts_dir()` — Документи/ukr-layout, типова тека
  діалогів «Відкрити… / Зберегти як… / Скрін».
- `scripts/compare_reference.py` — оптимізатор vs еталон автора
  (`config/reference_layout.json`); `scripts/sa_bench.py` — параметри SA на
  кількох seed (дивись середнє: розкид між seed 3–4 пункти);
  `scripts/multistart.py` — N стартів, найкраща розкладка (`--out` у
  форматі Rec>>, `--from` — старт із замороженими клавішами);
  `scripts/check_delta.py` — delta-оцінка == повний `score()`.
- `core/corpus.py` — статистика корпусу одним проходом: n-грами -> `statistic.json`,
  вибірка слів -> `word_stats.json`; мова/алфавіт — параметр (`LANGUAGES`: uk/be/pl,
  `detect_language`), апострофи ’ ‘ ʼ ` між літерами зводяться до `'`; CPU — `cpu_share`
  (воркери + паузи). CLI — `scripts/ngram_counter.py ТЕКА --out config [--lang] [--cpu]`;
  міні-апка — `python -m uiux.stats_app` / `ukr_stats.py` (вибір теки з .txt, CPU) пише один
  файл `ukr_<тека>_<дата>.json` (мова в назві: ukr/bel/pol; n-грами + words + meta) у
  Документи/ukr-layout/статистика. CLI з `--out config` — вбудована пара statistic.json + word_stats.json.
- `core/trainer.py` + `uiux/trainer.py` — тренажер друку (кнопка «Тренування», модальне вікно з
  розкладкою з дошки): слова з цитат `config/quotes_uk.json` + псевдослова за біграмами, рівні =
  скільки літер відкрито (домашній ряд -> усі), перекладач фізичних клавіш для звичайної клавіатури;
  «Поєднання» — найдорожчі бі/триграми розкладки (`MovementScoringEngine.ngram_penalty`), статистика
  по літерах між сесіями (`trainer_stats.json` у теці налаштувань), «Сам підвищуй»; «Класика» (цитати,
  автор тултіпом) і «Свій текст…» (.txt уривками) з «Великі» / «Розділові» (зміна вигляду не міняє цитату / місце в тексті — `keep_quote`, `same_place`);
  розмір тексту/схеми — «− +»; лупа — пошук цитати (`uiux/quote_search.py`, `trainer.search_quotes`: префікси слів, І).
  Стан — WORKLOG «Наступні кроки» -9.
- `config/stats_files.py` — файли статистики для оптимізатора: список у теці статистики,
  `load()`, підписи. GUI: «Статистика: … ▾» біля CPU (вбудована / файли з теки / «Вибрати
  файл…»; лише українська), вибір у settings.json `statistic_file`, `startup_statistic()`.
- `scripts/zmk/` — клавіатура (Eyelash Corne, ZMK Studio по USB): `studio.py`
  (протокол; порт `auto`), `cyr_from_layout.py` (розкладка <-> шар CYR),
  `keyboard_sync.py` (запис/читання одним викликом — кнопки «На клаву» /
  «З клави» в GUI; автознімки — `config/zmk/snapshots/`, у .gitignore; у `config/zmk`
  лише віхи, архів — `~/Documents/layout/zmk_snapshots/`), `layers_html.py` (схема шарів для артефакту). Після
  кожної зміни розкладки на клавіатурі — оновити артефакт шарів (див. WORKLOG).
- `.ignore*` — локальні файли автора (корпус ~16 ГБ у `.ignore_storage/`,
  нотатки, старі тести). У git не потрапляють.

## Запуск

```bash
source .venv/bin/activate
python -m uiux.app            # GUI (з кореня проєкту)
python main.py --geometry generic_105_alpha --iterations 20000   # без GUI
python ukr_layout.py          # GUI через точку входу exe (--smoke — закрити через 3 с)
```

Збірка exe (фаза 6; в одній теці `ukr-layout.exe` + `ukr-stats.exe`): Windows — GitHub Actions `Build Windows` (вручну або тег `v*`;
з гілки: `gh workflow run build-windows.yml --ref ГІЛКА`).
Локально (Linux, перевірка spec):
```bash
systemd-run --user --scope -q -p CPUQuota=60% nice -n 10 .venv/bin/python -m PyInstaller \
  --noconfirm --distpath dist --workpath build packaging/ukr_layout.spec
```
Тести (`tests/`, разом ~2 хв, 113 тестів; GUI-тест потребує дисплея):
```bash
systemd-run --user --scope -q -p CPUQuota=60% nice -n 10 \
  xvfb-run -a env OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

## Правила роботи

- Один коміт на один пункт/виправлення. Не пушити без дозволу.
- Кілька незалежних частин в одному запиті (з 2026-11-26, прохання автора) — окремі субагенти, кожен у
  своєму git worktree, паралельно; потім кожен ретестить на баги диф ІНШОГО. Злиття, повний прогін тестів
  і коміт — основна сесія. Тести субагентів — лише цільові файли, по черзі: `flock` на спільний lock-файл +
  квота CPU (див. нижче). Субагенти не пушать і не чіпають `config/recorded_layout.json` та чужі незакомічені зміни.
- Обмеження CPU (60% — побажання автора) — **через cgroup, не cpulimit** (з 2026-11-19):
  `systemd-run --user --scope -q -p CPUQuota=60% nice -n 10 env OPENBLAS_NUM_THREADS=1 .venv/bin/python ...`
  Квоту тримає ядро для всієї групи (дочірні процеси й потоки теж), процес
  ніхто не зупиняє. cpulimit шле SIGSTOP/SIGCONT і тричі підвів: 2026-11-02
  `cpulimit -m bash ...` — fork bomb (load ~3800); 2026-11-15 збірка exe і
  2026-11-19 pytest лишились зупиненими (стан `T`). Ніколи не вертатись до нього.
  **Будь-які** обчислення, крім миттєвих перевірок, — під квотою, по одному
  процесу, без паралельних прогонів (одна квота на один запуск). Воркери
  multiprocessing — з `os.nice()`.
- Згенеровані текстові файли (статистика, звіти) — не більше 50 МБ.
- Нові ваги — у `moves.yaml` з коментарем, що вони означають; схема
  обов'язкових ключів — `_REQUIRED_MOVES_SCHEMA` у `core/scorer.py`.

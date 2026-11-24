#!/usr/bin/env bash
# Ярлики оптимізатора і статистики в меню застосунків Linux (freedesktop .desktop).
#
#   packaging/linux/install-shortcuts.sh            — створити (меню + робочий стіл, якщо є)
#   packaging/linux/install-shortcuts.sh --remove   — прибрати
#
# Запускає з цієї теки проєкту через .venv/bin/python (див. README: «Linux»).
# Перенесли теку — запустіть ще раз.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
PY="$ROOT/.venv/bin/python"

names=(ukr-layout ukr-stats)
titles=("Оптимізатор розкладки" "Статистика текстів")
notes=("Оптимізатор української розкладки" "Частоти літер і n-грам ваших текстів")
scripts=(ukr_layout.py ukr_stats.py)

if [[ "${1:-}" == "--remove" ]]; then
    for n in "${names[@]}"; do rm -f "$APPS/$n.desktop" "$DESKTOP/$n.desktop"; done
    echo "Ярлики прибрано."
    exit 0
fi

[[ -x "$PY" ]] || { echo "Немає $PY — спершу: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
mkdir -p "$APPS"
for i in "${!names[@]}"; do
    n="${names[$i]}"
    cat > "$APPS/$n.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${titles[$i]}
Comment=${notes[$i]}
Exec="$PY" "$ROOT/${scripts[$i]}"
Path=$ROOT
Icon=$ROOT/packaging/icons/$n.png
Terminal=false
Categories=Utility;
EOF
    chmod +x "$APPS/$n.desktop"
    if [[ -d "$DESKTOP" ]]; then
        cp "$APPS/$n.desktop" "$DESKTOP/$n.desktop"
        chmod +x "$DESKTOP/$n.desktop"
        gio set "$DESKTOP/$n.desktop" metadata::trusted true 2>/dev/null || true
    fi
done
update-desktop-database "$APPS" 2>/dev/null || true
echo "Готово: «${titles[0]}» і «${titles[1]}» — у меню застосунків${DESKTOP:+ і на робочому столі}."

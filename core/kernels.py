"""Скомпільовані (numba) ядра delta-оцінки для MovementScoringEngine.try_layout.

Одне ядро на вид сімейства n-грам робить за один прохід те, що NumPy-шлях
робить ~10 операціями з проміжними масивами: об'єднання n-грам переміщених
літер (інвертований індекс у форматі CSR), код позицій / рук, штраф з
таблиці, новий внесок і різницю зі старим.

Якщо numba не встановлена — AVAILABLE = False, і scorer лишається на NumPy.
Порядок підсумовування інший, ніж у NumPy (послідовний, а не попарний),
тож результат може відрізнятися в останніх бітах (~1e-15 відносно).
"""

import sys

import numpy as np

try:
    from numba import njit
    AVAILABLE = True
except ImportError:  # pragma: no cover - залежить від середовища
    AVAILABLE = False

# Кеш скомпільованого коду на диску — лише з вихідників: у зібраному exe
# (PyInstaller) .py поруч немає, і numba з cache=True падає ще на імпорті.
# Там ядра компілюються при першому прогоні (кілька секунд).
_CACHE = not getattr(sys, "frozen", False)


if AVAILABLE:
    @njit(cache=_CACHE, nogil=True)
    def _union(indptr, indices, chars, mark, sub):
        """n-грами, що містять будь-яку з chars, -> sub[:m] (без повторів)."""
        m = 0
        for i in range(chars.shape[0]):
            c = chars[i]
            for t in range(indptr[c], indptr[c + 1]):
                s = indices[t]
                if not mark[s]:
                    mark[s] = True
                    sub[m] = s
                    m += 1
        for t in range(m):
            mark[sub[t]] = False
        return m

    @njit(cache=_CACHE, nogil=True)
    def delta_position(indptr, indices, chars, mark, sub, new,
                       keys, weight, total, cost, position, n_pos):
        """Бі/три/скіп-грами: код = кортеж позицій літер."""
        m = _union(indptr, indices, chars, mark, sub)
        k = keys.shape[0]
        acc = 0.0
        for t in range(m):
            s = sub[t]
            code = position[keys[0, s]]
            for j in range(1, k):
                code = code * n_pos + position[keys[j, s]]
            v = total[code] * weight[s]
            new[t] = v
            acc += v - cost[s]
        return m, acc

    @njit(cache=_CACHE, nogil=True)
    def delta_hand(indptr, indices, chars, mark, sub, new,
                   keys, weight, total, cost, hand):
        """Пінбол у словах: код = біти рук літер."""
        m = _union(indptr, indices, chars, mark, sub)
        k = keys.shape[0]
        acc = 0.0
        for t in range(m):
            s = sub[t]
            code = hand[keys[0, s]]
            for j in range(1, k):
                code |= hand[keys[j, s]] << j
            v = total[code] * weight[s]
            new[t] = v
            acc += v - cost[s]
        return m, acc

    @njit(cache=_CACHE, nogil=True)
    def delta_same_hand(indptr, indices, chars, mark, sub, new,
                        masks, weight, total, cost, right):
        """Серії однією рукою в словах: код = 1, якщо всі літери на одній руці."""
        m = _union(indptr, indices, chars, mark, sub)
        left = ~right
        acc = 0.0
        for t in range(m):
            s = sub[t]
            mask = masks[s]
            code = 1 if ((mask & right) == 0 or (mask & left) == 0) else 0
            v = total[code] * weight[s]
            new[t] = v
            acc += v - cost[s]
        return m, acc


def csr(by_char):
    """Список масивів індексів по літерах -> (indptr, indices)."""
    lengths = np.array([len(a) for a in by_char], dtype=np.int64)
    indptr = np.zeros(len(by_char) + 1, dtype=np.int64)
    np.cumsum(lengths, out=indptr[1:])
    indices = np.concatenate(by_char).astype(np.int64) if len(by_char) else np.zeros(0, np.int64)
    return indptr, indices

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional
from dataclasses import replace
# клас типів символів
class KeyType(Enum):
    LETTER = auto()
    PUNCT = auto()
    SPACE = auto()
    MODIFIER = auto()  # Shift і подібне


class Hand(Enum):
    LEFT = "left"
    RIGHT = "right"


class Finger(Enum):
    # Індекси: 1-Мізинець, 2-Безіменний, 3-Середній, 4-Вказівний, 5-Великий (Thumb)
    PINKY = 1
    RING = 2
    MIDDLE = 3
    INDEX = 4
    THUMB = 5


@dataclass
class Key:
    """Описує одну фізичну позицію на клавіатурі."""
    # Незмінні властивості (беруться з geometry.json)
    position_id: int
    x: float
    y: float
    row: int
    home_row: int
    col: int
    home_col: int
    hand: Hand
    finger: Finger
    base_cost: float

    # Змінні властивості
    char: str = ""
    is_frozen: bool = False


@dataclass
class ScoreMetrics:
    """Деталізований звіт про штрафи та бонуси розкладки для запису в БД та UI."""
    base_effort: float = 0.0

    # SFB та SFS
    sfb_penalty: float = 0.0
    sfs_penalty: float = 0.0
    double_tap_penalty: float = 0.0

    # Триграми (перекати та чергування)
    oht_inward_penalty: float = 0.0
    oht_outward_penalty: float = 0.0
    oht_awkward_penalty: float = 0.0
    strict_alternation_penalty: float = 0.0

    alternation_bonus: float = 0.0
    # Загальний бал
    total_penalty: float = 0.0

    # Skipgram
    skipgram_same_finger_penalty: float = 0.0
    skipgram_same_hand_penalty: float = 0.0

    # finger alternation
    finger_alternation_penalty: float = 0.0


@dataclass
class Layout:
    """Описує весь стан клавіатури на певній ітерації."""
    keys: List[Key]
    iteration_number: int = 0
    score: Optional[ScoreMetrics] = None

    def get_key_by_char(self, char: str) -> Optional[Key]:
        """Єдиний дозволений тип логіки в моделях — це read-only хелпери."""
        for key in self.keys:
            if key.char == char:
                return key
        return None

def clone_layout(layout: Layout) -> Layout:
    return Layout(
        keys=[replace(k) for k in layout.keys],
        iteration_number = layout.iteration_number,
        score=layout.score,
    )

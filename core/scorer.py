# core/scorer.py
"""
Модуль оцінювання розкладки (Scoring Engine).
Отримує стан розкладки та очищений текст, повертає деталізований звіт про штрафи.
"""

from typing import List, Dict, Tuple
from core.models import Key, ScoreMetrics, Finger, Hand
import config.weights
import json # config.geometry.json
import math

class MovementScoringEngine:
    def __init__(self,
                 layout_keys: List[Key],
                 weights_config: Dict,
                 geometry_config: Dict = None,
                 ):
        """
        Take the config info about key's coordinates and movement assessment and count
        the value of penolties for currently iterated layout
        """
        self.char_map: Dict[str, Key] = {key.char: key for key in layout_keys if key.char}
        self.weights = weights_config
        self.geometry = geometry_config or {}
        self.row_index = Key.row


    @staticmethod
    def get_row_name(row_index) -> str:
         return {0: "top", 1: "home", 2: "bottom"}.get(row_index, "unknown")


    @staticmethod
    def _get_finger_strength(finger: Finger) -> str:
        """Визначає силу пальця за допомогою Enum."""
        if finger in (Finger.INDEX, Finger.MIDDLE):
            return "strong_fingers"
        return "weak_fingers"

    def score_movements(self, text: str) -> ScoreMetrics:
        metrics = ScoreMetrics()
        if not text:
            return metrics

        # 1. Перетворюємо текст на безперервний потік рухів (об'єктів Key)
        # Всі невідомі символи (напр., спецзнаки, якщо їх немає в розкладці) ігноруються
        key_stream: List[Key] = [self.char_map[char] for char in text if char in self.char_map]

        # Базове навантаження рахуємо одразу
        for key in key_stream:
            metrics.base_effort += key.base_cost

        # 2. Аналізуємо "Моторні Біграми" (вікно у 2 рухи)
        for i in range(len(key_stream) - 1):
            k1, k2 = key_stream[i], key_stream[i+1]
            metrics.sfb_penalty += self._calculate_sfb(k1, k2)

        # 3. Аналізуємо "Моторні Триграми" (вікно у 3 рухи)
        for i in range(len(key_stream) - 2):
            k1, k2, k3 = key_stream[i], key_stream[i+1], key_stream[i+2]
            self._evaluate_movement_trigram(k1, k2, k3, metrics)

        # Підсумок (формула може брати коефіцієнти з self.weights)
        metrics.total_penalty = (
            metrics.base_effort +
            metrics.sfb_penalty +
            metrics.sfs_penalty +
            metrics.outward_roll_penalty +
            metrics.inward_roll_bonus +
            metrics.alternation_bonus
        )

        return metrics

    def _evaluate_movement_trigram(self, k1: Key, k2: Key, k3: Key, metrics: ScoreMetrics):
        """Оцінка трьох рухів підряд: перекати (OHT), злами, пінбол та SFS."""
        # розпаковка результатів функції визначення типу руху
        start_row, end_row, move_type, finger_strength = self._get_movement_details(k1, k3)

        """Аналіз SFS (Same Finger Skip)."""
        if k1.hand == k3.hand and k1.finger.value == k3.finger.value and k1 != k3:
            metrics.sfs_penalty += self.severe_penalties.get("sfs_penalty", 3)

        row_diff = abs(k1.row - k3.row)
        # 0.
        if row_diff == 2:
            # Специфічний штраф для правої руки з нижнього на верхній по діагоналі
            if k1.hand == Hand.RIGHT and k1.row == 2 and move_type == "diagonal" :
                return self.severe_penalties.get("R_bottom_to_top_diagonal", 12.0)

            return self.severe_penalties.get(f"SFS_{move_type}", 10.0)

        # 0.1 specific position "\" or "Ґ"
        if (row_diff == 2 or row_diff == 1) and (0 < (k2.col - k1.col) <= 2):
            return self.severe_penalties.get("R_home_to_top_far_diagonal", 13.0)

        # 1. Пінбол (Ліва -> Права -> Ліва або навпаки)
        if k1.hand == k3.hand and k1.hand != k2.hand:
            metrics.strict_alternation_penalty += self.weights["TRIGRAM_PENALTIES"].get("strict_alternation", 3)
            return  # Якщо це пінбол, це точно не OHT

        # 2. Перекати однією рукою (One Hand Trigram - OHT)
        if k1.hand == k2.hand == k3.hand:
            f1, f2, f3 = k1.finger.value, k2.finger.value, k3.finger.value

            # Якщо всі три кнопки натискаються різними пальцями або з ковзанням
            # Шукаємо напрямок: 1-мізинець, 2-безіменний, 3-середній, 4-вказівний

            # Напрямок ДО центру (Inward): індекси пальців зростають
            if f1 <= f2 <= f3 and not (f1 == f2 == f3):
                metrics.oht_inward_penalty += self.weights["TRIGRAM_PENALTIES"].get("OHT_inward", 2)

            # Напрямок ВІД центру (Outward): індекси пальців спадають
            elif f1 >= f2 >= f3 and not (f1 == f2 == f3):
                metrics.oht_outward_penalty += self.weights["TRIGRAM_PENALTIES"].get("OHT_outward", 5)

            # Злам напрямку (Awkward): туди-сюди (напр. середній -> мізинець -> вказівний)
            elif (f1 < f2 > f3) or (f1 > f2 < f3):
                metrics.oht_awkward_penalty += self.weights["TRIGRAM_PENALTIES"].get("OHT_awkward", 8)


    def _calculate_sfb(self, k1: Key, k2: Key) -> float:
        """
        Розраховує штраф за натискання двох клавіш одним пальцем
        """
        # Якщо руки або пальці різні, це не SFB
        if k1.hand != k2.hand or k1.finger.value != k2.finger.value:
            return 0.0

        start_row, end_row, move_type, finger_strength = self._get_movement_details(k1, k2)

        row_diff = abs(k1.row - k2.row)

        if row_diff == 2:
            if k1.hand == Hand.RIGHT and k1.row == 2 and move_type == "diagonal":
                return self.weights.get("SEVERE_PENALTIES", {}).get(f"SFS_{move_type}", 10.0)
            return
        
        # 2. Пошук у матриці SFB
        move_tuple = (start_row, end_row, move_type)
        penalty_dict = self.weights.get("SFB_PENALTIES", {}).get(finger_strength, {})

        return penalty_dict.get(move_tuple, 5.0)

    def _get_movement_details(self, k1: Key, k2: Key) -> Tuple[str, str, str, str]:
        """
        Аналізує перехід між двома клавішами.
        Повертає: (початковий_ряд, кінцевий_ряд, тип_руху, сила_пальця)
        """
        start_row = self.get_row_name(k1.row)
        end_row = self.get_row_name(k2.row)

        # Перевіряємо, чи залишився палець у своєму стовпці
        move_type = "straight" if k1.col == k2.col else "diagonal"

        # Визначаємо силу пальця (Enum передаємо напряму)
        finger_strength = self._get_finger_strength(k1.finger)

        return start_row, end_row, move_type, finger_strength

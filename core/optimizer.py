import copy
import random
import core.scorer as scoring
import core.models as models

class LayoutOptimizer:
    def __init__(self, initial_layout, text_data, config):
        self.best_layout = initial_layout
        self.text_data = text_data
        # Отримуємо початкову оцінку
        self.best_score = scoring.calculate_total_penalty(self.best_layout, self.text_data)

    def run_optimization(self, iterations=10000, ui_callback=None):
        for i in range(iterations):
            # 1. Робимо копію для експериментів
            candidate_layout = copy.deepcopy(self.best_layout)

            # 2. Мутація: вибираємо дві випадкові незаморожені кнопки і міняємо місцями
            unfrozen_keys = [k for k in candidate_layout.keys if not k.is_frozen]
            key1, key2 = random.sample(unfrozen_keys, 2)
            key1.char, key2.char = key2.char, key1.char

            # 3. Оцінюємо мутанта
            candidate_score = scoring.calculate_total_penalty(candidate_layout, self.text_data)

            # 4. Відбір (Hill Climbing)
            if candidate_score < self.best_score:
                self.best_layout = candidate_layout
                self.best_score = candidate_score

            # 5. Оновлення UI
            if ui_callback and i % 500 == 0:
                ui_callback(self.best_layout, self.best_score, current_iteration=i)

        return self.best_layout
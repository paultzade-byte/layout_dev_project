# slider_spec

# slider_spec.py
SLIDER_DESCRIPTORS = {
    "base_effort": {
        "row_multiplier": {
            "top": {"default": 1.5, "label": "Top row penalty", "min": 0.01, "max": 3.0},
            "home_row": {"default": 1.0, "label": "Home row penalty", "min": 0.01, "max": 3.0},
        },
        "finger_multiplier": {
            "pinky": {"default": 1.4, "label": "Pinky effort", "min": 0.01, "max": 3.0},
        },
    },
    "same_finger": {
        "double_tap": {"default": 2.0, "label": "SFB double tap", "min": 0.01, "max": 5.0},
    },
    "roll": {
        "outward": {"default": 0.9, "label": "Outward roll penalty", "min": 0.01, "max": 1.0},
    },
}


def _is_leaf(node: dict) -> bool:
    return "default" in node and "label" in node


def slider_data_conveyer(tree: dict = SLIDER_DESCRIPTORS, path: tuple = ()):
    for key, value in tree.items():
        current_path = path + (key,)
        if _is_leaf(value):
            yield current_path, value
        else:
            yield from slider_data_conveyer(value, current_path)

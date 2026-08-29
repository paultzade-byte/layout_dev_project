"""Build validated domain layouts from the selected geometry configuration."""

from typing import Any, Dict

from core.models import Finger, Hand, Key, Layout


_HAND_BY_CONFIG_VALUE = {"L": Hand.LEFT, "R": Hand.RIGHT}
_FINGER_BY_CONFIG_VALUE = {
    "L_pinky": Finger.PINKY,
    "R_pinky": Finger.PINKY,
    "L_ring": Finger.RING,
    "R_ring": Finger.RING,
    "L_middle": Finger.MIDDLE,
    "R_middle": Finger.MIDDLE,
    "L_index": Finger.INDEX,
    "R_index": Finger.INDEX,
    "L_thumb": Finger.THUMB,
    "R_thumb": Finger.THUMB,
}



def build_key_from_position(position: Dict[str, Any]) -> Key:
    """Будує один Key з одного запису geometry['positions']. Використовується
    і в build_layout(), і при ресинку геометрії після drag&drop в UI."""
    hand = _HAND_BY_CONFIG_VALUE[position["hand"]]
    finger = _FINGER_BY_CONFIG_VALUE[position["finger"]]
    char = position.get("default", "")
    if not isinstance(char, str):
        raise TypeError("default must be a string")
    return Key(
        position_id=position["id"],
        x=float(position.get("x", position["col"])),
        y=float(position.get("y", position["row"])),
        row=position["row"],
        home_row=position["home_row"],
        home_col=position["home_col"],
        col=position["col"],
        hand=hand,
        finger=finger,
        base_cost=float(position.get("base_cost", 1.0)),
        char=char,
        is_frozen=position.get("role") == "mod" or not char,
    )

def build_layout(geometry: Dict[str, Any]) -> Layout:
    positions = geometry.get("positions")
    if not isinstance(positions, list):
        raise ValueError("geometry must contain a 'positions' list")
    keys = []
    for position in positions:
        try:
            keys.append(build_key_from_position(position))
        except (KeyError, TypeError, ValueError) as error:
            position_id = position.get("id", "unknown")
            raise ValueError(f"invalid geometry position {position_id}: {error}") from error
    if len({key.position_id for key in keys}) != len(keys):
        raise ValueError("geometry position ids must be unique")
    return Layout(keys=keys)

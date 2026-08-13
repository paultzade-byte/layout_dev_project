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


def build_layout(geometry: Dict[str, Any]) -> Layout:
    """Create a ``Layout`` from one layout entry in ``geometry.json``.

    Modifier and empty positions are frozen so optimization may not exchange
    their values with typeable characters.
    """
    positions = geometry.get("positions")
    if not isinstance(positions, list):
        raise ValueError("geometry must contain a 'positions' list")

    keys = []
    for position in positions:
        try:
            hand = _HAND_BY_CONFIG_VALUE[position["hand"]]
            finger = _FINGER_BY_CONFIG_VALUE[position["finger"]]
            char = position.get("default", "")
            if not isinstance(char, str):
                raise TypeError("default must be a string")
            keys.append(
                Key(
                    position_id=position["id"],
                    x=float(position.get("x", position["col"])),
                    y=float(position.get("y", position["row"])),
                    row=position["row"],
                    col=position["col"],
                    hand=hand,
                    finger=finger,
                    base_cost=float(position.get("base_cost", 1.0)),
                    char=char,
                    is_frozen=position.get("role") == "mod" or not char,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            position_id = position.get("id", "unknown")
            raise ValueError(f"invalid geometry position {position_id}: {error}") from error

    if len({key.position_id for key in keys}) != len(keys):
        raise ValueError("geometry position ids must be unique")
    return Layout(keys=keys)

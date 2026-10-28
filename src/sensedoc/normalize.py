"""Turn values written many different ways into one standard form."""

import re

VOLUME_UNITS_ML = {"ml": 1, "cl": 10, "l": 1000, "ltr": 1000, "litre": 1000, "liter": 1000}
VOLUME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|cl|ltr|litre|liter|l)\b", re.IGNORECASE)


def volume_to_ml(text: str) -> float | None:
    """'50cl' -> 500.0, '1.5L' -> 1500.0, 'big bottle' -> None"""
    match = VOLUME_PATTERN.search(text)
    if not match:
        return None
    number, unit = match.groups()
    return float(number) * VOLUME_UNITS_ML[unit.lower()]


NORMALIZERS = {"volume_ml": volume_to_ml}

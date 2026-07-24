"""Relative time-window ('15m', '1h', '3d') → absolute unix-second range."""

import time

_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def window_range(window: str) -> tuple[int, int]:
    now = int(time.time())
    n, unit = int(window[:-1]), window[-1]
    return now - n * _MULT[unit], now

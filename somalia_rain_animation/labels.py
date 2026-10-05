"""Forecast day dates and titles, shared by the video frames and the app data."""
from __future__ import annotations

import datetime as dt

from . import config

EAT = dt.timedelta(hours=config.EAT_OFFSET_HOURS)
N_DAYS = len(config.FORECAST_HOURS)


def fmt_date(d):
    return f"{d:%A} {d.day} {d:%B %Y}"


def fmt_eat(t):
    return f"{t:%H:%M} EAT, {t:%A} {t.day} {t:%B %Y}"


def day_date(t0: dt.datetime, k: int) -> dt.date:
    """Calendar date (EAT) at the middle of forecast day k; t0 is the start of day 1 in UTC."""
    return (t0 + dt.timedelta(hours=24 * k - 12) + EAT).date()


def day_window(t0: dt.datetime, k: int) -> tuple[dt.datetime, dt.datetime]:
    """Start and end of forecast day k in EAT."""
    return t0 + dt.timedelta(hours=24 * (k - 1)) + EAT, t0 + dt.timedelta(hours=24 * k) + EAT


def week_range(t0: dt.datetime) -> str:
    a, b = day_date(t0, 1), day_date(t0, N_DAYS)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {b:%B %Y}"
    return f"{a.day} {a:%B}–{b.day} {b:%B %Y}"


def total_title(t0: dt.datetime, n: int = N_DAYS) -> str:
    a, b = day_date(t0, 1), day_date(t0, n)
    return f"Weekly Total: {a:%A} {a.day} {a:%B} to {fmt_date(b)}"

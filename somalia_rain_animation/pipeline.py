"""Steps 1 to 3 shared by the video (cli) and the app data (publish):
choose the run, download the APCP totals, difference into daily grids and check the sum."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config, gfs


@dataclass
class RunData:
    date: dt.date            # GFS run date
    cycle: int               # run cycle, UTC hour
    lead: int                # days between the run date and forecast day 1
    hours: list[int]         # forecast hours closing each day
    days: list[np.ndarray]   # daily rainfall (mm) on the native 0.25 degree grid
    lat1: np.ndarray         # ascending latitudes of the native grid
    lon1: np.ndarray
    run_id: str              # e.g. 20261005_00Z or 20261004_00Z_from_20261005

    @property
    def run_dt(self) -> dt.datetime:
        return dt.datetime(self.date.year, self.date.month, self.date.day, self.cycle)

    @property
    def t0(self) -> dt.datetime:
        """Start of forecast day 1 (UTC)."""
        return self.run_dt + dt.timedelta(days=self.lead)

    @property
    def first_day(self) -> dt.date:
        return self.date + dt.timedelta(days=self.lead)


def select_run(date: dt.date | None, start: dt.date | None, cycle: int):
    """Return (run date, lead days, closing hours). Raises gfs.RunNotAvailable or ValueError."""
    if date is None:
        print(f"Looking for the latest published {cycle:02d}Z run...")
        need = 24 * ((start - dt.date.today()).days + len(config.FORECAST_HOURS) + 1) if start else None
        date = gfs.latest_run(cycle, last_hour=need)
    lead = (start - date).days if start else 0
    if lead < 0 or lead > 9:
        raise ValueError(f"--start-date must be 0 to 9 days after the run date ({date:%Y-%m-%d}).")
    hours = [24 * (lead + k) for k in range(1, len(config.FORECAST_HOURS) + 1)]
    if not gfs.is_available(date, cycle, hours[-1]):
        raise gfs.RunNotAvailable(
            f"The {cycle:02d}Z run of {date:%Y-%m-%d} is not (yet) available on NOMADS up to "
            f"hour {hours[-1]}. GFS runs are usually complete about 4 to 5 hours after the cycle time.")
    return date, lead, hours


def run_id_for(date: dt.date, cycle: int, lead: int) -> str:
    first = date + dt.timedelta(days=lead)
    return f"{date:%Y%m%d}_{cycle:02d}Z" + (f"_from_{first:%Y%m%d}" if lead else "")


def compute_run(date: dt.date | None = None, start: dt.date | None = None, cycle: int = 0,
                grib_root: Path | None = None) -> RunData:
    date, lead, hours = select_run(date, start, cycle)
    run_id = run_id_for(date, cycle, lead)
    grib_dir = (grib_root or config.OUTPUT_DIR) / run_id / "grib"
    print(f"Run: {cycle:02d}Z {date:%Y-%m-%d}, days from {date + dt.timedelta(days=lead):%Y-%m-%d} "
          f"(hours {24 * lead} to {hours[-1]})")

    # Steps 1 and 2: download and read the 0 to N hour totals
    base = None
    if lead:
        base = gfs.read_total(gfs.download(date, cycle, 24 * lead, grib_dir), 24 * lead)[0]
    totals = []
    for h in hours:
        vals, lat1, lon1 = gfs.read_total(gfs.download(date, cycle, h, grib_dir), h)
        totals.append(vals)

    # Step 3: daily differences and sum check
    days = gfs.daily_from_totals(totals, base)
    if base is None:
        gfs.sum_check(days, totals[-1])
    else:
        gfs.sum_check(days, totals[-1] - base, label=f"f{hours[-1]:03d} minus f{24 * lead:03d}")
    return RunData(date, cycle, lead, hours, days, lat1, lon1, run_id)

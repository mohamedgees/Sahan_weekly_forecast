"""GFS 0.25 degree APCP: download, read, daily differencing and regridding."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import numpy as np
import pygrib
import requests
from scipy.interpolate import RegularGridInterpolator

from . import config


class RunNotAvailable(RuntimeError):
    pass


def grib_name(cycle: int, fhour: int) -> str:
    return f"gfs.t{cycle:02d}z.pgrb2.0p25.f{fhour:03d}"


def request_params(date: dt.date, cycle: int, fhour: int) -> dict:
    return {
        "dir": f"/gfs.{date:%Y%m%d}/{cycle:02d}/atmos",
        "file": grib_name(cycle, fhour),
        "var_APCP": "on",
        "lev_surface": "on",
        "subregion": "",
        **{k: str(v) for k, v in config.SUBREGION.items()},
    }


def _fetch(date, cycle, fhour, timeout=60) -> bytes | None:
    """One request. Returns GRIB bytes, None if the file is not on the server."""
    r = requests.get(config.NOMADS_URL, params=request_params(date, cycle, fhour), timeout=timeout)
    if r.status_code == 404 or (r.ok and not r.content.startswith(b"GRIB")):
        return None
    r.raise_for_status()
    return r.content


def is_available(date: dt.date, cycle: int, last_hour: int | None = None) -> bool:
    """A run counts as published when its last needed step (f168 by default) can be fetched."""
    try:
        return _fetch(date, cycle, last_hour or config.FORECAST_HOURS[-1], timeout=30) is not None
    except requests.RequestException:
        return False


def latest_run(cycle: int = 0, days_back: int = 3, last_hour: int | None = None) -> dt.date:
    today = dt.datetime.now(dt.timezone.utc).date()
    for back in range(days_back + 1):
        d = today - dt.timedelta(days=back)
        if dt.datetime(d.year, d.month, d.day, cycle, tzinfo=dt.timezone.utc) > dt.datetime.now(dt.timezone.utc):
            continue
        if is_available(d, cycle, last_hour):
            return d
        print(f"  {cycle:02d}Z run of {d:%Y-%m-%d} not yet available, trying the day before")
    raise RunNotAvailable(f"No published {cycle:02d}Z run found in the last {days_back} days.")


def download(date: dt.date, cycle: int, fhour: int, dest_dir: Path,
             retries: int = 5, wait: float = 10.0) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / grib_name(cycle, fhour)
    if path.exists() and path.read_bytes()[:4] == b"GRIB":
        print(f"  {path.name}: cached")
        return path
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            data = _fetch(date, cycle, fhour)
            if data is None:
                raise RunNotAvailable(
                    f"{grib_name(cycle, fhour)} for the {cycle:02d}Z run of {date:%Y-%m-%d} is not "
                    "yet available on NOMADS. Try an earlier run or wait for this one to finish.")
            path.write_bytes(data)
            print(f"  {path.name}: downloaded {len(data) / 1024:.0f} kB")
            return path
        except RunNotAvailable:
            raise
        except requests.RequestException as e:
            last_err = e
            print(f"  {path.name}: attempt {attempt}/{retries} failed ({e}); retrying in {wait:.0f} s")
            time.sleep(wait)
            wait *= 1.5
    raise RuntimeError(f"Download of {path.name} failed after {retries} attempts: {last_err}")


def read_total(path: Path, fhour: int):
    """Return (values, lats_1d, lons_1d) for the 0 to fhour APCP total, lats ascending."""
    with pygrib.open(str(path)) as grbs:
        msgs = [m for m in grbs if m.shortName == "tp" or m.name == "Total Precipitation"]
        match = [m for m in msgs if m.startStep == 0 and m.endStep == fhour]
        if not match:
            found = ", ".join(f"{m.startStep} to {m.endStep}" for m in msgs) or "none"
            raise RuntimeError(f"{path.name}: no APCP message for hours 0 to {fhour} (found: {found})")
        m = match[0]
        vals = np.asarray(m.values, dtype="float64")
        lats, lons = m.latlons()
    lat1, lon1 = lats[:, 0], lons[0, :]
    if lat1[0] > lat1[-1]:
        lat1, vals = lat1[::-1], vals[::-1, :]
    return np.ma.filled(vals, np.nan), lat1, lon1


def daily_from_totals(totals: list[np.ndarray], base: np.ndarray | None = None) -> list[np.ndarray]:
    """Day N = total(0 to end of day N) minus total(0 to start of day N). `base` is the
    0 to start total when the first day does not begin at the run time."""
    days, prev = [], (np.zeros_like(totals[0]) if base is None else base)
    for t in totals:
        days.append(np.clip(t - prev, 0, None))
        prev = t
    return days


def sum_check(days, final_total, label="f168"):
    s = np.sum(days, axis=0)
    diff = np.abs(s - final_total)
    print(f"Sum check: sum of {len(days)} daily grids vs {label} total")
    print(f"  domain mean  daily sum = {np.nanmean(s):.3f} mm, total = {np.nanmean(final_total):.3f} mm")
    print(f"  domain max   daily sum = {np.nanmax(s):.3f} mm, total = {np.nanmax(final_total):.3f} mm")
    print(f"  max abs difference     = {np.nanmax(diff):.4f} mm  (nonzero only where a negative step was clipped)")
    print(f"  cells differing > 0.01 = {(diff > 0.01).sum()} of {diff.size}")
    return float(np.nanmax(diff))


def target_grid(extent):
    x0, x1, y0, y1 = extent
    lons = np.round(np.arange(x0, x1 + config.GRID_STEP / 2, config.GRID_STEP), 4)
    lats = np.round(np.arange(y0, y1 + config.GRID_STEP / 2, config.GRID_STEP), 4)
    return lons, lats


def regrid(vals, lat1, lon1, lons, lats):
    f = RegularGridInterpolator((lat1, lon1), vals, method="linear", bounds_error=True)
    yy, xx = np.meshgrid(lats, lons, indexing="ij")
    return f(np.column_stack([yy.ravel(), xx.ravel()])).reshape(yy.shape)

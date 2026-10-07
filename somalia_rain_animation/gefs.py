"""GEFS ensemble (31 members, 0.25 degree): chance of rain per forecast day.

GFS gives one amount per place and day. GEFS runs the same model 31 times from slightly different
starts; the chance of rain is the share of members that forecast at least a threshold. The members'
APCP comes in 6 hour pieces, so each forecast day adds up four files per member.

Output (chance.json, read by the app): for each day the chance (0 to 100) of
  rain   2 mm or more in the day (anything above the Dry category)
  heavy  30 mm or more in the day (the heavy rain alert level)
and for the week the chance of 50 mm or more, on the native 0.25 degree grid.
These are raw ensemble chances, not calibrated against observations.
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pygrib
import requests

from . import config

URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl"
MEMBERS = ["gec00"] + [f"gep{i:02d}" for i in range(1, 31)]
RAIN_MM, HEAVY_MM, WEEK_MM = 2.0, 30.0, 50.0


def _name(member: str, cycle: int, fhour: int) -> str:
    return f"{member}.t{cycle:02d}z.pgrb2s.0p25.f{fhour:03d}"


def _download(date: dt.date, cycle: int, member: str, fhour: int, dest: Path, retries: int = 6) -> Path:
    path = dest / _name(member, cycle, fhour)
    if path.exists() and path.read_bytes()[:4] == b"GRIB":
        return path
    params = {"dir": f"/gefs.{date:%Y%m%d}/{cycle:02d}/atmos/pgrb2sp25", "file": _name(member, cycle, fhour),
              "var_APCP": "on", "lev_surface": "on", "subregion": "",
              **{k: str(v) for k, v in config.SUBREGION.items()}}
    wait = 5.0
    for attempt in range(retries):
        try:
            r = requests.get(URL, params=params, timeout=60)
            if r.ok and r.content.startswith(b"GRIB"):
                path.write_bytes(r.content)
                return path
            if r.status_code == 404:
                raise FileNotFoundError(path.name)
        except requests.RequestException:
            pass
        time.sleep(wait)   # NOMADS limits request rates: back off and retry
        wait *= 1.6
    raise RuntimeError(f"GEFS download failed: {path.name}")


def _read_6h(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The 6 hour APCP in one GEFS file (mm), lats ascending."""
    with pygrib.open(str(path)) as grbs:
        m = [g for g in grbs if g.shortName == "tp" or g.name == "Total Precipitation"][0]
        vals = np.asarray(m.values, dtype="float64")
        lats, lons = m.latlons()
    lat1, lon1 = lats[:, 0], lons[0, :]
    if lat1[0] > lat1[-1]:
        lat1, vals = lat1[::-1], vals[::-1, :]
    return np.clip(np.ma.filled(vals, 0.0), 0, None), lat1, lon1


def member_days(date: dt.date, cycle: int, hours: list[int], dest: Path, workers: int = 3):
    """Daily rain per member: array (members, days, lat, lon) for the days closing at `hours`."""
    dest.mkdir(parents=True, exist_ok=True)
    steps = sorted({h - k for h in hours for k in (18, 12, 6, 0)})
    jobs = [(m, s) for m in MEMBERS for s in steps]
    with ThreadPoolExecutor(workers) as pool:   # a few at a time: NOMADS blocks heavy users
        paths = list(pool.map(lambda j: _download(date, cycle, j[0], j[1], dest), jobs))
    by = dict(zip(jobs, paths))
    lat1 = lon1 = None
    out = []
    for m in MEMBERS:
        days = []
        for h in hours:
            day = None
            for s in (h - 18, h - 12, h - 6, h):
                v, lat1, lon1 = _read_6h(by[(m, s)])
                day = v if day is None else day + v
            days.append(day)
        out.append(days)
    return np.asarray(out), lat1, lon1


def chances(md: np.ndarray) -> dict[str, np.ndarray]:
    """Percent of members at or above each threshold."""
    res = {}
    for d in range(md.shape[1]):
        res[f"rain_day{d + 1}"] = 100.0 * (md[:, d] >= RAIN_MM).mean(axis=0)
        res[f"heavy_day{d + 1}"] = 100.0 * (md[:, d] >= HEAVY_MM).mean(axis=0)
    res["week50"] = 100.0 * (md.sum(axis=1) >= WEEK_MM).mean(axis=0)
    return res


def export_chance(date: dt.date, cycle: int, hours: list[int], dest_grib: Path, out_dir: Path):
    """Write chance.json next to the run's other files and return the member data
    (md, lat1, lon1) for the area chances; None (and no file) if GEFS is unavailable."""
    try:
        t = time.time()
        md, lat1, lon1 = member_days(date, cycle, hours, dest_grib)
        ch = chances(md)
    except Exception as e:   # the forecast is still published without chances
        print(f"  GEFS chances skipped: {e}")
        return None
    import json
    pack = lambda g: np.round(g).astype(int).ravel().tolist()
    data = {"lat0": float(lat1[0]), "dlat": float(lat1[1] - lat1[0]), "nlat": len(lat1),
            "lon0": float(lon1[0]), "dlon": float(lon1[1] - lon1[0]), "nlon": len(lon1),
            "scale": 1, "members": len(MEMBERS),
            "thresholds": {"rain": RAIN_MM, "heavy": HEAVY_MM, "week": WEEK_MM},
            "grids": {k: pack(v) for k, v in ch.items()}}
    (out_dir / "chance.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"  GEFS chances: {len(MEMBERS)} members, {time.time() - t:.0f} s")
    return md, lat1, lon1

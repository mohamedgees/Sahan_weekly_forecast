"""Daily weather beyond rainfall from the same GFS 0.25 degree run: temperature, heat index, wind,
gusts and humidity for days 1 to 7, and rainfall for days 8 to 14 (week 2).

Temperature, wind, gusts and humidity come from the 3 hourly files (f003 to f168): TMAX and TMIN are
3 or 6 hour windows and the others are instantaneous, so the day's highest and lowest need every step.
The heat index ("feels like") is worked out from 2 m temperature and humidity with the NOAA formula
(the GRIB filter does not serve GFS's own APTMP field).
Day k covers 00 to 24 UTC (03:00 to 03:00 EAT), the same days as the rainfall.
Kept apart from gfs.py and pipeline.py so the video stays rainfall only.
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pygrib
import requests

from . import config, gfs

FIELDS = ("tmax", "tmin", "2t", "2r", "10u", "10v", "gust")


def _name(cycle: int, fhour: int) -> str:
    return f"gfs.t{cycle:02d}z.wx2.f{fhour:03d}"   # not the rain file name; wx2: with APCP and soil water


def _download(date: dt.date, cycle: int, fhour: int, dest: Path, retries: int = 6) -> Path:
    path = dest / _name(cycle, fhour)
    if path.exists() and path.read_bytes()[:4] == b"GRIB":
        return path
    params = {"dir": f"/gfs.{date:%Y%m%d}/{cycle:02d}/atmos", "file": gfs.grib_name(cycle, fhour),
              "var_TMAX": "on", "var_TMIN": "on", "var_TMP": "on", "var_UGRD": "on", "var_VGRD": "on",
              "var_GUST": "on", "var_RH": "on", "var_APCP": "on", "var_SOILW": "on",
              "lev_2_m_above_ground": "on", "lev_10_m_above_ground": "on", "lev_surface": "on",
              "lev_0-0.1_m_below_ground": "on",
              "subregion": "", **{k: str(v) for k, v in config.SUBREGION.items()}}
    wait = 5.0
    for _ in range(retries):
        try:
            r = requests.get(config.NOMADS_URL, params=params, timeout=60)
            if r.ok and r.content.startswith(b"GRIB"):
                path.write_bytes(r.content)
                return path
            if r.status_code == 404:
                raise gfs.RunNotAvailable(f"{gfs.grib_name(cycle, fhour)} is not on NOMADS")
        except requests.RequestException:
            pass
        time.sleep(wait)   # NOMADS limits request rates: back off and retry
        wait *= 1.6
    raise RuntimeError(f"GFS weather download failed: {path.name}")


def _read(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """The fields of one step on the native grid, lats ascending."""
    out, lat1, lon1 = {}, None, None
    with pygrib.open(str(path)) as grbs:
        for m in grbs:
            # Rain since the start of the run (for 3 hour amounts) and topsoil water (flash floods);
            # files cached before these were added simply lack them
            if m.shortName == "tp" and m.startStep == 0 and "tp" not in out:
                out["tp"] = np.asarray(m.values, dtype="float64")
            elif m.shortName in ("soilw", "swvl1") and "soil" not in out:
                out["soil"] = np.asarray(m.values, dtype="float64")
            if m.shortName in FIELDS and m.shortName not in out:
                v = np.asarray(m.values, dtype="float64")
                if lat1 is None:
                    lats, lons = m.latlons()
                    lat1, lon1 = lats[:, 0], lons[0, :]
                out[m.shortName] = v
    missing = [f for f in FIELDS if f not in out]
    if missing:
        raise RuntimeError(f"{path.name}: missing {', '.join(missing)}")
    if lat1[0] > lat1[-1]:
        lat1, out = lat1[::-1], {k: v[::-1, :] for k, v in out.items()}
    return out, lat1, lon1


def heat_index(t_c: np.ndarray, rh: np.ndarray) -> np.ndarray:
    """NOAA heat index (°C) from temperature (°C) and relative humidity (%); the temperature itself below
    about 27 °C, where the formula does not apply (Rothfusz regression with the NWS adjustments)."""
    t = t_c * 9 / 5 + 32
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 6.83783e-3 * t * t
          - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    low = (rh < 13) & (t >= 80) & (t <= 112)
    hi = np.where(low, hi - (13 - rh) / 4 * np.sqrt(np.clip(17 - np.abs(t - 95), 0, None) / 17), hi)
    high = (rh > 85) & (t >= 80) & (t <= 87)
    hi = np.where(high, hi + (rh - 85) / 10 * (87 - t) / 5, hi)
    hi = np.where((simple + t) / 2 < 80, simple, hi)
    return np.where(t_c < 26.7, t_c, (hi - 32) * 5 / 9)


def daily_weather(date: dt.date, cycle: int, lead: int, ndays: int, dest: Path, workers: int = 2):
    """Per day on the native grid: tmax, tmin, heat (max heat index), wind (max 10 m wind), gust (max),
    all °C or km/h, and rh (mean %), rhmin (%). Returns (days: list of dicts, lat1, lon1)."""
    dest.mkdir(parents=True, exist_ok=True)
    t = time.time()
    steps = [24 * lead + s for s in range(3, 24 * ndays + 1, 3)]
    with ThreadPoolExecutor(workers) as pool:   # a few at a time: NOMADS blocks heavy users
        paths = list(pool.map(lambda h: _download(date, cycle, h, dest), steps))
    lat1 = lon1 = None
    days = []
    prev_tp = None if lead else 0.0   # rain total at the previous step (unknown before the first step)
    for k in range(ndays):
        acc = {"tmax": None, "tmin": None, "heat": None, "wind": None, "gust": None, "rhmin": None}
        rh_sum, n = None, 0
        for path in paths[8 * k: 8 * (k + 1)]:   # 8 steps of 3 hours per day
            f, lat1, lon1 = _read(path)
            # Flash flood inputs: wettest 3 hours of the day, and topsoil water at the start of the day
            if "tp" in f:
                if prev_tp is not None:
                    r3 = np.clip(f["tp"] - prev_tp, 0, None)
                    acc["rain3h"] = r3 if acc.get("rain3h") is None else np.maximum(acc["rain3h"], r3)
                prev_tp = f["tp"]
            if "soil" in f and "soil" not in acc:
                acc["soil"] = np.nan_to_num(f["soil"])
            vals = {"tmax": f["tmax"] - 273.15, "tmin": f["tmin"] - 273.15,
                    "heat": heat_index(f["2t"] - 273.15, f["2r"]),
                    "wind": np.hypot(f["10u"], f["10v"]) * 3.6, "gust": f["gust"] * 3.6, "rhmin": f["2r"]}
            for key, v in vals.items():
                if acc[key] is None:
                    acc[key] = v
                elif key in ("tmin", "rhmin"):
                    acc[key] = np.minimum(acc[key], v)
                else:
                    acc[key] = np.maximum(acc[key], v)
            rh_sum = f["2r"] if rh_sum is None else rh_sum + f["2r"]
            n += 1
        acc["rh"] = rh_sum / n
        days.append(acc)
    print(f"  weather: {len(steps)} steps, {ndays} days, {time.time() - t:.0f} s")
    return days, lat1, lon1


def week2_rain(date: dt.date, cycle: int, lead: int, dest: Path):
    """Rainfall for days 8 to 14 (mm per day) from the APCP totals after the first week, with a sum check.
    The base is the 0 to end-of-day-7 total (the rain pipeline's last file, already in `dest`)."""
    h7 = 24 * (lead + 7)
    base_total = gfs.read_total(gfs.download(date, cycle, h7, dest), h7)[0]
    hours = [h7 + 24 * k for k in range(1, 8)]
    totals = [gfs.read_total(gfs.download(date, cycle, h, dest), h)[0] for h in hours]
    days = gfs.daily_from_totals(totals, base_total)
    gfs.sum_check(days, totals[-1] - base_total, label=f"f{hours[-1]:03d} minus f{24 * (lead + 7):03d}")
    return days

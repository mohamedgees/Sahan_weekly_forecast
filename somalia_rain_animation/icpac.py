"""Seasonal outlooks from ICPAC (IGAD Climate Prediction and Applications Centre) for the app's Seasonal tab.

The outlooks are ICPAC's official seasonal forecasts for the Greater Horn of Africa (the GHACOF season
forecasts shown on https://www.icpac.net/seasonal-forecast/): for each place, the probability (%) of the
season being below normal, normal or above normal. They are read from ICPAC's data files
(https://eahazardswatch.icpac.net/ftp/seasonal_prob_prec/ and seasonal_prob_temp/, one NetCDF file per
forecast, named e.g. PredictedProbabilityRain_Mar-May_Feb2026.nc: the months covered and the month of
issue). The legend colours come from ICPAC's Hazards Watch dataset list. The app credits ICPAC and links
to its site.

Seasons follow ICPAC's forum calendar:
  rain  Gu   March to May, issued in February      Deyr  October to December, issued in August
  temp  the same, and Jilaal January to March (December) and Xagaa June to September (May)
Where that issue is missing, the last forecast for the same months issued before the season began is used.

ICPAC leaves out areas that are usually dry in the season (grey on its maps); inland those stay empty.
Along the coast (up to 0.5 degree inland), where ICPAC's grid stops short of the coastline, land takes the
nearest value, as on ICPAC's printed maps.

Checked on every publish run; an outlook is built once and kept (restored from the live site).
Output in site/seasonal/:
  latest.json                                   the seasons (newest first) with their variables, the
                                                overlay bounds, and "rain" / "temp" for app 1.9.0
  <var>_<Mon>-<Mon>_<YYYY-MM>_v4/overlay.png    transparent overlay in Web Mercator rows over the map
  <var>_<Mon>-<Mon>_<YYYY-MM>_v4/overlay_hd.png the same at high detail
  <var>_<Mon>-<Mon>_<YYYY-MM>_v4/data.json      legend, dominant category and probability per region and
                                                district, and a 0.05 degree grid for tap lookups
                                                (category * 100 + lower bound of the probability class)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

from . import config
from .layers import map_extent

API = "https://eahazardswatch.icpac.net/api/datasets/"
FTP = "https://eahazardswatch.icpac.net/ftp/"
VARIABLES = {
    "rain": ("Seasonal Rainfall Probabilistic Forecast", "seasonal_prob_prec", "Rain"),
    "temp": ("Seasonal Temperature Probabilistic Forecast", "seasonal_prob_temp", "Temp"),
}
CATEGORIES = [("below", "Below Normal"), ("normal", "Normal"), ("above", "Above Normal")]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON_ORDER = ["jilaal", "gu", "xagaa", "deyr"]
# Per variable and season: (first month, last month, month of issue), preferred first
PLAN = {
    "rain": {"gu": [("Mar", "May", "Feb")], "deyr": [("Oct", "Dec", "Aug")]},
    "temp": {"jilaal": [("Jan", "Mar", "Dec")], "gu": [("Mar", "May", "Feb")],
             "xagaa": [("Jun", "Sep", "May"), ("Jul", "Sep", "Jun")], "deyr": [("Oct", "Dec", "Aug"), ("Oct", "Dec", "Sep")]},
}
KEPT = {"rain": 4, "temp": 8}   # seasons per variable: the last two years
GRID = 0.05                     # tap and area grid (degrees)
COAST_CELLS = 10                # coastal gaps filled up to 0.5 degree from the sea and from ICPAC's data
VERSION = 4                     # outlooks built before this (from the map server) are rebuilt
_LOWS = [33, 40, 50, 60, 70, 80, 90]
# ICPAC's rainfall legend (Hazards Watch, checked on 13 October 2026), if the dataset list cannot be read
_FALLBACK = {"below": ["#FEFF7F", "#FFE300", "#FDAA00", "#FE8D01", "#FF7201", "#FE3801", "#FF0200"],
             "normal": ["#E5FFFF", "#B2FFFF", "#7FFFFE", "#66FFFF", "#4BFFFF", "#1CFFFF", "#00FFFF"],
             "above": ["#BBFFBA", "#65F964", "#4AB811", "#38AA0F", "#2A9C0A", "#138004", "#015000"]}


def _legends() -> dict:
    """Colour classes per variable and category from the Hazards Watch dataset list."""
    items = requests.get(API, timeout=60).json()
    items = items if isinstance(items, list) else next(v for v in items.values() if isinstance(v, list))
    out = {}
    for var, (name, _, _) in VARIABLES.items():
        d = next(i for i in items if i.get("name") == name)
        legend = {}
        for cat, title in CATEGORIES:
            lay = next(l for l in d["layers"] if l["name"] == title)
            names = [it["name"] for it in lay["legendConfig"]["items"]]
            colours = [it["color"] for it in lay["legendConfig"]["items"]]
            # A swatch labelled N is the class just below N; the last ("%") is the top class
            lows = [33] + [int(n) for n in names[:-1]]
            legend[cat] = [{"colour": c, "min": lo, "max": (int(names[i]) if i < len(names) - 1 else 100)}
                           for i, (c, lo) in enumerate(zip(colours, lows))]
        out[var] = legend
    return out


def _issues(var: str, today: dt.date) -> list[tuple[dt.date, str, str, str]]:
    """(month of issue, first month, last month, file url) of this year's and last year's forecasts."""
    _, folder, word = VARIABLES[var]
    pat = re.compile(rf'href="PredictedProbability{word}_([A-Z][a-z]{{2}})-([A-Z][a-z]{{2}})_([A-Z][a-z]{{2}})(\d{{4}})\.nc"')
    out = []
    for year in (today.year - 1, today.year):
        r = requests.get(f"{FTP}{folder}/netcdf/{year}/", timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for a, b, im, iy in pat.findall(r.text):
            if a in MONTHS and b in MONTHS and im in MONTHS:
                url = f"{FTP}{folder}/netcdf/{year}/PredictedProbability{word}_{a}-{b}_{im}{iy}.nc"
                out.append((dt.date(int(iy), MONTHS.index(im) + 1, 1), a, b, url))
    return out


def _wanted(issues: dict[str, list]) -> dict[str, dict[tuple[int, str], tuple]]:
    """Per variable: (year, season) -> (issued, first month, last month, url), the outlook to show."""
    out = {}
    for var, plan in PLAN.items():
        found: dict[tuple[int, str], tuple] = {}
        for issued, a, b, url in issues.get(var, []):
            for key, prefs in plan.items():
                for rank, (pa, pb, pm) in enumerate(prefs):
                    if (a, b) != (pa, pb):
                        continue
                    m = MONTHS.index(a) + 1   # the forecast starts after the month of issue
                    start = dt.date(issued.year + (1 if m <= issued.month else 0), m, 1)
                    # The planned month of issue first, then the latest earlier issue for the same months
                    score = (0 if MONTHS[issued.month - 1] == pm else 1, rank, -issued.toordinal())
                    if (start.year, key) not in found or score < found[(start.year, key)][0]:
                        found[(start.year, key)] = (score, (issued, a, b, url))
        newest = sorted(found, key=lambda k: (k[0], SEASON_ORDER.index(k[1])), reverse=True)[:KEPT[var]]
        out[var] = {k: found[k][1] for k in newest}
    return out


def _file_probabilities(url: str):
    """(lats, lons, category 1 below 2 normal 3 above or 0, probability %) from one of ICPAC's files.
    Files come as below/normal/above or pr_below/pr_normal/pr_above (percent), each filled only where
    its category dominates."""
    import netCDF4
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "f.nc"
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        path.write_bytes(r.content)
        with netCDF4.Dataset(path) as d:
            v = d.variables
            lat, lon = np.asarray(d["lat"][:], dtype=float), np.asarray(d["lon"][:], dtype=float)
            keys = next(k for k in (("below", "normal", "above"), ("pr_below", "pr_normal", "pr_above")) if k[0] in v)
            arr = np.stack([np.ma.filled(np.squeeze(v[k][:]).astype(float), np.nan) for k in keys])
    arr = np.where(arr >= 33, arr, np.nan)   # under a third is not a dominant category
    have = ~np.isnan(arr)
    filled = np.where(have, arr, -1)
    cat = np.where(have.any(0), filled.argmax(0) + 1, 0)
    return lat, lon, cat, np.where(have.any(0), filled.max(0), np.nan)


def _codes(g, url: str) -> np.ndarray:
    """Category * 100 + lower bound of the probability class on the value grid (rows from the south); -1 none."""
    lat, lon, cat, prob = _file_probabilities(url)
    fy = np.round((g.lats - lat[0]) / (lat[1] - lat[0])).astype(int)
    fx = np.round((g.lons - lon[0]) / (lon[1] - lon[0])).astype(int)
    oky, okx = (fy >= 0) & (fy < len(lat)), (fx >= 0) & (fx < len(lon))
    iy, ix = np.clip(fy, 0, len(lat) - 1), np.clip(fx, 0, len(lon) - 1)
    c, p = cat[np.ix_(iy, ix)], prob[np.ix_(iy, ix)]
    lows = np.array(_LOWS)
    lo = lows[np.clip(np.searchsorted(lows, np.nan_to_num(p), side="right") - 1, 0, len(lows) - 1)]
    return np.where(np.outer(oky, okx) & (c > 0), c * 100 + lo, -1)


def _fill(codes: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Thin coastal gaps take the nearest value: land cells within COAST_CELLS of the sea and of ICPAC's
    data. ICPAC's gaps inland and its wider coastal strips (usually dry areas) stay empty; the sea is cleared."""
    valid = codes >= 0
    if not valid.any():
        return np.where(land, codes, -1)
    dist, (iy, ix) = ndimage.distance_transform_edt(~valid, return_indices=True)
    from_sea = ndimage.distance_transform_edt(land)
    fill = land & ~valid & (dist <= COAST_CELLS) & (from_sea <= COAST_CELLS)
    out = np.where(fill, codes[iy, ix], codes)
    return np.where(land, out, -1)


def _areas(lyr, codes: np.ndarray, lons, lats) -> dict:
    """Dominant category and its typical probability per region and district."""
    from .export import mask
    out = {"regions": [], "districts": []}
    shapes = [("regions", r["adm1_name"], None, r.geometry) for _, r in lyr["admin1"].iterrows()]
    shapes += [("districts", r["adm2_name"], r["adm1_name"], r.geometry) for _, r in lyr["admin2"].iterrows()
               if r["adm2_name"] != "Unspecified"]
    for kind, name, region, geom in shapes:
        cells = codes[mask(geom, lons, lats)]
        cells = cells[cells >= 0]
        if not len(cells):
            continue
        cats = cells // 100
        top = int(np.bincount(cats).argmax())
        lows = cells[cats == top] % 100
        e = {"name": name, "category": CATEGORIES[top - 1][0], "prob_min": int(np.median(lows)),
             "share": round(float((cats == top).mean() * 100))}
        if region:
            e["region"] = region
        out[kind].append(e)
    return out


class _Grids:
    """The value grid and display grids with their land masks, made once per run."""

    def __init__(self, lyr):
        from .export import land_geometry, mask, mercator_lats
        self.lyr = lyr
        x0, x1, y0, y1 = map_extent(lyr)
        _, land = land_geometry(lyr)
        self.lons = np.round(np.arange(x0, x1 + GRID / 2, GRID), 4)
        self.lats = np.round(np.arange(y0, y1 + GRID / 2, GRID), 4)
        self.land = mask(land, self.lons, self.lats)
        self.display = {}
        for suffix, step in (("", config.GRID_STEP), ("_hd", config.HD_GRID_STEP)):
            lons = np.round(np.arange(x0, x1 + step / 2, step), 4)
            mlats = mercator_lats(y0, y1, int(round((y1 - y0) / step)) + 1)
            ix = np.clip(np.round((lons - self.lons[0]) / GRID).astype(int), 0, len(self.lons) - 1)
            iy = np.clip(np.round((mlats - self.lats[0]) / GRID).astype(int), 0, len(self.lats) - 1)
            self.display[suffix] = (ix, iy, mask(land, lons, mlats))


def _build(g: _Grids, var: str, legend: dict, issued: dt.date, url: str, folder: Path) -> bool:
    """One outlook; False when ICPAC's file has nothing over the map."""
    lons, lats = g.lons, g.lats
    codes = _fill(_codes(g, url), g.land)
    if not (codes >= 0).any():
        return False
    folder.mkdir(parents=True, exist_ok=True)
    palette = {(ci + 1) * 100 + cl["min"]: [int(cl["colour"][k:k + 2], 16) for k in (1, 3, 5)]
               for ci, (cat, _) in enumerate(CATEGORIES) for cl in legend[cat]}
    # For drawing, values reach two cells out to sea, so the finer coastline clips them cleanly
    near = codes < 0
    dist, (ny, nx) = ndimage.distance_transform_edt(near, return_indices=True)
    shown = np.where(near & ~g.land & (dist <= 2), codes[ny, nx], codes)
    for suffix, (ix, iy, on_land) in g.display.items():
        c = shown[np.ix_(iy, ix)]
        rgba = np.zeros(c.shape + (4,), dtype=np.uint8)
        for code, col in palette.items():
            rgba[c == code, :3] = col
        rgba[..., 3] = np.where((c >= 0) & on_land, 255, 0)
        Image.fromarray(rgba[::-1]).save(folder / f"overlay{suffix}.png", optimize=True)
    data = {"variable": var, "issued": issued.isoformat(), "source": "ICPAC", "file": url.rsplit("/", 1)[-1],
            "legend": legend, "lat0": float(lats[0]), "dlat": GRID, "nlat": len(lats),
            "lon0": float(lons[0]), "dlon": GRID, "nlon": len(lons),
            "codes": codes.astype(int).ravel().tolist(), **_areas(g.lyr, codes, lons, lats)}
    (folder / "data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return True


def _tag(var: str, issued: dt.date, a: str, b: str) -> str:
    """Folder name; the version is part of it, since the app keeps an outlook's files once downloaded."""
    return f"{var}_{a}-{b}_{issued:%Y-%m}_v{VERSION}"


def _entry(var: str, issued: dt.date, a: str, b: str) -> dict:
    tag = _tag(var, issued, a, b)
    return {"folder": tag, "issued": issued.isoformat(), "season_start": a, "season_end": b,
            "overlay": f"{tag}/overlay.png", "overlay_hd": f"{tag}/overlay_hd.png", "data": f"{tag}/data.json",
            "v": VERSION}


def update(lyr, site: Path, today: dt.date | None = None):
    st = site / "seasonal"
    latest_path = st / "latest.json"
    old = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    built = {e["folder"] for e in [s.get(v) for s in old.get("seasons", []) for v in VARIABLES]
             if e and e.get("v") == VERSION and (st / e["folder"] / "data.json").exists()}
    try:
        legends = _legends()
    except Exception as e:
        legends = dict(old.get("legends") or {})
        print(f"  seasonal outlook: ICPAC legend not read ({e}); using the last one")
    if "rain" not in legends:
        legends["rain"] = {c: [{"colour": col, "min": lo, "max": (_LOWS + [100])[i + 1]}
                               for i, (col, lo) in enumerate(zip(cols, _LOWS))] for c, cols in _FALLBACK.items()}
    legends.setdefault("temp", legends["rain"])
    issues = {}
    for var in VARIABLES:
        try:
            issues[var] = _issues(var, today or dt.date.today())
        except Exception as e:
            print(f"  seasonal outlook: ICPAC file list not read for {var} ({e})")
    if not issues:
        print("  seasonal outlook: ICPAC not reached; the published outlooks are kept")
        return
    grids, made = None, []
    seasons: dict[tuple[int, str], dict] = {}
    for var, picks in _wanted(issues).items():
        for (year, key), (issued, a, b, url) in picks.items():
            tag = _tag(var, issued, a, b)
            if tag not in built:
                grids = grids or _Grids(lyr)
                try:
                    if not _build(grids, var, legends[var], issued, url, st / tag):
                        continue
                except Exception as e:
                    print(f"  seasonal outlook: {tag} not built ({e})")
                    continue
                built.add(tag)
                made.append(tag)
            s = seasons.setdefault((year, key), {"id": f"{key}_{year}", "season": key, "year": year})
            s[var] = _entry(var, issued, a, b)
    order = sorted(seasons, key=lambda k: (k[0], SEASON_ORDER.index(k[1])), reverse=True)
    latest = {"version": VERSION, "seasons": [seasons[k] for k in order], "legends": legends}
    # App 1.9.0 shows only "rain" and "temp": the newest of each
    for var in VARIABLES:
        newest = next((seasons[k][var] for k in order if var in seasons[k]), None)
        if newest:
            latest[var] = newest
    x0, x1, y0, y1 = map_extent(lyr)
    latest["bounds"] = {"south": y0, "west": x0, "north": y1, "east": x1}
    latest["credit"] = "ICPAC (IGAD Climate Prediction and Applications Centre)"
    latest["link"] = "https://www.icpac.net/seasonal-forecast/"
    st.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(latest, indent=1), encoding="utf-8")
    names = ", ".join(f"{s['id']} ({'+'.join(v for v in VARIABLES if v in s)})" for s in latest["seasons"])
    print(f"  seasonal outlook: {names}" + (f"; built {len(made)}" if made else ""))


def restore(base: str, site: Path, get):
    """Copy the published seasonal outlooks back (publish --restore-from), so they survive each deploy."""
    try:
        if not get(base + "seasonal/latest.json", site / "seasonal" / "latest.json"):
            return
        latest = json.loads((site / "seasonal" / "latest.json").read_text(encoding="utf-8"))
        entries = [latest.get(v) for v in VARIABLES] + [s.get(v) for s in latest.get("seasons", []) for v in VARIABLES]
        for folder in {e["folder"]: e for e in entries if e}.values():
            for key in ("overlay", "overlay_hd", "data"):
                get(base + "seasonal/" + folder[key], site / "seasonal" / folder[key])
    except Exception as e:
        print(f"  restore: seasonal outlook not restored ({e})")

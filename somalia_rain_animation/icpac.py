"""Seasonal outlooks from ICPAC (IGAD Climate Prediction and Applications Centre) for the app's Seasonal tab.

Source: ICPAC East Africa Hazards Watch (https://eahazardswatch.icpac.net), datasets "Seasonal Rainfall
Probabilistic Forecast" and "Seasonal Temperature Probabilistic Forecast" (about 10 km, a new forecast
most months). Each forecast gives, per place, the probability of the season being below normal, normal or
above normal; the map server draws each category only where it dominates, in shades by probability.
The map server does not give values, so the dominant category and its probability class are read back
from the colours with the dataset's legend (legendConfig). The app credits ICPAC and links to its site.

The map server keeps earlier forecasts (time=YYYY-Mon, the month of issue). Which months each one covers
is read from the names of ICPAC's data files (PredictedProbabilityRain_Mar-May_Feb2026.nc). Each Somali
season (Jilaal, Gu, Xagaa, Deyr) of the last two years gets one outlook per variable: the last one issued
before the season began.

The overlays are drawn here from the decoded values, not copied from the map server: ICPAC's grid stops
short of the coast in places (and at 51.0 E, short of Cape Guardafui), so land cells near the coast take
the nearest value, and the colours are clipped to the app's own coastline. Areas ICPAC leaves out
inland (usually dry in that season) stay empty.

Checked on every publish run; an outlook is built once and kept (restored from the live site).
Output in site/seasonal/:
  latest.json                      the seasons (newest first) with both variables, the overlay bounds,
                                   and "rain" / "temp" for ICPAC's latest forecast (app 1.9.0)
  <var>_<YYYY-MM>_v2/overlay.png     transparent overlay in Web Mercator rows over the app's map extent
  <var>_<YYYY-MM>_v2/overlay_hd.png  the same at high detail
  <var>_<YYYY-MM>_v2/data.json     legend, dominant category and probability per region and district,
                                   and a 0.05 degree grid for tap lookups (category * 100 + lower bound)
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import re
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

from . import config
from .layers import map_extent

API = "https://eahazardswatch.icpac.net/api/datasets/"
WMS = "https://eahazardswatch.icpac.net/mapserver/"
FTP = "https://eahazardswatch.icpac.net/ftp/"
VARIABLES = {
    "rain": ("Seasonal Rainfall Probabilistic Forecast", "seasonal_precipitation_prob", "seasonal_prob_prec", "Rain"),
    "temp": ("Seasonal Temperature Probabilistic Forecast", "seasonal_temperature_prob", "seasonal_prob_temp", "Temp"),
}
CATEGORIES = [("below", "Below Normal"), ("normal", "Normal"), ("above", "Above Normal")]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Somali seasons by calendar month; a forecast belongs to the season most of its months fall in
SEASONS = {"jilaal": (1, 2, 3), "gu": (4, 5, 6), "xagaa": (7, 8, 9), "deyr": (10, 11, 12)}
SEASONS_KEPT = 8        # the last two years
GRID = 0.05             # tap and area grid (degrees)
FILL_CELLS = 10         # coastal gaps filled up to 0.5 degree from ICPAC's data
VERSION = 2             # outlooks built before this (map server images as they were) are rebuilt


def _info() -> dict:
    """Latest forecast and legend for each variable from the Hazards Watch dataset list."""
    items = requests.get(API, timeout=60).json()
    items = items if isinstance(items, list) else next(v for v in items.values() if isinstance(v, list))
    out = {}
    for var, (name, layer, _, _) in VARIABLES.items():
        d = next(i for i in items if i.get("name") == name)
        legend = {}
        for cat, title in CATEGORIES:
            lay = next(l for l in d["layers"] if l["name"] == title)
            names = [it["name"] for it in lay["legendConfig"]["items"]]
            colours = [it["color"] for it in lay["legendConfig"]["items"]]
            # A swatch labelled N is the class just below N; the last ("%") is the top class.
            # Checked against ICPAC's published map: southern Somalia at 90 % above normal is the "%" colour.
            lows = [33] + [int(n) for n in names[:-1]]
            legend[cat] = [{"colour": c, "min": lo, "max": (int(names[i]) if i < len(names) - 1 else 100)}
                           for i, (c, lo) in enumerate(zip(colours, lows))]
        issued = dt.date.fromisoformat(d["latest_date"][:10])
        m = re.search(r"Latest:\s*([A-Za-z]{3})\s*-\s*([A-Za-z]{3})", d.get("summary", ""))
        out[var] = {"layer": layer, "issued": issued, "season": (m.group(1), m.group(2)) if m else None,
                    "legend": legend, "dataset_title": name}
    return out


def _issues(var: str, today: dt.date) -> dict[dt.date, tuple[str, str]]:
    """Month of issue -> (first, last month) for this year's and last year's forecasts, from the names of
    ICPAC's data files. Where one month has two files, the one uploaded last is the forecast shown."""
    _, _, folder, word = VARIABLES[var]
    found: dict[dt.date, tuple[tuple, tuple[str, str]]] = {}
    pat = re.compile(rf'href="PredictedProbability{word}_([A-Z][a-z]{{2}})-([A-Z][a-z]{{2}})_([A-Z][a-z]{{2}})(\d{{4}})\.nc"'
                     r'>[^<]*</a>\s+(\d{2})-([A-Z][a-z]{2})-(\d{4}) (\d{2}):(\d{2})')
    for year in (today.year - 1, today.year):
        r = requests.get(f"{FTP}{folder}/netcdf/{year}/", timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for a, b, im, iy, dd, mm, yy, hh, mi in pat.findall(r.text):
            if a not in MONTHS or b not in MONTHS or im not in MONTHS:
                continue
            issued = dt.date(int(iy), MONTHS.index(im) + 1, 1)
            uploaded = (int(yy), MONTHS.index(mm), int(dd), int(hh), int(mi))
            if issued not in found or uploaded > found[issued][0]:
                found[issued] = (uploaded, (a, b))
    return {k: v[1] for k, v in found.items()}


def _season_of(issued: dt.date, start: str, end: str) -> tuple[str, int, dt.date]:
    """(season, year, first day of the season) that most of the forecast months fall in."""
    a, b = MONTHS.index(start) + 1, MONTHS.index(end) + 1
    months = [(a - 1 + k) % 12 + 1 for k in range((b - a) % 12 + 1)]
    # Forecast months follow the month of issue: those before it in the calendar are next year
    year_of = {m: issued.year + (1 if m < issued.month else 0) for m in months}
    key = max(SEASONS, key=lambda s: sum(m in SEASONS[s] for m in months))
    first = next(m for m in months if m in SEASONS[key])
    year = year_of[first]
    return key, year, dt.date(year, SEASONS[key][0], 1)


def _wanted(info: dict, today: dt.date) -> list[dict]:
    """Seasons newest first, each with the outlook per variable to show: {"id", "season", "year", var: (issued, start, end)}."""
    seasons: dict[tuple[int, int], dict] = {}
    for var, inf in info.items():
        try:
            issues = _issues(var, today)
        except Exception as e:   # the file list is only for the labels of earlier forecasts
            print(f"  seasonal outlook: ICPAC file list not read for {var} ({e}); latest forecast only")
            issues = {}
        if inf["season"]:
            issues[inf["issued"]] = inf["season"]
        by_season: dict[tuple, list] = {}
        for issued, (a, b) in issues.items():
            key, year, begins = _season_of(issued, a, b)
            by_season.setdefault((year, list(SEASONS).index(key), key, begins), []).append((issued, a, b))
        for (year, order, key, begins), cands in by_season.items():
            before = sorted(c for c in cands if c[0] < begins)
            pick = before[-1] if before else min(cands)   # the last outlook before the season began
            s = seasons.setdefault((year, order), {"id": f"{key}_{year}", "season": key, "year": year})
            s[var] = pick
    newest = sorted(seasons, reverse=True)
    return [seasons[k] for k in newest[:SEASONS_KEPT]]


def _merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0


def _getmap(layer: str, issued: dt.date, bbox, size, srs: str) -> np.ndarray:
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "TRANSPARENT": "True",
              "LAYERS": layer, "STYLES": "", "BBOX": ",".join(f"{v:.6f}" for v in bbox),
              "WIDTH": size[0], "HEIGHT": size[1], "FORMAT": "image/png", "SRS": srs,
              "REGION_STATE": "IGAD", "MASK_NAME": "ADMIN", "time": f"{issued.year}-{MONTHS[issued.month - 1]}"}
    r = requests.get(WMS, params=params, timeout=120)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"ICPAC map server: {r.text[:200]}")
    return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))


def _merged(layer: str, issued: dt.date, bbox, size, srs) -> np.ndarray:
    """The three category layers in one image (each is drawn only where its category dominates)."""
    img = None
    for cat, _ in CATEGORIES:
        a = _getmap(f"{layer}_{cat}", issued, bbox, size, srs)
        img = a if img is None else np.where(a[..., 3:4] > img[..., 3:4], a, img)
    return img


def _decode(img: np.ndarray, legend: dict) -> np.ndarray:
    """Category * 100 + lower probability bound per pixel (1 below, 2 normal, 3 above); -1 where empty."""
    swatches = [(ci + 1, cl["min"], [int(cl["colour"][k:k + 2], 16) for k in (1, 3, 5)])
                for ci, (cat, _) in enumerate(CATEGORIES) for cl in legend[cat]]
    rgb = img[..., :3].astype(int)
    best = np.full(rgb.shape[:2], -1)
    dist = np.full(rgb.shape[:2], 1e9)
    for code, lo, col in swatches:
        d = ((rgb - np.array(col)) ** 2).sum(axis=2)
        better = d < dist
        best = np.where(better, code * 100 + lo, best)
        dist = np.where(better, d, dist)
    return np.where((img[..., 3] > 0) & (dist < 40 ** 2), best, -1)


def _fill(codes: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Land cells ICPAC left empty near the coast (or in small holes) take the nearest value; the sea is
    cleared. Larger inland gaps, where ICPAC gives no outlook for the season, stay empty."""
    valid = codes >= 0
    if not valid.any():
        return np.where(land, codes, -1)
    dist, (iy, ix) = ndimage.distance_transform_edt(~valid, return_indices=True)
    from_sea = ndimage.distance_transform_edt(land)
    fill = land & ~valid & (dist <= FILL_CELLS) & ((from_sea <= FILL_CELLS) | (dist <= 2))
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
        self.extent = (x0, x1, y0, y1)
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


def _build(g: _Grids, var: str, info: dict, issued: dt.date, folder: Path) -> bool:
    """One outlook; False when ICPAC has nothing over the map for that month."""
    x0, x1, y0, y1 = g.extent
    lons, lats = g.lons, g.lats
    img = _merged(info["layer"], issued, (x0 - GRID / 2, y0 - GRID / 2, lons[-1] + GRID / 2, lats[-1] + GRID / 2),
                  (len(lons), len(lats)), "EPSG:4326")
    codes = _fill(_decode(img, info["legend"])[::-1], g.land)   # image row 0 is north
    if not (codes >= 0).any():
        return False
    folder.mkdir(parents=True, exist_ok=True)
    # Colours per code from the legend
    palette = {(ci + 1) * 100 + cl["min"]: [int(cl["colour"][k:k + 2], 16) for k in (1, 3, 5)]
               for ci, (cat, _) in enumerate(CATEGORIES) for cl in info["legend"][cat]}
    # For drawing, values reach two cells past the coast, so the finer coastline clips them cleanly
    near = codes < 0
    dist, (ny, nx) = ndimage.distance_transform_edt(near, return_indices=True)
    shown = np.where(near & (dist <= 2), codes[ny, nx], codes)
    for suffix, (ix, iy, on_land) in g.display.items():
        c = shown[np.ix_(iy, ix)]
        rgba = np.zeros(c.shape + (4,), dtype=np.uint8)
        for code, col in palette.items():
            rgba[c == code, :3] = col
        rgba[..., 3] = np.where((c >= 0) & on_land, 255, 0)
        Image.fromarray(rgba[::-1]).save(folder / f"overlay{suffix}.png", optimize=True)
    data = {"variable": var, "issued": issued.isoformat(), "source": "ICPAC",
            "dataset": info["dataset_title"], "legend": info["legend"],
            "lat0": float(lats[0]), "dlat": GRID, "nlat": len(lats),
            "lon0": float(lons[0]), "dlon": GRID, "nlon": len(lons),
            "codes": codes.astype(int).ravel().tolist(), **_areas(g.lyr, codes, lons, lats)}
    (folder / "data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return True


def _tag(var: str, issued: dt.date) -> str:
    """Folder name; the version is part of it, since the app keeps an outlook's files once downloaded."""
    return f"{var}_{issued:%Y-%m}_v{VERSION}"


def _entry(var: str, issued: dt.date, start: str | None, end: str | None) -> dict:
    tag = _tag(var, issued)
    return {"folder": tag, "issued": issued.isoformat(), "season_start": start, "season_end": end,
            "overlay": f"{tag}/overlay.png", "overlay_hd": f"{tag}/overlay_hd.png", "data": f"{tag}/data.json",
            "v": VERSION}


def update(lyr, site: Path, today: dt.date | None = None):
    st = site / "seasonal"
    latest_path = st / "latest.json"
    old = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    built = {e["folder"] for e in [old.get("rain"), old.get("temp"),
                                   *[s.get(v) for s in old.get("seasons", []) for v in VARIABLES]]
             if e and e.get("v") == VERSION and (st / e["folder"] / "data.json").exists()}
    info = _info()
    wanted = _wanted(info, today or dt.date.today())
    grids = None
    made, empty = [], set()

    def ensure(var, issued) -> bool:
        nonlocal grids
        tag = _tag(var, issued)
        if tag in built:
            return True
        if tag in empty:
            return False
        grids = grids or _Grids(lyr)
        try:
            ok = _build(grids, var, info[var], issued, st / tag)
        except Exception as e:
            print(f"  seasonal outlook: {tag} not built ({e})")
            ok = False
        (built.add if ok else empty.add)(tag)
        if ok:
            made.append(tag)
        return ok

    seasons = []
    for s in wanted:
        e = {"id": s["id"], "season": s["season"], "year": s["year"]}
        for var in VARIABLES:
            if var in s and ensure(var, s[var][0]):
                e[var] = _entry(var, *s[var])
        if any(v in e for v in VARIABLES):
            seasons.append(e)
    latest = {"version": VERSION, "seasons": seasons}
    for var, inf in info.items():
        s = inf["season"]
        if ensure(var, inf["issued"]):
            latest[var] = _entry(var, inf["issued"], *(s or (None, None)))
    x0, x1, y0, y1 = map_extent(lyr)
    latest["bounds"] = {"south": y0, "west": x0, "north": y1, "east": x1}
    latest["credit"] = "ICPAC (IGAD Climate Prediction and Applications Centre)"
    latest["link"] = "https://www.icpac.net/seasonal-forecast/"
    st.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(latest, indent=1), encoding="utf-8")
    names = ", ".join(f"{s['id']} ({'+'.join(v for v in VARIABLES if v in s)})" for s in seasons)
    print(f"  seasonal outlook: {len(seasons)} seasons: {names}" + (f"; built {len(made)}" if made else ""))


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

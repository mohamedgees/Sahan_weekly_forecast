"""Seasonal outlook from ICPAC (IGAD Climate Prediction and Applications Centre) for the app's Seasonal tab.

Source: ICPAC East Africa Hazards Watch (https://eahazardswatch.icpac.net), datasets "Seasonal Rainfall
Probabilistic Forecast" and "Seasonal Temperature Probabilistic Forecast" (about 10 km, a new forecast
each month). Each forecast gives, per place, the probability of the season being below normal, normal or
above normal; the map server draws each category only where it dominates, in shades by probability.
The map server does not give values, so the dominant category and its probability class are read back
from the colours with the dataset's legend (legendConfig). The app credits ICPAC and links to its site.

Checked on every publish run (one API call); maps are downloaded only when ICPAC has a new month.
Output in site/seasonal/:
  latest.json                      both variables: season, issue month, folder, overlay bounds
  <var>_<YYYY-MM>/overlay.png      transparent overlay in Web Mercator rows over the app's map extent
  <var>_<YYYY-MM>/overlay_hd.png   the same at high detail
  <var>_<YYYY-MM>/data.json        legend, dominant category and probability per region and district,
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

from . import config
from .layers import map_extent

API = "https://eahazardswatch.icpac.net/api/datasets/"
WMS = "https://eahazardswatch.icpac.net/mapserver/"
VARIABLES = {
    "rain": ("Seasonal Rainfall Probabilistic Forecast", "seasonal_precipitation_prob"),
    "temp": ("Seasonal Temperature Probabilistic Forecast", "seasonal_temperature_prob"),
}
CATEGORIES = [("below", "Below Normal"), ("normal", "Normal"), ("above", "Above Normal")]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GRID = 0.05   # tap and area grid (degrees)


def _info() -> dict:
    """Latest forecast and legend for each variable from the Hazards Watch dataset list."""
    items = requests.get(API, timeout=60).json()
    items = items if isinstance(items, list) else next(v for v in items.values() if isinstance(v, list))
    out = {}
    for var, (name, layer) in VARIABLES.items():
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


def _merged(info: dict, bbox, size, srs) -> np.ndarray:
    """The three category layers in one image (each is drawn only where its category dominates)."""
    img = None
    for cat, _ in CATEGORIES:
        a = _getmap(f"{info['layer']}_{cat}", info["issued"], bbox, size, srs)
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


def _build(lyr, var: str, info: dict, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    x0, x1, y0, y1 = map_extent(lyr)
    # Overlays in Web Mercator rows, the same frame as the forecast overlays
    for suffix, step in (("", config.GRID_STEP), ("_hd", config.HD_GRID_STEP)):
        w = int(round((x1 - x0) / step)) + 1
        h = int(round((y1 - y0) / step)) + 1
        bbox = (x0 * math.pi / 180 * 6378137.0, _merc_y(y0), x1 * math.pi / 180 * 6378137.0, _merc_y(y1))
        Image.fromarray(_merged(info, bbox, (w, h), "EPSG:3857")).save(folder / f"overlay{suffix}.png", optimize=True)
    # Values on a plain lat/lon grid (rows from the south)
    lons = np.round(np.arange(x0, x1 + GRID / 2, GRID), 4)
    lats = np.round(np.arange(y0, y1 + GRID / 2, GRID), 4)
    img = _merged(info, (x0 - GRID / 2, y0 - GRID / 2, lons[-1] + GRID / 2, lats[-1] + GRID / 2),
                  (len(lons), len(lats)), "EPSG:4326")
    codes = _decode(img, info["legend"])[::-1]   # image row 0 is north
    data = {"variable": var, "issued": info["issued"].isoformat(), "source": "ICPAC",
            "dataset": info["dataset_title"], "legend": info["legend"],
            "lat0": float(lats[0]), "dlat": GRID, "nlat": len(lats),
            "lon0": float(lons[0]), "dlon": GRID, "nlon": len(lons),
            "codes": codes.astype(int).ravel().tolist(), **_areas(lyr, codes, lons, lats)}
    (folder / "data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def update(lyr, site: Path):
    st = site / "seasonal"
    latest_path = st / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    info = _info()
    x0, x1, y0, y1 = map_extent(lyr)
    changed = False
    for var, inf in info.items():
        tag = f"{var}_{inf['issued']:%Y-%m}"
        if latest.get(var, {}).get("folder") == tag and (st / tag / "data.json").exists():
            continue
        _build(lyr, var, inf, st / tag)
        s = inf["season"]
        latest[var] = {"folder": tag, "issued": inf["issued"].isoformat(),
                       "season_start": s[0] if s else None, "season_end": s[1] if s else None,
                       "overlay": f"{tag}/overlay.png", "overlay_hd": f"{tag}/overlay_hd.png", "data": f"{tag}/data.json"}
        changed = True
        print(f"  seasonal outlook: {var} issued {inf['issued']:%B %Y}" + (f", {s[0]} to {s[1]}" if s else ""))
    if changed:
        latest["bounds"] = {"south": y0, "west": x0, "north": y1, "east": x1}
        latest["credit"] = "ICPAC (IGAD Climate Prediction and Applications Centre)"
        latest["link"] = "https://www.icpac.net/seasonal-forecast/"
        st.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(json.dumps(latest, indent=1), encoding="utf-8")
    else:
        print("  seasonal outlook: no new ICPAC forecast")


def restore(base: str, site: Path, get):
    """Copy the published seasonal outlook back (publish --restore-from), so it survives each deploy."""
    try:
        if not get(base + "seasonal/latest.json", site / "seasonal" / "latest.json"):
            return
        latest = json.loads((site / "seasonal" / "latest.json").read_text(encoding="utf-8"))
        for var in VARIABLES:
            if var in latest:
                for key in ("overlay", "overlay_hd", "data"):
                    get(base + "seasonal/" + latest[var][key], site / "seasonal" / latest[var][key])
    except Exception as e:
        print(f"  restore: seasonal outlook not restored ({e})")

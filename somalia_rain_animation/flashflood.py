"""Flash flood risk for the app's Flood watch tab.

Flash floods come when heavy, short rain falls on steep or bare ground or already wet soil and gathers in
wadis (toggas) within hours. The risk is worked out per small sub-basin (HydroBASINS level 12, about
135 km²) and forecast day from:
  susceptibility (static, built once): slope from the HydroSHEDS 15 arc-second DEM, and the upstream area
                 of the sub-basin (wadis that collect water from a large area); the main Juba and Shabelle
                 channels are left out, their floods are river floods
  rain           GFS daily rain and the wettest 3 hours (weather.py), at the sub-basin
  wet soil       GFS 0–10 cm soil moisture at the start of the day lowers the threshold
  confidence     GEFS: share of the 31 runs with 30 mm and 50 mm or more that day
Levels: 1 Watch (rain at or above the threshold), 2 High (1.5 × threshold, or 3 hour rain of
FLASH_3H_MM or more, and at least FLASH_HIGH_MIN_CHANCE % of the GEFS runs give 30 mm). Thresholds are in
config.py (FLASH_*), to be tuned against reported events.

    python -m somalia_rain_animation.flashflood --build [--hydro DIR]   # once: data/flash_basins.geojson
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from . import config

BASINS = config.PROJECT_DIR / "data" / "flash_basins.geojson"


# ---------- static layer (once) ----------
def build(hydro_dir: Path):
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize
    from .layers import load_all

    lyr = load_all(report=False)
    somalia = lyr["admin0"].geometry.union_all().buffer(0.05)
    x0, y0, x1, y1 = somalia.bounds
    b = gpd.read_file(hydro_dir / "hybas_af_lev12_v1c.shp", bbox=(x0, y0, x1, y1))
    b = b[b.intersects(somalia)].copy()
    print(f"  sub-basins in Somalia: {len(b)}")

    # Mean slope per sub-basin from the DEM (degrees, with the east-west spacing shrinking with latitude)
    with rasterio.open(next(hydro_dir.glob("**/hyd_af_dem_15s*.tif"))) as src:
        win = src.window(x0, y0, x1, y1)
        dem = src.read(1, window=win).astype("float64")
        tr = src.window_transform(win)
    dem[dem < -100] = np.nan
    lat = tr.f + tr.e * (np.arange(dem.shape[0]) + 0.5)
    dy = abs(tr.e) * 110574.0
    dx = tr.a * 111320.0 * np.cos(np.radians(lat))[:, None]
    gy, gx = np.gradient(dem)
    slope = np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))
    # Mean slope per sub-basin: burn row numbers into the DEM grid, then average by number
    zones = rasterize(((g, i + 1) for i, g in enumerate(b.geometry)), out_shape=dem.shape, transform=tr,
                      fill=0, dtype="int32")
    ok = (zones > 0) & np.isfinite(slope)
    sums = np.bincount(zones[ok], weights=slope[ok], minlength=len(b) + 1)
    cnts = np.bincount(zones[ok], minlength=len(b) + 1)
    b["slope"] = np.round(np.where(cnts[1:] > 0, sums[1:] / np.maximum(cnts[1:], 1), 0.0), 2)

    # Susceptibility: slope class, plus one for wadis collecting water from a large area;
    # sub-basins on the main Juba and Shabelle (huge upstream area) are left out.
    s = np.select([b["slope"] >= config.FLASH_SLOPE_STEEP, b["slope"] >= config.FLASH_SLOPE_MID], [3, 2], 1)
    s = s + ((b["UP_AREA"] >= config.FLASH_WADI_KM2) & (b["UP_AREA"] < config.FLASH_RIVER_KM2)).astype(int)
    b["sus"] = np.clip(s, 1, 3)
    b = b[b["UP_AREA"] < config.FLASH_RIVER_KM2]
    pts = b.geometry.representative_point()
    out = gpd.GeoDataFrame({"id": b["HYBAS_ID"].astype("int64"), "sus": b["sus"].astype(int),
                            "slope": b["slope"], "up": b["UP_AREA"].round(0),
                            "lon": pts.x.round(4), "lat": pts.y.round(4)},
                           geometry=b.geometry.simplify(0.004, preserve_topology=True), crs=b.crs)
    BASINS.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(BASINS, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": 4})
    counts = np.bincount(out["sus"], minlength=4)[1:]
    print(f"  wrote {BASINS} ({BASINS.stat().st_size // 1024} kB): susceptibility 1/2/3 = {list(counts)}")


# ---------- daily risk ----------
def _sample(grid: np.ndarray, lat1, lon1, lats, lons) -> np.ndarray:
    f = RegularGridInterpolator((lat1, lon1), np.nan_to_num(grid), method="linear", bounds_error=False, fill_value=0)
    return f(np.column_stack([lats, lons]))


def compute(rd, wx_days: list[dict], chance_grids: dict | None, places: list, lyr) -> dict | None:
    """flash.json content for a run: per day the sub-basins at Watch or High, per district the highest
    level, and the towns and IDP camps in sub-basins at risk. None without the static layer."""
    if not BASINS.exists():
        print("  flash floods skipped: no data/flash_basins.geojson (run flashflood --build once)")
        return None
    import geopandas as gpd
    b = gpd.read_file(BASINS)
    lats, lons = b["lat"].to_numpy(), b["lon"].to_numpy()
    sus = b["sus"].to_numpy()
    base = np.choose(sus - 1, config.FLASH_THRESHOLD_MM)   # mm per day by susceptibility 1, 2, 3
    # District of each sub-basin (for the lists and the tap card)
    a2 = lyr["admin2"][lyr["admin2"]["adm2_name"] != "Unspecified"][["adm2_name", "adm1_name", "geometry"]]
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lons, lats), crs="EPSG:4326")
    j = gpd.sjoin(pts, a2, predicate="within", how="left")
    j = j[~j.index.duplicated()]
    dist = list(zip(j["adm2_name"].fillna(""), j["adm1_name"].fillna("")))

    days, district_levels = [], {}
    place_pts = np.array([[p[1], p[0]] for p in places]) if places else np.zeros((0, 2))
    exposed = {}
    for k, (rain, wx) in enumerate(zip(rd.days, wx_days)):
        r24 = _sample(rain, rd.lat1, rd.lon1, lats, lons)
        r3 = _sample(wx["rain3h"], rd.lat1, rd.lon1, lats, lons) if "rain3h" in wx else np.zeros_like(r24)
        wet = _sample(wx["soil"], rd.lat1, rd.lon1, lats, lons) >= config.FLASH_WET_SOIL if "soil" in wx else False
        thr = np.where(wet, base - config.FLASH_WET_BONUS_MM, base)
        level = np.where((r24 >= 1.5 * thr) | (r3 >= config.FLASH_3H_MM), 2, np.where(r24 >= thr, 1, 0))
        c50 = (_sample(np.asarray(chance_grids[f"vheavy_day{k + 1}"]), rd.lat1, rd.lon1, lats, lons)
               if chance_grids and f"vheavy_day{k + 1}" in chance_grids else None)
        # High only when the ensemble agrees: enough of the 31 runs give 30 mm or more that day
        if chance_grids and f"heavy_day{k + 1}" in chance_grids:
            c30 = _sample(np.asarray(chance_grids[f"heavy_day{k + 1}"]), rd.lat1, rd.lon1, lats, lons)
            level = np.where((level == 2) & (c30 < config.FLASH_HIGH_MIN_CHANCE), 1, level)
        flagged = np.flatnonzero(level > 0)
        days.append({str(int(b["id"].iat[i])): [int(level[i]), round(float(r24[i])),
                                                  None if c50 is None else int(round(c50[i]))] for i in flagged})
        for i in flagged:
            key = dist[i]
            if key[0]:
                lv = district_levels.setdefault(key, [0] * len(rd.days))
                lv[k] = max(lv[k], int(level[i]))
        # Towns and IDP camps in sub-basins at risk (villages are too many to list), with the level
        risk = b.iloc[flagged].assign(level=level[flagged])
        if len(risk) and len(place_pts):
            sel = [p for p in places if p[3] <= 2 or (len(p) > 5 and p[5] == 1)]
            sp = gpd.GeoDataFrame(geometry=gpd.points_from_xy([p[0] for p in sel], [p[1] for p in sel]), crs="EPSG:4326")
            hit = gpd.sjoin(sp, risk[["level", "geometry"]], predicate="within")
            for i, lv in hit.groupby(level=0)["level"].max().items():
                p = sel[i]
                e = exposed.setdefault(p[2] + "|" + (p[4] if len(p) > 4 else ""), {
                    "name": p[2], "district": p[4] if len(p) > 4 else "", "idp": bool(len(p) > 5 and p[5] == 1),
                    "lon": p[0], "lat": p[1], "days": [], "level": 0})
                e["days"].append(k)
                e["level"] = max(e["level"], int(lv))
    districts = [{"name": d, "region": r, "levels": lv} for (d, r), lv in district_levels.items()]
    districts.sort(key=lambda x: (-max(x["levels"]), -sum(x["levels"]), x["name"]))
    # The cap is per day, so a busy day (many IDP camps around one town) does not push out the other days
    ranked = sorted(exposed.values(), key=lambda e: (-e["level"], not e["idp"], e["name"]))
    keep = set()
    for k in range(len(rd.days)):
        keep.update(id(e) for e in [e for e in ranked if k in e["days"]][:config.FLASH_PLACES_MAX])
    places_out = sorted((e for e in ranked if id(e) in keep),
                        key=lambda e: (-e["level"], not e["idp"], e["days"][0], e["name"]))
    n_high = sum(1 for d in days for v in d.values() if v[0] == 2)
    print(f"  flash floods: {sum(len(d) for d in days)} sub-basin days flagged ({n_high} High), "
          f"{len(districts)} districts, {len(places_out)} towns and IDP camps")
    return {"days": days, "districts": districts, "places": places_out,
            "levels": ["Watch", "High"], "basins": "static/flash_basins.geojson"}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m somalia_rain_animation.flashflood")
    p.add_argument("--build", action="store_true", help="Build data/flash_basins.geojson (once)")
    p.add_argument("--hydro", type=Path, default=config.HYDRO_DIR, help="Folder with HydroSHEDS files")
    a = p.parse_args(argv)
    if a.build:
        build(a.hydro)


if __name__ == "__main__":
    main()

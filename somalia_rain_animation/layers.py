"""Load the vector layers and report on them."""
from __future__ import annotations

import geopandas as gpd
import numpy as np

from . import config


def load_layer(name, required=True, report=False):
    path = config.DATA_DIR / name
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required layer not found: {path}")
        return None
    gdf = gpd.read_file(path)
    if report:
        cols = [c for c in gdf.columns if c != "geometry"]
        print(f"  {name}: CRS {gdf.crs}, {len(gdf)} features, columns {cols}")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def load_all(report=True):
    print("Input layers:")
    lyr = {
        "admin0": load_layer(config.ADMIN0, report=report),
        "admin1": load_layer(config.ADMIN1, report=report),
        "admin2": load_layer(config.ADMIN2, report=report),
        "neighbours": load_layer(config.NEIGHBOURS, report=report),
        "rivers": load_layer(config.RIVERS, required=False, report=report),
        "catchments": load_layer(config.CATCHMENTS, required=False, report=report),
        "capitals": load_layer(config.CAPITALS, required=False, report=report),
    }
    cap = lyr["capitals"]
    if cap is not None:
        for wrong, (right, x, y) in config.CAPITAL_FIXES.items():
            hit = cap[config.CAPITAL_NAME_COL] == wrong
            if hit.any():
                cap.loc[hit, config.CAPITAL_NAME_COL] = right
                cap.loc[hit, "geometry"] = gpd.points_from_xy([x] * hit.sum(), [y] * hit.sum())
                print(f"  Capitals: replaced {wrong} with {right} ({y}N {x}E)")
    missing = [k for k in ("rivers", "catchments") if lyr[k] is None]
    if missing:
        print(f"  Note: {' and '.join(missing)} not found. Build them with "
              "'python -m somalia_rain_animation.hydro' (see README). Continuing without.")
    return lyr


def map_extent(lyr):
    """Bounds of Somalia, catchments and rivers plus a margin, limited to the GFS subregion."""
    b = [lyr[k].total_bounds for k in ("admin0", "catchments", "rivers") if lyr.get(k) is not None]
    b = np.array(b)
    m = config.EXTENT_MARGIN
    x0, y0 = b[:, 0].min() - m, b[:, 1].min() - m
    x1, y1 = b[:, 2].max() + m, b[:, 3].max() + m
    s = config.SUBREGION
    return (round(max(x0, s["leftlon"] + 0.5), 2), round(min(x1, s["rightlon"] - 0.5), 2),
            round(max(y0, s["bottomlat"] + 0.5), 2), round(min(y1, s["toplat"] - 0.5), 2))

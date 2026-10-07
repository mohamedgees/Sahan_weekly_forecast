"""Data products for the app and web dashboard.

Per run, in site/runs/<run_id>/:
  day1.png .. day7.png, total.png   transparent rain overlays in Web Mercator rows
  values.json                       native 0.25 degree grid (mm x 10) for tap lookups
  summary.json                      region and basin statistics
  meta.json                         dates, titles, overlay bounds, file list
Once per site, in site/static/:
  admin0, admin1, neighbours, capitals, rivers, basins (.geojson) and style.json
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import shapely
from matplotlib.colors import to_rgb
from PIL import Image

from . import config, gfs, labels
from .layers import map_extent
from .pipeline import RunData


# ---------- masks and grids ----------
def land_geometry(lyr):
    """All land in view; the small close (grow then shrink) seals slivers between country polygons,
    as in render.FrameRenderer."""
    somalia = lyr["admin0"].geometry.union_all().buffer(0)
    land = lyr["neighbours"].geometry.union_all().union(somalia).buffer(0.02).buffer(-0.02)
    return somalia, land


def mask(geom, lons, lats):
    shapely.prepare(geom)
    xx, yy = np.meshgrid(lons, lats)
    return shapely.contains_xy(geom, xx, yy)


def mercator_lats(lat0, lat1, n):
    """n latitudes, ascending, evenly spaced in Web Mercator y between lat0 and lat1."""
    y = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    ys = np.linspace(y(lat0), y(lat1), n)
    return np.degrees(2 * np.arctan(np.exp(ys)) - math.pi / 2)


def classify_rgba(grid, in_somalia, on_land):
    """Overlay colours: Somalia full colour (0 to 2 white); land outside clear under 2 mm;
    sea at SEA_ALPHA, clear under 2 mm. Same rules as the video frames."""
    rgb = np.array([[round(c * 255) for c in to_rgb(h)] for h in config.CLASS_COLOURS], dtype=np.uint8)
    idx = np.clip(np.digitize(np.nan_to_num(grid, nan=0.0), config.CLASS_BOUNDS[1:]), 0, len(rgb) - 1)
    out = np.zeros(grid.shape + (4,), dtype=np.uint8)
    out[..., :3] = rgb[idx]
    wet = grid >= config.CLASS_BOUNDS[1]
    alpha = np.where(on_land, 255, round(255 * config.SEA_ALPHA))
    out[..., 3] = np.where(in_somalia, 255, np.where(wet, alpha, 0))
    return out


# ---------- statistics ----------
def region_stats(fine_days, lons, lats, lyr):
    """Area weighted daily means, weekly mean, P90, max and % area >= 50 mm per region and basin."""
    xx, yy = np.meshgrid(lons, lats)
    w = np.cos(np.deg2rad(yy))
    week = np.sum(fine_days, axis=0)

    def stats(geom):
        # Only the grid window around the shape: fast enough for the 90 districts
        bx0, by0, bx1, by1 = geom.bounds
        ix = np.flatnonzero((lons >= bx0) & (lons <= bx1))
        iy = np.flatnonzero((lats >= by0) & (lats <= by1))
        if not len(ix) or not len(iy):
            return None
        win = (slice(iy[0], iy[-1] + 1), slice(ix[0], ix[-1] + 1))
        m = mask(geom, lons[win[1]], lats[win[0]])
        if not m.any():
            return None
        ww = w[win][m]
        daily = [float((g[win][m] * ww).sum() / ww.sum()) for g in fine_days]
        wk = week[win][m]
        return {"daily_mean": [round(v, 1) for v in daily],
                "week_mean": round(float((wk * ww).sum() / ww.sum()), 1),
                "week_p90": round(float(np.percentile(wk, 90)), 1),
                "week_max": round(float(wk.max()), 1),
                "pct_area_50mm": round(float((wk >= 50).mean() * 100), 1),
                "pct_area_lt5mm": round(float((wk < 5).mean() * 100), 1),
                # highest point amount on each day (the app's heavy rain days card)
                "daily_max": [round(float(g[win][m].max()), 1) for g in fine_days]}

    regions = []
    for _, r in lyr["admin1"].iterrows():
        s = stats(r.geometry)
        if s:
            regions.append({"name": r[config.ADMIN1_NAME_COL], "pcode": r.get("adm1_pcode", ""), **s})
    # Districts, for the region details in the app's Summary tab
    districts = []
    if lyr.get("admin2") is not None:
        for _, r in lyr["admin2"].iterrows():
            if r["adm2_name"] == "Unspecified":
                continue
            s = stats(r.geometry)
            if s:
                districts.append({"name": r["adm2_name"], "region": r["adm1_name"],
                                  "pcode": r.get("adm2_pcode", ""), **s})
    basins = []
    if lyr.get("catchments") is not None:
        for _, r in lyr["catchments"].iterrows():
            s = stats(r.geometry)
            if s:
                basins.append({"name": r["name"], "part": r["part"], **s})
    som = stats(lyr["admin0"].geometry.union_all())
    return {"somalia": som, "regions": regions, "districts": districts, "basins": basins}


# ---------- per run ----------
def export_run(lyr, rd: RunData, site: Path) -> dict:
    out = site / "runs" / rd.run_id
    out.mkdir(parents=True, exist_ok=True)
    x0, x1, y0, y1 = map_extent(lyr)
    somalia, land = land_geometry(lyr)
    total = np.sum(rd.days, axis=0)
    grids = list(rd.days) + [total]
    names = [f"day{k}" for k in range(1, len(rd.days) + 1)] + ["total"]

    # Overlays: columns at GRID_STEP, rows evenly spaced in Mercator so the image drops straight
    # onto a Web Mercator map between its corner coordinates.
    # Two sets: standard (GRID_STEP) for the country view, high detail (HD_GRID_STEP) that the
    # app loads when zoomed in.
    for suffix, step in (("", config.GRID_STEP), ("_hd", config.HD_GRID_STEP)):
        lons = np.round(np.arange(x0, x1 + step / 2, step), 4)
        mlats = mercator_lats(y0, y1, int(round((y1 - y0) / step)) + 1)
        in_som, on_land = mask(somalia, lons, mlats), mask(land, lons, mlats)
        for name, g in zip(names, grids):
            rgba = classify_rgba(gfs.regrid(g, rd.lat1, rd.lon1, lons, mlats), in_som, on_land)
            Image.fromarray(rgba[::-1]).save(out / f"{name}{suffix}.png", optimize=True)   # row 0 = north

    # Tap values: native grid, mm x 10 as integers, rows from the south
    def pack(g):
        return np.where(np.isnan(g), -1, np.round(g * 10)).astype(int).ravel().tolist()
    values = {"lat0": float(rd.lat1[0]), "dlat": float(rd.lat1[1] - rd.lat1[0]), "nlat": len(rd.lat1),
              "lon0": float(rd.lon1[0]), "dlon": float(rd.lon1[1] - rd.lon1[0]), "nlon": len(rd.lon1),
              "scale": 10, "grids": {n: pack(g) for n, g in zip(names, grids)}}
    (out / "values.json").write_text(json.dumps(values, separators=(",", ":")), encoding="utf-8")

    # Summaries on the regular display grid
    flons, flats = gfs.target_grid((x0, x1, y0, y1))
    fine = [gfs.regrid(g, rd.lat1, rd.lon1, flons, flats) for g in rd.days]
    summary = region_stats(fine, flons, flats, lyr)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    days = []
    for k in range(1, len(rd.days) + 1):
        s, e = labels.day_window(rd.t0, k)
        d = labels.day_date(rd.t0, k)
        days.append({"id": f"day{k}", "n": k, "date": d.isoformat(), "title": labels.fmt_date(d),
                     "valid_start_eat": s.isoformat(timespec="minutes"),
                     "valid_end_eat": e.isoformat(timespec="minutes")})
    meta = {
        "run_id": rd.run_id, "run_date": rd.date.isoformat(), "cycle": rd.cycle, "lead_days": rd.lead,
        "first_day": labels.day_date(rd.t0, 1).isoformat(),
        "last_day": labels.day_date(rd.t0, len(rd.days)).isoformat(),
        "week_range": labels.week_range(rd.t0), "total_title": labels.total_title(rd.t0),
        "source": f"NOAA-NCEP-GFS, {rd.cycle:02d}Z run of {rd.date.day} {rd.date:%B %Y}",
        "bounds": {"south": y0, "west": x0, "north": y1, "east": x1},
        "days": days,
        "overlays": {n: f"{n}.png" for n in names},
        "overlays_hd": {n: f"{n}_hd.png" for n in names},
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"  exported run data: {out}")
    return meta


# ---------- once per site ----------
def _write_geojson(gdf, path, cols):
    gdf = gdf[cols + ["geometry"]].copy()
    gdf["geometry"] = gdf.geometry.simplify(0.003, preserve_topology=True)
    gdf.to_file(path, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": 4})


def export_static(lyr, site: Path):
    from .render import LABEL_OFFSETS   # region label nudges used on the video frames
    st = site / "static"
    st.mkdir(parents=True, exist_ok=True)
    _write_geojson(lyr["admin0"], st / "admin0.geojson", [])

    a1 = lyr["admin1"].copy()
    pts = a1.geometry.representative_point()
    off = [LABEL_OFFSETS.get(n, (0, 0)) for n in a1[config.ADMIN1_NAME_COL]]
    a1["name"] = a1[config.ADMIN1_NAME_COL]
    a1["pcode"] = a1.get("adm1_pcode", "")
    a1["label_lon"] = [round(p.x + o[0], 3) for p, o in zip(pts, off)]
    a1["label_lat"] = [round(p.y + o[1], 3) for p, o in zip(pts, off)]
    _write_geojson(a1, st / "admin1.geojson", ["name", "pcode", "label_lon", "label_lat"])

    # Neighbour name positions as on the video frames: inside the map view, Ethiopia kept near the basins
    x0, x1, y0, y1 = map_extent(lyr)
    inner = shapely.box(x0, y0, x1, y1).buffer(-0.3)
    # Districts: names and label points for the place picker and the tap card
    a2 = lyr["admin2"].copy()
    p2 = a2.geometry.representative_point()
    a2["name"], a2["region"] = a2["adm2_name"], a2["adm1_name"]
    a2["label_lon"] = [round(p.x, 3) for p in p2]
    a2["label_lat"] = [round(p.y, 3) for p in p2]
    _write_geojson(a2, st / "admin2.geojson", ["name", "region", "label_lon", "label_lat"])

    nb = lyr["neighbours"].copy()
    nb["name"] = nb[config.NEIGHBOUR_NAME_COL]
    lon, lat = [], []
    for name, g in zip(nb["name"], nb.geometry):
        g = g.intersection(inner)
        if g.is_empty or g.area < 0.3:
            lon.append(None); lat.append(None); continue
        if name == "Ethiopia":
            g = g.intersection(shapely.box(37, 3.5, 41.5, 11))
        p = g.representative_point()
        lon.append(round(p.x, 3)); lat.append(round(p.y, 3))
    nb["label_lon"], nb["label_lat"] = lon, lat
    _write_geojson(nb, st / "neighbours.geojson", ["name", "label_lon", "label_lat"])

    if lyr.get("capitals") is not None:
        cap = lyr["capitals"].copy()
        cap["name"] = cap[config.CAPITAL_NAME_COL]
        cap["region"] = cap.get("REGION", "")
        cap[["name", "region", "geometry"]].to_file(st / "capitals.geojson", driver="GeoJSON")
    if lyr.get("rivers") is not None:
        _write_geojson(lyr["rivers"], st / "rivers.geojson", ["name", "section"])
    if lyr.get("catchments") is not None:
        bas = lyr["catchments"].copy()
        somalia = lyr["admin0"].geometry.union_all().buffer(0)
        pts = [g.difference(somalia).representative_point() for g in bas.geometry]   # label upstream part
        bas["label_lon"] = [round(p.x, 3) for p in pts]
        bas["label_lat"] = [round(p.y, 3) for p in pts]
        _write_geojson(bas, st / "basins.geojson", ["name", "part", "area_km2", "label_lon", "label_lat"])

    style = {
        "classes": [{"min": lo, "max": hi, "colour": c, "label": lab}
                    for lo, hi, c, lab in zip(config.CLASS_BOUNDS, config.CLASS_BOUNDS[1:] + [None],
                                              config.CLASS_COLOURS, config.CLASS_LABELS)],
        "ocean": config.OCEAN_COLOUR, "sea_alpha": config.SEA_ALPHA,
        "coast_glow": config.COAST_GLOW_COLOUR, "coast_line": config.COAST_LINE_COLOUR,
        "neighbour_fill": config.NEIGHBOUR_FILL, "neighbour_edge": config.NEIGHBOUR_EDGE,
        "neighbour_label": config.NEIGHBOUR_LABEL_COLOUR, "catchment": config.CATCHMENT_COLOUR,
        "catchment_labels": config.CATCHMENT_LABELS, "river": config.RIVER_COLOUR,
        "banner": config.BANNER_COLOURS, "accent": config.ACCENT_COLOUR,
        "date_badge": config.DATE_BADGE_COLOUR, "date_text": config.DATE_TEXT_COLOUR,
        "sea_labels": [{"name": n, "lon": x, "lat": y} for n, (x, y), _ in config.SEA_LABELS],
        "categories": {
            kind: [{"label": n, "min": lo, "max": hi} for n, lo, hi in scheme]
            for kind, scheme in (("daily", config.DAILY_CATEGORIES), ("weekly", config.WEEKLY_CATEGORIES))
        },
        "disclaimer": config.DISCLAIMER.replace("\n", " "),
        "notice": "This forecast is based on NOAA GFS model data and is not an official warning. "
                  "For official advisories, please refer to the national authorities.",
    }
    (st / "style.json").write_text(json.dumps(style, indent=1), encoding="utf-8")
    print(f"  exported static layers: {st}")

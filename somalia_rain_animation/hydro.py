"""Build Juba and Shabelle rivers and catchments from HydroRIVERS and HydroBASINS.

Run once:  python -m somalia_rain_animation.hydro
Writes data/juba_shabelle_rivers.geojson, data/juba_shabelle_catchments.geojson
and data/catchment_preview.png for checking before use.

Method
  * Anchor reaches are the HydroRIVERS reaches nearest Dolo (Juba) and Beledweyne
    (Shabelle). Each stem runs downstream from its anchor to the sea or the confluence,
    and upstream along the largest contributing reach to the headwaters.
  * Shabelle catchment: every reach upstream of the last Shabelle reach before it
    joins the Juba.
  * Juba catchment: every reach upstream of the Juba mouth, except the Shabelle and
    the Lagh Dera (the large branch from Kenya that HydroSHEDS routes into the Juba
    just above the mouth).
  * "Upstream of Somalia" parts: reaches upstream of the point where each stem
    first enters Somalia.
  * Reaches are mapped to HydroBASINS level 12 polygons (HYBAS_L12) and dissolved.
"""
from __future__ import annotations

import glob

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import shapely
from shapely.geometry import Point, Polygon

from . import config
from .layers import load_layer

ANCHORS = {"Juba": (42.07, 4.18), "Shabelle": (45.20, 4.74)}
MOUTH = (42.55, -0.25)
BBOX = (33, -5, 52, 13)


def _find(pattern):
    hits = glob.glob(str(config.HYDRO_DIR / "**" / pattern), recursive=True)
    if not hits:
        raise FileNotFoundError(f"{pattern} not found under {config.HYDRO_DIR}. See README for download links.")
    return hits[0]


def _nearest(riv, xy, min_upland=20000):
    big = riv[riv.UPLAND_SKM > min_upland]
    return big.distance(Point(xy)).idxmin()


def build():
    riv = gpd.read_file(_find("HydroRIVERS_v10_af.shp"), bbox=BBOX).set_index("HYRIV_ID")
    som = load_layer(config.ADMIN0).geometry.union_all()

    mouth = _nearest(riv, MOUTH)
    riv = riv[riv.MAIN_RIV == riv.loc[mouth, "MAIN_RIV"]]
    ups: dict[int, list[int]] = {}
    for i, n in riv.NEXT_DOWN.items():
        ups.setdefault(n, []).append(i)

    def downstream(i):
        path = [i]
        while riv.loc[path[-1], "NEXT_DOWN"] in riv.index:
            path.append(riv.loc[path[-1], "NEXT_DOWN"])
        return path

    def headwater(i):
        path = [i]
        while ups.get(path[-1]):
            path.append(max(ups[path[-1]], key=lambda u: riv.loc[u, "UPLAND_SKM"]))
        return path[::-1]

    def upstream_all(i, include_self=True):
        out, stack = set(), [i]
        while stack:
            r = stack.pop()
            out.add(r)
            stack.extend(ups.get(r, []))
        return out if include_self else out - {i}

    juba_down = downstream(_nearest(riv, ANCHORS["Juba"]))
    shab_down = downstream(_nearest(riv, ANCHORS["Shabelle"]))
    juba_set = set(juba_down)
    conf_idx = next(k for k, r in enumerate(shab_down) if r in juba_set)
    shab_end = shab_down[conf_idx - 1]
    stems = {
        "Juba": headwater(juba_down[0])[:-1] + juba_down,
        "Shabelle": headwater(shab_down[0])[:-1] + shab_down[:conf_idx],
    }

    shab_reaches = upstream_all(shab_end)
    # Large side branches joining the Juba stem that are neither the Shabelle nor upstream Juba
    stem_set = set(stems["Juba"])
    side = [u for r in stems["Juba"] for u in ups.get(r, [])
            if u not in stem_set and u not in shab_reaches and riv.loc[u, "UPLAND_SKM"] > 100000]
    excluded = set().union(*[upstream_all(s) for s in side]) if side else set()
    for s in side:
        x, y = riv.loc[s].geometry.coords[-1]
        print(f"Excluded branch (Lagh Dera): reach {s}, {riv.loc[s, 'UPLAND_SKM']:,.0f} km2, joins at {x:.2f}E {y:.2f}N")
    juba_reaches = upstream_all(stems["Juba"][-1]) - shab_reaches - excluded

    def inside(r):
        return som.contains(riv.loc[r].geometry.interpolate(0.5, normalized=True))

    def upstream_of_somalia(stem, full):
        # First stem reach after the last stretch outside Somalia; take everything
        # upstream of it that lies outside Somalia (both branches meeting on the border).
        last_out = max(k for k, r in enumerate(stem) if not inside(r))
        entry = stem[min(last_out + 1, len(stem) - 1)]
        sel = {r for r in upstream_all(entry, include_self=False) if r in full and not inside(r)}
        print(f"{'Juba' if stem is stems['Juba'] else 'Shabelle'} enters Somalia at reach {entry} "
              f"({riv.loc[entry].geometry.coords[0][0]:.2f}E {riv.loc[entry].geometry.coords[0][1]:.2f}N), "
              f"upstream area {riv.loc[entry, 'UPLAND_SKM']:,.0f} km2")
        return sel

    parts = {
        ("Juba", "full"): juba_reaches,
        ("Shabelle", "full"): shab_reaches,
        ("Juba", "upstream_of_somalia"): upstream_of_somalia(stems["Juba"], juba_reaches),
        ("Shabelle", "upstream_of_somalia"): upstream_of_somalia(stems["Shabelle"], shab_reaches),
    }

    basins = gpd.read_file(_find("hybas_af_lev12_v1c.shp"), bbox=BBOX).set_index("HYBAS_ID")
    # Assign each level 12 basin to the river with most local catchment area in it
    owner = (pd.concat([riv.loc[list(r), ["HYBAS_L12", "CATCH_SKM"]].assign(name=n)
                        for (n, p), r in parts.items() if p == "full"])
             .groupby(["HYBAS_L12", "name"]).CATCH_SKM.sum().reset_index()
             .sort_values("CATCH_SKM").drop_duplicates("HYBAS_L12", keep="last")
             .set_index("HYBAS_L12").name)
    rows = []
    for (name, part), reaches in parts.items():
        ids = set(riv.loc[list(reaches), "HYBAS_L12"])
        ids = {i for i in ids if owner.get(i) == name and i in basins.index}
        geom = basins.loc[list(ids)].geometry.union_all().buffer(0)
        # Fill holes left by small level 12 basins that carry no river reach
        geom = shapely.MultiPolygon([Polygon(p.exterior) for p in getattr(geom, "geoms", [geom])
                                     if p.area > 1e-4]).buffer(0)
        area = basins.loc[list(ids), "SUB_AREA"].sum()
        rows.append(dict(name=name, part=part, area_km2=round(area), n_basins=len(ids), geometry=geom))
    catch = gpd.GeoDataFrame(rows, crs="EPSG:4326")

    rivers = gpd.GeoDataFrame(
        [dict(name=n, section=("Somalia" if som.contains(riv.loc[r].geometry.interpolate(0.5, normalized=True)) else "upstream"),
              geometry=riv.loc[r].geometry) for n, st in stems.items() for r in st],
        crs="EPSG:4326").dissolve(by=["name", "section"]).reset_index()

    out_c = config.PROJECT_DIR / config.CATCHMENTS
    out_r = config.PROJECT_DIR / config.RIVERS
    out_c.parent.mkdir(parents=True, exist_ok=True)
    catch.to_file(out_c, driver="GeoJSON")
    rivers.to_file(out_r, driver="GeoJSON")
    print(catch.drop(columns="geometry").to_string(index=False))
    print(f"Wrote {out_c}\nWrote {out_r}")
    preview(catch, rivers, riv.loc[list(excluded)] if excluded else None)
    return catch, rivers


def preview(catch, rivers, excluded=None):
    adm0 = load_layer(config.ADMIN0)
    nb = load_layer(config.NEIGHBOURS)
    fig, ax = plt.subplots(figsize=(10, 11), dpi=130)
    ax.set_facecolor(config.OCEAN_COLOUR)
    nb.plot(ax=ax, color=config.NEIGHBOUR_FILL, edgecolor=config.NEIGHBOUR_EDGE, lw=0.5)
    adm0.plot(ax=ax, color="#FFFFFF", edgecolor="none")
    full = catch[catch.part == "full"]
    upst = catch[catch.part == "upstream_of_somalia"]
    for (_, r), c in zip(full.iterrows(), ["#F4B183", "#9DC3E6"]):
        gpd.GeoSeries([r.geometry]).plot(ax=ax, color=c, alpha=0.6, edgecolor="none")
    upst.plot(ax=ax, facecolor="none", edgecolor="#555555", hatch="//", lw=0.6)
    full.boundary.plot(ax=ax, color=config.CATCHMENT_COLOUR, lw=1.2)
    if excluded is not None:
        excluded.plot(ax=ax, color="#888888", lw=0.4)
    rivers.plot(ax=ax, color=config.RIVER_COLOUR, lw=1.4)
    adm0.boundary.plot(ax=ax, color="black", lw=1.6)
    for _, r in full.iterrows():
        p = r.geometry.representative_point()
        ax.annotate(f"{r['name']}\n{r.area_km2:,.0f} km²", (p.x, p.y), ha="center", fontsize=10, weight="bold")
    ax.set_xlim(34, 52); ax.set_ylim(-4, 13)
    ax.set_title("Juba and Shabelle catchments for approval\n"
                 "Fill: full catchment. Hatched: part upstream of Somalia. Grey lines: excluded Lagh Dera",
                 fontsize=11)
    out = config.PROJECT_DIR / "data" / "catchment_preview.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    build()

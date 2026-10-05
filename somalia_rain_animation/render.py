"""Draw one map frame per day."""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import geopandas as gpd
import shapely
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrow, PathPatch, Patch, Rectangle
from matplotlib.path import Path as MplPath
from shapely.geometry import box

from . import config, labels
from .labels import fmt_date, fmt_eat

CMAP =ListedColormap(config.CLASS_COLOURS)
NORM = BoundaryNorm(config.CLASS_BOUNDS + [1e6], CMAP.N)
BANNER_CMAP = LinearSegmentedColormap.from_list("banner", config.BANNER_COLOURS)
LABEL_OFFSETS = {"Banadir": (0.55, -0.2), "Bakool": (0.15, -0.4), "Middle Juba": (0, -0.3), "Lower Shabelle": (-0.35, 0.05),
                 "Woqooyi Galbeed": (0.15, 0.12)}  # region labels moved clear of capitals
HALO = [pe.withStroke(linewidth=2.2, foreground="white")]

# Layout, in inches
FIG_W = 12.0
MAP_W = 11.0
BANNER_H, ACCENT_H, GAP, LEGEND_H, FOOTER_H = 1.35, 0.07, 0.25, 1.25, 0.85


def geom_to_path(geom):
    """Shapely (Multi)Polygon to a matplotlib Path, holes included."""
    verts, codes = [], []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.geom_type != "Polygon":
            continue
        for ring in [poly.exterior, *poly.interiors]:
            xy = np.asarray(ring.coords)
            verts.append(xy)
            codes.append([MplPath.MOVETO] + [MplPath.LINETO] * (len(xy) - 2) + [MplPath.CLOSEPOLY])
    return MplPath(np.concatenate(verts), np.concatenate(codes))


class FrameRenderer:
    def __init__(self, lyr, extent, lons, lats, run_dt, cycle, mode="daily",
                 admin2=False, capitals=True, dpi=200, lead_days=0):
        self.lyr, self.extent, self.lons, self.lats = lyr, extent, lons, lats
        self.run_dt, self.cycle, self.mode = run_dt, cycle, mode
        # Start of forecast day 1 (UTC); later than the run time when --start-date is used
        self.t0 = run_dt + dt.timedelta(days=lead_days)
        self.admin2, self.capitals, self.dpi = admin2, capitals, dpi
        catch = lyr.get("catchments")
        self.catch_full = catch[catch["part"] == "full"] if catch is not None else None
        somalia = lyr["admin0"].geometry.union_all().buffer(0)
        self.mask_path = geom_to_path(somalia)
        self.catch_path = None
        if self.catch_full is not None:
            outside = self.catch_full.geometry.union_all().buffer(0).difference(somalia)
            if not outside.is_empty:
                self.catch_path = geom_to_path(outside)
        self.view = box(extent[0], extent[2], extent[1], extent[3])
        # union of all land; the small close (grow then shrink) seals slivers between country polygons
        land = (lyr["neighbours"].geometry.union_all().union(somalia).buffer(0.02).buffer(-0.02)
                .intersection(self.view.buffer(1)))
        self.land_path = geom_to_path(land)
        self.sea_path = geom_to_path(self.view.buffer(1).difference(land))
        # Coastal glow rings: land grown by each step, minus the land, so only sea is tinted
        simple = land.simplify(0.01)
        self.coast_rings = [geom_to_path(simple.buffer(d).difference(land).intersection(self.view.buffer(0.5)))
                            for d in config.COAST_GLOW_STEPS]
        self.coast_line = land.boundary.intersection(self.view.buffer(0.5))
        logo = config.PROJECT_DIR / config.LOGO
        self.logo = plt.imread(logo) if logo.exists() else None
        self.watermark = None
        if self.logo is not None:
            # One colour silhouette of the logo (house anti-crop watermark), dark ink for a light map
            wm = np.array(self.logo, dtype=float)
            wm[..., :3] = np.array(matplotlib.colors.to_rgb(config.WATERMARK_COLOUR))
            self.watermark = wm

    # ---------- text ----------
    def _mid(self, k):
        """Calendar date (EAT) at the middle of forecast day k."""
        return labels.day_date(self.t0, k)

    def week_range(self):
        return labels.week_range(self.t0)

    def titles(self, n, total=False):
        eat = dt.timedelta(hours=config.EAT_OFFSET_HOURS)
        end = self.t0 + dt.timedelta(hours=24 * n) + eat
        mid = self._mid
        if total:
            start = self.t0 + eat
            when = labels.total_title(self.t0, n)
        elif self.mode == "daily":
            start = self.t0 + dt.timedelta(hours=24 * (n - 1)) + eat
            when = fmt_date(mid(n))
        else:
            start = self.t0 + eat
            when = (f"Total for {fmt_date(mid(1))}" if n == 1 else
                    f"Total from {mid(1):%A} {mid(1).day} {mid(1):%B} to {fmt_date(mid(n))}")
        return when, f"Valid {fmt_eat(start)} to {fmt_eat(end)}"

    # ---------- drawing ----------
    def draw(self, grid, n, out_path, total=False):
        x0, x1, y0, y1 = self.extent
        map_h = MAP_W * (y1 - y0) / (x1 - x0)
        fig_h = BANNER_H + ACCENT_H + GAP + map_h + GAP + LEGEND_H + FOOTER_H
        fig = plt.figure(figsize=(FIG_W, fig_h), dpi=self.dpi)
        fy = lambda inch: inch / fig_h          # inches from bottom to figure fraction
        mx = (FIG_W - MAP_W) / 2 / FIG_W

        self._banner(fig, fy(fig_h - BANNER_H), fy(BANNER_H), fy(ACCENT_H), n, total)

        ax = fig.add_axes([mx, fy(FOOTER_H + LEGEND_H + GAP), MAP_W / FIG_W, fy(map_h)])
        self._map(ax, grid)
        self._watermark(fig, ax)

        self._legend(fig, fy(FOOTER_H), fy(LEGEND_H))
        self._footer(fig, fy(FOOTER_H), mx)
        # Write to a temporary file and swap it in, retrying: OneDrive briefly locks
        # files it is syncing, which makes a direct overwrite fail with Errno 22.
        out_path = Path(out_path)
        tmp = out_path.with_name(f".{out_path.stem}.tmp.png")
        fig.savefig(tmp, dpi=self.dpi, facecolor="white")
        plt.close(fig)
        for attempt in range(10):
            try:
                os.replace(tmp, out_path)
                break
            except OSError:
                if attempt == 9:
                    raise
                time.sleep(1.5)

    def _banner(self, fig, y, h, accent_h, n, total=False):
        bx = fig.add_axes([0, y, 1, h]); bx.axis("off")
        bx.imshow(np.linspace(0, 1, 512)[None, :], cmap=BANNER_CMAP, aspect="auto",
                  extent=(0, 1, 0, 1))
        bx.set_xlim(0, 1); bx.set_ylim(0, 1)
        ac = fig.add_axes([0, y - accent_h, 1, accent_h]); ac.axis("off")
        ac.add_patch(Rectangle((0, 0), 1, 1, color=config.ACCENT_COLOUR, transform=ac.transAxes))
        when, _ = self.titles(n, total)
        t = bx.text(0.04, 0.72, "Weekly Rainfall Forecast", color="white", fontsize=28, weight="bold",
                    va="center", transform=bx.transAxes)
        bx.annotate(self.week_range(), xy=(1, 0.22), xycoords=t, xytext=(12, 0),
                    textcoords="offset points", color="#D6ECF7", fontsize=14, va="bottom")
        # The date is the part that changes each frame, so it gets a high contrast badge
        bx.text(0.047, 0.28, when, color=config.DATE_TEXT_COLOUR, fontsize=19, weight="bold",
                va="center", transform=bx.transAxes,
                bbox=dict(boxstyle="round,pad=0.38,rounding_size=0.6", fc=config.DATE_BADGE_COLOUR, ec="none"))
        bx.text(0.96, 0.72, "SOMALIA", color="white", fontsize=15, weight="bold", ha="right",
                va="center", alpha=0.9, transform=bx.transAxes)

    def _map(self, ax, grid):
        x0, x1, y0, y1 = self.extent
        ax.set_facecolor(config.OCEAN_COLOUR)
        L = self.lyr
        L["neighbours"].plot(ax=ax, color=config.NEIGHBOUR_FILL, edgecolor=config.NEIGHBOUR_EDGE,
                             linewidth=0.5, zorder=1)
        for ring in self.coast_rings:
            ax.add_patch(PathPatch(ring, facecolor=config.COAST_GLOW_COLOUR, edgecolor="none",
                                   alpha=config.COAST_GLOW_ALPHA, zorder=1.5))

        d = config.GRID_STEP / 2
        ext = (self.lons[0] - d, self.lons[-1] + d, self.lats[0] - d, self.lats[-1] + d)
        kw = dict(cmap=CMAP, norm=NORM, origin="lower", extent=ext, interpolation="nearest")
        wet = np.ma.masked_less(grid, config.CLASS_BOUNDS[1])  # 0 to 2 mm left clear outside Somalia
        land = ax.imshow(wet, alpha=config.FADED_ALPHA, zorder=2, **kw)
        land.set_clip_path(PathPatch(self.land_path, transform=ax.transData))
        sea = ax.imshow(wet, alpha=config.SEA_ALPHA, zorder=2, **kw)
        sea.set_clip_path(PathPatch(self.sea_path, transform=ax.transData))
        if self.catch_path is not None and config.CATCHMENT_ALPHA > 0:
            up = ax.imshow(wet, alpha=config.CATCHMENT_ALPHA, zorder=2.5, **kw)
            up.set_clip_path(PathPatch(self.catch_path, transform=ax.transData))
        full = ax.imshow(grid, zorder=3, **kw)
        full.set_clip_path(PathPatch(self.mask_path, transform=ax.transData))

        if self.catch_full is not None:
            self._catchments(ax)
        if self.admin2:
            L["admin2"].boundary.plot(ax=ax, color="#BBBBBB", linewidth=0.25, zorder=5)
        L["admin1"].boundary.plot(ax=ax, color="#6E6E6E", linewidth=0.6, zorder=6)
        for _, r in L["admin1"].iterrows():
            p = r.geometry.representative_point()
            dx, dy = LABEL_OFFSETS.get(r[config.ADMIN1_NAME_COL], (0, 0))
            ax.text(p.x + dx, p.y + dy, r[config.ADMIN1_NAME_COL], fontsize=8.5, weight="bold", color="#2B2B2B",
                    ha="center", va="center", zorder=9, path_effects=HALO)
        if L.get("rivers") is not None:
            L["rivers"].plot(ax=ax, color=config.RIVER_COLOUR, linewidth=1.3, zorder=7)
            self._river_labels(ax)
        gpd.GeoSeries([self.coast_line]).plot(ax=ax, color=config.COAST_LINE_COLOUR, linewidth=0.4, zorder=7.5)
        L["admin0"].boundary.plot(ax=ax, color="black", linewidth=1.8, zorder=8)

        self._neighbour_labels(ax)
        for name, (x, y), size in config.SEA_LABELS:
            if x0 < x < x1 and y0 < y < y1:
                ax.text(x, y, name, fontsize=size, color=config.SEA_LABEL_COLOUR, style="italic",
                        ha="center", va="center", zorder=9,
                        path_effects=[pe.withStroke(linewidth=2, foreground=config.OCEAN_COLOUR)])
        if self.capitals and L.get("capitals") is not None:
            self._capitals(ax)
        self._scale_bar(ax)
        self._north_arrow(ax)

        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("auto")
        ax.set_xlabel(""); ax.set_ylabel("")
        ax.tick_params(labelsize=8, colors="#555555")
        ax.set_xticks(range(int(np.ceil(x0)), int(x1) + 1, 2))
        ax.set_yticks(range(int(np.ceil(y0)), int(y1) + 1, 2))
        ax.xaxis.set_major_formatter(lambda v, _: f"{abs(v):.0f}°{'E' if v >= 0 else 'W'}")
        ax.yaxis.set_major_formatter(lambda v, _: f"{abs(v):.0f}°{'N' if v >= 0 else 'S'}")
        for s in ax.spines.values():
            s.set_color("#777777")

    def _legend(self, fig, y, h):
        lx = fig.add_axes([0.03, y, 0.94, h]); lx.axis("off")
        handles = [Patch(facecolor=c, edgecolor="#555555", linewidth=0.6, label=l)
                   for c, l in zip(config.CLASS_COLOURS, config.CLASS_LABELS)]
        lg = lx.legend(handles=handles, title="Rainfall (mm)", loc="upper center", ncol=6,
                       bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=9.5, title_fontsize=11,
                       handlelength=2.4, handleheight=1.2, columnspacing=1.6)
        lg.get_title().set_weight("bold")
        lx.add_artist(lg)
        lines = [Line2D([], [], color="black", lw=1.8, label="Somalia border"),
                 Line2D([], [], color="#6E6E6E", lw=0.8, label="Region boundary")]
        if self.catch_full is not None:
            lines.append(Line2D([], [], color=config.CATCHMENT_COLOUR, lw=1.0, ls=(0, (5, 2.5)),
                                label="Juba and Shabelle basins (upstream)"))
        if self.lyr.get("rivers") is not None:
            lines.append(Line2D([], [], color=config.RIVER_COLOUR, lw=1.3, label="Rivers"))
        lx.legend(handles=lines, loc="lower center", ncol=len(lines), bbox_to_anchor=(0.5, 0.02),
                  frameon=False, fontsize=9, columnspacing=2.0)

    def _capitals(self, ax):
        """Regional capitals: white dot with a dark ring, bold dark label to the upper right."""
        cap = self.lyr["capitals"]
        ax.scatter(cap.geometry.x, cap.geometry.y, s=26, facecolor="white", edgecolor="#1A1A1A",
                   linewidth=1.1, zorder=10)
        ax.scatter(cap.geometry.x, cap.geometry.y, s=4, color="#1A1A1A", zorder=10.1)
        for _, r in cap.iterrows():
            name = str(r[config.CAPITAL_NAME_COL])
            dx, dy = config.CAPITAL_LABEL_OFFSETS.get(name, (0.09, 0.0))
            ax.text(r.geometry.x + dx, r.geometry.y + dy, name, fontsize=6, weight="normal",
                    color="#1A1A1A", ha="left" if dx >= 0 else "right",
                    va="center" if dy == 0 else ("bottom" if dy > 0 else "top"),
                    zorder=10, path_effects=HALO)

    def _catchments(self, ax):
        """Basin divides upstream of Somalia: thin dashed earth line on a soft white casing,
        with spaced basin names. Inside Somalia the rivers already carry the story, so the
        divides are left off there to keep the map clean."""
        somalia = self.lyr["admin0"].geometry.union_all().buffer(0)
        for _, r in self.catch_full.iterrows():
            edge = r.geometry.boundary.difference(somalia.buffer(0.02))
            if edge.is_empty:
                continue
            g = gpd.GeoSeries([edge])
            g.plot(ax=ax, color="white", linewidth=2.6, alpha=0.6, zorder=4)
            g.plot(ax=ax, color=config.CATCHMENT_COLOUR, linewidth=1.0, linestyle=(0, (5, 2.5)), zorder=4.1)
            up = r.geometry.difference(somalia)
            if up.is_empty:
                continue
            p = up.representative_point()
            name = config.CATCHMENT_LABELS.get(r["name"], r["name"].upper())
            ax.text(p.x, p.y, " ".join(name), fontsize=8, color=config.CATCHMENT_COLOUR, weight="bold",
                    ha="center", va="center", zorder=9, path_effects=HALO)

    def _watermark(self, fig, ax):
        """Centred on the map, faint, above the rainfall but under nothing important."""
        if self.watermark is None or not config.WATERMARK:
            return
        pos = ax.get_position()
        fig_w, fig_h = fig.get_size_inches()
        w = pos.width * config.WATERMARK_WIDTH
        lh, lw = self.watermark.shape[:2]
        h = w * fig_w * lh / lw / fig_h
        wa = fig.add_axes([pos.x0 + (pos.width - w) / 2, pos.y0 + (pos.height - h) / 2, w, h], zorder=5)
        wa.imshow(self.watermark, alpha=config.WATERMARK_ALPHA)
        wa.axis("off")

    def _footer(self, fig, h, mx):
        fx = fig.add_axes([0, 0, 1, h]); fx.axis("off")
        fx.axhline(0.98, xmin=mx, xmax=1 - mx, color="#CCCCCC", lw=0.8)
        date_s = f"{self.run_dt.day} {self.run_dt:%B %Y}"
        fx.text(mx, 0.5, f"Source: NOAA-NCEP-GFS, {self.cycle:02d}Z run of {date_s}.\n"
                "Compiled by TerraTech Solutions, www.tetso.net", fontsize=9, color="#444444",
                va="center", transform=fx.transAxes, linespacing=1.5)
        fx.text(0.535, 0.5, config.DISCLAIMER, fontsize=7.5, color="#666666", style="italic",
                ha="center", va="center", transform=fx.transAxes, linespacing=1.4)
        if self.logo is not None:
            lh, lw = self.logo.shape[:2]
            fig_w, fig_h = fig.get_size_inches()
            w_in = 2.6
            h_frac = w_in * lh / lw / fig_h
            la = fig.add_axes([1 - mx - w_in / fig_w, (h * 0.5) - h_frac / 2, w_in / fig_w, h_frac])
            la.imshow(self.logo); la.axis("off")

    def _neighbour_labels(self, ax):
        for _, r in self.lyr["neighbours"].iterrows():
            g = r.geometry.intersection(self.view.buffer(-0.3))
            if g.is_empty or g.area < 0.3:
                continue
            p = g.representative_point() if r[config.NEIGHBOUR_NAME_COL] != "Ethiopia" else \
                g.intersection(box(37, 3.5, 41.5, 11)).representative_point()
            ax.text(p.x, p.y, r[config.NEIGHBOUR_NAME_COL], fontsize=13, color=config.NEIGHBOUR_LABEL_COLOUR,
                    weight="bold", ha="center", va="center", zorder=9,
                    path_effects=[pe.withStroke(linewidth=3, foreground="white")])

    def _river_labels(self, ax):
        riv = self.lyr["rivers"]
        som = riv[riv["section"] == "Somalia"] if "section" in riv else riv
        spots = {"Juba": 0.35, "Shabelle": 0.2}
        for name, frac in spots.items():
            sub = som[som["name"] == name]
            if sub.empty:
                continue
            line = shapely.line_merge(sub.geometry.union_all())
            if line.geom_type == "MultiLineString":
                line = max(line.geoms, key=lambda g: g.length)
            p = line.interpolate(frac, normalized=True)
            ax.text(p.x + 0.12, p.y, name, fontsize=9, color=config.RIVER_COLOUR, style="italic",
                    weight="bold", zorder=9, path_effects=HALO)

    def _scale_bar(self, ax):
        x0, _, y0, _ = self.extent
        lat = y0 + 0.45
        km_per_deg = 111.32 * np.cos(np.deg2rad(lat))
        seg_km, nseg = 100, 3
        sx = x0 + 0.4
        for i in range(nseg):
            w = seg_km / km_per_deg
            ax.add_patch(Rectangle((sx + i * w, lat), w, 0.1, facecolor="black" if i % 2 == 0 else "white",
                                   edgecolor="black", lw=0.6, zorder=11))
        for i in range(nseg + 1):
            ax.text(sx + i * seg_km / km_per_deg, lat + 0.18, f"{i * seg_km}", fontsize=7.5, ha="center",
                    zorder=11, path_effects=HALO)
        ax.text(sx + nseg * seg_km / km_per_deg + 0.2, lat + 0.01, "km", fontsize=7.5, zorder=11, path_effects=HALO)

    def _north_arrow(self, ax):
        x0, _, _, y1 = self.extent
        x, y = x0 + 0.55, y1 - 1.25
        ax.add_patch(FancyArrow(x, y, 0, 0.7, width=0.07, head_width=0.36, head_length=0.36,
                                color="black", zorder=11, length_includes_head=True))
        ax.text(x, y + 0.82, "N", ha="center", va="bottom", fontsize=12, weight="bold", zorder=11,
                path_effects=HALO)

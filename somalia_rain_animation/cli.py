"""Command line entry point: make the frames, GIF, MP4 and player for one run."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

from . import animate, config, gfs
from .layers import load_all, map_extent
from .pipeline import RunData, compute_run
from .render import FrameRenderer


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m somalia_rain_animation",
                                description="Animated 7 day GFS rainfall forecast map for Somalia.")
    p.add_argument("--date", help="Run date YYYYMMDD (default: latest published run)")
    p.add_argument("--start-date", help="First forecast day YYYYMMDD, when later than the run date "
                   "(for example tomorrow, using today's run). Default: the run date")
    p.add_argument("--cycle", type=int, default=0, choices=[0, 6, 12, 18], help="Run cycle in UTC (default 00)")
    p.add_argument("--mode", choices=["daily", "cumulative"], default="daily",
                   help="daily totals, or running totals from day 1")
    p.add_argument("--admin2", action="store_true", help="Draw district (admin2) boundaries")
    p.add_argument("--no-capitals", action="store_true", help="Leave out the regional capitals")
    p.add_argument("--dpi", type=int, default=220, help="Frame resolution (default 220, about 2640 px wide)")
    p.add_argument("--no-total", action="store_true",
                   help="Daily mode: do not end with the weekly total frame")
    p.add_argument("--no-video", action="store_true", help="Write PNG frames only")
    return p.parse_args(argv)


def parse_date(s):
    """YYYYMMDD; also accepts 2026-10-08 or 2026/10/08 as typed in the workflow form."""
    if not s or not s.strip():
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    try:
        return dt.datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise SystemExit(f"ERROR: '{s}' is not a date. Use YYYYMMDD, for example 20261008.")


def render_media(lyr, rd: RunData, out_dir: Path, mode="daily", admin2=False, capitals=True,
                 dpi=220, total=True, video=True, verbose=True):
    """Steps 4 and 5: regrid, draw the frames, then the GIF, MP4 and player page."""
    grids = rd.days if mode == "daily" else list(np.cumsum(rd.days, axis=0))
    extent = map_extent(lyr)
    lons, lats = gfs.target_grid(extent)
    if verbose:
        print(f"Map extent lon {extent[0]} to {extent[1]}, lat {extent[2]} to {extent[3]}; "
              f"grid {len(lats)} x {len(lons)}")
    fine = [gfs.regrid(g, rd.lat1, rd.lon1, lons, lats) for g in grids]

    out_dir.mkdir(parents=True, exist_ok=True)
    r = FrameRenderer(lyr, extent, lons, lats, rd.run_dt, rd.cycle, mode=mode,
                      admin2=admin2, capitals=capitals, dpi=dpi, lead_days=rd.lead)
    frames = []
    for n, g in enumerate(fine, start=1):
        f = out_dir / f"{mode}_day{n}.png"
        r.draw(g, n, f)
        frames.append(f)
        print(f"  frame {n}: {f.name}")
    if mode == "daily" and total:
        # Close the daily sequence with the 7 day accumulation
        f = out_dir / "daily_total.png"
        r.draw(gfs.regrid(np.sum(rd.days, axis=0), rd.lat1, rd.lon1, lons, lats), len(rd.days), f, total=True)
        frames.append(f)
        print(f"  frame total: {f.name}")

    media = {"frames": frames}
    if video:
        gif = out_dir / f"rainfall_{mode}_{rd.run_id}.gif"
        mp4 = out_dir / f"rainfall_{mode}_{rd.run_id}.mp4"
        animate.make_gif(frames, gif)
        animate.make_mp4(frames, mp4)
        media["gif"] = gif
        if mp4.exists():
            media["mp4"] = mp4
            media["html"] = animate.make_player(mp4, f"Somalia Weekly Rainfall Forecast, {r.week_range()}")
    return media


def main(argv=None):
    a = parse_args(argv)
    lyr = load_all()
    try:
        rd = compute_run(parse_date(a.date), parse_date(a.start_date), a.cycle)
    except (gfs.RunNotAvailable, ValueError) as e:
        sys.exit(f"ERROR: {e}")
    out_dir = config.OUTPUT_DIR / rd.run_id
    print(f"  ->  {out_dir}")
    render_media(lyr, rd, out_dir, mode=a.mode, admin2=a.admin2, capitals=not a.no_capitals,
                 dpi=a.dpi, total=not a.no_total, video=not a.no_video)
    print("Done.")

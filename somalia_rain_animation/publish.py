"""Build the published site: app data, video media, manifest and alerts.

    python -m somalia_rain_animation.publish [--date YYYYMMDD] [--start-date YYYYMMDD]
                                             [--restore-from URL] [--no-media] [--force]

Used by the GitHub Actions workflow. --restore-from downloads the currently published site first,
so earlier runs stay in the manifest; a run that is not yet on NOMADS is a soft skip (exit 0).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import requests

from . import alerts, config, export, gfs
from .cli import parse_date, render_media
from .layers import load_all
from .pipeline import compute_run

WEB_DIR = Path(__file__).parent / "web"


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m somalia_rain_animation.publish")
    p.add_argument("--date", help="Run date YYYYMMDD (default: latest published run)")
    p.add_argument("--start-date", help="First forecast day YYYYMMDD (default: the run date)")
    p.add_argument("--cycle", type=int, default=0, choices=[0, 6, 12, 18])
    p.add_argument("--site", type=Path, default=config.SITE_DIR, help="Output folder for the site")
    p.add_argument("--restore-from", help="Base URL of the live site, to keep earlier runs")
    p.add_argument("--no-media", action="store_true", help="Skip frames, GIF and MP4")
    p.add_argument("--no-alerts", action="store_true")
    p.add_argument("--force", action="store_true", help="Rebuild a run that is already published")
    return p.parse_args(argv)


# ---------- restore the live site ----------
def _get(url, dest: Path):
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return True


def restore(base: str, site: Path):
    base = base.rstrip("/") + "/"
    try:
        if not _get(base + "manifest.json", site / "manifest.json"):
            print(f"  restore: no live site at {base} yet, starting fresh")
            return
    except requests.RequestException as e:
        print(f"  restore: could not reach {base} ({e}), starting fresh")
        return
    _get(base + "sent_alerts.json", site / "sent_alerts.json")
    man = json.loads((site / "manifest.json").read_text(encoding="utf-8"))
    for run in man["runs"]:
        rdir = site / "runs" / run["id"]
        if not _get(f"{base}runs/{run['id']}/meta.json", rdir / "meta.json"):
            continue
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        files = list(meta["overlays"].values()) + ["values.json", "summary.json"]
        files += [f"media/{v}" for v in meta.get("media", {}).values()]
        for f in files:
            _get(f"{base}runs/{run['id']}/{f}", rdir / f)
    print(f"  restore: {len(man['runs'])} runs from {base}")


# ---------- manifest ----------
def update_manifest(site: Path, meta: dict, keep: int):
    path = site / "manifest.json"
    man = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
    entry = {"id": meta["run_id"], "run_date": meta["run_date"], "cycle": meta["cycle"],
             "first_day": meta["first_day"], "last_day": meta["last_day"],
             "week_range": meta["week_range"], "path": f"runs/{meta['run_id']}/"}
    runs = [r for r in man["runs"] if r["id"] != entry["id"]] + [entry]
    runs.sort(key=lambda r: (r["first_day"], r["run_date"], r["cycle"]), reverse=True)
    for old in runs[keep:]:
        shutil.rmtree(site / "runs" / old["id"], ignore_errors=True)
        print(f"  pruned old run {old['id']}")
    runs = runs[:keep]
    man = {"updated_utc": meta["generated_utc"], "latest": runs[0]["id"], "runs": runs}
    path.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


def main(argv=None):
    a = parse_args(argv)
    site = a.site
    site.mkdir(parents=True, exist_ok=True)
    if a.restore_from:
        restore(a.restore_from, site)

    lyr = load_all()
    try:
        rd = compute_run(parse_date(a.date), parse_date(a.start_date), a.cycle)
    except gfs.RunNotAvailable as e:
        print(f"SKIP: {e}")
        return 0
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    man_path = site / "manifest.json"
    if man_path.exists() and not a.force:
        if any(r["id"] == rd.run_id for r in json.loads(man_path.read_text(encoding="utf-8"))["runs"]):
            print(f"SKIP: run {rd.run_id} is already published (use --force to rebuild)")
            return 0

    export.export_static(lyr, site)
    meta = export.export_run(lyr, rd, site)
    rdir = site / "runs" / rd.run_id

    if not a.no_media:
        media = render_media(lyr, rd, config.OUTPUT_DIR / rd.run_id)
        meta["media"] = {}
        for kind in ("gif", "mp4", "html"):
            if kind in media:
                dest = rdir / "media" / media[kind].name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(media[kind], dest)
                meta["media"][kind] = media[kind].name
        (rdir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    man = update_manifest(site, meta, config.MANIFEST_KEEP)
    print(f"  manifest: {len(man['runs'])} runs, latest {man['latest']}")

    for f in WEB_DIR.glob("*"):          # web dashboard (index.html) served next to the data
        shutil.copy2(f, site / f.name)
    (site / ".nojekyll").write_text("", encoding="utf-8")

    if not a.no_alerts:
        summary = json.loads((rdir / "summary.json").read_text(encoding="utf-8"))
        alerts.send_alerts(meta, summary, site)
    print(f"Published: {site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

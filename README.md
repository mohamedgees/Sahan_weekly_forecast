# somalia_rain_animation

Animated 7 day rainfall forecast maps for Somalia from NOAA GFS 0.25 degree data.
Each run produces one PNG frame per forecast day, an animated GIF and an MP4.

## What it does

1. Downloads `gfs.tCCz.pgrb2.0p25.fNNN` for NNN = 024, 048, ..., 168 from the NOMADS GRIB
   filter (APCP at the surface, subregion lon 35 to 53, lat −6 to 16). Failed downloads are
   retried; a run that is not yet published is reported clearly.
2. Reads the APCP message for hours 0 to NNN (kg/m² = mm) with pygrib and stops if it is missing.
3. Daily rainfall for day N = total(0 to 24N) minus total(0 to 24(N−1)), negatives clipped to 0.
   Prints a check that the 7 daily grids add up to the f168 total.
4. Interpolates each grid bilinearly to 0.02 degrees over Somalia and the catchments
   (their bounds plus a 0.35 degree margin). The source data stays 0.25 degree GFS.
5. Classifies into the 11 SWALIM rainfall classes plus an "Above 250" class and draws the frames.

Rainfall uses the SWALIM 7 day forecast legend (0 - 2 up to 200 - 250 mm), with an extra "Above 250"
class in magenta. Rainfall is drawn at full colour over land. Outside Somalia, areas under 2 mm are left clear so the
grey country background shows. Rain over the sea is shown fainter (`SEA_ALPHA` in config.py), and the
coast has a soft blue band in the SWALIM style. The changing date sits in a yellow badge in the banner so
it reads well on phones.

## Installation

pygrib has no Windows wheels on PyPI, so use conda-forge. With
[micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html):

```
micromamba create -n somrain -f environment.yml
```

(or `conda env create -f environment.yml`). Always run the project inside the activated
environment (`micromamba activate somrain`, or `micromamba run -n somrain ...`). Calling the
environment's `python.exe` directly without activating it can crash when drawing on Windows.

## Input files

Put these in the project folder (names are set in `somalia_rain_animation/config.py`):

| Layer | File |
|---|---|
| Somalia admin0 | `som_admin0.geojson` |
| Somalia admin1 | `som_admin1.geojson` |
| Somalia admin2 | `som_admin2.geojson` |
| Neighbouring countries | `Bordering Contouries Somalia.json` |
| Juba and Shabelle rivers (optional) | `data/juba_shabelle_rivers.geojson` |
| Juba and Shabelle catchments (optional) | `data/juba_shabelle_catchments.geojson` |
| Regional capitals (optional, points) | `Regional Capital.json` (names from `DISTRICT`) |

`CAPITAL_FIXES` in `config.py` corrects capitals on load (Baki is replaced by Borama for Awdal).
All layers are reprojected to EPSG:4326 on load, and each file's CRS, columns and feature
count are printed at the start of every run.

### Building the rivers and catchments (once)

Download and unzip into `data/hydrosheds/`:

* HydroRIVERS Africa: https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_af_shp.zip
* HydroBASINS Africa level 12: https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_af_lev12_v1c.zip

Then run:

```
python -m somalia_rain_animation.hydro
```

This writes both GeoJSON files and `data/catchment_preview.png` for checking. The Juba
catchment (about 216,000 km²) excludes the Lagh Dera from Kenya, which HydroSHEDS routes
into the Juba just above its mouth. The Shabelle catchment (about 298,000 km²) is everything
draining to the Shabelle above its confluence with the Juba. Each catchment also has an
"upstream of Somalia" part.

## Usage

```
python -m somalia_rain_animation [--date YYYYMMDD] [--start-date YYYYMMDD] [--cycle {0,6,12,18}]
                                 [--mode {daily,cumulative}] [--admin2]
                                 [--no-capitals] [--dpi 220] [--no-total] [--no-video]
```

| Option | Meaning |
|---|---|
| `--date` | Run date. Default: the latest published run of the chosen cycle |
| `--start-date` | First forecast day when later than the run date, for example tomorrow from today's run. Uses hours 24(N) to 24(N+7) of the same run; output goes to `output/<run>_from_<start>/` |
| `--cycle` | Run cycle in UTC, default 00 |
| `--mode cumulative` | Running totals (day 1, days 1 to 2, ... days 1 to 7) instead of daily totals |
| `--admin2` | Draw district boundaries |
| `--no-capitals` | Leave out the regional capitals |
| `--no-total` | Daily mode: leave out the closing weekly total frame |

Example for a week starting tomorrow, from today's 00Z run:

```
micromamba run -n somrain python -m somalia_rain_animation --date 20261004 --start-date 20261005
```

Example:

```
micromamba run -n somrain python -m somalia_rain_animation
```

## Output

`output/<YYYYMMDD>_<CC>Z/`

* `daily_day1.png` ... `daily_day7.png` (or `cumulative_day*.png`)
* `daily_total.png`: daily mode ends with the 7 day accumulation
* `rainfall_<mode>_<date>_<CC>Z.gif`: 1.5 s per frame, last frame (weekly total) held for 5 s
* `rainfall_<mode>_<date>_<CC>Z.mp4`: same timing, full frame resolution (about 2640 px wide), H.264
* `rainfall_<mode>_<run>.html`: a player page for the MP4 that autoplays (muted), loops and has a Play/Pause button. Keep it in the same folder as the MP4
* `grib/`: the downloaded GRIB files, reused if the run is processed again

Each frame has a title banner reading "Weekly Rainfall Forecast" with the forecast date beneath it, a faint
centred TerraTech Solutions watermark on the map (`WATERMARK_*` in config.py),
the rainfall legend along the bottom, and a footer with the data source, "Compiled by TerraTech
Solutions" and the TerraTech Solutions logo (`assets/terratech_logo.png`). Banner colours and the
logo path are set in `config.py`. The map is zoomed to Somalia and the Juba and Shabelle catchments.

Times are shown in East Africa Time (UTC+3). Forecasts are GFS model output with no bias correction.

## Automation, web dashboard and app data

`python -m somalia_rain_animation.publish` builds a static site in `site/` that the web dashboard and the
Android app read:

| Path | Content |
|---|---|
| `index.html` | Web dashboard (Leaflet): pick a forecast, step or play through the days, tap for rainfall, region and basin summary table |
| `manifest.json` | Published runs, newest first, and the latest run id (`MANIFEST_KEEP` runs are kept) |
| `runs/<run>/day1.png … total.png` | Transparent rain overlays, rows spaced for Web Mercator maps; corners in `meta.json` → `bounds` |
| `runs/<run>/values.json` | Native 0.25 degree grid, rainfall in mm × 10, for tap lookups |
| `runs/<run>/summary.json` | Area mean rainfall per day and week, P90, maximum and % area ≥ 50 mm, per region and basin |
| `runs/<run>/meta.json` | Day dates and titles, week range, source line, overlay bounds, media files |
| `runs/<run>/media/` | The GIF, MP4 and player page of that run |
| `static/` | Simplified GeoJSON layers and `style.json` (legend, colours, notices) generated from `config.py` |

Options: `--date`, `--start-date`, `--cycle` as above; `--restore-from URL` downloads the live site first so
earlier runs are kept; `--no-media` skips the video; `--force` rebuilds a run already published. A run not yet
on NOMADS is skipped with exit code 0.

Preview locally:

```
micromamba run -n somrain python -m somalia_rain_animation.publish --date 20261004 --start-date 20261005
micromamba run -n somrain python -m http.server 8766 --directory site
```

then open http://localhost:8766/.

### GitHub Actions

`.github/workflows/forecast.yml` runs the publisher every day at 05:30 UTC (and on demand from the Actions
tab, with optional run date, start date and force) and deploys `site/` to GitHub Pages. Set up once:

1. Push this repository to GitHub (public, for free GitHub Pages).
2. Settings → Pages → Source: **GitHub Actions**.
3. Optional, for push alerts: add the Firebase service account JSON as the repository secret
   `FCM_SERVICE_ACCOUNT`. Without it, alerts are printed in the log only.

The site is then served at `https://<owner>.github.io/<repository>/`.

### Push alerts

Firebase Cloud Messaging topics, sent by `alerts.py` after each publish:

| Topic | Sent when |
|---|---|
| `new_forecast` | the first run published in each calendar week |
| `heavy_rain_<pcode>` (e.g. `heavy_rain_so12`) | a region's area mean reaches `ALERT_DAILY_MM` in a day or `ALERT_WEEKLY_MM` over the week |
| `basin_juba`, `basin_shabelle` | the upstream basin mean reaches `ALERT_BASIN_WEEKLY_MM` over the week |

Each alert is sent once; `site/sent_alerts.json` remembers what has gone out.

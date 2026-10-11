"""Fixed settings: paths, input file names, extents and rainfall classes."""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR
OUTPUT_DIR = PROJECT_DIR / "output"
HYDRO_DIR = PROJECT_DIR / "data" / "hydrosheds"

# Input layers (all GeoJSON, reprojected to EPSG:4326 on load)
ADMIN0 = "som_admin0.geojson"
ADMIN1 = "som_admin1.geojson"
ADMIN2 = "som_admin2.geojson"
NEIGHBOURS = "Bordering Contouries Somalia.json"
RIVERS = "data/juba_shabelle_rivers.geojson"          # optional
CATCHMENTS = "data/juba_shabelle_catchments.geojson"  # optional
CAPITALS = "Regional Capital.json"                    # optional, points
CAPITAL_NAME_COL = "DISTRICT"
# Named places for the app's tap card ("Near <village>"); optional, points
SETTLEMENTS = "som_settlements_2022.json"
# Rank by settlement type: lower wins when two places are about equally close to a tap
SETTLEMENT_RANKS = {"National Capital": 0, "Regional Capital": 0, "District Capital": 1, "Town": 2,
                    "Part of town": 2, "Settlement": 3, "IDP Camp": 3, "Temporary nomadic settlement": 4}
# Corrections applied on load: name in file -> (correct name, lon, lat)
CAPITAL_FIXES = {"Baki": ("Borama", 43.1828, 9.9361)}   # Awdal capital
# Label nudges (degrees) where a capital label would collide with something
CAPITAL_LABEL_OFFSETS = {"Borama": (-0.09, 0.0)}   # default is just right of the point

ADMIN1_NAME_COL = "adm1_name"
NEIGHBOUR_NAME_COL = "CNTRY_NAME"

# NOMADS GRIB filter
NOMADS_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
FORECAST_HOURS = [24, 48, 72, 96, 120, 144, 168]
SUBREGION = dict(leftlon=35, rightlon=53, toplat=16, bottomlat=-6)

# Map extent: bounds of Somalia and the catchments plus a margin (degrees)
GRID_STEP = 0.02      # display grid; finer than 0.05 for smooth class edges on large screens
HD_GRID_STEP = 0.008  # high detail overlays for the app when zoomed in
EXTENT_MARGIN = 0.35

# Rainfall classes (mm). The last class is open ended.
# SWALIM 7 day forecast legend (standard ArcGIS colours), plus an open ended
# "Above 250" class in ArcGIS magenta so extreme totals stand out from 200 - 250.
CLASS_BOUNDS = [0, 2, 5, 10, 20, 30, 40, 50, 100, 150, 200, 250]
CLASS_COLOURS = ["#FFFFFF", "#FFEBBE", "#A3FF73", "#267300", "#BEE8FF", "#00C5FF",
                 "#73B2FF", "#004DA8", "#4C0073", "#E64C00", "#730000", "#FF00C5"]
CLASS_LABELS = ["0 - 2", "2 - 5", "5 - 10", "10 - 20", "20 - 30", "30 - 40",
                "40 - 50", "50 - 100", "100 - 150", "150 - 200", "200 - 250", "Above 250"]

# Weather layers for the app (weather.py, export.export_weather): daily value per layer, map classes
# (the last class open ended) and labels. Palettes from ColorBrewer (RdYlBu, PuBu, BrBG), readable
# with colour blindness. "week" is how the week button combines the days (max or mean).
WEATHER_LAYERS = {
    "temperature": {
        "field": "tmax", "unit": "°C", "week": "max",
        "title": "Highest temperature", "title_so": "Heerkulka ugu sarreeya",
        "bounds": [0, 20, 25, 30, 33, 36, 39, 42, 45],
        "colours": ["#4575B4", "#74ADD1", "#ABD9E9", "#FFFFBF", "#FEE090", "#FDAE61", "#F46D43", "#D73027", "#A50026"],
        "labels": ["Below 20", "20 - 25", "25 - 30", "30 - 33", "33 - 36", "36 - 39", "39 - 42", "42 - 45", "Above 45"],
    },
    "wind": {
        "field": "wind", "unit": "km/h", "week": "max",
        "title": "Strongest wind", "title_so": "Dabaysha ugu xooggan",
        "bounds": [0, 10, 20, 30, 40, 50, 60, 80],
        "colours": ["#F1EEF6", "#D0D1E6", "#A6BDDB", "#74A9CF", "#3690C0", "#0570B0", "#045A8D", "#023858"],
        "labels": ["Below 10", "10 - 20", "20 - 30", "30 - 40", "40 - 50", "50 - 60", "60 - 80", "Above 80"],
    },
    "humidity": {
        "field": "rh", "unit": "%", "week": "mean",
        "title": "Humidity (day average)", "title_so": "Huurka (celcelis maalinle)",
        "bounds": [0, 20, 30, 40, 50, 60, 70, 80, 90],
        "colours": ["#8C510A", "#BF812D", "#DFC27D", "#F6E8C3", "#C7EAE5", "#80CDC1", "#35978F", "#01665E", "#003C30"],
        "labels": ["Below 20", "20 - 30", "30 - 40", "40 - 50", "50 - 60", "60 - 70", "70 - 80", "80 - 90", "Above 90"],
    },
}
# Heat index ("feels like", °C) levels from the NOAA heat index chart
HEAT_LEVELS = [(27, "Caution", "Digtoonow"), (32, "Extreme caution", "Aad u digtoonow"),
               (41, "Danger", "Khatar"), (54, "Extreme danger", "Khatar weyn")]
HOT_TMAX_C = 40.0          # ensemble chance of a day this hot (GEFS)
STRONG_GUST_KMH = 50.0     # ensemble chance of gusts this strong (GEFS)
WEEK2_DAYS = 7             # rainfall days 8 to 14 from the same GFS run

# Flash floods (flashflood.py). Susceptibility per sub-basin: slope classes (degrees), plus one for
# wadis with a large upstream area; sub-basins on the main rivers (larger upstream area) are left out.
FLASH_SLOPE_MID, FLASH_SLOPE_STEEP = 1.0, 3.0
FLASH_WADI_KM2, FLASH_RIVER_KM2 = 500.0, 50000.0
FLASH_THRESHOLD_MM = [50.0, 40.0, 30.0]   # daily rain for Watch at susceptibility 1, 2, 3 (High: 1.5 ×)
FLASH_3H_MM = 30.0                        # 3 hour rain that alone gives High
FLASH_WET_SOIL = 0.25                     # 0–10 cm soil water (m³/m³) counted as wet
FLASH_WET_BONUS_MM = 10.0                 # wet soil lowers the threshold by this much
FLASH_PLACES_MAX = 40                     # towns and IDP camps listed at most per day
FLASH_HIGH_MIN_CHANCE = 20.0             # % of GEFS runs with 30 mm or more that day, needed for High

# Plain language rain categories: (label, lower limit inclusive, upper limit exclusive).
# They group the legend classes (limits fall on CLASS_BOUNDS) and have no colours of their own.
# Used by the app (tap card, My place, share text) and the alert wording.
DAILY_CATEGORIES = [            # mm per day
    ("Dry", 0, 2),
    ("Light", 2, 10),
    ("Moderate", 10, 30),
    ("Heavy", 30, 50),
    ("Very heavy", 50, None),
]
WEEKLY_CATEGORIES = [           # mm per week (7 day total)
    ("Negligible", 0, 5),
    ("Light", 5, 20),
    ("Moderate", 20, 50),
    ("Heavy", 50, 100),
    ("Very heavy", 100, 200),
    ("Extreme", 200, None),
]


# Somali names of the categories, in the same order (approved by TerraTech, October 2026)
DAILY_CATEGORIES_SO = ["Qalalan", "Kab-lakac", "Calaacal", "Dhudhun", "Gacan"]
WEEKLY_CATEGORIES_SO = ["Kab-lakac", "Calaacal", "Xidid dool", "Dhudhun", "Gacan", "Gaari-waa"]


def category(mm: float, scheme=DAILY_CATEGORIES, so: bool = False) -> str:
    """Plain language label for a rainfall amount, e.g. category(35) -> 'Heavy' ('Dhudhun' with so)."""
    names = ((DAILY_CATEGORIES_SO if scheme is DAILY_CATEGORIES else WEEKLY_CATEGORIES_SO) if so
             else [n for n, _lo, _hi in scheme])
    label = names[0]
    for name, (_n, lo, _hi) in zip(names, scheme):
        if mm >= lo:
            label = name
    return label

# Map styling
OCEAN_COLOUR = "#E3F1FB"
SEA_LABEL_COLOUR = "#2C6A9A"
# Coastal shading in the SWALIM style: blue strongest at the shore, fading out to sea
COAST_GLOW_COLOUR = "#7FB3DE"
COAST_GLOW_STEPS = [0.03, 0.06, 0.1, 0.15, 0.21, 0.28, 0.36]   # ring widths, degrees
COAST_GLOW_ALPHA = 0.11      # per ring; rings overlap, so the shore gets the sum
COAST_LINE_COLOUR = "#5E8FBF"
SEA_LABELS = [("INDIAN OCEAN", (49.4, 1.6), 14), ("GULF OF ADEN", (46.4, 11.95), 10.5)]
NEIGHBOUR_FILL = "#E6E6E6"
NEIGHBOUR_EDGE = "#9A9A9A"
NEIGHBOUR_LABEL_COLOUR = "#9C3D12"
CATCHMENT_COLOUR = "#6B4F3A"   # muted earth brown, dashed, drawn upstream of Somalia only
CATCHMENT_LABELS = {"Juba": "JUBA BASIN", "Shabelle": "SHABELLE BASIN"}
RIVER_COLOUR = "#1F6FD1"
FADED_ALPHA = 1.0     # rain over neighbouring countries at full colour (under 2 mm left clear)
SEA_ALPHA = 0.45       # rain over the sea, strong enough to follow rain coming in from the sea
CATCHMENT_ALPHA = 0.0   # extra layer over the faded one in catchments outside Somalia (0 = same as elsewhere)

# Branding
LOGO = "assets/terratech_logo.png"
BANNER_COLOURS = ["#0B2545", "#134074", "#1B6CA8"]   # title banner gradient, left to right
ACCENT_COLOUR = "#E08B5F"                            # logo orange stripe under the banner
DATE_BADGE_COLOUR = "#FFD400"   # changing date: navy text on a yellow badge, readable on phones
DATE_TEXT_COLOUR = "#0B2545"
WATERMARK_COLOUR = "#1A1A1A"   # centre watermark silhouette (white suits dark maps only)
WATERMARK = False     # centre logo watermark switched off
WATERMARK_ALPHA = 0.12
WATERMARK_WIDTH = 0.6          # fraction of map width

DISCLAIMER = ("Disclaimer: The boundaries and names shown on this map\n"
              "do not imply official recognition or endorsement\n"
              "by TerraTech Solutions.")

EAT_OFFSET_HOURS = 3

# Published site for the app and web dashboard (built by `python -m somalia_rain_animation.publish`)
SITE_DIR = PROJECT_DIR / "site"
MANIFEST_KEEP = 14            # runs kept online; older run folders are removed

# Push alerts (Firebase Cloud Messaging topics). A region alert fires when its area mean
# forecast reaches either threshold; each region, day and week is alerted once.
ALERT_DAILY_MM = 30.0         # area mean rainfall in one day ("Heavy" in DAILY_CATEGORIES)
ALERT_WEEKLY_MM = 75.0        # area mean rainfall over the 7 days
ALERT_BASIN_WEEKLY_MM = 50.0  # upstream Juba or Shabelle basin mean over the 7 days (topics basin_juba, basin_shabelle)
FCM_ENV = "FCM_SERVICE_ACCOUNT"   # env var holding the service account JSON (GitHub secret)
FCM_CHANNEL = "forecast_alerts"   # Android notification channel created by the app
FCM_TEST_TOPIC = "test"           # test notifications only reach phones with 'Test alerts' on


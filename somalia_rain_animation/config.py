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
EXTENT_MARGIN = 0.35

# Rainfall classes (mm). The last class is open ended.
# SWALIM 7 day forecast legend (standard ArcGIS colours), plus an open ended
# "Above 250" class in ArcGIS magenta so extreme totals stand out from 200 - 250.
CLASS_BOUNDS = [0, 2, 5, 10, 20, 30, 40, 50, 100, 150, 200, 250]
CLASS_COLOURS = ["#FFFFFF", "#FFEBBE", "#A3FF73", "#267300", "#BEE8FF", "#00C5FF",
                 "#73B2FF", "#004DA8", "#4C0073", "#E64C00", "#730000", "#FF00C5"]
CLASS_LABELS = ["0 - 2", "2 - 5", "5 - 10", "10 - 20", "20 - 30", "30 - 40",
                "40 - 50", "50 - 100", "100 - 150", "150 - 200", "200 - 250", "Above 250"]

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
ALERT_DAILY_MM = 25.0         # area mean rainfall in one day
ALERT_WEEKLY_MM = 75.0        # area mean rainfall over the 7 days
ALERT_BASIN_WEEKLY_MM = 50.0  # upstream Juba or Shabelle basin mean over the 7 days (topics basin_juba, basin_shabelle)
FCM_ENV = "FCM_SERVICE_ACCOUNT"   # env var holding the service account JSON (GitHub secret)


# Progress: Sahan weekly rainfall forecast

Last updated: 8 October 2026.

## Done

1. **Forecast maps and video** (`somalia_rain_animation`): GFS 7 day rainfall in the SWALIM style, daily
   frames plus weekly total, GIF, MP4 and an autoplaying player page.
2. **Publisher and app data** (`python -m somalia_rain_animation.publish`): overlays (standard and `_hd`),
   tap values, `summary.json` with Somalia, regions, **districts** (since 7 October) and basins, static
   layers, `style.json`, manifest.
3. **Automation**: GitHub repository `mohamedgees/Sahan_weekly_forecast` (public). Workflow
   *Rainfall forecast* deploys to https://mohamedgees.github.io/Sahan_weekly_forecast/. Manual run
   options: run date, start date, force rebuild, send a test notification.
   **Open problem:** GitHub has not started any scheduled run (crons 05:17, 06:47, 09:17 UTC) since the
   repository was created; all runs so far were started by hand. Fix planned: an outside daily trigger
   (cron-job.org calling the workflow dispatch API with a fine-grained token), see Next steps.
4. **Android app "Sahan Rainfall"** (Flutter) in `C:\dev\somalia_rain_app`, private repository
   `mohamedgees/Sahan_rainfall_app`. Current version **1.6.0 (build 10)**, named **Sahan** (store title "Sahan: Somalia Rain Forecast"; header "Somalia 7 Day Rainfall Forecast" / "Saadaasha Roobka 7da Maalmood"); icon: Somali rain drop (single-hump camel, herder with shoulder stick, qurac), concepts in `Desktop\Sahan App Release\Icon concepts\` (chosen: somali-8):
   - Somali by default with English (lib/i18n.dart; short Somali on screen, full text on hold or (i));
     language button (SOM / ENG with flags) in the blue headers. User's wording: "Goob" for any place;
     rain names daily Qalalan, Kab-lakac, Calaacal, Dhudhun, Gacan; weekly Kab-lakac, Calaacal,
     Xidid dool, Dhudhun, Gacan, Gaari-waa; Summary tab is "War bixin".
   - Map: day buttons, play, tap card, search, zoom, Goobtayda, legend with category brackets, share
     (no site link in the text).
   - War bixin: highlights, Juba and Shabelle catchment cards, regions as heat strips that open to their
     districts with map pins, pinned day header, Wettest / A–Z.
   - Alerts in the app language (Somali on `so_` topics); app guide (14 step spotlight tour, replay
     from About); Crashlytics.
5. **Push alerts**: Firebase project *Sahan Rainfall* (Spark, free). Secret `FCM_SERVICE_ACCOUNT` in the
   forecast repository. Topics `new_forecast`, `basin_juba`, `basin_shabelle`, `heavy_rain_<pcode>`,
   `test`, and the same with an `so_` prefix for Somali.
6. **Releases**: signed APKs in `Desktop\Sahan App Release\` (1.0.0 to 1.5.0 as Sahan-Rainfall-<v>.apk, from 1.6.0 as Sahan-<v>.apk), shared by WhatsApp;
   all signed with `C:\dev\keys\sahan-release.jks` (passwords in `android\key.properties`; both kept out
   of git; **back them up**). Release builds are ARM only (phones); for the x86_64 emulator build a
   debug `--target-platform android-x64`. The in-app update notice (`web/app_version.json`) is still at
   1.0.0 because no public release link exists yet.

## Tools on this computer

- Python environment: `~/micromamba/micromamba.exe run -r ~/micromamba/root -n somrain ...`.
- Flutter 3.47.6 in `C:\dev\flutter`; Android SDK in `C:\Users\mmask\AppData\Local\Android\Sdk`.
- Emulator: `emulator -avd Medium_Phone_API_37.0 -gpu swiftshader_indirect -scale 0.8` (software
  graphics: the default gives a black window on this PC).
- New release: raise `version` in pubspec.yaml, `flutter build apk --release --target-platform
  android-arm,android-arm64`, copy to `Desktop\Sahan App Release\Sahan-Rainfall-<version>.apk`.

## Next steps (when ready)

1. Daily trigger outside GitHub (cron-job.org + fine-grained token with Actions read and write on
   Sahan_weekly_forecast), so the forecast publishes every morning.
2. Public release link and in-app update notice (GitHub release on the public repo, then
   `web/app_version.json`).
3. Google Play later: developer account (one-off US$25), privacy policy page, store listing, and for a
   new personal account a 14-day closed test with at least 12 testers.

## Notes

- Crashlytics, 7 October: the two map LateInitializationError crashes (1.4.0) are fixed in 1.4.1. The
  `SystemLibraryLoader` crash on 1.1.1 came from installing the ARM release on the x86_64 emulator
  during testing, not from users.
- Plan file: `C:\Users\mmask\.claude\plans\i-am-thinking-of-immutable-pizza.md`.

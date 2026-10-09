# Progress: Sahan weekly rainfall forecast

Last updated: 9 October 2026.

## Done

1. **Forecast maps and video** (`somalia_rain_animation`): GFS 7 day rainfall in the SWALIM style, daily
   frames plus weekly total, GIF, MP4 and an autoplaying player page.
2. **Publisher and app data** (`python -m somalia_rain_animation.publish`): overlays (standard and `_hd`),
   tap values, `summary.json` with Somalia, regions, **districts** (since 7 October) and basins, static
   layers, `style.json`, manifest.
3. **Automation**: GitHub repository `mohamedgees/Sahan_weekly_forecast` (public). Workflow
   *Rainfall forecast* deploys to https://mohamedgees.github.io/Sahan_weekly_forecast/. Manual run
   options: run date, start date, force rebuild, send a test notification.
   **Daily start:** GitHub's own schedule does run, but about 6½ hours late (05:17 UTC starts near 11:50).
   Since 9 October an outside trigger starts it on time: cron-job.org job "Sahan forecast 08:45"
   (Africa/Nairobi) calls the workflow dispatch API with a fine-grained token (Actions read and write on
   this repository only). **The token expires on 30 December 2026: renew it and update the job's
   Authorization header before then.** The GitHub crons stay as backups (a run that finds the forecast
   published stops in about a minute).
   Since 9 October the publisher also writes `static/settlements.json` (10,206 named places with district
   and IDP flag) and `week_max_at` in summary.json, and alerts are one message per area per week with
   the highest point near a named place, districts most affected, chance and advice (Somali approved).
4. **Android app "Sahan Rainfall"** (Flutter) in `C:\dev\somalia_rain_app`, private repository
   `mohamedgees/Sahan_rainfall_app`. Current version **1.8.0 (build 17)**, named **Sahan** (store title "Sahan: Somalia Rain Forecast"; header "Somalia 7 Day Rainfall Forecast" / "Saadaasha Roobka 7da Maalmood"); icon: Somali rain drop (single-hump camel, herder with shoulder stick, qurac), concepts in `Desktop\Sahan App Release\Icon concepts\` (chosen: somali-8):
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
   - Since 1.8.0: tap card "Near <village>" / "<n> km from" with district and region; village, town and
     IDP camp names on the map by zoom (one name per town); highest point per region in War bixin;
     Alerts tab with This week (rivers, regions and districts under alert), My place alerts by district,
     received alerts as cards in the app language, region chips.
5. **Push alerts**: Firebase project *Sahan Rainfall* (Spark, free). Secret `FCM_SERVICE_ACCOUNT` in the
   forecast repository. Topics `new_forecast`, `basin_juba`, `basin_shabelle`, `heavy_rain_<pcode>`,
   `test`, district topics `heavy_rain_<district pcode>` (My place, since 1.8.0), and the same with an
   `so_` prefix for Somali.
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

Launch plan agreed on 9 October (both repositories private, data on Cloudflare Pages at an own domain,
Google Play as an organisation account):
1. Back up the signing key (password manager + offline USB; SHA-256 of sahan-release.jks
   56ca2c34f306718435463e46c8cfdf3d14feedfd883da963134cb458f49ab5aa). Start the D-U-N-S request and
   the Play organisation account.
2. Hosting: publish to Cloudflare Pages at the own domain as well as github.io; app 1.9.0 reads the own
   domain (github.io as fallback), downloads static layers only when changed, builds an AAB; do not use
   `PUBLIC_RELEASE_TOKEN` in release.yml; stale forecast check; backup of `sent_alerts.json`.
3. Play: privacy policy page (coarse location on the phone, Crashlytics, notifications), data safety,
   rating, Somali and English listing; internal, closed, then staged production rollout.
4. After most users have the Play version: make the forecast repository private, stop github.io.

## Notes

- Crashlytics, 7 October: the two map LateInitializationError crashes (1.4.0) are fixed in 1.4.1. The
  `SystemLibraryLoader` crash on 1.1.1 came from installing the ARM release on the x86_64 emulator
  during testing, not from users.
- Plan file: `C:\Users\mmask\.claude\plans\i-am-thinking-of-immutable-pizza.md`.

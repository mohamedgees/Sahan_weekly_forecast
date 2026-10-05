# Progress: Sahan weekly rainfall forecast

Last updated: 5 October 2026.

## Done

1. **Forecast maps and video** (`somalia_rain_animation`): GFS 7 day rainfall in the SWALIM style, daily
   frames plus weekly total, GIF, MP4 and an autoplaying player page.
2. **Publisher and app data** (`python -m somalia_rain_animation.publish`): overlays, tap values,
   region and basin summaries, static layers, `style.json`, manifest, push alerts (dry run until Firebase).
3. **Automation**: GitHub repository `mohamedgees/Sahan_weekly_forecast` (public). The workflow
   *Rainfall forecast* runs daily at 05:30 UTC and deploys to
   https://mohamedgees.github.io/Sahan_weekly_forecast/ (web dashboard). First run succeeded 5 October.
4. **Android app** "Sahan Rainfall" in `C:\dev\somalia_rain_app` (Flutter, local git only):
   map with day chips and play, tap for rainfall, Summary and About tabs, offline cache.
   Tested on the emulator *Medium_Phone_API_37.0*.

## Tools on this computer

- Python environment: `micromamba run -n somrain ...` (see README).
- Flutter 3.47.6 in `C:\dev\flutter` (on the user PATH); Android Studio; Android SDK with
  NDK 28.2.13676358 in `C:\Users\mmask\AppData\Local\Android\Sdk`.
- Run the app: start the emulator from Android Studio (Device Manager) or
  `emulator -avd Medium_Phone_API_37.0`, then in `C:\dev\somalia_rain_app`: `flutter run`.

## Next steps

1. **Where the app code lives on GitHub**: an `app/` folder in this repository, or a separate private
   repository (decision pending).
2. **Push alerts (plan step 5)**: create a Firebase project; add `google-services.json` to the app and the
   service account JSON as the GitHub secret `FCM_SERVICE_ACCOUNT`; add an Alerts screen with topic
   subscriptions (`new_forecast`, `heavy_rain_<pcode>`, `basin_juba`, `basin_shabelle`).
3. **Release build (plan step 6)**: TerraTech app icon and splash screen, signing key, release APK / AAB;
   choose Play Store or direct APK download.

## Notes

- Neighbour and basin label positions reach the live site on the next workflow run.
- The full plan: `C:\Users\mmask\.claude\plans\i-am-thinking-of-immutable-pizza.md`.

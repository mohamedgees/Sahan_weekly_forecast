# Progress: Sahan weekly rainfall forecast

Last updated: 5 October 2026.

## Done

1. **Forecast maps and video** (`somalia_rain_animation`): GFS 7 day rainfall in the SWALIM style, daily
   frames plus weekly total, GIF, MP4 and an autoplaying player page.
2. **Publisher and app data** (`python -m somalia_rain_animation.publish`): overlays, tap values,
   region and basin summaries, static layers, `style.json`, manifest.
3. **Automation**: GitHub repository `mohamedgees/Sahan_weekly_forecast` (public). The workflow
   *Rainfall forecast* runs daily at 05:30 UTC and deploys to
   https://mohamedgees.github.io/Sahan_weekly_forecast/ (web dashboard). Manual run options: run date,
   start date, force rebuild, send a test notification.
4. **Android app "Sahan Rainfall"** (Flutter) in `C:\dev\somalia_rain_app`, code in the **private**
   repository `mohamedgees/Sahan_rainfall_app`: map with day buttons and play, tap for rainfall,
   Summary, Alerts and About tabs, offline cache, Sahan logo, icon and splash.
5. **Push alerts**: Firebase project *Sahan Rainfall* (Spark, free). Secret `FCM_SERVICE_ACCOUNT` in the
   forecast repository. Topics `new_forecast`, `basin_juba`, `basin_shabelle`, `heavy_rain_<pcode>`, `test`.
   Tested end to end on 5 October.
6. **Release 1.0.0**: signed APK `Desktop\Sahan App Release\Sahan-Rainfall-1.0.0.apk` (32.6 MB, phones),
   shared directly. Signing key `C:\dev\keys\sahan-release.jks`, passwords in
   `C:\dev\somalia_rain_app\android\key.properties` (both kept out of git; **back them up**).

## Tools on this computer

- Python environment: `micromamba run -n somrain ...` (see README).
- Flutter 3.47.6 in `C:\dev\flutter` (on the user PATH); Android Studio; Android SDK with
  NDK 28.2.13676358 in `C:\Users\mmask\AppData\Local\Android\Sdk`.
- Run the app: start the emulator from Android Studio (Device Manager) or
  `emulator -avd Medium_Phone_API_37.0`, then in `C:\dev\somalia_rain_app`: `flutter run`.
- New release: see the app README (raise the version, build for phones, rename the APK).

## Next steps (when ready)

1. Share the APK with staff and partners; collect feedback.
2. Optional: a public download page for the APK (for example on tetso.net or the forecast site).
3. Google Play later: developer account (one-off US$25), privacy policy page, store listing, and for a
   new personal account a 14-day closed test with at least 12 testers.

## Notes

- The full plan: `C:\Users\mmask\.claude\plans\i-am-thinking-of-immutable-pizza.md`.

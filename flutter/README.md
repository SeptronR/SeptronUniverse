# SeptronUniverse mobile app (Flutter)

Android + iOS app for every role shell (Prompts/42). The repository holds `lib/`, `tool/`, `assets/` and the
release configuration; the platform folders are generated on the build machine.

## First build

```bash
cd flutter
flutter create . --org com.septronr --project-name septron_universe --platforms=android,ios   # generates android/ ios/ once
flutter pub get
flutter run --dart-define=APP_API_URL=http://10.0.2.2:8000/api/v1 --dart-define=APP_ENV=development
```

`--dart-define`s: `APP_API_URL`, `APP_WS_URL`, `APP_ENV`, `APP_VERSION` (compared with `/mobile/config` min versions),
`APP_SENTRY_DSN` (crash reporting off when empty), `PIN_SHA256` (optional certificate pinning).
Push needs `android/app/google-services.json` / `ios/Runner/GoogleService-Info.plist`; without them push is skipped.

## Native hooks (add after `flutter create`)

* **SafeScreen** — channel `septron/secure_screen` (`enable` / `disable`). Android `MainActivity.kt`:
  ```kotlin
  MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "septron/secure_screen").setMethodCallHandler { call, result ->
      when (call.method) {
          "enable" -> window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
          "disable" -> window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
      }
      result.success(null)
  }
  ```
  iOS `AppDelegate.swift`: on `enable` add a hidden secure `UITextField` layer over the window (capture shows black).
* **App Links / Universal Links** — Android intent filter `https://<host>/verify/*`, `/apply/*` with
  `android:autoVerify="true"`; iOS associated domain `applinks:<host>`. The server serves
  `/.well-known/assetlinks.json` and `apple-app-site-association` from `platform_settings['mobile.app_ids']`.
* **Permissions** — camera (scanner, evidence), location (geo attendance, driver GPS), Bluetooth (thermal printer),
  notifications, biometrics (`NSFaceIDUsageDescription`), photo library. iOS `PrivacyInfo.xcprivacy` declares
  `NSPrivacyAccessedAPICategoryUserDefaults` and file timestamp APIs; Play data-safety: no data sold, crash logs
  without PII, location only while a trip is active.

## Structure

* `lib/core` — network (dio envelope / tenant headers / refresh / Idempotency-Key / retry / READ_ONLY), auth
  (+ biometric gate, sessions), router (`role_shells.dart` per-role tabs, `screen_registry.dart`, deep links),
  offline (`cache_repository.dart` SQLite cache with TTL + stale, `write_queue_repository.dart`, `sync_service.dart`,
  `queue_targets.dart`), remote config (force update / maintenance / `mobile.app`), notifications (FCM channels,
  deep links, topics), payments (Razorpay + UPI intent), print (ESC/POS 58 / 80 mm), scan (QR / barcode), analytics.
* `lib/shared/widgets` — catalogue: `SegmentedScope`, `OfflineBanner` / `SyncStatusSheet` / `StaleBadge`,
  `SafeScreen`, `ApprovalCard`, `AttendanceGrid`, `QRCodeCard`, `MasterDetail`, empty / error / skeleton states,
  `confirmAction`, `FeatureHint`.
* `lib/features/<module>` — screens per phase (NN.10 sections).

## Structural checks (CI)

```bash
flutter analyze
dart format --set-exit-if-changed lib tool
dart run tool/check_l10n.dart --strings
dart run tool/check_screen_registry.dart        # vs tool/expected_screens.json (backend/scripts/extract_mobile_screens.py)
dart run tool/check_portal_parity.dart          # vs /portal/config snapshots saved by scripts/verify/42_mobile.ps1
python ../backend/scripts/check_tokens_sync.py  # web ↔ app theme tokens (npm run tokens:export)
flutter build appbundle && flutter build ipa --no-codesign
```

## Release

`fastlane android beta|release|promote rollout:0.5`, `fastlane ios beta|release`, or the Codemagic workflows in
`codemagic.yaml`. Staged rollout 10 % → 50 % → 100 %; promote only while crash-free sessions ≥ 99.5 %.

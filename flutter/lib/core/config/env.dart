/// Build-time configuration via --dart-define (docs/Mobile_App_UI_Structure.md §1).
///
///   flutter run --dart-define=APP_API_URL=http://10.0.2.2:8000/api/v1 --dart-define=APP_ENV=development
class Env {
  Env._();

  static const String apiUrl = String.fromEnvironment(
    'APP_API_URL',
    defaultValue: 'http://localhost:8000/api/v1',
  );
  static const String wsUrl = String.fromEnvironment(
    'APP_WS_URL',
    defaultValue: 'ws://localhost:8000/ws',
  );
  static const String mapTileUrl = String.fromEnvironment(
    'APP_MAP_TILE_URL',
    defaultValue: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  );
  static const String env =
      String.fromEnvironment('APP_ENV', defaultValue: 'development');
  static const String sentryDsn =
      String.fromEnvironment('APP_SENTRY_DSN', defaultValue: '');
  static const String pinSha256 =
      String.fromEnvironment('PIN_SHA256', defaultValue: '');

  static bool get isProduction => env == 'production';
}

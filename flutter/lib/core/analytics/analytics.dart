import 'package:flutter/widgets.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import '../config/env.dart';

/// Crash reporting + screen / event breadcrumbs (Prompts/42 §42.6 `analytics/`). Sentry only when `APP_SENTRY_DSN`
/// is set; never sends PII (no user names, phone numbers or IDs beyond the opaque user id).
class Analytics {
  Analytics._();

  static bool get enabled => Env.sentryDsn.isNotEmpty;

  static Future<void> run(Widget app, void Function(Widget) runner) async {
    if (!enabled) return runner(app);
    await SentryFlutter.init(
      (o) {
        o.dsn = Env.sentryDsn;
        o.environment = Env.env;
        o.sendDefaultPii = false;
        o.tracesSampleRate = Env.isProduction ? 0.1 : 1.0;
      },
      appRunner: () => runner(app),
    );
  }

  static void screen(String route) {
    if (enabled) Sentry.addBreadcrumb(Breadcrumb(category: 'navigation', message: route));
  }

  static void event(String name, [Map<String, Object?> props = const {}]) {
    if (enabled) Sentry.addBreadcrumb(Breadcrumb(category: 'event', message: name, data: props));
  }

  static void error(Object e, [StackTrace? st]) {
    if (enabled) Sentry.captureException(e, stackTrace: st);
  }

  static NavigatorObserver observer() => SentryNavigatorObserver();
}

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';
import 'core/analytics/analytics.dart';
import 'core/notifications/push_service.dart';

/// Entry point (Prompts/42 §42.6 bootstrap): date formatting → FCM background handler + [PushService.init]
/// (no-op without Firebase config) → Sentry (when a DSN is defined) → ProviderScope. Remote config, `/auth/me`
/// and the router are loaded by [UniverseApp].
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('en_IN');
  FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
  await PushService.instance.init();
  await Analytics.run(const ProviderScope(child: UniverseApp()), runApp);
}

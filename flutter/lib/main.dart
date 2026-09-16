import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';

/// Entry point (docs/Mobile_App_UI_Structure.md §1): ProviderScope, date formatting; Phase 42 adds
/// PushService.init and RemoteConfig.load before runApp.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('en_IN');
  runApp(const ProviderScope(child: UniverseApp()));
}

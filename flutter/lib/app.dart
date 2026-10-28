import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/auth/auth_controller.dart';
import 'core/auth/biometric_gate.dart';
import 'core/auth/session.dart';
import 'core/constants.dart';
import 'core/notifications/push_service.dart';
import 'core/remote_config/remote_config.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';
import 'l10n/app_localizations.dart';

/// MaterialApp.router (Prompts/42 §42.6): remote config (force update / maintenance / `mobile.app`), `/auth/me`
/// bootstrap, push deep-link dispatch into the router, biometric gate, theme + locale providers.
class UniverseApp extends ConsumerStatefulWidget {
  const UniverseApp({super.key});

  @override
  ConsumerState<UniverseApp> createState() => _UniverseAppState();
}

class _UniverseAppState extends ConsumerState<UniverseApp> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final slug = ref.read(sessionProvider).institutionSlug;
      await ref.read(remoteConfigProvider.notifier).load(institutionSlug: slug);
      try {
        await ref.read(authControllerProvider).bootstrap();
      } catch (_) {
        // offline cold start: the cached session stays, screens fall back to the cache
      }
    });
    PushService.instance.onNavigate = (link) => ref.read(routerProvider).go(link.location);
  }

  @override
  Widget build(BuildContext context) {
    final router = ref.watch(routerProvider);
    final themeMode = ref.watch(themeModeProvider);
    final locale = ref.watch(localeProvider);
    return MaterialApp.router(
      title: kAppName,
      debugShowCheckedModeBanner: false,
      routerConfig: router,
      themeMode: themeMode,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      locale: locale,
      supportedLocales: AppLocalizations.supportedLocales,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      builder: (context, child) => RemoteConfigGate(child: BiometricGate(child: child ?? const SizedBox.shrink())),
    );
  }
}

final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.system);
final localeProvider = StateProvider<Locale?>((ref) => null);

import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config/env.dart';
import '../offline/write_queue_repository.dart';
import '../providers.dart';

/// `GET /mobile/config` (Prompts/42 §42.6 bootstrap): min versions / force update, maintenance banner, read-only
/// flag, feature hints, cache TTL, write-queue limits, biometric timeout, screenshot-blocked routes, `mobile.app`.
class RemoteConfig {
  const RemoteConfig({
    this.forceUpdate = false,
    this.updateAvailable = false,
    this.storeUrl,
    this.maintenanceBanner,
    this.readOnly = false,
    this.featureHints = const {},
    this.cacheTtl = const Duration(minutes: 5),
    this.writeQueue = const {},
    this.biometricTimeout = const Duration(minutes: 5),
    this.screenshotBlockRoutes = const ['marks', 'valuation', 'pii'],
    this.mobileEnabled = true,
    this.loaded = false,
  });

  factory RemoteConfig.fromJson(Map<String, dynamic> j, String platform) => RemoteConfig(
        forceUpdate: j['force_update'] as bool? ?? false,
        updateAvailable: j['update_available'] as bool? ?? false,
        storeUrl: (j['store_urls'] as Map?)?[platform] as String?,
        maintenanceBanner: j['maintenance_banner'] as String?,
        readOnly: j['read_only'] as bool? ?? false,
        featureHints: ((j['feature_hints'] as Map?) ?? const {}).map((k, v) => MapEntry('$k', '$v')),
        cacheTtl: Duration(seconds: (j['cache_ttl_seconds'] as num?)?.toInt() ?? 300),
        writeQueue: ((j['write_queue'] as Map?) ?? const {}).map((k, v) => MapEntry('$k', (v as num).toInt())),
        biometricTimeout: Duration(minutes: (j['biometric_timeout_minutes'] as num?)?.toInt() ?? 5),
        screenshotBlockRoutes: ((j['screenshot_block_routes'] as List?) ?? const ['marks', 'valuation', 'pii']).cast<String>(),
        mobileEnabled: j['mobile_enabled'] as bool? ?? true,
        loaded: true,
      );

  final bool forceUpdate;
  final bool updateAvailable;
  final String? storeUrl;
  final String? maintenanceBanner;
  final bool readOnly;
  final Map<String, String> featureHints;
  final Duration cacheTtl;
  final Map<String, int> writeQueue;
  final Duration biometricTimeout;
  final List<String> screenshotBlockRoutes;
  final bool mobileEnabled;
  final bool loaded;

  static const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: '1.0.0');
}

class RemoteConfigController extends StateNotifier<RemoteConfig> {
  RemoteConfigController(this._ref) : super(const RemoteConfig());

  final Ref _ref;

  static String get platform => kIsWeb ? 'web' : (Platform.isIOS ? 'ios' : 'android');

  Future<void> load({String? institutionSlug}) async {
    try {
      final res = await Dio(BaseOptions(baseUrl: Env.apiUrl, connectTimeout: const Duration(seconds: 5)))
          .get<Map<String, dynamic>>('/mobile/config', queryParameters: {
        'platform': platform,
        'app_version': RemoteConfig.appVersion,
        if (institutionSlug != null) 'institution_slug': institutionSlug,
      });
      final data = (res.data?['data'] as Map?)?.cast<String, dynamic>();
      if (data == null) return;
      state = RemoteConfig.fromJson(data, platform);
      final q = _ref.read(writeQueueProvider);
      q.maxItems = state.writeQueue['max_items'] ?? q.maxItems;
      q.maxAge = Duration(hours: state.writeQueue['max_age_hours'] ?? q.maxAge.inHours);
    } catch (e) {
      debugPrint('remote config unavailable: $e'); // offline start: keep defaults
    }
  }
}

final remoteConfigProvider =
    StateNotifierProvider<RemoteConfigController, RemoteConfig>((ref) => RemoteConfigController(ref));

/// Read-only from `/mobile/config`, `/platform/read-only` or a `503 READ_ONLY` seen by the dio client.
final readOnlyModeProvider = StateProvider<bool>((ref) => ref.watch(remoteConfigProvider).readOnly);

/// Wraps the app: blocking force-update screen, "mobile not enabled" screen, maintenance banner.
class RemoteConfigGate extends ConsumerWidget {
  const RemoteConfigGate({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cfg = ref.watch(remoteConfigProvider);
    if (cfg.forceUpdate) {
      return _Blocking(
        icon: Icons.system_update,
        title: 'Update required',
        body: 'This version is no longer supported. Please update the app to continue.',
        action: cfg.storeUrl == null
            ? null
            : FilledButton(
                onPressed: () => launchUrl(Uri.parse(cfg.storeUrl!), mode: LaunchMode.externalApplication),
                child: const Text('Update'),
              ),
      );
    }
    if (!cfg.mobileEnabled) {
      return const _Blocking(
        icon: Icons.phonelink_lock,
        title: 'Mobile access not enabled',
        body: 'Your institution has not enabled the mobile app. Please use the web portal.',
      );
    }
    final banner = cfg.maintenanceBanner;
    if (banner == null && !cfg.updateAvailable) return child;
    return Column(children: [
      if (banner != null)
        MaterialBanner(content: Text(banner), leading: const Icon(Icons.construction), actions: const [SizedBox.shrink()]),
      if (cfg.updateAvailable && cfg.storeUrl != null)
        MaterialBanner(
          content: const Text('A new version is available'),
          actions: [
            TextButton(
              onPressed: () => launchUrl(Uri.parse(cfg.storeUrl!), mode: LaunchMode.externalApplication),
              child: const Text('Update'),
            ),
          ],
        ),
      Expanded(child: child),
    ]);
  }
}

class _Blocking extends StatelessWidget {
  const _Blocking({required this.icon, required this.title, required this.body, this.action});

  final IconData icon;
  final String title;
  final String body;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Icon(icon, size: 64),
                const SizedBox(height: 16),
                Text(title, style: Theme.of(context).textTheme.headlineSmall, textAlign: TextAlign.center),
                const SizedBox(height: 8),
                Text(body, textAlign: TextAlign.center),
                if (action != null) ...[const SizedBox(height: 24), action!],
              ]),
            ),
          ),
        ),
      );
}

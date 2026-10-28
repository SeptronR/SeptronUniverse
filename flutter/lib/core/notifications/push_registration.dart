import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_state.dart';
import '../providers.dart';

/// Registers the FCM token with `POST /devices` after sign-in (Prompts/04 §04.10). Firebase is optional in
/// development builds: without an initialised Firebase app (no google-services config) registration is skipped.
class PushRegistration {
  PushRegistration(this._ref);

  final Ref _ref;

  /// Topics from the principal (Prompts/42 §42.6): `role:<slug>`, `institution:<id>`, scopes (`college:<id>`, …).
  List<String> topics() {
    final auth = _ref.read(authStateProvider);
    return {
      for (final r in auth.roles) 'role:$r',
      if (auth.institutionId != null) 'institution:${auth.institutionId}',
      for (final s in auth.scopes)
        if (s.scopeId != null && const {'college', 'department', 'batch', 'hostel'}.contains(s.scopeType)) '${s.scopeType}:${s.scopeId}',
    }.toList();
  }

  Future<void> register() async {
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null) return;
      _token = token;
      await _ref.read(dioProvider).post<Map<String, dynamic>>(
            '/devices',
            data: {
              'provider': 'fcm',
              'platform': !kIsWeb && Platform.isIOS ? 'ios' : 'android',
              'token': token,
              'topics': topics(),
            },
            options: Options(extra: {'idempotent': false}),
          );
      FirebaseMessaging.instance.onTokenRefresh.listen((t) => _ref.read(dioProvider).post<Map<String, dynamic>>(
            '/devices',
            data: {'provider': 'fcm', 'platform': !kIsWeb && Platform.isIOS ? 'ios' : 'android', 'token': t, 'topics': topics()},
            options: Options(extra: {'idempotent': false}),
          ));
    } catch (e) {
      debugPrint('push registration skipped: $e');
    }
  }

  String? _token;

  /// Logout: `DELETE /devices?provider=fcm&token=…` so the server stops pushing to this device.
  Future<void> unregister() async {
    final t = _token;
    if (t == null) return;
    try {
      await _ref.read(dioProvider).delete<void>('/devices', queryParameters: {'provider': 'fcm', 'token': t});
    } catch (_) {}
    _token = null;
  }
}

final pushRegistrationProvider = Provider<PushRegistration>((ref) => PushRegistration(ref));

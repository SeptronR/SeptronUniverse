import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';

/// Registers the FCM token with `POST /devices` after sign-in (Prompts/04 §04.10). Firebase is optional in
/// development builds: without an initialised Firebase app (no google-services config) registration is skipped.
class PushRegistration {
  PushRegistration(this._ref);

  final Ref _ref;

  Future<void> register() async {
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null) return;
      await _ref.read(dioProvider).post<Map<String, dynamic>>(
            '/devices',
            data: {
              'provider': 'fcm',
              'platform': !kIsWeb && Platform.isIOS ? 'ios' : 'android',
              'token': token,
            },
            options: Options(extra: {'idempotent': false}),
          );
      FirebaseMessaging.instance.onTokenRefresh.listen((t) => _ref.read(dioProvider).post<Map<String, dynamic>>(
            '/devices',
            data: {'provider': 'fcm', 'platform': !kIsWeb && Platform.isIOS ? 'ios' : 'android', 'token': t},
            options: Options(extra: {'idempotent': false}),
          ));
    } catch (e) {
      debugPrint('push registration skipped: $e');
    }
  }
}

final pushRegistrationProvider = Provider<PushRegistration>((ref) => PushRegistration(ref));

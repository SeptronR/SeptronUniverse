import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/dio_client.dart';
import '../notifications/push_registration.dart';
import '../offline/cache_repository.dart';
import '../offline/write_queue_repository.dart';
import '../providers.dart';
import 'auth_state.dart';
import 'session.dart';

/// Bootstrap → `/auth/me` → AuthState (then FCM registration with topics); logout → `/auth/logout`, push
/// unregister, cache + write-queue wipe, session clear.
class AuthController {
  AuthController(this._ref);

  final Ref _ref;

  Future<AuthState> bootstrap() async {
    final session = _ref.read(sessionProvider);
    if (!session.isAuthenticated) return const AuthState();
    try {
      final res =
          await _ref.read(dioProvider).get<Map<String, dynamic>>('/auth/me');
      final data = res.data?['data'] as Map<String, dynamic>? ?? const {};
      final state = AuthState.fromMe(data);
      _ref.read(authStateProvider.notifier).state = state;
      await _ref.read(pushRegistrationProvider).register();
      return state;
    } catch (e) {
      throw toApiException(e);
    }
  }

  Future<void> logout() async {
    await _ref.read(pushRegistrationProvider).unregister();
    try {
      await _ref.read(dioProvider).post<void>('/auth/logout');
    } catch (_) {}
    await _ref.read(cacheRepositoryProvider).clear();
    await _ref.read(writeQueueProvider).clear();
    await _ref.read(sessionProvider.notifier).clear();
    _ref.read(authStateProvider.notifier).state = const AuthState();
  }
}

final authControllerProvider =
    Provider<AuthController>((ref) => AuthController(ref));

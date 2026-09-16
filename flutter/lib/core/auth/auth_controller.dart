import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/dio_client.dart';
import '../providers.dart';
import 'auth_state.dart';
import 'session.dart';

/// Bootstrap → `/auth/me` → AuthState; login/OTP/SSO and logout (push unregister, cache clear) land in Phase 42.
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
      return state;
    } catch (e) {
      throw toApiException(e);
    }
  }

  Future<void> logout() async {
    await _ref.read(sessionProvider.notifier).clear();
    _ref.read(authStateProvider.notifier).state = const AuthState();
  }
}

final authControllerProvider =
    Provider<AuthController>((ref) => AuthController(ref));

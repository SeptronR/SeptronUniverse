import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/auth/session.dart';
import '../../core/network/api_exception.dart';
import '../../core/providers.dart';

/// Result of a login attempt: either a principal, or the MFA step the API asked for (Prompts/02 §02.10).
class LoginOutcome {
  const LoginOutcome._(
      {this.state,
      this.mfaRequired = false,
      this.mfaSetupRequired = false,
      this.mfaSetupToken});

  factory LoginOutcome.success(AuthState state) => LoginOutcome._(state: state);

  factory LoginOutcome.mfa({required bool setupRequired, String? setupToken}) =>
      LoginOutcome._(
          mfaRequired: true,
          mfaSetupRequired: setupRequired,
          mfaSetupToken: setupToken);

  final AuthState? state;
  final bool mfaRequired;
  final bool mfaSetupRequired;
  final String? mfaSetupToken;
}

/// Auth API of the mobile app: password / OTP login, MFA enrolment, sessions and the forced password change.
/// The refresh token is stored in secure storage (the app has no cookie jar) and sent in the refresh body.
class AuthRepository {
  AuthRepository(this._ref);

  final Ref _ref;

  Dio get _dio => _ref.read(dioProvider);
  SessionNotifier get _session => _ref.read(sessionProvider.notifier);

  Future<LoginOutcome> login({
    required String identifier,
    required String password,
    String? mfaCode,
    String? institutionSlug,
    String? deviceLabel,
  }) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/auth/login',
        data: {
          'identifier': identifier,
          'password': password,
          if (mfaCode != null && mfaCode.isNotEmpty) 'mfa_code': mfaCode,
          if (institutionSlug != null) 'institution_slug': institutionSlug,
          'platform': 'android',
          if (deviceLabel != null) 'device_label': deviceLabel,
        },
        options: Options(extra: {'idempotent': false}),
      );
      return LoginOutcome.success(
          await _store(res.data?['data'] as Map<String, dynamic>? ?? const {}));
    } on DioException catch (e) {
      final api = ApiException.fromDio(e);
      if (api.code == ApiErrorCode.mfaRequired) {
        final details = api.details;
        return LoginOutcome.mfa(
          setupRequired: details['mfa_setup_required'] == true,
          setupToken: details['mfa_setup_token'] as String?,
        );
      }
      throw api;
    }
  }

  Future<void> sendOtp(
      {String? phone, String? email, String? institutionSlug}) async {
    await _dio.post<Map<String, dynamic>>(
      '/auth/send-otp',
      data: {
        if (phone != null) 'phone': phone,
        if (email != null) 'email': email,
        if (institutionSlug != null) 'institution_slug': institutionSlug,
      },
      options: Options(extra: {'idempotent': false}),
    );
  }

  Future<AuthState> verifyOtp(
      {String? phone,
      String? email,
      required String code,
      String? institutionSlug}) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/auth/verify-otp',
      data: {
        if (phone != null) 'phone': phone,
        if (email != null) 'email': email,
        'code': code,
        if (institutionSlug != null) 'institution_slug': institutionSlug,
        'platform': 'android',
      },
      options: Options(extra: {'idempotent': false}),
    );
    return _store(res.data?['data'] as Map<String, dynamic>? ?? const {});
  }

  Future<AuthState> me() async {
    final res = await _dio.get<Map<String, dynamic>>('/auth/me');
    final data = res.data?['data'] as Map<String, dynamic>? ?? const {};
    final state = AuthState.fromMe(data);
    _ref.read(authStateProvider.notifier).state = state;
    return state;
  }

  Future<void> changePassword(
      {required String currentPassword, required String newPassword}) async {
    await _dio.post<Map<String, dynamic>>(
      '/auth/change-password',
      data: {'current_password': currentPassword, 'new_password': newPassword},
      options: Options(extra: {'idempotent': false}),
    );
    await me();
  }

  Future<Map<String, dynamic>> mfaSetup({String? setupToken}) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/auth/mfa/setup',
      options: Options(
        extra: {'idempotent': false},
        headers:
            setupToken == null ? null : {'Authorization': 'Bearer $setupToken'},
      ),
    );
    return res.data?['data'] as Map<String, dynamic>? ?? const {};
  }

  Future<List<String>> mfaConfirm(String code, {String? setupToken}) async {
    final res = await _dio.post<Map<String, dynamic>>(
      '/auth/mfa/confirm',
      data: {'code': code},
      options: Options(
        extra: {'idempotent': false},
        headers:
            setupToken == null ? null : {'Authorization': 'Bearer $setupToken'},
      ),
    );
    final data = res.data?['data'] as Map<String, dynamic>? ?? const {};
    final token = data['access_token'] as String?;
    if (token != null) await _session.setAccessToken(token);
    return (data['recovery_codes'] as List<dynamic>? ?? const [])
        .cast<String>();
  }

  Future<List<Map<String, dynamic>>> sessions() async {
    final res = await _dio.get<Map<String, dynamic>>('/auth/sessions');
    return (res.data?['data'] as List<dynamic>? ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<void> revokeSession(String id) =>
      _dio.delete<void>('/auth/sessions/$id');

  Future<void> logout() async {
    try {
      await _dio.post<void>('/auth/logout',
          options: Options(extra: {'idempotent': false}));
    } on DioException {
      // the session is cleared locally either way
    }
    await _session.clear();
    _ref.read(authStateProvider.notifier).state = const AuthState();
  }

  Future<AuthState> _store(Map<String, dynamic> data) async {
    final access = data['access_token'] as String?;
    final refresh = data['refresh_token'] as String?;
    if (access != null) await _session.setAccessToken(access);
    if (refresh != null) await _session.setRefreshToken(refresh);
    final institution = data['institution'] as Map<String, dynamic>?;
    if (institution != null) {
      await _session.setTenant(
        institutionId: institution['id'] as String?,
        institutionSlug: institution['slug'] as String?,
      );
    }
    final state = AuthState.fromMe(data);
    _ref.read(authStateProvider.notifier).state = state;
    return state;
  }
}

final authRepositoryProvider =
    Provider<AuthRepository>((ref) => AuthRepository(ref));

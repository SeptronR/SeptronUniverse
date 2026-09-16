import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../providers.dart';

/// Persisted session (tokens + tenant selection) in secure storage. Phase 42 adds session list/revoke UI.
class SessionState {
  const SessionState({
    this.accessToken,
    this.institutionId,
    this.institutionSlug,
    this.collegeId,
  });

  final String? accessToken;
  final String? institutionId;
  final String? institutionSlug;
  final String? collegeId;

  bool get isAuthenticated => accessToken != null;

  SessionState copyWith({
    String? accessToken,
    String? institutionId,
    String? institutionSlug,
    String? collegeId,
    bool clearToken = false,
  }) =>
      SessionState(
        accessToken: clearToken ? null : (accessToken ?? this.accessToken),
        institutionId: institutionId ?? this.institutionId,
        institutionSlug: institutionSlug ?? this.institutionSlug,
        collegeId: collegeId ?? this.collegeId,
      );
}

class SessionNotifier extends StateNotifier<SessionState> {
  SessionNotifier(this._storage) : super(const SessionState()) {
    _restore();
  }

  final FlutterSecureStorage _storage;

  static const _kRefresh = 'refresh_token';
  static const _kInstitution = 'institution_id';
  static const _kSlug = 'institution_slug';
  static const _kCollege = 'college_id';

  Future<void> _restore() async {
    state = state.copyWith(
      institutionId: await _storage.read(key: _kInstitution),
      institutionSlug: await _storage.read(key: _kSlug),
      collegeId: await _storage.read(key: _kCollege),
    );
  }

  Future<String?> refreshToken() => _storage.read(key: _kRefresh);

  Future<void> setAccessToken(String token) async =>
      state = state.copyWith(accessToken: token);

  Future<void> setRefreshToken(String token) =>
      _storage.write(key: _kRefresh, value: token);

  Future<void> setTenant(
      {String? institutionId,
      String? institutionSlug,
      String? collegeId}) async {
    if (institutionId != null) {
      await _storage.write(key: _kInstitution, value: institutionId);
    }
    if (institutionSlug != null) {
      await _storage.write(key: _kSlug, value: institutionSlug);
    }
    if (collegeId != null) {
      await _storage.write(key: _kCollege, value: collegeId);
    }
    state = state.copyWith(
        institutionId: institutionId,
        institutionSlug: institutionSlug,
        collegeId: collegeId);
  }

  Future<void> clear() async {
    await _storage.delete(key: _kRefresh);
    state = const SessionState();
  }
}

final sessionProvider = StateNotifierProvider<SessionNotifier, SessionState>(
  (ref) => SessionNotifier(ref.watch(secureStorageProvider)),
);

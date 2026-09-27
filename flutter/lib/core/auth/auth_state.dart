import 'package:flutter_riverpod/flutter_riverpod.dart';

/// `meta.visibility` of a module list (docs/Authorization_and_Visibility.md §4) → drives `SegmentedScope`.
class VisibilityMeta {
  const VisibilityMeta(
      {this.self = true,
      this.scopes = const [],
      this.defaultScope = 'self',
      this.pii = false});

  factory VisibilityMeta.fromJson(Map<String, dynamic> json) => VisibilityMeta(
        self: json['self'] as bool? ?? true,
        scopes: (json['scopes'] as List<dynamic>? ?? const []).cast<String>(),
        defaultScope: json['default'] as String? ?? 'self',
        pii: json['pii'] as bool? ?? false,
      );

  final bool self;
  final List<String> scopes;
  final String defaultScope;
  final bool pii;

  bool get hasTabs => scopes.isNotEmpty;
}

/// Principal snapshot from `/auth/me`: user, roles, flat permissions, effective features, scopes.
class AuthState {
  const AuthState({
    this.userId,
    this.displayName,
    this.institutionId,
    this.isSuperAdmin = false,
    this.roles = const [],
    this.permissions = const {},
    this.features = const {},
    this.scopes = const [],
    this.visibilityByModule = const {},
    this.mustChangePassword = false,
    this.mfaEnabled = false,
  });

  final String? userId;
  final String? displayName;
  final String? institutionId;
  final bool isSuperAdmin;
  final List<String> roles;
  final Set<String> permissions;
  final Set<String> features;
  final List<({String scopeType, String? scopeId})> scopes;
  final Map<String, VisibilityMeta> visibilityByModule;

  /// Set by `/auth/me`: until the password is changed every non-auth route answers 403 (Prompts/02 §02.6 rule 5).
  final bool mustChangePassword;
  final bool mfaEnabled;

  bool get isAuthenticated => userId != null;

  /// Mirrors Principal.has(): super admin, exact `module:action`, or `module:manage`.
  bool can(String module, [String action = 'view']) =>
      isSuperAdmin ||
      permissions.contains('$module:$action') ||
      permissions.contains('$module:manage');

  /// Core keys are never gated; others come from the effective set.
  bool hasFeature(String key) =>
      key.startsWith('core.') || features.contains(key);

  VisibilityMeta visibility(String module) =>
      visibilityByModule[module] ?? const VisibilityMeta();

  /// Highest-ranking role decides the shell (docs/Mobile_App_UI_Structure.md §2.3).
  String get primaryRole => roles.isEmpty ? 'student' : roles.first;

  AuthState copyWith({Map<String, VisibilityMeta>? visibilityByModule}) =>
      AuthState(
        userId: userId,
        displayName: displayName,
        institutionId: institutionId,
        isSuperAdmin: isSuperAdmin,
        roles: roles,
        permissions: permissions,
        features: features,
        scopes: scopes,
        visibilityByModule: visibilityByModule ?? this.visibilityByModule,
        mustChangePassword: mustChangePassword,
        mfaEnabled: mfaEnabled,
      );

  static AuthState fromMe(Map<String, dynamic> data) {
    final user = data['user'] as Map<String, dynamic>? ?? data;
    return AuthState(
      userId: user['id'] as String?,
      displayName: user['display_name'] as String?,
      institutionId: user['institution_id'] as String?,
      isSuperAdmin: user['is_super_admin'] as bool? ?? false,
      roles: (data['role_slugs'] as List<dynamic>? ??
              user['role_slugs'] as List<dynamic>? ??
              const [])
          .cast<String>(),
      permissions: (data['permissions'] as List<dynamic>? ?? const [])
          .cast<String>()
          .toSet(),
      features: (data['features'] as List<dynamic>? ?? const [])
          .cast<String>()
          .toSet(),
      scopes: (data['scopes'] as List<dynamic>? ?? const [])
          .cast<Map<String, dynamic>>()
          .map((s) => (
                scopeType: s['scope_type'] as String,
                scopeId: s['scope_id'] as String?
              ))
          .toList(),
      mustChangePassword: user['must_change_password'] as bool? ?? false,
      mfaEnabled: user['mfa_enabled'] as bool? ?? false,
    );
  }
}

/// Phase 42 replaces this with the full AuthController (bootstrap → /auth/me, login/OTP/SSO, logout).
final authStateProvider = StateProvider<AuthState>((ref) => const AuthState());

import 'package:dio/dio.dart';

/// Error-code catalogue (docs/Technical_Architecture.md §1) mapped from the `{success:false, error:{code,...}}` envelope.
enum ApiErrorCode {
  validation('VALIDATION'),
  notFound('NOT_FOUND'),
  conflict('CONFLICT'),
  staleVersion('STALE_VERSION'),
  permissionDenied('PERMISSION_DENIED'),
  featureDisabled('FEATURE_DISABLED'),
  unauthenticated('UNAUTHENTICATED'),
  readOnly('READ_ONLY'),
  rateLimited('RATE_LIMITED'),
  idempotentReplay('IDEMPOTENT_REPLAY'),
  holdBlocked('HOLD_BLOCKED'),
  recordLocked('RECORD_LOCKED'),
  ruleViolation('RULE_VIOLATION'),
  integrationFailed('INTEGRATION_FAILED'),
  mfaRequired('MFA_REQUIRED'),
  internal('INTERNAL'),
  network('NETWORK'),
  unknown('UNKNOWN');

  const ApiErrorCode(this.wire);

  final String wire;

  static ApiErrorCode parse(String? code) => ApiErrorCode.values
      .firstWhere((c) => c.wire == code, orElse: () => ApiErrorCode.unknown);
}

class ApiException implements Exception {
  ApiException({
    required this.code,
    required this.message,
    this.statusCode,
    this.details = const {},
    this.requestId,
  });

  factory ApiException.fromDio(DioException e) {
    final data = e.response?.data;
    if (data is Map<String, dynamic> && data['error'] is Map<String, dynamic>) {
      final err = data['error'] as Map<String, dynamic>;
      return ApiException(
        code: ApiErrorCode.parse(err['code'] as String?),
        message: (err['message'] as String?) ?? 'Request failed',
        statusCode: e.response?.statusCode,
        details: (err['details'] as Map<String, dynamic>?) ?? const {},
        requestId: data['request_id'] as String?,
      );
    }
    final offline = e.type == DioExceptionType.connectionError ||
        e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout;
    return ApiException(
      code: offline ? ApiErrorCode.network : ApiErrorCode.unknown,
      message: offline
          ? 'You appear to be offline'
          : (e.message ?? 'Request failed'),
      statusCode: e.response?.statusCode,
    );
  }

  final ApiErrorCode code;
  final String message;
  final int? statusCode;
  final Map<String, dynamic> details;
  final String? requestId;

  bool get isFeatureDisabled => code == ApiErrorCode.featureDisabled;
  bool get isPermissionDenied => code == ApiErrorCode.permissionDenied;
  bool get isReadOnly => code == ApiErrorCode.readOnly;
  bool get isOffline => code == ApiErrorCode.network;

  @override
  String toString() => 'ApiException(${code.wire}, $statusCode): $message';
}

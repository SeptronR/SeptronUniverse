import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../auth/auth_events.dart';
import '../auth/session.dart';
import '../config/env.dart';
import 'api_exception.dart';

/// Envelope-aware dio client (docs/Mobile_App_UI_Structure.md §1 `network/dio_client.dart`).
///
/// * Bearer + `X-Institution-Id` / `X-Institution-Slug` / `X-College-Id` from the session
/// * `Idempotency-Key` (uuid v4 per submit) on POST/PUT/PATCH/DELETE unless `extra['idempotent'] == false`
/// * single-flight refresh on 401 (force-logout bus on failure)
/// * retry/backoff on network errors and 5xx (never on 4xx)
/// * `503 READ_ONLY` handled by the caller through [ApiException.isReadOnly]
///
/// Responses keep the envelope; `Paginated<T>` (shared/models) exposes `meta.visibility` to screens.
class DioClient {
  DioClient(this._ref) {
    dio = Dio(
      BaseOptions(
        baseUrl: Env.apiUrl,
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 30),
        headers: {'Accept': 'application/json'},
      ),
    );
    dio.interceptors.addAll([
      _HeadersInterceptor(_ref),
      _RefreshInterceptor(this),
      _RetryInterceptor(dio)
    ]);
  }

  final Ref _ref;
  late final Dio dio;
  Future<String?>? _refreshing;

  /// Single-flight refresh: concurrent 401s share one `/auth/refresh` call.
  Future<String?> refreshToken() {
    _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);
    return _refreshing!;
  }

  Future<String?> _doRefresh() async {
    final session = _ref.read(sessionProvider.notifier);
    final refresh = await session.refreshToken();
    if (refresh == null) return null;
    try {
      final bare = Dio(BaseOptions(baseUrl: Env.apiUrl));
      final res = await bare.post<Map<String, dynamic>>(
        '/auth/refresh',
        data: {'refresh_token': refresh},
      );
      final data = res.data?['data'] as Map<String, dynamic>?;
      final token = data?['access_token'] as String?;
      if (token != null) await session.setAccessToken(token);
      return token;
    } on DioException {
      return null;
    }
  }
}

class _HeadersInterceptor extends Interceptor {
  _HeadersInterceptor(this._ref);

  final Ref _ref;
  static const _uuid = Uuid();
  static const _mutations = {'POST', 'PUT', 'PATCH', 'DELETE'};

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final session = _ref.read(sessionProvider);
    if (session.accessToken != null) {
      options.headers['Authorization'] = 'Bearer ${session.accessToken}';
    }
    if (session.institutionId != null) {
      options.headers['X-Institution-Id'] = session.institutionId;
    }
    if (session.institutionSlug != null) {
      options.headers['X-Institution-Slug'] = session.institutionSlug;
    }
    if (session.collegeId != null) {
      options.headers['X-College-Id'] = session.collegeId;
    }
    final idempotent = options.extra['idempotent'] != false;
    if (_mutations.contains(options.method.toUpperCase()) &&
        idempotent &&
        !options.headers.containsKey('Idempotency-Key')) {
      options.headers['Idempotency-Key'] = _uuid.v4();
    }
    handler.next(options);
  }
}

class _RefreshInterceptor extends Interceptor {
  _RefreshInterceptor(this._client);

  final DioClient _client;

  @override
  Future<void> onError(
      DioException err, ErrorInterceptorHandler handler) async {
    final path = err.requestOptions.path;
    final retried = err.requestOptions.extra['_retried'] == true;
    if (err.response?.statusCode == 401 &&
        !retried &&
        !path.contains('/auth/')) {
      final token = await _client.refreshToken();
      if (token == null) {
        AuthEvents.instance.forceLogout('session_expired');
        return handler.reject(err);
      }
      final opts = err.requestOptions
        ..headers['Authorization'] = 'Bearer $token'
        ..extra['_retried'] = true;
      try {
        final res = await _client.dio.fetch<dynamic>(opts);
        return handler.resolve(res);
      } on DioException catch (e) {
        return handler.reject(e);
      }
    }
    handler.next(err);
  }
}

class _RetryInterceptor extends Interceptor {
  _RetryInterceptor(this._dio);

  static const int maxRetries = 2;

  final Dio _dio;

  bool _retryable(DioException e) {
    final status = e.response?.statusCode;
    if (status != null) return status >= 500;
    return e.type == DioExceptionType.connectionError ||
        e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout;
  }

  @override
  Future<void> onError(
      DioException err, ErrorInterceptorHandler handler) async {
    final attempt = (err.requestOptions.extra['_attempt'] as int?) ?? 0;
    final method = err.requestOptions.method.toUpperCase();
    // Mutations carry an Idempotency-Key, so a retry is safe on 5xx; 4xx are never retried.
    if (_retryable(err) &&
        attempt < maxRetries &&
        (method == 'GET' ||
            err.requestOptions.headers.containsKey('Idempotency-Key'))) {
      await Future<void>.delayed(Duration(milliseconds: 400 * (1 << attempt)));
      err.requestOptions.extra['_attempt'] = attempt + 1;
      try {
        return handler.resolve(await _dio.fetch<dynamic>(err.requestOptions));
      } on DioException catch (e) {
        return handler.reject(e);
      }
    }
    handler.next(err);
  }
}

/// Convenience: turn any dio error into the catalogue exception.
ApiException toApiException(Object error) => error is DioException
    ? ApiException.fromDio(error)
    : ApiException(code: ApiErrorCode.unknown, message: '$error');

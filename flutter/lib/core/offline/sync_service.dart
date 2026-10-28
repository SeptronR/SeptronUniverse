import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_exception.dart';
import '../providers.dart';
import 'db.dart';
import 'write_queue_repository.dart';

/// Write-queue flush (Prompts/42 §42.5): on connectivity (and on demand) send due items in order, batch size from
/// `/mobile/config` `write_queue.flush_batch`, each with its persisted `Idempotency-Key`.
///
/// * 2xx or `409 IDEMPOTENT_REPLAY` → done
/// * `409 CONFLICT|STALE_VERSION` → policy: `server_wins` → done + notice, `merge` → done, `prompt` → conflict
///   (the user keeps the server state or discards from the [SyncStatusSheet])
/// * `503 READ_ONLY`, network errors, 5xx → failed with backoff (kept)
/// * other 4xx (validation, permission) → conflict with the reason, never retried automatically
enum SyncStatus { idle, syncing, offline, error }

class SyncState {
  const SyncState({this.status = SyncStatus.idle, this.pending = 0, this.lastSync, this.notices = const []});

  final SyncStatus status;
  final int pending;
  final DateTime? lastSync;
  final List<String> notices;

  SyncState copyWith({SyncStatus? status, int? pending, DateTime? lastSync, List<String>? notices}) => SyncState(
        status: status ?? this.status,
        pending: pending ?? this.pending,
        lastSync: lastSync ?? this.lastSync,
        notices: notices ?? this.notices,
      );
}

class SyncService extends StateNotifier<SyncState> {
  SyncService(this._ref) : super(const SyncState()) {
    _sub = _ref.read(connectivityProvider).onConnectivityChanged.listen((r) {
      final online = r.any((c) => c != ConnectivityResult.none);
      if (online) {
        unawaited(flush());
      } else {
        state = state.copyWith(status: SyncStatus.offline);
      }
    });
    unawaited(refreshCount());
  }

  final Ref _ref;
  late final StreamSubscription<List<ConnectivityResult>> _sub;
  bool _running = false;
  int flushBatch = 50;

  WriteQueueRepository get _queue => _ref.read(writeQueueProvider);

  /// Queue a write and try to send it straight away.
  Future<WriteQueueRow> submit({
    required String kind,
    required String method,
    required String path,
    required Object? body,
    ConflictPolicy conflictPolicy = ConflictPolicy.serverWins,
  }) async {
    final row = await _queue.enqueue(kind: kind, method: method, path: path, body: body, conflictPolicy: conflictPolicy);
    await refreshCount();
    unawaited(flush());
    return row;
  }

  Future<void> refreshCount() async {
    state = state.copyWith(pending: await _queue.pendingCount());
  }

  Future<int> flush() async {
    if (_running) return 0;
    _running = true;
    state = state.copyWith(status: SyncStatus.syncing);
    var sent = 0;
    final notices = <String>[];
    var hadError = false;
    try {
      final dio = _ref.read(dioProvider);
      for (final item in await _queue.due(limit: flushBatch)) {
        await _queue.mark(item.id, WriteQueueStatus.sending);
        try {
          await dio.request<dynamic>(
            item.path,
            data: jsonDecode(item.body),
            options: Options(method: item.method, headers: {'Idempotency-Key': item.idempotencyKey}),
          );
          await _queue.mark(item.id, WriteQueueStatus.done);
          sent++;
        } on DioException catch (e) {
          final err = ApiException.fromDio(e);
          final status = e.response?.statusCode;
          if (status == 409 && err.code == ApiErrorCode.idempotentReplay) {
            await _queue.mark(item.id, WriteQueueStatus.done);
            sent++;
          } else if (status == 409) {
            switch (item.conflictPolicy) {
              case ConflictPolicy.serverWins:
                notices.add('${item.kind}: the server already has a newer version — kept the server state');
                await _queue.mark(item.id, WriteQueueStatus.done, error: err.message);
              case ConflictPolicy.merge:
                await _queue.mark(item.id, WriteQueueStatus.done);
              case ConflictPolicy.prompt:
                await _queue.mark(item.id, WriteQueueStatus.conflict, error: err.message);
            }
          } else if (status == null || status >= 500 || err.isReadOnly) {
            hadError = true;
            await _queue.mark(item.id, WriteQueueStatus.failed, error: err.message);
            if (status == null) break; // still offline — keep order, stop this round
          } else {
            await _queue.mark(item.id, WriteQueueStatus.conflict, error: err.message);
          }
        }
      }
      await _queue.prune();
    } catch (e) {
      hadError = true;
      debugPrint('sync flush failed: $e');
    } finally {
      _running = false;
      state = state.copyWith(
        status: hadError ? SyncStatus.error : SyncStatus.idle,
        pending: await _queue.pendingCount(),
        lastSync: DateTime.now(),
        notices: [...state.notices, ...notices].take(20).toList(),
      );
    }
    return sent;
  }

  void clearNotices() => state = state.copyWith(notices: const []);

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }
}

final syncServiceProvider = StateNotifierProvider<SyncService, SyncState>((ref) => SyncService(ref));

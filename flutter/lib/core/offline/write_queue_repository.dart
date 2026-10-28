import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import 'db.dart';

/// Persistent write queue (Prompts/42 §42.5): attendance marks, GPS pings, gate scans, out-pass decisions, mess
/// attendance, SOS, library / event / visitor scans. Each item keeps the `Idempotency-Key` it was created with, so
/// a replay after a lost response is answered `IDEMPOTENT_REPLAY` by the API instead of writing twice.
class WriteQueueRepository {
  WriteQueueRepository({this.maxItems = 5000, this.maxAge = const Duration(hours: 72)});

  int maxItems;
  Duration maxAge;
  static const _uuid = Uuid();
  OfflineDb? _db;

  Future<OfflineDb> get _open async => _db ??= await OfflineDb.open();

  Future<WriteQueueRow> enqueue({
    required String kind,
    required String method,
    required String path,
    required Object? body,
    ConflictPolicy conflictPolicy = ConflictPolicy.serverWins,
  }) async {
    final db = (await _open).db;
    final count = db.select("SELECT COUNT(*) AS n FROM write_queue WHERE status != 'done'").first['n'] as int;
    if (count >= maxItems) {
      throw StateError('Offline queue is full ($maxItems items) — reconnect to sync');
    }
    final row = WriteQueueRow(
      id: _uuid.v4(),
      kind: kind,
      method: method.toUpperCase(),
      path: path,
      body: jsonEncode(body),
      idempotencyKey: _uuid.v4(),
      status: WriteQueueStatus.pending,
      conflictPolicy: conflictPolicy,
      createdAt: DateTime.now(),
    );
    db.execute(
      'INSERT INTO write_queue (id, kind, method, path, body, idempotency_key, status, attempts, conflict_policy, '
      'created_at, next_attempt_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)',
      [
        row.id,
        row.kind,
        row.method,
        row.path,
        row.body,
        row.idempotencyKey,
        row.status.name,
        conflictPolicyName(row.conflictPolicy),
        row.createdAt.millisecondsSinceEpoch,
      ],
    );
    return row;
  }

  /// Items due for sending, oldest first (FIFO keeps attendance → finalize ordering).
  Future<List<WriteQueueRow>> due({int limit = 50}) async {
    final db = (await _open).db;
    final now = DateTime.now().millisecondsSinceEpoch;
    return db
        .select(
          "SELECT * FROM write_queue WHERE status IN ('pending', 'failed') AND next_attempt_at <= ? "
          'ORDER BY created_at LIMIT ?',
          [now, limit],
        )
        .map(WriteQueueRow.fromRow)
        .toList();
  }

  Future<List<WriteQueueRow>> open() async {
    final db = (await _open).db;
    return db
        .select("SELECT * FROM write_queue WHERE status != 'done' ORDER BY created_at")
        .map(WriteQueueRow.fromRow)
        .toList();
  }

  Future<void> mark(String id, WriteQueueStatus status, {String? error}) async {
    final db = (await _open).db;
    if (status == WriteQueueStatus.failed) {
      // exponential backoff: 15 s, 30 s, 60 s … capped at 30 min
      final attempts = (db.select('SELECT attempts FROM write_queue WHERE id = ?', [id]).firstOrNull?['attempts'] as int?) ?? 0;
      final delay = Duration(seconds: (15 * (1 << attempts.clamp(0, 7))).clamp(15, 1800));
      db.execute(
        'UPDATE write_queue SET status = ?, attempts = attempts + 1, last_error = ?, next_attempt_at = ? WHERE id = ?',
        [status.name, error, DateTime.now().add(delay).millisecondsSinceEpoch, id],
      );
      return;
    }
    db.execute('UPDATE write_queue SET status = ?, last_error = ? WHERE id = ?', [status.name, error, id]);
  }

  Future<void> retryNow(String id) async {
    (await _open).db.execute("UPDATE write_queue SET status = 'pending', next_attempt_at = 0 WHERE id = ?", [id]);
  }

  Future<void> discard(String id) async => (await _open).db.execute('DELETE FROM write_queue WHERE id = ?', [id]);

  /// Drop delivered items and anything older than `max_age_hours` (reported to the user before deletion).
  Future<int> prune() async {
    final db = (await _open).db;
    final cutoff = DateTime.now().subtract(maxAge).millisecondsSinceEpoch;
    db.execute("DELETE FROM write_queue WHERE status = 'done' OR created_at < ?", [cutoff]);
    return db.updatedRows;
  }

  Future<int> pendingCount() async {
    final db = (await _open).db;
    return db.select("SELECT COUNT(*) AS n FROM write_queue WHERE status IN ('pending', 'failed', 'sending', 'conflict')").first['n']
        as int;
  }

  Future<void> clear() async => (await _open).db.execute('DELETE FROM write_queue');
}

final writeQueueProvider = Provider<WriteQueueRepository>((ref) => WriteQueueRepository());

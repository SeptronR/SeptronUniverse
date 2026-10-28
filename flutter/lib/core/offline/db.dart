import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqlite3/sqlite3.dart';

/// Offline database (docs/Mobile_App_UI_Structure.md §1 `offline/db.dart`, Prompts/42 §42.5).
///
/// Plain SQLite through `package:sqlite3` (the native library ships with `sqlite3_flutter_libs`) — two tables,
/// so no drift code generation is needed:
///   cache_entries(key TEXT PRIMARY KEY, json TEXT, fetched_at INTEGER, ttl INTEGER)
///   write_queue(id TEXT PRIMARY KEY, kind TEXT, method TEXT, path TEXT, body TEXT, idempotency_key TEXT,
///               status TEXT, attempts INTEGER, last_error TEXT, conflict_policy TEXT, created_at INTEGER,
///               next_attempt_at INTEGER)
/// Falls back to an in-memory database when the documents directory is unavailable (tests, web).
class OfflineDb {
  OfflineDb._(this.db) {
    db.execute('''
      CREATE TABLE IF NOT EXISTS cache_entries (
        key TEXT PRIMARY KEY, json TEXT NOT NULL, fetched_at INTEGER NOT NULL, ttl INTEGER NOT NULL)''');
    db.execute('''
      CREATE TABLE IF NOT EXISTS write_queue (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
        conflict_policy TEXT NOT NULL DEFAULT 'server_wins', created_at INTEGER NOT NULL,
        next_attempt_at INTEGER NOT NULL DEFAULT 0)''');
  }

  final Database db;
  static OfflineDb? _instance;

  static Future<OfflineDb> open() async {
    if (_instance != null) return _instance!;
    Database database;
    try {
      final dir = await getApplicationDocumentsDirectory();
      database = sqlite3.open(p.join(dir.path, 'septron_offline.db'));
    } catch (_) {
      database = sqlite3.openInMemory();
    }
    return _instance = OfflineDb._(database);
  }

  /// Logout: wipe both tables (cache is namespaced per user, the queue belongs to the signed-in user).
  void wipe() {
    db.execute('DELETE FROM cache_entries');
    db.execute('DELETE FROM write_queue');
  }

  static bool get supported => !Platform.environment.containsKey('FLUTTER_TEST');
}

class CacheEntryRow {
  const CacheEntryRow(
      {required this.key,
      required this.json,
      required this.fetchedAt,
      required this.ttlSeconds});

  final String key;
  final String json;
  final DateTime fetchedAt;
  final int ttlSeconds;

  bool get isStale =>
      DateTime.now().difference(fetchedAt).inSeconds > ttlSeconds;

  dynamic get decoded => jsonDecode(json);
}

enum WriteQueueStatus { pending, sending, failed, done, conflict }

/// How a replayed write resolves against server state (Prompts/42 §42.5).
enum ConflictPolicy {
  /// finalized attendance sessions, scans: the server state stands, the item is dropped with a notice
  serverWins,

  /// out-pass decisions already decided elsewhere: the user chooses (keep server / discard)
  prompt,

  /// GPS batches: the server de-duplicates by (trip, ts) so a replay is merged
  merge,
}

ConflictPolicy conflictPolicyFrom(String v) => switch (v) {
      'prompt' => ConflictPolicy.prompt,
      'merge' => ConflictPolicy.merge,
      _ => ConflictPolicy.serverWins,
    };

String conflictPolicyName(ConflictPolicy p) => switch (p) {
      ConflictPolicy.prompt => 'prompt',
      ConflictPolicy.merge => 'merge',
      ConflictPolicy.serverWins => 'server_wins',
    };

class WriteQueueRow {
  const WriteQueueRow({
    required this.id,
    required this.kind,
    required this.method,
    required this.path,
    required this.body,
    required this.idempotencyKey,
    required this.status,
    this.attempts = 0,
    this.lastError,
    this.conflictPolicy = ConflictPolicy.serverWins,
    required this.createdAt,
  });

  factory WriteQueueRow.fromRow(Row r) => WriteQueueRow(
        id: r['id'] as String,
        kind: r['kind'] as String,
        method: r['method'] as String,
        path: r['path'] as String,
        body: r['body'] as String,
        idempotencyKey: r['idempotency_key'] as String,
        status: WriteQueueStatus.values.byName(r['status'] as String),
        attempts: r['attempts'] as int,
        lastError: r['last_error'] as String?,
        conflictPolicy: conflictPolicyFrom(r['conflict_policy'] as String),
        createdAt: DateTime.fromMillisecondsSinceEpoch(r['created_at'] as int),
      );

  final String id;

  /// attendance_marks | gps_batch | gate_scan | outpass_decision | mess_attendance | sos | library_scan |
  /// event_attendance | visitor_scan
  final String kind;
  final String method;
  final String path;
  final String body;
  final String idempotencyKey;
  final WriteQueueStatus status;
  final int attempts;
  final String? lastError;
  final ConflictPolicy conflictPolicy;
  final DateTime createdAt;
}

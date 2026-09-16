/// Offline database stub (docs/Mobile_App_UI_Structure.md §1 `offline/db.dart`).
///
/// Phase 42 implements the drift schema:
///   cache_entries(key TEXT PRIMARY KEY, json TEXT, fetched_at INTEGER, ttl INTEGER)
///   write_queue(id TEXT PRIMARY KEY, method TEXT, path TEXT, body TEXT, idempotency_key TEXT,
///               status TEXT, attempts INTEGER, last_error TEXT, created_at INTEGER)
/// and generates `db.g.dart` with build_runner. The typed rows below are the contract the cache and queue
/// repositories code against.
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
}

enum WriteQueueStatus { pending, sending, failed, done, conflict }

class WriteQueueRow {
  const WriteQueueRow({
    required this.id,
    required this.method,
    required this.path,
    required this.body,
    required this.idempotencyKey,
    required this.status,
    this.attempts = 0,
    this.lastError,
    required this.createdAt,
  });

  final String id;
  final String method;
  final String path;
  final String body;
  final String idempotencyKey;
  final WriteQueueStatus status;
  final int attempts;
  final String? lastError;
  final DateTime createdAt;
}

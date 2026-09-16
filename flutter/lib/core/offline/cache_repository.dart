import 'db.dart';

/// Read-through cache contract (timetable, attendance summaries, results, dues, notices, hostel status).
/// In-memory until Phase 42 backs it with drift; keys are namespaced per institution/user by the caller.
class CacheRepository {
  final Map<String, CacheEntryRow> _memory = {};

  Future<CacheEntryRow?> read(String key) async => _memory[key];

  Future<void> write(String key, String json,
      {Duration ttl = const Duration(minutes: 15)}) async {
    _memory[key] = CacheEntryRow(
        key: key,
        json: json,
        fetchedAt: DateTime.now(),
        ttlSeconds: ttl.inSeconds);
  }

  Future<void> invalidate(String keyPrefix) async {
    _memory.removeWhere((k, _) => k.startsWith(keyPrefix));
  }

  Future<void> clear() async => _memory.clear();
}

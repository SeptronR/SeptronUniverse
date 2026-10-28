import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_state.dart';
import '../auth/session.dart';
import 'db.dart';

/// Read-through cache (Prompts/42 §42.5): timetable, attendance summaries, results, dues, receipts, hall tickets,
/// ID card. Keys are namespaced `<institution>:<user>:<key>`; TTL per model from `/mobile/config` `cache_ttl`
/// unless the caller passes one; stale entries are still returned (with [CachedValue.stale]) when offline.
class CacheRepository {
  CacheRepository(this._ref);

  final Ref _ref;
  OfflineDb? _db;

  Future<OfflineDb> get _open async => _db ??= await OfflineDb.open();

  String _ns(String key) {
    final s = _ref.read(sessionProvider);
    final user = _ref.read(authStateProvider).userId;
    return '${s.institutionId ?? '-'}:${user ?? '-'}:$key';
  }

  Future<CacheEntryRow?> read(String key) async {
    final db = (await _open).db;
    final rows = db.select('SELECT key, json, fetched_at, ttl FROM cache_entries WHERE key = ?', [_ns(key)]);
    if (rows.isEmpty) return null;
    final r = rows.first;
    return CacheEntryRow(
      key: key,
      json: r['json'] as String,
      fetchedAt: DateTime.fromMillisecondsSinceEpoch(r['fetched_at'] as int),
      ttlSeconds: r['ttl'] as int,
    );
  }

  Future<void> write(String key, Object? value, {Duration ttl = const Duration(minutes: 15)}) async {
    final db = (await _open).db;
    db.execute(
      'INSERT OR REPLACE INTO cache_entries (key, json, fetched_at, ttl) VALUES (?, ?, ?, ?)',
      [_ns(key), value is String ? value : jsonEncode(value), DateTime.now().millisecondsSinceEpoch, ttl.inSeconds],
    );
  }

  /// Fresh cache → cached; otherwise fetch, store and return; on fetch failure fall back to the stale entry.
  Future<CachedValue<T>> readThrough<T>(
    String key,
    Future<T> Function() fetch, {
    Duration ttl = const Duration(minutes: 15),
    bool force = false,
  }) async {
    final hit = await read(key);
    if (!force && hit != null && !hit.isStale) {
      return CachedValue(hit.decoded as T, fetchedAt: hit.fetchedAt, stale: false, fromCache: true);
    }
    try {
      final value = await fetch();
      await write(key, value, ttl: ttl);
      return CachedValue(value, fetchedAt: DateTime.now(), stale: false, fromCache: false);
    } catch (_) {
      if (hit == null) rethrow;
      return CachedValue(hit.decoded as T, fetchedAt: hit.fetchedAt, stale: true, fromCache: true);
    }
  }

  Future<void> invalidate(String keyPrefix) async {
    (await _open).db.execute('DELETE FROM cache_entries WHERE key LIKE ?', ['${_ns(keyPrefix)}%']);
  }

  Future<void> clear() async => (await _open).db.execute('DELETE FROM cache_entries');
}

class CachedValue<T> {
  const CachedValue(this.value, {required this.fetchedAt, required this.stale, required this.fromCache});

  final T value;
  final DateTime fetchedAt;
  final bool stale;
  final bool fromCache;
}

final cacheRepositoryProvider = Provider<CacheRepository>((ref) => CacheRepository(ref));

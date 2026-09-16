import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'db.dart';

/// Write-queue flush contract: on connectivity, send items in order with the persisted Idempotency-Key;
/// conflict policy per item type (server_wins | prompt | merge) arrives in Phase 42.
enum SyncStatus { idle, syncing, offline, error }

class SyncService {
  final List<WriteQueueRow> _queue = [];

  List<WriteQueueRow> get pending => List.unmodifiable(_queue);

  Future<void> enqueue(WriteQueueRow item) async => _queue.add(item);

  Future<int> flush() async {
    // Phase 42: iterate _queue, POST with the stored Idempotency-Key, mark done/failed/conflict.
    return 0;
  }
}

final syncServiceProvider = Provider<SyncService>((ref) => SyncService());
final syncStatusProvider = StateProvider<SyncStatus>((ref) => SyncStatus.idle);

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/offline/db.dart';
import '../../core/offline/sync_service.dart';
import '../../core/offline/write_queue_repository.dart';
import '../../core/providers.dart';
import '../../core/remote_config/remote_config.dart';

/// `OfflineBanner` + `SyncStatus` chip (Prompts/42 §42.6): offline / read-only state, queued item count, last sync;
/// tap opens [SyncStatusSheet] with per-item errors and retry / discard.
class OfflineBanner extends ConsumerWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final online = ref.watch(isOnlineProvider);
    final readOnly = ref.watch(readOnlyModeProvider);
    final sync = ref.watch(syncServiceProvider);
    if (online && !readOnly && sync.pending == 0 && sync.notices.isEmpty) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    final text = [
      if (!online) 'Offline — showing saved data',
      if (readOnly) 'Read-only maintenance — changes are queued',
      if (sync.pending > 0) '${sync.pending} change(s) waiting to sync',
      if (sync.notices.isNotEmpty) sync.notices.last,
    ].join(' · ');
    return Material(
      color: readOnly ? scheme.tertiaryContainer : scheme.secondaryContainer,
      child: InkWell(
        onTap: () => SyncStatusSheet.show(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Row(children: [
            Icon(online ? Icons.sync : Icons.cloud_off_outlined, size: 18),
            const SizedBox(width: 8),
            Expanded(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
            if (sync.status == SyncStatus.syncing)
              const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ]),
        ),
      ),
    );
  }
}

class SyncStatusSheet extends ConsumerStatefulWidget {
  const SyncStatusSheet({super.key});

  static Future<void> show(BuildContext context) =>
      showModalBottomSheet<void>(context: context, isScrollControlled: true, builder: (_) => const SyncStatusSheet());

  @override
  ConsumerState<SyncStatusSheet> createState() => _SyncStatusSheetState();
}

class _SyncStatusSheetState extends ConsumerState<SyncStatusSheet> {
  late Future<List<WriteQueueRow>> _items = ref.read(writeQueueProvider).open();

  void _reload() => setState(() => _items = ref.read(writeQueueProvider).open());

  @override
  Widget build(BuildContext context) {
    final sync = ref.watch(syncServiceProvider);
    final queue = ref.read(writeQueueProvider);
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.7,
        child: Column(children: [
          ListTile(
            title: const Text('Sync status'),
            subtitle: Text(sync.lastSync == null ? 'Not synced yet' : 'Last sync ${TimeOfDay.fromDateTime(sync.lastSync!).format(context)}'),
            trailing: FilledButton.tonal(
              onPressed: () async {
                await ref.read(syncServiceProvider.notifier).flush();
                _reload();
              },
              child: const Text('Sync now'),
            ),
          ),
          for (final n in sync.notices) ListTile(dense: true, leading: const Icon(Icons.info_outline), title: Text(n)),
          const Divider(height: 1),
          Expanded(
            child: FutureBuilder<List<WriteQueueRow>>(
              future: _items,
              builder: (context, snap) {
                final items = snap.data ?? const [];
                if (items.isEmpty) return const Center(child: Text('Nothing waiting'));
                return ListView.separated(
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, i) {
                    final it = items[i];
                    return ListTile(
                      leading: Icon(switch (it.status) {
                        WriteQueueStatus.conflict => Icons.warning_amber,
                        WriteQueueStatus.failed => Icons.error_outline,
                        _ => Icons.schedule,
                      }),
                      title: Text(it.kind.replaceAll('_', ' ')),
                      subtitle: Text([it.status.name, if (it.attempts > 0) '${it.attempts} attempt(s)', if (it.lastError != null) it.lastError!].join(' · ')),
                      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                        IconButton(
                          tooltip: 'Retry',
                          icon: const Icon(Icons.refresh),
                          onPressed: () async {
                            await queue.retryNow(it.id);
                            await ref.read(syncServiceProvider.notifier).flush();
                            _reload();
                          },
                        ),
                        IconButton(
                          tooltip: 'Discard',
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () async {
                            await queue.discard(it.id);
                            await ref.read(syncServiceProvider.notifier).refreshCount();
                            _reload();
                          },
                        ),
                      ]),
                    );
                  },
                );
              },
            ),
          ),
        ]),
      ),
    );
  }
}

/// "Saved data from <time>" chip shown on cached lists past their TTL.
class StaleBadge extends StatelessWidget {
  const StaleBadge({super.key, required this.fetchedAt});

  final DateTime fetchedAt;

  @override
  Widget build(BuildContext context) => Chip(
        avatar: const Icon(Icons.history, size: 16),
        label: Text('Saved ${TimeOfDay.fromDateTime(fetchedAt).format(context)}'),
        visualDensity: VisualDensity.compact,
      );
}

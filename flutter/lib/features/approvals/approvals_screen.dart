import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../shared/utils/fmt.dart';

/// Approvals inbox tab for approver roles (Prompts/04 §04.10): cards, approve / reject with a comment, delegate by
/// user id (the web app has the full staff picker and timeline).
class InboxEntry {
  InboxEntry.fromJson(Map<String, dynamic> j)
      : instanceId = (j['instance'] as Map<String, dynamic>)['id'] as String,
        title = (j['entity_summary'] as String?) ?? ((j['instance'] as Map<String, dynamic>)['title'] as String? ?? ''),
        module = (j['instance'] as Map<String, dynamic>)['module'] as String,
        requester = (j['instance'] as Map<String, dynamic>)['started_by_name'] as String?,
        step = (j['instance'] as Map<String, dynamic>)['current_step'] as int,
        totalSteps = (j['instance'] as Map<String, dynamic>)['total_steps'] as int,
        startedAt = DateTime.parse((j['instance'] as Map<String, dynamic>)['started_at'] as String),
        via = j['via'] as String? ?? 'direct';

  final String instanceId;
  final String title;
  final String module;
  final String? requester;
  final int step;
  final int totalSteps;
  final DateTime startedAt;
  final String via;
}

class ApprovalsRepository {
  ApprovalsRepository(this._dio);

  final Dio _dio;

  Future<List<InboxEntry>> inbox() async {
    final res = await _dio.get<Map<String, dynamic>>('/workflow/inbox');
    return ((res.data?['data'] as List?) ?? const []).map((e) => InboxEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> act(String id, String decision, {String? comment, String? delegateTo}) =>
      _dio.post<Map<String, dynamic>>('/workflow/instances/$id/act',
          data: {'decision': decision, if (comment != null && comment.isNotEmpty) 'comment': comment, if (delegateTo != null) 'delegate_to': delegateTo},
          options: Options(extra: {'idempotent': false}));
}

final approvalsRepositoryProvider = Provider<ApprovalsRepository>((ref) => ApprovalsRepository(ref.watch(dioProvider)));
final inboxProvider = FutureProvider.autoDispose<List<InboxEntry>>((ref) => ref.watch(approvalsRepositoryProvider).inbox());

class ApprovalsScreen extends ConsumerWidget {
  const ApprovalsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final inbox = ref.watch(inboxProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Approvals')),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(inboxProvider),
        child: inbox.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [ListTile(title: Text('$e'))]),
          data: (rows) => ListView(
            padding: const EdgeInsets.all(8),
            children: [
              if (rows.isEmpty) const ListTile(title: Text('Nothing is waiting for you.')),
              for (final r in rows)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(r.title, style: Theme.of(context).textTheme.titleMedium),
                        Text('${Fmt.titleCase(r.module)} · ${r.requester ?? ''} · ${Fmt.dateTime(r.startedAt)} · '
                            'step ${r.step}/${r.totalSteps}${r.via == 'direct' ? '' : ' · via ${r.via}'}'),
                        const SizedBox(height: 8),
                        Wrap(spacing: 8, children: [
                          FilledButton(onPressed: () => _decide(context, ref, r, 'approve'), child: const Text('Approve')),
                          OutlinedButton(onPressed: () => _decide(context, ref, r, 'reject'), child: const Text('Reject')),
                          TextButton(onPressed: () => _decide(context, ref, r, 'delegate'), child: const Text('Delegate')),
                        ]),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _decide(BuildContext context, WidgetRef ref, InboxEntry r, String decision) async {
    final comment = TextEditingController();
    final delegate = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${Fmt.titleCase(decision)}: ${r.title}'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: comment, decoration: InputDecoration(labelText: decision == 'reject' ? 'Comment (required)' : 'Comment')),
          if (decision == 'delegate') TextField(controller: delegate, decoration: const InputDecoration(labelText: 'Delegate user id')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Confirm')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(approvalsRepositoryProvider).act(r.instanceId, decision,
          comment: comment.text, delegateTo: decision == 'delegate' ? delegate.text.trim() : null);
      ref.invalidate(inboxProvider);
    } catch (e) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

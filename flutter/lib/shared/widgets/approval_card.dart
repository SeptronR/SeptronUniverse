import 'package:flutter/material.dart';

/// `ApprovalCard` (workflow inbox, Prompts/42 §42.6): entity summary, step, age, approve / reject / delegate.
/// The caller posts to `/workflow/instances/{id}/act` with `{action, comment, delegate_to?}`.
class ApprovalCard extends StatelessWidget {
  const ApprovalCard({super.key, required this.item, required this.onAct});

  final Map<String, dynamic> item;
  final Future<void> Function(String action, String? comment) onAct;

  Future<void> _withComment(BuildContext context, String action, {bool required = false}) async {
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('${action[0].toUpperCase()}${action.substring(1)}'),
        content: TextField(controller: ctrl, maxLines: 3, decoration: InputDecoration(labelText: required ? 'Reason (required)' : 'Comment')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Submit')),
        ],
      ),
    );
    final text = ctrl.text.trim();
    ctrl.dispose();
    if (ok != true || (required && text.isEmpty)) return;
    await onAct(action, text.isEmpty ? null : text);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final summary = (item['summary'] ?? item['title'] ?? item['entity_type'] ?? 'Request').toString();
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(summary, style: t.titleSmall)),
            if (item['module'] != null) Chip(label: Text('${item['module']}'), visualDensity: VisualDensity.compact),
          ]),
          if (item['step_name'] != null) Text('Step: ${item['step_name']}', style: t.bodySmall),
          if (item['requested_by_name'] != null) Text('From: ${item['requested_by_name']}', style: t.bodySmall),
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            FilledButton(onPressed: () => onAct('approve', null), child: const Text('Approve')),
            OutlinedButton(onPressed: () => _withComment(context, 'reject', required: true), child: const Text('Reject')),
            TextButton(onPressed: () => _withComment(context, 'delegate'), child: const Text('Delegate')),
          ]),
        ]),
      ),
    );
  }
}

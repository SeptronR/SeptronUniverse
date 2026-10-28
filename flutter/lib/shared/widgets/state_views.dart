import 'package:flutter/material.dart';

import '../../core/network/api_exception.dart';
import '../../core/network/dio_client.dart';

/// Empty / error / loading states (Prompts/42 §42.6 widget catalogue).
class EmptyStateIllustration extends StatelessWidget {
  const EmptyStateIllustration({super.key, this.icon = Icons.inbox_outlined, required this.title, this.message, this.action});

  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 56, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(title, style: Theme.of(context).textTheme.titleMedium, textAlign: TextAlign.center),
            if (message != null) ...[const SizedBox(height: 4), Text(message!, textAlign: TextAlign.center)],
            if (action != null) ...[const SizedBox(height: 16), action!],
          ]),
        ),
      );
}

/// Error with the catalogue message; 403 shows "not allowed" with the reason code, never a raw stack.
class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final e = toApiException(error);
    final forbidden = e.code == ApiErrorCode.permissionDenied || e.code == ApiErrorCode.featureDisabled;
    return EmptyStateIllustration(
      icon: e.isOffline ? Icons.cloud_off_outlined : (forbidden ? Icons.lock_outline : Icons.error_outline),
      title: e.isOffline ? 'You are offline' : (forbidden ? 'Not allowed' : 'Something went wrong'),
      message: forbidden ? '${e.message} (${e.code.wire})' : e.message,
      action: onRetry == null ? null : OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
    );
  }
}

class Skeletons extends StatelessWidget {
  const Skeletons({super.key, this.rows = 6});

  final int rows;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme.surfaceContainerHighest;
    return ListView.builder(
      physics: const NeverScrollableScrollPhysics(),
      itemCount: rows,
      itemBuilder: (_, __) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          CircleAvatar(backgroundColor: c),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(height: 12, color: c),
              const SizedBox(height: 6),
              FractionallySizedBox(widthFactor: 0.6, child: Container(height: 10, color: c)),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// `ConfirmDialog` for irreversible actions; [requireText] makes the user type a word (e.g. "PUBLISH").
Future<bool> confirmAction(BuildContext context,
    {required String title, required String message, String confirm = 'Confirm', String? requireText}) async {
  final ctrl = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: Text(title),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(message),
          if (requireText != null) ...[
            const SizedBox(height: 12),
            TextField(controller: ctrl, onChanged: (_) => setState(() {}), decoration: InputDecoration(labelText: 'Type $requireText')),
          ],
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: requireText != null && ctrl.text.trim() != requireText ? null : () => Navigator.pop(ctx, true),
            child: Text(confirm),
          ),
        ],
      ),
    ),
  );
  ctrl.dispose();
  return ok ?? false;
}

/// `FeatureHint`: why a disabled module is missing (texts from `/mobile/config` feature_hints).
class FeatureHint extends StatelessWidget {
  const FeatureHint({super.key, required this.feature, this.hint});

  final String feature;
  final String? hint;

  @override
  Widget build(BuildContext context) => EmptyStateIllustration(
        icon: Icons.toggle_off_outlined,
        title: 'Not enabled for your institution',
        message: hint ?? 'Ask your administrator to enable "$feature".',
      );
}

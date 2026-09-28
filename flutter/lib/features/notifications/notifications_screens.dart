import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/routes.dart';
import '../../shared/utils/fmt.dart';
import 'notifications_repository.dart';

/// Notifications inbox (tab): pull to refresh, tap = mark read + deep link, mark all read, preferences.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(notificationsProvider);
    final repo = ref.read(notificationsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          IconButton(
            tooltip: 'Mark all read',
            icon: const Icon(Icons.done_all),
            onPressed: () async {
              await repo.readAll();
              ref.invalidate(notificationsProvider);
            },
          ),
          IconButton(
            tooltip: 'Preferences',
            icon: const Icon(Icons.tune),
            onPressed: () => context.push(AppRoutes.notificationPreferences),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(notificationsProvider),
        child: items.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [ListTile(title: Text('$e'))]),
          data: (rows) => rows.isEmpty
              ? ListView(children: const [ListTile(title: Text('You are all caught up.'))])
              : ListView.separated(
                  itemCount: rows.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) {
                    final n = rows[i];
                    return ListTile(
                      leading: Icon(n.isRead ? Icons.notifications_none : Icons.notifications_active,
                          color: n.isRead ? null : Theme.of(context).colorScheme.primary),
                      title: Text(n.title,
                          style: TextStyle(fontWeight: n.isRead ? FontWeight.normal : FontWeight.w600)),
                      subtitle: Text([if (n.body != null) n.body!, Fmt.dateTime(n.createdAt)].join('\n'),
                          maxLines: 3, overflow: TextOverflow.ellipsis),
                      onTap: () async {
                        if (!n.isRead) await repo.markRead(n.id);
                        ref.invalidate(notificationsProvider);
                        final route = mobileRouteFor(n.route);
                        if (route != null && context.mounted) context.push(route);
                      },
                    );
                  },
                ),
        ),
      ),
    );
  }
}

/// Web deep links → app routes (`/announcements/<id>` → announcement detail, `/approvals…` → approvals tab).
String? mobileRouteFor(String? webRoute) {
  if (webRoute == null) return null;
  if (webRoute.startsWith('/announcements/')) {
    return '${AppRoutes.announcements}?id=${webRoute.split('/').last}';
  }
  if (webRoute.startsWith('/approvals')) return AppRoutes.approvals;
  return null;
}

/// Preferences: categories × channels, digest (quiet hours are edited on the web profile).
class NotificationPreferencesScreen extends ConsumerStatefulWidget {
  const NotificationPreferencesScreen({super.key});

  @override
  ConsumerState<NotificationPreferencesScreen> createState() => _PrefsState();
}

class _PrefsState extends ConsumerState<NotificationPreferencesScreen> {
  List<PreferenceRow>? _rows;
  static const _channels = ['sms', 'whatsapp', 'email', 'push'];

  @override
  void initState() {
    super.initState();
    ref.read(notificationsRepositoryProvider).preferences().then((r) => setState(() => _rows = r));
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    return Scaffold(
      appBar: AppBar(title: const Text('Notification preferences'), actions: [
        TextButton(
          onPressed: rows == null
              ? null
              : () async {
                  await ref.read(notificationsRepositoryProvider).savePreferences(rows);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Preferences saved')));
                  }
                },
          child: const Text('Save'),
        ),
      ]),
      body: rows == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                for (final r in rows)
                  ExpansionTile(
                    title: Text(Fmt.titleCase(r.category)),
                    subtitle: r.mandatory ? const Text('Always delivered') : Text(r.channels.join(', ')),
                    children: [
                      for (final c in _channels)
                        CheckboxListTile(
                          title: Text(c),
                          value: r.channels.contains(c),
                          onChanged: r.mandatory
                              ? null
                              : (v) => setState(() => v == true ? r.channels.add(c) : r.channels.remove(c)),
                        ),
                      ListTile(
                        title: const Text('Digest'),
                        trailing: DropdownButton<String>(
                          value: r.digest,
                          items: const [
                            DropdownMenuItem(value: 'none', child: Text('none')),
                            DropdownMenuItem(value: 'daily', child: Text('daily')),
                            DropdownMenuItem(value: 'weekly', child: Text('weekly')),
                          ],
                          onChanged: r.mandatory ? null : (v) => setState(() => r.digest = v ?? 'none'),
                        ),
                      ),
                    ],
                  ),
              ],
            ),
    );
  }
}

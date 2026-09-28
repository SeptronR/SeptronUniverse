import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../shared/utils/fmt.dart';

/// Announcements (Prompts/04 §04.10): list (audience-filtered by the API, pinned first), detail, acknowledge.
class AnnouncementItem {
  AnnouncementItem.fromJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        title = j['title'] as String,
        body = j['body'] as String? ?? '',
        pinned = j['is_pinned'] == true,
        requiresAck = j['requires_ack'] == true,
        acknowledgedAt = j['my_acknowledged_at'] as String?,
        publishAt = j['publish_at'] as String?;

  final String id;
  final String title;
  final String body;
  final bool pinned;
  final bool requiresAck;
  final String? acknowledgedAt;
  final String? publishAt;

  /// Announcement bodies are HTML from the web editor; the app shows plain text.
  String get plainBody => body.replaceAll(RegExp(r'<br\s*/?>|</p>|</li>'), '\n').replaceAll(RegExp(r'<[^>]+>'), '').trim();
}

class AnnouncementsRepository {
  AnnouncementsRepository(this._dio);

  final Dio _dio;

  Future<List<AnnouncementItem>> list() async {
    final res = await _dio.get<Map<String, dynamic>>('/announcements', queryParameters: {'scope': 'self', 'page_size': 50});
    return ((res.data?['data'] as List?) ?? const []).map((e) => AnnouncementItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<AnnouncementItem> get(String id) async {
    final res = await _dio.get<Map<String, dynamic>>('/announcements/$id');
    return AnnouncementItem.fromJson(res.data?['data'] as Map<String, dynamic>);
  }

  Future<void> acknowledge(String id) => _dio.post<Map<String, dynamic>>('/announcements/$id/acknowledge',
      data: {'acknowledge': true}, options: Options(extra: {'idempotent': false}));
}

final announcementsRepositoryProvider =
    Provider<AnnouncementsRepository>((ref) => AnnouncementsRepository(ref.watch(dioProvider)));
final announcementsProvider =
    FutureProvider.autoDispose<List<AnnouncementItem>>((ref) => ref.watch(announcementsRepositoryProvider).list());

class AnnouncementsScreen extends ConsumerWidget {
  const AnnouncementsScreen({super.key, this.openId});

  final String? openId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (openId != null) return AnnouncementDetailScreen(id: openId!);
    final list = ref.watch(announcementsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Announcements')),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(announcementsProvider),
        child: list.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [ListTile(title: Text('$e'))]),
          data: (rows) => ListView(
            children: [
              if (rows.isEmpty) const ListTile(title: Text('No announcements.')),
              for (final a in rows)
                ListTile(
                  leading: Icon(a.pinned ? Icons.push_pin : Icons.campaign_outlined),
                  title: Text(a.title),
                  subtitle: Text(Fmt.dateTime(DateTime.tryParse(a.publishAt ?? ''))),
                  trailing: a.requiresAck
                      ? Icon(a.acknowledgedAt != null ? Icons.check_circle : Icons.error_outline,
                          color: a.acknowledgedAt != null ? Colors.green : Colors.orange)
                      : null,
                  onTap: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(builder: (_) => AnnouncementDetailScreen(id: a.id))),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class AnnouncementDetailScreen extends ConsumerStatefulWidget {
  const AnnouncementDetailScreen({super.key, required this.id});

  final String id;

  @override
  ConsumerState<AnnouncementDetailScreen> createState() => _DetailState();
}

class _DetailState extends ConsumerState<AnnouncementDetailScreen> {
  AnnouncementItem? _item;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final item = await ref.read(announcementsRepositoryProvider).get(widget.id);
    if (mounted) setState(() => _item = item);
  }

  @override
  Widget build(BuildContext context) {
    final a = _item;
    return Scaffold(
      appBar: AppBar(title: Text(a?.title ?? 'Announcement')),
      body: a == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(a.plainBody),
                const SizedBox(height: 24),
                if (a.requiresAck)
                  a.acknowledgedAt != null
                      ? const ListTile(leading: Icon(Icons.check_circle, color: Colors.green), title: Text('Acknowledged'))
                      : FilledButton(
                          onPressed: () async {
                            await ref.read(announcementsRepositoryProvider).acknowledge(a.id);
                            ref.invalidate(announcementsProvider);
                            await _load();
                          },
                          child: const Text('I have read this'),
                        ),
              ],
            ),
    );
  }
}

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Bodies may be rich text (announcements are HTML): tags stripped, common entities decoded, whitespace collapsed.
String? _plain(String? html) => html
    ?.replaceAll(RegExp(r'<[^>]+>'), ' ')
    .replaceAll('&nbsp;', ' ')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
    .replaceAll('&amp;', '&')
    .replaceAll(RegExp(r'\s+'), ' ')
    .trim();

/// `/notifications` + `/notification-preferences/me` (Prompts/04 §04.8; self only).
class AppNotificationItem {
  AppNotificationItem.fromJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        title = j['title'] as String,
        body = _plain(j['body'] as String?),
        route = j['route'] as String?,
        isRead = j['is_read'] == true,
        createdAt = DateTime.parse(j['created_at'] as String);

  final String id;
  final String title;
  final String? body;
  final String? route;
  final bool isRead;
  final DateTime createdAt;
}

class PreferenceRow {
  PreferenceRow.fromJson(Map<String, dynamic> j)
      : category = j['category'] as String,
        channels = List<String>.from(j['channels'] as List),
        quietHours = j['quiet_hours'] as Map<String, dynamic>?,
        digest = j['digest'] as String? ?? 'none',
        mandatory = j['mandatory'] == true;

  final String category;
  List<String> channels;
  Map<String, dynamic>? quietHours;
  String digest;
  final bool mandatory;

  Map<String, dynamic> toJson() => {
        'category': category,
        'channels': channels,
        'quiet_hours': quietHours,
        'digest': digest,
      };
}

class NotificationsRepository {
  NotificationsRepository(this._dio);

  final Dio _dio;

  Future<List<AppNotificationItem>> list({bool unreadOnly = false}) async {
    final res = await _dio.get<Map<String, dynamic>>('/notifications',
        queryParameters: {'unread': unreadOnly, 'page_size': 50});
    return ((res.data?['data'] as List?) ?? const [])
        .map((e) => AppNotificationItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> markRead(String id) =>
      _dio.post<Map<String, dynamic>>('/notifications/$id/read',
          options: Options(extra: {'idempotent': false}));

  Future<void> readAll() =>
      _dio.post<Map<String, dynamic>>('/notifications/read-all',
          options: Options(extra: {'idempotent': false}));

  Future<List<PreferenceRow>> preferences() async {
    final res =
        await _dio.get<Map<String, dynamic>>('/notification-preferences/me');
    final items =
        ((res.data?['data'] as Map<String, dynamic>?)?['items'] as List?) ??
            const [];
    return items
        .map((e) => PreferenceRow.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> savePreferences(List<PreferenceRow> rows) =>
      _dio.put<Map<String, dynamic>>('/notification-preferences/me',
          data: {'items': rows.map((r) => r.toJson()).toList()});
}

final notificationsRepositoryProvider = Provider<NotificationsRepository>(
    (ref) => NotificationsRepository(ref.watch(dioProvider)));

final notificationsProvider =
    FutureProvider.autoDispose<List<AppNotificationItem>>(
        (ref) => ref.watch(notificationsRepositoryProvider).list());

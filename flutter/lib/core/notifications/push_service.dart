import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../router/deeplinks.dart';

/// FCM + local notifications (Prompts/42 §42.6 `notifications/`): Android channels per category (emergency is high
/// priority with sound), foreground display, tap → [DeepLink] dispatch (cold start parks it in [PendingDeepLink]).
/// Token registration with topics is [PushRegistration]. Without Firebase configuration (development) it no-ops.
class PushService {
  PushService._();

  static final instance = PushService._();
  final _local = FlutterLocalNotificationsPlugin();
  void Function(DeepLink link)? onNavigate;
  bool _ready = false;

  static const channels = <String, (String, Importance)>{
    'academics': ('Academics', Importance.defaultImportance),
    'fees': ('Fees & payments', Importance.defaultImportance),
    'exams': ('Exams & results', Importance.high),
    'hostel': ('Hostel', Importance.defaultImportance),
    'approvals': ('Approvals', Importance.high),
    'emergency': ('Emergency', Importance.max),
    'system': ('System', Importance.low),
  };

  Future<void> init() async {
    if (_ready || kIsWeb) return;
    try {
      await Firebase.initializeApp();
    } catch (e) {
      debugPrint('push disabled (no Firebase config): $e');
      return;
    }
    await _local.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(),
      ),
      onDidReceiveNotificationResponse: (r) => _open(r.payload),
    );
    final android = _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    for (final e in channels.entries) {
      await android?.createNotificationChannel(
        AndroidNotificationChannel(e.key, e.value.$1, importance: e.value.$2, playSound: e.key != 'system'),
      );
    }
    await FirebaseMessaging.instance.requestPermission();
    FirebaseMessaging.onMessage.listen(_showForeground);
    FirebaseMessaging.onMessageOpenedApp.listen((m) => _dispatch(m.data));
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) {
      final link = DeepLink.fromPushData(initial.data);
      if (link != null) PendingDeepLink.pending = link;
    }
    _ready = true;
  }

  Future<void> _showForeground(RemoteMessage m) async {
    final n = m.notification;
    if (n == null) return;
    final category = channels.containsKey(m.data['category']) ? m.data['category'] as String : 'system';
    final ch = channels[category]!;
    await _local.show(
      m.hashCode,
      n.title,
      n.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          category,
          ch.$1,
          importance: ch.$2,
          priority: category == 'emergency' ? Priority.max : Priority.defaultPriority,
          fullScreenIntent: category == 'emergency',
        ),
        iOS: DarwinNotificationDetails(interruptionLevel: category == 'emergency' ? InterruptionLevel.timeSensitive : null),
      ),
      payload: jsonEncode(m.data),
    );
  }

  void _open(String? payload) {
    if (payload == null) return;
    try {
      _dispatch((jsonDecode(payload) as Map).cast<String, dynamic>());
    } catch (_) {}
  }

  void _dispatch(Map<String, dynamic> data) {
    final link = DeepLink.fromPushData(data);
    if (link == null) return;
    if (onNavigate != null) {
      onNavigate!(link);
    } else {
      PendingDeepLink.pending = link;
    }
  }
}

/// Background isolate handler (registered in main.dart): nothing to do beyond letting FCM show the notification.
@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {}

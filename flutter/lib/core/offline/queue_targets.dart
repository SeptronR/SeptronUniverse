import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'db.dart';
import 'sync_service.dart';
import 'write_queue_repository.dart';

/// The offline-capable writes (Prompts/42 §42.4 write-queue targets) with their conflict policies. Screens call
/// these instead of dio so the write survives airplane mode and replays with the same `Idempotency-Key`.
class QueueTargets {
  QueueTargets(this._sync);

  final SyncService _sync;

  /// Faculty: bulk marks for a class session — finalized-on-web sessions → server wins.
  Future<WriteQueueRow> attendanceMarks(String sessionId, Map<String, dynamic> body) =>
      _sync.submit(kind: 'attendance_marks', method: 'POST', path: '/class-sessions/$sessionId/attendance', body: body);

  /// Teacher device without network for several sessions (`attendance.offline_mobile`).
  Future<WriteQueueRow> attendanceOfflineBatch(List<Map<String, dynamic>> sessions) =>
      _sync.submit(kind: 'attendance_marks', method: 'POST', path: '/attendance/offline-batch', body: {'sessions': sessions});

  /// Driver: GPS pings batched every 10 s; the API de-duplicates by (trip, ts) → merge.
  Future<WriteQueueRow> gpsBatch(String tripId, List<Map<String, dynamic>> pings) => _sync.submit(
      kind: 'gps_batch',
      method: 'POST',
      path: '/transport/gps/ingest',
      body: {'trip_id': tripId, 'pings': pings},
      conflictPolicy: ConflictPolicy.merge);

  /// Gate staff / warden: out-pass QR mark-out / return.
  Future<WriteQueueRow> gateScan(String qrToken, String direction) => _sync.submit(
      kind: 'gate_scan',
      method: 'POST',
      path: '/hostel-gate/scan',
      body: {'qr_token': qrToken, 'direction': direction, 'scanned_at': DateTime.now().toUtc().toIso8601String()});

  /// Warden: out-pass decision; already decided on the web → the user chooses.
  Future<WriteQueueRow> outpassDecision(String leaveId, String decision, {String? remarks}) => _sync.submit(
      kind: 'outpass_decision',
      method: 'POST',
      path: '/hostel-leaves/$leaveId/decide',
      body: {'decision': decision, if (remarks != null) 'remarks': remarks},
      conflictPolicy: ConflictPolicy.prompt);

  Future<WriteQueueRow> messAttendance(Map<String, dynamic> body) =>
      _sync.submit(kind: 'mess_attendance', method: 'POST', path: '/mess-attendance', body: body);

  /// SOS: the same Idempotency-Key returns the same alert id however often it is replayed.
  /// `{alert_type, location: {text | lat/lng}}`
  Future<WriteQueueRow> sos(Map<String, dynamic> body) =>
      _sync.submit(kind: 'sos', method: 'POST', path: '/emergency/sos', body: body);

  Future<WriteQueueRow> libraryScan(String action, Map<String, dynamic> body) =>
      _sync.submit(kind: 'library_scan', method: 'POST', path: '/library/circulation/$action', body: body);

  Future<WriteQueueRow> eventAttendance(String eventId, String code) =>
      _sync.submit(kind: 'event_attendance', method: 'POST', path: '/events/$eventId/attendance', body: {'code': code});

  Future<WriteQueueRow> visitorScan(String code) =>
      _sync.submit(kind: 'visitor_scan', method: 'POST', path: '/facilities/visitor-passes/scan', body: {'code': code});
}

final queueTargetsProvider = Provider<QueueTargets>((ref) => QueueTargets(ref.read(syncServiceProvider.notifier)));

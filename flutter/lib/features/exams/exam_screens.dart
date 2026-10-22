import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 14 mobile (Prompts/14 §14.10): student **Exams** (registration items with eligibility / fee, submit, hall
/// ticket, seats), faculty **Duties** (list, swap request), invigilator **Conduct** (session → paper → hall attendance
/// with booklet numbers, malpractice report). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class ExamRepository {
  ExamRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()});
  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async =>
      (await _dio.post<Map<String, dynamic>>(path, data: body ?? {}, options: _once)).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> myRegistration() async => ((await _get('/exam-registration/me')) as Map).cast<String, dynamic>();
  Future<void> submit() => _post('/exam-registration/me/submit');
  Future<List<Map<String, dynamic>>> seats() async => _list(await _get('/exam-registration/me/seat'));
  Future<List<Map<String, dynamic>>> duties() async => _list(await _get('/invigilation-duties/me'));
  Future<void> swap(String id, String reason) => _post('/invigilation-duties/$id/swap-request', {'reason': reason});
  Future<List<Map<String, dynamic>>> sessions() async => _list(await _get('/exam-sessions'));
  Future<List<Map<String, dynamic>>> papers(String sessionId) async => _list(await _get('/exam-sessions/$sessionId/papers'));
  Future<List<Map<String, dynamic>>> hall(String paperId) async => _list(await _get('/exam-papers/$paperId/attendance'));
  Future<void> mark(String paperId, List<Map<String, dynamic>> items) => _post('/exam-papers/$paperId/attendance', {'items': items});
  Future<void> malpractice(String paperId, String itemId, String report) =>
      _post('/exam-papers/$paperId/malpractice-reports', {'exam_registration_item_id': itemId, 'category': 'material', 'invigilator_report': report});
  String hallTicketUrl() => '${_dio.options.baseUrl}/exam-registration/me/hall-ticket.pdf';
}

final examRepositoryProvider = Provider<ExamRepository>((ref) => ExamRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, Object e) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));

class StudentExamsScreen extends ConsumerStatefulWidget {
  const StudentExamsScreen({super.key});

  @override
  ConsumerState<StudentExamsScreen> createState() => _StudentExamsScreenState();
}

class _StudentExamsScreenState extends ConsumerState<StudentExamsScreen> {
  late Future<Map<String, dynamic>> _reg = ref.read(examRepositoryProvider).myRegistration();

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(examRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Exams')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _reg,
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final r = snap.data!;
          final items = ((r['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(12), children: [
            ListTile(title: Text('${r['session_name']}'), subtitle: Text('Status ${r['status']} · fee ₹${((r['total_fee_paise'] as num?) ?? 0) / 100}')),
            for (final h in ((r['holds'] as List?) ?? const [])) ListTile(leading: const Icon(Icons.block, color: Colors.red), title: Text('$h')),
            for (final i in items)
              Card(
                child: ListTile(
                  title: Text('${i['course_code']} · ${i['paper_type']}'),
                  subtitle: Text('${i['exam_date'] ?? 'TBA'} ${i['session_slot'] ?? ''} · ${i['eligibility']}${i['seat'] != null ? ' · ${i['seat']['room']} / ${i['seat']['seat']}' : ''}'),
                ),
              ),
            if (r['status'] == 'draft')
              FilledButton(
                onPressed: () async {
                  try {
                    await repo.submit();
                    setState(() => _reg = repo.myRegistration());
                  } catch (e) {
                    if (context.mounted) _snack(context, e);
                  }
                },
                child: const Text('Submit registration'),
              ),
            if (r['hall_ticket_available'] == true)
              OutlinedButton.icon(
                icon: const Icon(Icons.badge_outlined),
                label: Text('Hall ticket ${r['hall_ticket_number']}'),
                onPressed: () => launchUrl(Uri.parse(repo.hallTicketUrl()), mode: LaunchMode.externalApplication),
              ),
          ]);
        },
      ),
    );
  }
}

class MyDutiesScreen extends ConsumerStatefulWidget {
  const MyDutiesScreen({super.key});

  @override
  ConsumerState<MyDutiesScreen> createState() => _MyDutiesScreenState();
}

class _MyDutiesScreenState extends ConsumerState<MyDutiesScreen> {
  late Future<List<Map<String, dynamic>>> _d = ref.read(examRepositoryProvider).duties();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Exam duties')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _d,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final d in snap.data!)
                    ListTile(
                      title: Text('${d['exam_date']} ${d['session_slot']} · ${d['room_code'] ?? 'TBA'}'),
                      subtitle: Text('${d['role']} · ${d['status']}'),
                      trailing: ['assigned', 'accepted'].contains(d['status'])
                          ? TextButton(
                              onPressed: () async {
                                try {
                                  await ref.read(examRepositoryProvider).swap('${d['id']}', 'Requested from the app');
                                  setState(() => _d = ref.read(examRepositoryProvider).duties());
                                } catch (e) {
                                  if (context.mounted) _snack(context, e);
                                }
                              },
                              child: const Text('Swap'))
                          : null,
                    ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('No duties.')),
                ]),
        ),
      );
}

class ExamConductScreen extends ConsumerStatefulWidget {
  const ExamConductScreen({super.key});

  @override
  ConsumerState<ExamConductScreen> createState() => _ExamConductScreenState();
}

class _ExamConductScreenState extends ConsumerState<ExamConductScreen> {
  String? _session;
  String? _paper;
  List<Map<String, dynamic>> _rows = const [];
  final Map<String, Map<String, dynamic>> _edits = {};

  Future<void> _load() async {
    if (_paper == null) return;
    try {
      final rows = await ref.read(examRepositoryProvider).hall(_paper!);
      setState(() => _rows = rows);
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(examRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Hall attendance'), actions: [
        IconButton(
          icon: const Icon(Icons.save),
          onPressed: _edits.isEmpty || _paper == null
              ? null
              : () async {
                  try {
                    await repo.mark(_paper!, [for (final e in _edits.entries) {'exam_registration_item_id': e.key, ...e.value}]);
                    _edits.clear();
                    await _load();
                  } catch (e) {
                    if (context.mounted) _snack(context, e);
                  }
                },
        ),
      ]),
      body: ListView(padding: const EdgeInsets.all(8), children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: repo.sessions(),
          builder: (context, snap) => DropdownButton<String>(
            isExpanded: true,
            hint: const Text('Session'),
            value: _session,
            items: [for (final s in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${s['id']}', child: Text('${s['name']}'))],
            onChanged: (v) => setState(() {
              _session = v;
              _paper = null;
            }),
          ),
        ),
        if (_session != null)
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.papers(_session!),
            builder: (context, snap) => DropdownButton<String>(
              isExpanded: true,
              hint: const Text('Paper'),
              value: _paper,
              items: [for (final p in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${p['id']}', child: Text('${p['paper_code']} ${p['exam_date'] ?? ''} ${p['session_slot'] ?? ''}'))],
              onChanged: (v) {
                setState(() => _paper = v);
                _load();
              },
            ),
          ),
        for (final r in _rows)
          Card(
            child: ListTile(
              title: Text('${r['hall_ticket_number'] ?? ''} · ${r['student_name'] ?? ''}'),
              subtitle: TextFormField(
                initialValue: '${r['answer_booklet_number'] ?? ''}',
                decoration: const InputDecoration(labelText: 'Booklet no.'),
                onChanged: (v) => _edits['${r['exam_registration_item_id']}'] = {'status': _edits['${r['exam_registration_item_id']}']?['status'] ?? 'present', 'answer_booklet_number': v},
              ),
              trailing: Wrap(children: [
                IconButton(
                    icon: Icon(Icons.person_off, color: (_edits['${r['exam_registration_item_id']}']?['status'] ?? r['status']) == 'absent' ? Colors.red : null),
                    onPressed: () => setState(() => _edits['${r['exam_registration_item_id']}'] = {'status': 'absent'})),
                IconButton(
                    icon: const Icon(Icons.report_gmailerrorred),
                    onPressed: () async {
                      try {
                        await repo.malpractice(_paper!, '${r['exam_registration_item_id']}', 'Reported from the app');
                        await _load();
                      } catch (e) {
                        if (context.mounted) _snack(context, e);
                      }
                    }),
              ]),
            ),
          ),
      ]),
    );
  }
}

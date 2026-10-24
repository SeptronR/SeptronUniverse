import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 16 mobile (Prompts/16 §16.10): student **Revaluation** (eligible items → request, status timeline),
/// **Malpractice** (notice, statement, decision, appeal), **Transcripts** (request, status, download link) and the
/// COE / exam-cell **Reval queue** (decide with revised marks). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _rupees(dynamic p) => '₹${(((p ?? 0) as num) / 100).toStringAsFixed(0)}';

class PostResultRepository {
  PostResultRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> sessions() async => _list(await _get('/exam-sessions'));
  Future<List<Map<String, dynamic>>> eligibility(String sessionId) async =>
      _list(((await _get('/reval/eligibility', {'session_id': sessionId})) as Map?)?['items']);
  Future<void> requestReval(String itemId, String type) => _post('/reval-requests', {'exam_registration_item_id': itemId, 'request_type': type});
  Future<List<Map<String, dynamic>>> myReval() async => _list(await _get('/reval-requests/me'));
  Future<List<Map<String, dynamic>>> myCases() async => _list(await _get('/malpractice-cases/me'));
  Future<void> statement(String id, String text) => _post('/malpractice-cases/$id/statement', {'text': text});
  Future<void> appeal(String id, String grounds) => _post('/malpractice-cases/$id/appeal', {'grounds': grounds});
  Future<List<Map<String, dynamic>>> transcriptTypes() async => _list(await _get('/transcripts/types'));
  Future<List<Map<String, dynamic>>> myTranscripts() async => _list(await _get('/transcripts/me'));
  Future<void> requestTranscript(String type, int copies) => _post('/transcripts/requests', {'transcript_type': type, 'copies': copies, 'delivery': 'digital'});
  Future<List<Map<String, dynamic>>> sessionReval(String sessionId) async => _list(await _get('/exam-sessions/$sessionId/reval-requests'));
  Future<void> decide(String id, num? marks) => _post('/reval-requests/$id/decide', {'revised_marks': marks});
}

final postResultRepositoryProvider = Provider<PostResultRepository>((ref) => PostResultRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<String?> _ask(BuildContext context, String title, String label) async {
  final c = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, maxLines: 4, decoration: InputDecoration(labelText: label)),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('OK'))],
    ),
  );
  return ok == true ? c.text : null;
}

class _SessionDropdown extends ConsumerWidget {
  const _SessionDropdown({required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: ref.read(postResultRepositoryProvider).sessions(),
      builder: (context, snap) => DropdownButton<String>(
        isExpanded: true,
        value: value,
        hint: const Text('Exam session'),
        items: [for (final s in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${s['id']}', child: Text('${s['name']}'))],
        onChanged: onChanged,
      ),
    );
  }
}

class RevalScreen extends ConsumerStatefulWidget {
  const RevalScreen({super.key});

  @override
  ConsumerState<RevalScreen> createState() => _RevalScreenState();
}

class _RevalScreenState extends ConsumerState<RevalScreen> {
  String? _session;
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(postResultRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Revaluation')),
      body: ListView(padding: const EdgeInsets.all(8), children: [
        _SessionDropdown(value: _session, onChanged: (v) => setState(() => _session = v)),
        if (_session != null)
          FutureBuilder<List<Map<String, dynamic>>>(
            key: ValueKey('e$_session$_tick'),
            future: repo.eligibility(_session!),
            builder: (context, snap) {
              if (snap.hasError) return Text(_error(snap.error!));
              if (!snap.hasData) return const LinearProgressIndicator();
              return Column(children: [
                for (final i in snap.data!)
                  Card(
                    child: ListTile(
                      title: Text('${i['course_code']} · ${i['letter_grade'] ?? ''}'),
                      subtitle: Wrap(spacing: 4, children: [
                        for (final t in ((i['allowed_types'] as List?) ?? const []))
                          ActionChip(
                            label: Text('$t ${_rupees((i['fees'] as Map?)?[t])}'),
                            onPressed: (i['existing'] as Map?)?[t] != null
                                ? null
                                : () async {
                                    try {
                                      await repo.requestReval('${i['exam_registration_item_id']}', '$t');
                                      if (context.mounted) _snack(context, 'Requested — pay the fee to proceed');
                                      setState(() => _tick++);
                                    } catch (e) {
                                      if (context.mounted) _snack(context, _error(e));
                                    }
                                  },
                          ),
                      ]),
                    ),
                  ),
              ]);
            },
          ),
        const Padding(padding: EdgeInsets.all(8), child: Text('My requests', style: TextStyle(fontWeight: FontWeight.w600))),
        FutureBuilder<List<Map<String, dynamic>>>(
          key: ValueKey('m$_tick'),
          future: repo.myReval(),
          builder: (context, snap) => Column(children: [
            for (final r in snap.data ?? const <Map<String, dynamic>>[])
              ListTile(
                title: Text('${r['course_code']} · ${r['request_type']}'),
                subtitle: Text('${r['status']} · fee ${r['invoice_status'] ?? '—'}${r['revised_marks'] != null ? ' · ${r['original_marks']} → ${r['revised_marks']}' : ''}'),
              ),
          ]),
        ),
      ]),
    );
  }
}

class MyMalpracticeScreen extends ConsumerStatefulWidget {
  const MyMalpracticeScreen({super.key});

  @override
  ConsumerState<MyMalpracticeScreen> createState() => _MyMalpracticeScreenState();
}

class _MyMalpracticeScreenState extends ConsumerState<MyMalpracticeScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(postResultRepositoryProvider).myCases();

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(postResultRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Malpractice')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          if (snap.data!.isEmpty) return const ListTile(title: Text('No cases.'));
          return ListView(children: [
            for (final c in snap.data!)
              Card(
                child: ListTile(
                  title: Text('${c['case_number']} · ${c['course_code'] ?? ''} · ${c['status']}'),
                  subtitle: Text(c['punishment'] != null ? 'Decision: ${c['punishment']} — ${c['decision_text']}' : 'Category ${c['category']}'),
                  trailing: TextButton(
                    child: Text(c['punishment'] != null ? 'Appeal' : 'Statement'),
                    onPressed: () async {
                      final appeal = c['punishment'] != null;
                      final text = await _ask(context, appeal ? 'Appeal' : 'Statement', appeal ? 'Grounds' : 'Your statement');
                      if (text == null) return;
                      try {
                        appeal ? await repo.appeal('${c['id']}', text) : await repo.statement('${c['id']}', text);
                        if (context.mounted) _snack(context, 'Submitted');
                        setState(() => _f = repo.myCases());
                      } catch (e) {
                        if (context.mounted) _snack(context, _error(e));
                      }
                    },
                  ),
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class MyTranscriptsScreen extends ConsumerStatefulWidget {
  const MyTranscriptsScreen({super.key});

  @override
  ConsumerState<MyTranscriptsScreen> createState() => _MyTranscriptsScreenState();
}

class _MyTranscriptsScreenState extends ConsumerState<MyTranscriptsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(postResultRepositoryProvider).myTranscripts();

  Future<void> _new() async {
    final repo = ref.read(postResultRepositoryProvider);
    final types = await repo.transcriptTypes();
    if (!mounted) return;
    final type = await showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(title: const Text('Transcript type'), children: [
        for (final t in types)
          SimpleDialogOption(onPressed: () => Navigator.pop(ctx, '${t['transcript_type']}'), child: Text('${t['transcript_type']} · ${_rupees(t['fee_paise'])}')),
      ]),
    );
    if (type == null) return;
    try {
      await repo.requestTranscript(type, 1);
      if (mounted) _snack(context, 'Requested — pay from Fees');
      setState(() => _f = repo.myTranscripts());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Transcripts')),
      floatingActionButton: FloatingActionButton.extended(onPressed: _new, icon: const Icon(Icons.add), label: const Text('Request')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return ListView(children: [
            for (final t in snap.data!)
              ListTile(
                leading: const Icon(Icons.description_outlined),
                title: Text('${t['transcript_type']} × ${t['copies']} · ${t['status']}'),
                subtitle: Text('fee ${t['invoice_status'] ?? '—'}${t['document_number'] != null ? ' · ${t['document_number']}' : ''}'),
              ),
          ]);
        },
      ),
    );
  }
}

class RevalQueueScreen extends ConsumerStatefulWidget {
  const RevalQueueScreen({super.key});

  @override
  ConsumerState<RevalQueueScreen> createState() => _RevalQueueScreenState();
}

class _RevalQueueScreenState extends ConsumerState<RevalQueueScreen> {
  String? _session;
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(postResultRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Reval queue')),
      body: ListView(padding: const EdgeInsets.all(8), children: [
        _SessionDropdown(value: _session, onChanged: (v) => setState(() => _session = v)),
        if (_session != null)
          FutureBuilder<List<Map<String, dynamic>>>(
            key: ValueKey('q$_session$_tick'),
            future: repo.sessionReval(_session!),
            builder: (context, snap) {
              if (snap.hasError) return Text(_error(snap.error!));
              if (!snap.hasData) return const LinearProgressIndicator();
              return Column(children: [
                for (final r in snap.data!)
                  ListTile(
                    title: Text('${r['registration_number'] ?? ''} · ${r['course_code']} · ${r['request_type']}'),
                    subtitle: Text('${r['status']} · original ${r['original_marks'] ?? '—'} · revised ${r['revised_marks'] ?? '—'}'),
                    trailing: ['marks_changed', 'no_change', 'rejected'].contains(r['status'])
                        ? null
                        : TextButton(
                            child: const Text('Decide'),
                            onPressed: () async {
                              final m = await _ask(context, 'Revised marks', 'Marks (blank = keep evaluator marks)');
                              if (m == null) return;
                              try {
                                await repo.decide('${r['id']}', num.tryParse(m));
                                if (context.mounted) _snack(context, 'Decided');
                                setState(() => _tick++);
                              } catch (e) {
                                if (context.mounted) _snack(context, _error(e));
                              }
                            },
                          ),
                  ),
              ]);
            },
          ),
      ]),
    );
  }
}

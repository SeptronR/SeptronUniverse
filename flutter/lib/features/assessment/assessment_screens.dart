import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 13 mobile (Prompts/13 §13.10): faculty **Marks** (my offerings → assessments → question-wise entry with a
/// numeric keypad → save → submit), student **Courses** (published content, assignment submission, timed quiz with
/// autosave every few seconds — answers are kept locally until the server confirms) and **Marks**, HOD **marks
/// verification** cards. Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class AssessmentRepository {
  AssessmentRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()});

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async =>
      (await _dio.post<Map<String, dynamic>>(path, data: body ?? {}, options: _once)).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> myOfferings() async => _list(await _get('/course-offerings/mine'));
  Future<List<Map<String, dynamic>>> assessments(String offeringId) async =>
      _list(await _get('/course-offerings/$offeringId/assessments'));
  Future<Map<String, dynamic>> grid(String id) async => ((await _get('/offering-assessments/$id/marks')) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> save(String id, List<Map<String, dynamic>> rows) async =>
      ((await _post('/offering-assessments/$id/marks', {'rows': rows})) as Map).cast<String, dynamic>();
  Future<void> submit(String id) => _post('/offering-assessments/$id/submit');
  Future<List<Map<String, dynamic>>> queue(String status) async => _list(await _get('/offering-assessments', {'status': status}));
  Future<void> verify(String id, String decision, [String? comment]) =>
      _post('/offering-assessments/$id/verify', {'decision': decision, 'comment': comment});
  Future<List<Map<String, dynamic>>> myMarks() async => _list(await _get('/marks/me'));
  Future<List<Map<String, dynamic>>> modules(String offeringId) async => _list(await _get('/course-offerings/$offeringId/modules'));
  Future<void> view(String contentId) => _post('/contents/$contentId/view', {'progress_pct': 100});
  Future<List<Map<String, dynamic>>> assignments(String offeringId) async =>
      _list(await _get('/course-offerings/$offeringId/assignments'));
  Future<void> submitAssignment(String id, String text) => _post('/assignments/$id/submit', {'text_answer': text});
  Future<List<Map<String, dynamic>>> quizzes(String offeringId) async => _list(await _get('/course-offerings/$offeringId/quizzes'));
  Future<Map<String, dynamic>> start(String quizId) async => ((await _post('/quizzes/$quizId/start')) as Map).cast<String, dynamic>();
  Future<void> saveAnswers(String attemptId, Map<String, dynamic> answers) =>
      _dio.put('/quiz-attempts/$attemptId/answers', data: {'answers': answers});
  Future<Map<String, dynamic>> submitAttempt(String attemptId) async =>
      ((await _post('/quiz-attempts/$attemptId/submit')) as Map).cast<String, dynamic>();
}

final assessmentRepositoryProvider =
    Provider<AssessmentRepository>((ref) => AssessmentRepository(ref.watch(dioProvider)));

// ---- faculty marks ---------------------------------------------------------------------------------------------------
class FacultyMarksScreen extends ConsumerWidget {
  const FacultyMarksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(assessmentRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Marks')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: repo.myOfferings(),
        builder: (context, snap) => !snap.hasData
            ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
            : ListView(children: [
                for (final o in snap.data!)
                  ExpansionTile(
                    title: Text('${o['course_code']} · ${o['section_code']}'),
                    subtitle: Text('${o['course_title'] ?? ''}'),
                    children: [
                      FutureBuilder<List<Map<String, dynamic>>>(
                        future: repo.assessments('${o['id']}'),
                        builder: (context, a) => Column(children: [
                          for (final x in a.data ?? const <Map<String, dynamic>>[])
                            ListTile(
                              title: Text('${x['name']}'),
                              subtitle: Text('${x['status']} · ${x['marks_entered']}/${x['roster']} marked'),
                              trailing: const Icon(Icons.chevron_right),
                              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                                  builder: (_) => MarksEntryScreen(assessmentId: '${x['id']}', title: '${x['name']}'))),
                            ),
                        ]),
                      ),
                    ],
                  ),
              ]),
      ),
    );
  }
}

class MarksEntryScreen extends ConsumerStatefulWidget {
  const MarksEntryScreen({super.key, required this.assessmentId, required this.title});

  final String assessmentId;
  final String title;

  @override
  ConsumerState<MarksEntryScreen> createState() => _MarksEntryScreenState();
}

class _MarksEntryScreenState extends ConsumerState<MarksEntryScreen> {
  Map<String, dynamic>? _grid;
  final Map<String, Map<String, dynamic>> _edits = {};
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final g = await ref.read(assessmentRepositoryProvider).grid(widget.assessmentId);
      setState(() => _grid = g);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  Future<void> _act(Future<void> Function() f, String done) async {
    setState(() => _busy = true);
    try {
      await f();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      _edits.clear();
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final g = _grid;
    final repo = ref.read(assessmentRepositoryProvider);
    if (g == null) return Scaffold(appBar: AppBar(title: Text(widget.title)), body: const Center(child: CircularProgressIndicator()));
    final qs = ((g['questions'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final rows = ((g['rows'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final readOnly = g['read_only'] == true;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title), actions: [
        if (!readOnly)
          IconButton(
              icon: const Icon(Icons.save),
              onPressed: _busy || _edits.isEmpty
                  ? null
                  : () => _act(
                      () => repo.save(widget.assessmentId, [
                            for (final e in _edits.entries) {'student_program_enrollment_id': e.key, ...e.value}
                          ]),
                      'Saved')),
        if (!readOnly)
          IconButton(icon: const Icon(Icons.send), onPressed: _busy ? null : () => _act(() => repo.submit(widget.assessmentId), 'Submitted')),
      ]),
      body: ListView.builder(
        itemCount: rows.length,
        itemBuilder: (context, i) {
          final r = rows[i];
          final id = '${r['student_program_enrollment_id']}';
          final qw = Map<String, dynamic>.from((r['question_wise'] as Map?) ?? const {});
          return Card(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${r['registration_number']} · ${r['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                Wrap(spacing: 8, children: [
                  if (qs.isEmpty)
                    SizedBox(
                      width: 90,
                      child: TextFormField(
                        enabled: !readOnly,
                        initialValue: r['marks']?.toString() ?? '',
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(labelText: '/${g['assessment']['max_marks']}'),
                        onChanged: (v) => _edits[id] = {'marks': double.tryParse(v)},
                      ),
                    ),
                  for (final q in qs)
                    SizedBox(
                      width: 70,
                      child: TextFormField(
                        enabled: !readOnly,
                        initialValue: qw['${q['question_no']}']?.toString() ?? '',
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(labelText: '${q['question_no']} /${q['max_marks']}'),
                        onChanged: (v) {
                          final cur = Map<String, dynamic>.from((_edits[id]?['question_wise'] as Map?) ?? qw);
                          cur['${q['question_no']}'] = double.tryParse(v);
                          cur.removeWhere((k, v) => v == null || k.startsWith('_'));
                          _edits[id] = {'question_wise': cur};
                        },
                      ),
                    ),
                  FilterChip(
                    label: const Text('AB'),
                    selected: (_edits[id]?['is_absent'] ?? r['is_absent']) == true,
                    onSelected: readOnly ? null : (v) => setState(() => _edits[id] = {...?_edits[id], 'is_absent': v}),
                  ),
                ]),
              ]),
            ),
          );
        },
      ),
    );
  }
}

// ---- HOD verification --------------------------------------------------------------------------------------------------
class MarksVerificationScreen extends ConsumerStatefulWidget {
  const MarksVerificationScreen({super.key});

  @override
  ConsumerState<MarksVerificationScreen> createState() => _MarksVerificationScreenState();
}

class _MarksVerificationScreenState extends ConsumerState<MarksVerificationScreen> {
  late Future<List<Map<String, dynamic>>> _q = ref.read(assessmentRepositoryProvider).queue('submitted');

  Future<void> _decide(String id, String decision) async {
    try {
      await ref.read(assessmentRepositoryProvider).verify(id, decision, decision == 'reject' ? 'Please recheck' : null);
      setState(() => _q = ref.read(assessmentRepositoryProvider).queue('submitted'));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Marks verification')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _q,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final a in snap.data!)
                    Card(
                      child: ListTile(
                        title: Text('${a['course_code']} ${a['section_code']} · ${a['name']}'),
                        subtitle: Text('${a['marks_entered']} marked'),
                        trailing: Wrap(children: [
                          IconButton(icon: const Icon(Icons.check, color: Colors.green), onPressed: () => _decide('${a['id']}', 'approve')),
                          IconButton(icon: const Icon(Icons.undo, color: Colors.orange), onPressed: () => _decide('${a['id']}', 'reject')),
                        ]),
                      ),
                    ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('Nothing to verify.')),
                ]),
        ),
      );
}

// ---- student marks / courses ---------------------------------------------------------------------------------------------
class StudentMarksScreen extends ConsumerWidget {
  const StudentMarksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        appBar: AppBar(title: const Text('My courses & marks')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: ref.read(assessmentRepositoryProvider).myMarks(),
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final m in snap.data!)
                    Card(
                      child: ListTile(
                        title: Text('${m['course_code']} · ${m['course_title']}'),
                        subtitle: Text([
                          for (final c in ((m['components'] as List?) ?? const []).cast<Map<String, dynamic>>())
                            '${c['name']}: ${c['is_absent'] == true ? 'AB' : c['marks'] ?? '—'}/${c['max_marks']}'
                        ].join(' · ')),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                            builder: (_) => StudentCourseScreen(offeringId: '${m['offering_id']}', title: '${m['course_code']}'))),
                      ),
                    ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('No courses yet.')),
                ]),
        ),
      );
}

class StudentCourseScreen extends ConsumerWidget {
  const StudentCourseScreen({super.key, required this.offeringId, required this.title});

  final String offeringId;
  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(assessmentRepositoryProvider);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(title: Text(title), bottom: const TabBar(tabs: [Tab(text: 'Content'), Tab(text: 'Assignments'), Tab(text: 'Quizzes')])),
        body: TabBarView(children: [
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.modules(offeringId),
            builder: (context, snap) => ListView(children: [
              for (final m in snap.data ?? const <Map<String, dynamic>>[])
                ExpansionTile(title: Text('${m['title']}'), children: [
                  for (final c in ((m['contents'] as List?) ?? const []).cast<Map<String, dynamic>>())
                    ListTile(
                      leading: const Icon(Icons.description_outlined),
                      title: Text('${c['title']}'),
                      subtitle: Text('${c['content_type']}${c['my_progress'] != null ? ' · ${c['my_progress']}%' : ''}'),
                      onTap: () => repo.view('${c['id']}'),
                    ),
                ]),
            ]),
          ),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.assignments(offeringId),
            builder: (context, snap) => ListView(children: [
              for (final a in snap.data ?? const <Map<String, dynamic>>[])
                ListTile(
                  title: Text('${a['title']}'),
                  subtitle: Text('${a['status']} · due ${a['due_at'] ?? '—'}${a['my_submission'] != null ? ' · ${a['my_submission']['status']}' : ''}'),
                  trailing: a['status'] == 'published' && a['my_submission'] == null
                      ? TextButton(
                          onPressed: () async {
                            final c = TextEditingController();
                            final ok = await showDialog<bool>(
                              context: context,
                              builder: (_) => AlertDialog(
                                title: const Text('Submit'),
                                content: TextField(controller: c, maxLines: 5),
                                actions: [FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Submit'))],
                              ),
                            );
                            if (ok == true) {
                              try {
                                await repo.submitAssignment('${a['id']}', c.text);
                              } catch (e) {
                                if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
                              }
                            }
                          },
                          child: const Text('Submit'))
                      : null,
                ),
            ]),
          ),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.quizzes(offeringId),
            builder: (context, snap) => ListView(children: [
              for (final q in snap.data ?? const <Map<String, dynamic>>[])
                ListTile(
                  title: Text('${q['title']}'),
                  subtitle: Text('${q['duration_minutes']} min · ${q['status']}'),
                  trailing: q['status'] == 'published'
                      ? TextButton(
                          onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => QuizScreen(quizId: '${q['id']}'))),
                          child: const Text('Start'))
                      : null,
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class QuizScreen extends ConsumerStatefulWidget {
  const QuizScreen({super.key, required this.quizId});

  final String quizId;

  @override
  ConsumerState<QuizScreen> createState() => _QuizScreenState();
}

class _QuizScreenState extends ConsumerState<QuizScreen> {
  Map<String, dynamic>? _attempt;
  final Map<String, dynamic> _answers = {};
  bool _dirty = false;
  Timer? _timer;
  int _left = 0;

  @override
  void initState() {
    super.initState();
    ref.read(assessmentRepositoryProvider).start(widget.quizId).then((a) {
      setState(() {
        _attempt = a;
        _answers.addAll(Map<String, dynamic>.from((a['answers'] as Map?) ?? const {}));
      });
      _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    }).catchError((Object e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
        Navigator.pop(context);
      }
    });
  }

  void _tick() {
    final a = _attempt;
    if (a == null) return;
    final left = DateTime.parse('${a['ends_at']}').difference(DateTime.now()).inSeconds;
    setState(() => _left = left < 0 ? 0 : left);
    if (_dirty && DateTime.now().second % 5 == 0) {
      _dirty = false;
      ref.read(assessmentRepositoryProvider).saveAnswers('${a['attempt_id']}', _answers).catchError((_) => _dirty = true);
    }
    if (left <= 0) _submit();
  }

  Future<void> _submit() async {
    final a = _attempt;
    if (a == null) return;
    _timer?.cancel();
    try {
      await ref.read(assessmentRepositoryProvider).saveAnswers('${a['attempt_id']}', _answers);
      final r = await ref.read(assessmentRepositoryProvider).submitAttempt('${a['attempt_id']}');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(r['show_result'] == true ? 'Score ${r['total_score']}' : 'Submitted')));
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final qs = ((_attempt?['questions'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return Scaffold(
      appBar: AppBar(title: Text('${_left ~/ 60}:${(_left % 60).toString().padLeft(2, '0')} left'), actions: [
        TextButton(onPressed: _submit, child: const Text('Submit')),
      ]),
      body: _attempt == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(12), children: [
              for (final (i, q) in qs.indexed)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(8),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${i + 1}. ${q['body_primary']}'),
                      for (final o in ((q['options'] as List?) ?? const []).cast<Map<String, dynamic>>())
                        ListTile(
                          dense: true,
                          leading: Icon(_answers['${q['question_id']}'] == o['id'] ? Icons.radio_button_checked : Icons.radio_button_unchecked),
                          title: Text('(${o['label']}) ${o['body_primary']}'),
                          onTap: () => setState(() {
                            _answers['${q['question_id']}'] = o['id'];
                            _dirty = true;
                          }),
                        ),
                    ]),
                  ),
                ),
            ]),
    );
  }
}

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/providers.dart';

/// Phase 27 mobile (Prompts/27 §27.10): faculty **Mentees** (cards with risk chips → 360°, log a session — dictate notes
/// with the keyboard microphone — action items, confidential toggle, refer) and **Slots**; HOD **High-risk** list
/// (acknowledge); student **Mentor** (book, sessions, action items), **Grievances** (raise incl. anonymous, track,
/// rate), **Discipline** (notices, statement), **Surveys** (pending → quick forms), **Clubs** (join, log hours with a
/// photo, ledger, achievements); parent **Support** (book the mentor, shared notes, ward grievances, notices);
/// grievance officer **Grievance board** (triage / resolve with SLA); officers **Hours verification** with evidence.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _day(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month}/${d.year}';
}

String _when(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

String _today() => DateTime.now().toIso8601String().substring(0, 10);

class SupportRepository {
  SupportRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  Future<dynamic> _put(String path, [Object? body]) async => (await _dio.put<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  // mentoring
  Future<List<Map<String, dynamic>>> mentees() async => _list(await _get('/mentoring/mentees'));
  Future<Map<String, dynamic>> mentee360(String enrollmentId) async => ((await _get('/mentoring/mentees/$enrollmentId/360')) as Map).cast<String, dynamic>();
  Future<void> logSession(Map<String, dynamic> body) => _post('/mentoring/sessions', body);
  Future<void> refer(String enrollmentId, String reason) => _post('/mentoring/referrals', {'enrollment_id': enrollmentId, 'reason': reason});
  Future<List<Map<String, dynamic>>> mySlots() async => _list(await _get('/mentoring/slots'));
  Future<void> publishSlot(DateTime start, int minutes, int weeks) => _post('/mentoring/slots', {
        'starts_at': start.toUtc().toIso8601String(),
        'ends_at': start.add(Duration(minutes: minutes)).toUtc().toIso8601String(),
        'repeat_weeks': weeks,
      });
  Future<void> bookingAction(String id, String action) => _post('/mentoring/bookings/$id/$action');
  Future<Map<String, dynamic>> myMentor() async => ((await _get('/mentoring/me')) as Map? ?? {}).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> wardMentors() async => _list(await _get('/mentoring/wards'));
  Future<void> book(String slotId) => _post('/mentoring/slots/$slotId/book', {});
  Future<List<Map<String, dynamic>>> mySessions() async => _list(await _get('/mentoring/sessions/me'));
  Future<void> tick(String sessionId, int idx, bool done) => _put('/mentoring/sessions/$sessionId/action-items/$idx', {'done': done});
  // risk
  Future<List<Map<String, dynamic>>> highRisk() async => _list(await _get('/risk/flags', {'level': 'high'}));
  Future<void> acknowledge(String id, String action) => _post('/risk/flags/$id/acknowledge', {'action': action});
  // grievances
  Future<Map<String, dynamic>> raise(Map<String, dynamic> body) async => ((await _post('/grievances', body)) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> myGrievances({bool wards = false}) async => _list(await _get(wards ? '/grievances/wards' : '/grievances/me'));
  Future<void> rate(String id, int rating) => _post('/grievances/$id/rate', {'rating': rating});
  Future<void> reopen(String id, String reason) => _post('/grievances/$id/reopen', {'reason': reason});
  Future<List<Map<String, dynamic>>> board() async => _list(await _get('/grievances'));
  Future<void> triage(String id, Map<String, dynamic> body) => _post('/grievances/$id/triage', body);
  Future<void> resolve(String id, String resolution) => _post('/grievances/$id/resolve', {'resolution': resolution});
  // discipline
  Future<List<Map<String, dynamic>>> myCases() async => _list(await _get('/discipline/cases/me'));
  Future<void> statement(String id, String text) => _post('/discipline/cases/$id/statement', {'text': text});
  // surveys
  Future<List<Map<String, dynamic>>> pendingSurveys() async => _list(await _get('/surveys/me/pending'));
  Future<Map<String, dynamic>> form(String id, String? target) async =>
      ((await _get('/surveys/$id/form', {if (target != null) 'target_id': target})) as Map).cast<String, dynamic>();
  Future<void> respond(String id, String? target, Map<String, dynamic> answers) => _post('/surveys/$id/respond', {'target_id': target, 'answers': answers});
  // clubs
  Future<List<Map<String, dynamic>>> clubs() async => _list(await _get('/clubs'));
  Future<void> join(String id) => _post('/clubs/$id/join');
  Future<String?> uploadEvidence(XFile file) async {
    final form = FormData.fromMap({'file': await MultipartFile.fromFile(file.path, filename: file.name)});
    final r = await _dio.post<Map<String, dynamic>>('/activity-hours/evidence', data: form);
    return (r.data?['data'] as Map?)?['evidence_url'] as String?;
  }

  Future<void> logHours(Map<String, dynamic> body) => _post('/activity-hours', body);
  Future<Map<String, dynamic>> ledger() async => ((await _get('/activity-hours/ledger')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> myAchievements() async => _list(await _get('/achievements/me'));
  Future<void> submitAchievement(Map<String, dynamic> body) => _post('/achievements', body);
  Future<List<Map<String, dynamic>>> pendingHours() async => _list(await _get('/activity-hours', {'status': 'pending'}));
  Future<void> verifyHours(List<String> ids, bool approve) => _post('/activity-hours/verify', {'ids': ids, 'approve': approve});
}

final supportRepositoryProvider = Provider<SupportRepository>((ref) => SupportRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<void> _act(BuildContext context, Future<void> Function() fn, String done, VoidCallback refresh) async {
  try {
    await fn();
    if (context.mounted) _snack(context, done);
    refresh();
  } catch (e) {
    if (context.mounted) _snack(context, _error(e));
  }
}

Future<String?> _ask(BuildContext context, String title, {String hint = ''}) async {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, maxLines: 4, decoration: InputDecoration(hintText: hint)),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('OK'))],
    ),
  );
}

Widget _futureList(Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing yet'}) => FutureBuilder<List<Map<String, dynamic>>>(
      future: f,
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        if (snap.data!.isEmpty) return Padding(padding: const EdgeInsets.all(16), child: Text(empty));
        return Column(children: [for (final r in snap.data!) row(r)]);
      },
    );

Widget _riskChip(dynamic level) {
  if (level == null) return const SizedBox.shrink();
  final color = level == 'high' ? Colors.red : level == 'medium' ? Colors.orange : Colors.green;
  return Chip(label: Text('$level'), backgroundColor: color.withValues(alpha: 0.15), visualDensity: VisualDensity.compact);
}

Widget _header(String text) => Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600)));

// ---- faculty: mentees + 360 + slots ---------------------------------------------------------------------------------------
class MenteesScreen extends ConsumerStatefulWidget {
  const MenteesScreen({super.key});

  @override
  ConsumerState<MenteesScreen> createState() => _MenteesScreenState();
}

class _MenteesScreenState extends ConsumerState<MenteesScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.mentees();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('My mentees'), actions: [
          IconButton(icon: const Icon(Icons.event_available_outlined), tooltip: 'Slots', onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MentorSlotsScreen()))),
        ]),
        body: RefreshIndicator(
          onRefresh: () async => setState(() => _f = _repo.mentees()),
          child: ListView(children: [
            _futureList(
              _f,
              (m) => ListTile(
                title: Text('${m['student_name'] ?? ''}'),
                subtitle: Text('${m['registration_number'] ?? ''} · ${m['sessions']} session(s)'),
                trailing: _riskChip(m['risk_level']),
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => Mentee360Screen(enrollmentId: '${m['student_program_enrollment_id']}', assignmentId: '${m['id']}'))),
              ),
              empty: 'No mentees this term',
            ),
          ]),
        ),
      );
}

class Mentee360Screen extends ConsumerStatefulWidget {
  const Mentee360Screen({super.key, required this.enrollmentId, required this.assignmentId});

  final String enrollmentId;
  final String assignmentId;

  @override
  ConsumerState<Mentee360Screen> createState() => _Mentee360ScreenState();
}

class _Mentee360ScreenState extends ConsumerState<Mentee360Screen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<Map<String, dynamic>> _f = _repo.mentee360(widget.enrollmentId);

  Future<void> _logSession() async {
    final notes = TextEditingController();
    final items = TextEditingController();
    var confidential = false;
    var share = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Log session'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: notes, maxLines: 5, decoration: const InputDecoration(labelText: 'Notes (tap the keyboard mic to dictate)')),
              TextField(controller: items, maxLines: 3, decoration: const InputDecoration(labelText: 'Action items (one per line)')),
              SwitchListTile(value: confidential, title: const Text('Confidential'), onChanged: (v) => set(() => confidential = v)),
              SwitchListTile(value: share, title: const Text('Share summary with guardian'), onChanged: (v) => set(() => share = v)),
            ]),
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save'))],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    await _act(
      context,
      () => _repo.logSession({
        'assignment_id': widget.assignmentId,
        'held_on': _today(),
        'notes': notes.text,
        'action_items': [for (final t in items.text.split('\n').where((x) => x.trim().isNotEmpty)) {'text': t.trim(), 'owner': 'student'}],
        'is_confidential': confidential,
        'share_with_guardian': share,
        if (share) 'guardian_summary': notes.text.length > 300 ? notes.text.substring(0, 300) : notes.text,
      }),
      'Session logged',
      () => setState(() => _f = _repo.mentee360(widget.enrollmentId)),
    );
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: _f,
        builder: (context, snap) {
          final p = snap.data ?? const {};
          final student = (p['student'] as Map?) ?? const {};
          return Scaffold(
            appBar: AppBar(title: Text('${student['name'] ?? 'Mentee'}')),
            floatingActionButton: FloatingActionButton.extended(onPressed: _logSession, icon: const Icon(Icons.edit_note), label: const Text('Log session')),
            body: snap.hasError
                ? Center(child: Text(_error(snap.error!)))
                : !snap.hasData
                    ? const Center(child: CircularProgressIndicator())
                    : ListView(children: [
                        ListTile(title: const Text('Attendance'), trailing: Text('${p['attendance_pct'] ?? '—'}%')),
                        ListTile(title: const Text('CIA average (scaled)'), trailing: Text('${(p['cia_summary'] as Map?)?['avg_scaled'] ?? '—'}')),
                        ListTile(title: const Text('Overdue dues'), trailing: Text('₹${((((p['dues'] as Map?)?['overdue_paise'] ?? 0) as num) / 100).toStringAsFixed(0)}')),
                        ListTile(title: const Text('Open holds'), trailing: Text('${(p['holds'] as List?)?.length ?? 0}')),
                        ListTile(title: const Text('Risk'), trailing: _riskChip((p['risk'] as Map?)?['level'])),
                        _header('Sessions'),
                        for (final s in ((p['sessions'] as List?) ?? const []).cast<Map<String, dynamic>>())
                          ListTile(
                            leading: Icon(s['is_confidential'] == true ? Icons.lock_outline : Icons.chat_bubble_outline),
                            title: Text(_day(s['held_on'])),
                            subtitle: Text(s['redacted'] == true ? 'Confidential' : '${s['notes'] ?? ''}'),
                          ),
                        Padding(
                          padding: const EdgeInsets.all(16),
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.support_agent),
                            label: const Text('Refer to counselling'),
                            onPressed: () async {
                              final reason = await _ask(context, 'Reason for referral');
                              if (reason == null || reason.length < 3 || !context.mounted) return;
                              await _act(context, () => _repo.refer(widget.enrollmentId, reason), 'Referred', () {});
                            },
                          ),
                        ),
                        const SizedBox(height: 80),
                      ]),
          );
        },
      );
}

class MentorSlotsScreen extends ConsumerStatefulWidget {
  const MentorSlotsScreen({super.key});

  @override
  ConsumerState<MentorSlotsScreen> createState() => _MentorSlotsScreenState();
}

class _MentorSlotsScreenState extends ConsumerState<MentorSlotsScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.mySlots();

  void _refresh() => setState(() => _f = _repo.mySlots());

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Mentoring slots')),
        floatingActionButton: FloatingActionButton(
          child: const Icon(Icons.add),
          onPressed: () async {
            final d = await showDatePicker(context: context, firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 90)));
            if (d == null || !context.mounted) return;
            final t = await showTimePicker(context: context, initialTime: const TimeOfDay(hour: 10, minute: 0));
            if (t == null || !context.mounted) return;
            await _act(context, () => _repo.publishSlot(DateTime(d.year, d.month, d.day, t.hour, t.minute), 30, 3), 'Published (4 weeks)', _refresh);
          },
        ),
        body: ListView(children: [
          _futureList(
            _f,
            (s) => ExpansionTile(
              title: Text(_when(s['starts_at'])),
              subtitle: Text('${s['booked']}/${s['capacity']} booked'),
              children: [
                for (final b in ((s['bookings'] as List?) ?? const []).cast<Map<String, dynamic>>())
                  ListTile(
                    title: Text('${b['student_name'] ?? b['guardian_name'] ?? ''}'),
                    subtitle: Text('${b['status']}'),
                    trailing: b['status'] == 'booked'
                        ? Wrap(children: [
                            IconButton(icon: const Icon(Icons.check), onPressed: () => _act(context, () => _repo.bookingAction('${b['id']}', 'attended'), 'Marked attended', _refresh)),
                            IconButton(icon: const Icon(Icons.close), onPressed: () => _act(context, () => _repo.bookingAction('${b['id']}', 'no-show'), 'Marked no-show', _refresh)),
                          ])
                        : null,
                  ),
              ],
            ),
            empty: 'No slots published',
          ),
        ]),
      );
}

// ---- HOD: high-risk -------------------------------------------------------------------------------------------------------
class HighRiskScreen extends ConsumerStatefulWidget {
  const HighRiskScreen({super.key});

  @override
  ConsumerState<HighRiskScreen> createState() => _HighRiskScreenState();
}

class _HighRiskScreenState extends ConsumerState<HighRiskScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.highRisk();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('High-risk students')),
        body: RefreshIndicator(
          onRefresh: () async => setState(() => _f = _repo.highRisk()),
          child: ListView(children: [
            _futureList(
              _f,
              (r) => ListTile(
                title: Text('${r['student_name'] ?? ''}'),
                subtitle: Text('Score ${r['score']} · attendance ${((r['factors'] as Map?)?['attendance'] as Map?)?['avg_pct'] ?? '—'}%'),
                trailing: r['acknowledged'] == true
                    ? const Icon(Icons.verified_outlined, color: Colors.green)
                    : TextButton(
                        child: const Text('Acknowledge'),
                        onPressed: () async {
                          final a = await _ask(context, 'Action taken');
                          if (a == null || a.length < 3 || !context.mounted) return;
                          await _act(context, () => _repo.acknowledge('${r['id']}', a), 'Acknowledged', () => setState(() => _f = _repo.highRisk()));
                        },
                      ),
              ),
              empty: 'No high-risk students',
            ),
          ]),
        ),
      );
}

// ---- student: mentor ------------------------------------------------------------------------------------------------------
class MyMentorScreen extends ConsumerStatefulWidget {
  const MyMentorScreen({super.key});

  @override
  ConsumerState<MyMentorScreen> createState() => _MyMentorScreenState();
}

class _MyMentorScreenState extends ConsumerState<MyMentorScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<Map<String, dynamic>> _m = _repo.myMentor();
  late Future<List<Map<String, dynamic>>> _s = _repo.mySessions();

  void _refresh() => setState(() {
        _m = _repo.myMentor();
        _s = _repo.mySessions();
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('My mentor')),
        body: RefreshIndicator(
          onRefresh: () async => _refresh(),
          child: ListView(children: [
            FutureBuilder<Map<String, dynamic>>(
              future: _m,
              builder: (context, snap) {
                if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
                final m = snap.data ?? const {};
                return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  ListTile(leading: const Icon(Icons.person_outline), title: Text('${m['mentor_name'] ?? 'Not assigned yet'}'), subtitle: Text('${m['mentor_email'] ?? ''}')),
                  _header('Book a slot'),
                  Wrap(spacing: 8, children: [
                    for (final s in ((m['next_slots'] as List?) ?? const []).cast<Map<String, dynamic>>())
                      ActionChip(label: Text(_when(s['starts_at'])), onPressed: () => _act(context, () => _repo.book('${s['id']}'), 'Booked', _refresh)),
                  ]),
                  _header('Action items'),
                  for (final a in ((m['open_action_items'] as List?) ?? const []).cast<Map<String, dynamic>>())
                    CheckboxListTile(
                      value: false,
                      title: Text('${a['text']}'),
                      subtitle: a['due_on'] != null ? Text('Due ${_day(a['due_on'])}') : null,
                      onChanged: (_) => _act(context, () => _repo.tick('${a['session_id']}', (a['index'] as num).toInt(), true), 'Done', _refresh),
                    ),
                ]);
              },
            ),
            _header('Sessions'),
            _futureList(_s, (s) => ListTile(leading: Icon(s['redacted'] == true ? Icons.lock_outline : Icons.chat_bubble_outline), title: Text(_day(s['held_on'])), subtitle: Text(s['redacted'] == true ? 'Confidential' : '${s['notes'] ?? ''}'))),
          ]),
        ),
      );
}

// ---- grievances (student / parent) ------------------------------------------------------------------------------------------
class GrievancesScreen extends ConsumerStatefulWidget {
  const GrievancesScreen({super.key, this.wards = false});

  final bool wards;

  @override
  ConsumerState<GrievancesScreen> createState() => _GrievancesScreenState();
}

class _GrievancesScreenState extends ConsumerState<GrievancesScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.myGrievances(wards: widget.wards);
  static const _cats = ['academic', 'exam', 'fee', 'hostel', 'harassment', 'ragging', 'discrimination', 'infrastructure', 'other'];

  void _refresh() => setState(() => _f = _repo.myGrievances(wards: widget.wards));

  Future<void> _raise() async {
    var cat = 'academic';
    var anon = false;
    final desc = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Raise a grievance'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(value: cat, items: [for (final c in _cats) DropdownMenuItem(value: c, child: Text(c))], onChanged: (v) => set(() => cat = v ?? cat)),
            TextField(controller: desc, maxLines: 4, decoration: const InputDecoration(labelText: 'What happened?')),
            if (!widget.wards) SwitchListTile(value: anon, title: const Text('Anonymous'), onChanged: (v) => set(() => anon = v)),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Submit'))],
        ),
      ),
    );
    if (ok != true || desc.text.trim().length < 10 || !mounted) return;
    try {
      final r = await _repo.raise({'category': cat, 'description': desc.text.trim(), 'is_anonymous': anon});
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Ticket ${r['ticket_number']}'),
          content: Text(r['tracking_secret'] != null ? 'Keep this secret to track your anonymous grievance (shown once):\n\n${r['tracking_secret']}' : 'Routed to ${r['committee'] ?? 'the grievance cell'}.'),
          actions: [FilledButton(onPressed: () => Navigator.pop(ctx), child: const Text('OK'))],
        ),
      );
      _refresh();
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.wards ? 'Ward grievances' : 'My grievances')),
        floatingActionButton: FloatingActionButton.extended(onPressed: _raise, icon: const Icon(Icons.add_comment_outlined), label: const Text('Raise')),
        body: RefreshIndicator(
          onRefresh: () async => _refresh(),
          child: ListView(children: [
            _futureList(
              _f,
              (g) => ListTile(
                title: Text('${g['ticket_number']} · ${g['category']}'),
                subtitle: Text('${g['status']}${g['sla_due_at'] != null ? ' · SLA ${_when(g['sla_due_at'])}' : ''}'),
                trailing: ['resolved', 'closed'].contains(g['status']) && g['satisfaction_rating'] == null
                    ? PopupMenuButton<int>(
                        icon: const Icon(Icons.star_outline),
                        itemBuilder: (_) => [for (var i = 5; i >= 1; i--) PopupMenuItem(value: i, child: Text('$i ★'))],
                        onSelected: (v) => _act(context, () => _repo.rate('${g['id']}', v), 'Thank you', _refresh),
                      )
                    : null,
                onLongPress: ['resolved', 'closed'].contains(g['status'])
                    ? () async {
                        final r = await _ask(context, 'Reopen — why?');
                        if (r == null || r.length < 3 || !context.mounted) return;
                        await _act(context, () => _repo.reopen('${g['id']}', r), 'Reopened', _refresh);
                      }
                    : null,
              ),
              empty: 'No grievances',
            ),
          ]),
        ),
      );
}

// ---- grievance officer board ----------------------------------------------------------------------------------------------
class GrievanceBoardScreen extends ConsumerStatefulWidget {
  const GrievanceBoardScreen({super.key});

  @override
  ConsumerState<GrievanceBoardScreen> createState() => _GrievanceBoardScreenState();
}

class _GrievanceBoardScreenState extends ConsumerState<GrievanceBoardScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.board();
  static const _cols = ['open', 'acknowledged', 'under_review', 'escalated', 'reopened', 'resolved'];

  void _refresh() => setState(() => _f = _repo.board());

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: _cols.length,
        child: Scaffold(
          appBar: AppBar(title: const Text('Grievance board'), bottom: TabBar(isScrollable: true, tabs: [for (final c in _cols) Tab(text: c.replaceAll('_', ' '))])),
          body: FutureBuilder<List<Map<String, dynamic>>>(
            future: _f,
            builder: (context, snap) {
              if (snap.hasError) return Center(child: Text(_error(snap.error!)));
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              return TabBarView(children: [
                for (final c in _cols)
                  RefreshIndicator(
                    onRefresh: () async => _refresh(),
                    child: ListView(children: [
                      for (final g in snap.data!.where((x) => x['status'] == c))
                        ListTile(
                          leading: Icon(g['confidential'] == true ? Icons.lock_outline : Icons.report_outlined, color: g['sla_breached'] == true ? Colors.red : null),
                          title: Text('${g['ticket_number']} · ${g['category']}'),
                          subtitle: Text('${g['committee'] ?? ''} · SLA ${_when(g['sla_due_at'])}'),
                          trailing: PopupMenuButton<String>(
                            itemBuilder: (_) => const [
                              PopupMenuItem(value: 'ack', child: Text('Acknowledge')),
                              PopupMenuItem(value: 'review', child: Text('Under review')),
                              PopupMenuItem(value: 'resolve', child: Text('Resolve')),
                            ],
                            onSelected: (v) async {
                              if (v == 'resolve') {
                                final r = await _ask(context, 'Resolution');
                                if (r == null || r.length < 3 || !context.mounted) return;
                                await _act(context, () => _repo.resolve('${g['id']}', r), 'Resolved', _refresh);
                              } else {
                                await _act(context, () => _repo.triage('${g['id']}', {'status': v == 'ack' ? 'acknowledged' : 'under_review'}), 'Updated', _refresh);
                              }
                            },
                          ),
                        ),
                    ]),
                  ),
              ]);
            },
          ),
        ),
      );
}

// ---- discipline notices --------------------------------------------------------------------------------------------------
class DisciplineNoticesScreen extends ConsumerStatefulWidget {
  const DisciplineNoticesScreen({super.key});

  @override
  ConsumerState<DisciplineNoticesScreen> createState() => _DisciplineNoticesScreenState();
}

class _DisciplineNoticesScreenState extends ConsumerState<DisciplineNoticesScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.myCases();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Disciplinary notices')),
        body: ListView(children: [
          _futureList(
            _f,
            (c) => ExpansionTile(
              title: Text('${c['case_number']} · ${c['category']}'),
              subtitle: Text('${c['status']}'),
              children: [
                for (final n in ((c['notices'] as List?) ?? const []).cast<Map<String, dynamic>>()) ListTile(title: Text('${n['text']}'), subtitle: Text(_when(n['at']))),
                if (c['hearing_at'] != null) ListTile(leading: const Icon(Icons.event), title: Text('Hearing ${_when(c['hearing_at'])}')),
                if (c['is_subject'] == true && !['decided', 'closed', 'appealed'].contains(c['status']))
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Submit statement'),
                    onPressed: () async {
                      final t = await _ask(context, 'Your statement');
                      if (t == null || t.length < 5 || !context.mounted) return;
                      await _act(context, () => _repo.statement('${c['id']}', t), 'Submitted', () => setState(() => _f = _repo.myCases()));
                    },
                  ),
              ],
            ),
            empty: 'No cases',
          ),
        ]),
      );
}

// ---- surveys ---------------------------------------------------------------------------------------------------------------
class SurveysScreen extends ConsumerStatefulWidget {
  const SurveysScreen({super.key});

  @override
  ConsumerState<SurveysScreen> createState() => _SurveysScreenState();
}

class _SurveysScreenState extends ConsumerState<SurveysScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.pendingSurveys();

  Future<void> _open(String surveyId, Map<String, dynamic> target) async {
    final form = await _repo.form(surveyId, target['target_id'] as String?);
    if (!mounted) return;
    final answers = <String, dynamic>{};
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => SafeArea(
          child: Padding(
            padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
            child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(16), children: [
              Text('${form['title']}${target['label'] != null ? ' — ${target['label']}' : ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
              for (final q in ((form['questions'] as List?) ?? const []).cast<Map<String, dynamic>>()) ...[
                const SizedBox(height: 12),
                Text('${q['text']}'),
                if (q['type'] == 'text')
                  TextField(onChanged: (v) => answers['${q['id']}'] = v)
                else
                  Wrap(spacing: 6, children: [
                    for (var v = (q['scale'] == 4 ? 0 : 1); v <= ((q['scale'] as num?)?.toInt() ?? 5); v++)
                      ChoiceChip(label: Text('$v'), selected: answers['${q['id']}'] == v, onSelected: (_) => set(() => answers['${q['id']}'] = v)),
                  ]),
              ],
              const SizedBox(height: 16),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Submit')),
            ]),
          ),
        ),
      ),
    );
    if (ok != true || !mounted) return;
    await _act(context, () => _repo.respond(surveyId, target['target_id'] as String?, answers), 'Thank you', () => setState(() => _f = _repo.pendingSurveys()));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Surveys')),
        body: ListView(children: [
          _futureList(
            _f,
            (s) => ExpansionTile(
              initiallyExpanded: true,
              title: Text('${s['title']}'),
              subtitle: Text('Closes ${_when(s['closes_at'])}'),
              children: [
                for (final t in ((s['targets'] as List?) ?? const []).cast<Map<String, dynamic>>())
                  ListTile(
                    title: Text('${t['label'] ?? 'Respond'}'),
                    trailing: t['responded'] == true ? const Icon(Icons.check, color: Colors.green) : const Icon(Icons.chevron_right),
                    onTap: t['responded'] == true ? null : () => _open('${s['survey_id']}', t),
                  ),
              ],
            ),
            empty: 'Nothing pending',
          ),
        ]),
      );
}

// ---- clubs / hours / achievements ------------------------------------------------------------------------------------------
class ClubsScreen extends ConsumerStatefulWidget {
  const ClubsScreen({super.key});

  @override
  ConsumerState<ClubsScreen> createState() => _ClubsScreenState();
}

class _ClubsScreenState extends ConsumerState<ClubsScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _clubs = _repo.clubs();
  late Future<Map<String, dynamic>> _ledger = _repo.ledger();
  late Future<List<Map<String, dynamic>>> _ach = _repo.myAchievements();

  void _refresh() => setState(() {
        _clubs = _repo.clubs();
        _ledger = _repo.ledger();
        _ach = _repo.myAchievements();
      });

  Future<void> _logHours() async {
    var type = 'nss';
    final hours = TextEditingController(text: '2');
    final desc = TextEditingController();
    XFile? photo;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Log activity hours'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(value: type, items: [for (final t in const ['nss', 'ncc', 'community_service', 'club', 'sports']) DropdownMenuItem(value: t, child: Text(t))], onChanged: (v) => set(() => type = v ?? type)),
            TextField(controller: hours, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Hours')),
            TextField(controller: desc, decoration: const InputDecoration(labelText: 'What did you do?')),
            OutlinedButton.icon(
              icon: const Icon(Icons.photo_camera_outlined),
              label: Text(photo == null ? 'Photo evidence' : 'Photo attached'),
              onPressed: () async {
                final f = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 70);
                if (f != null) set(() => photo = f);
              },
            ),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Log'))],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    await _act(context, () async {
      final evidence = photo != null ? await _repo.uploadEvidence(photo!) : null;
      await _repo.logHours({'activity_type': type, 'hours': double.tryParse(hours.text) ?? 0, 'on_date': _today(), 'description': desc.text, 'evidence_url': evidence});
    }, 'Logged — awaiting verification', _refresh);
  }

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 3,
        child: Scaffold(
          appBar: AppBar(title: const Text('Clubs & activities'), bottom: const TabBar(tabs: [Tab(text: 'Clubs'), Tab(text: 'Hours'), Tab(text: 'Achievements')])),
          floatingActionButton: FloatingActionButton(onPressed: _logHours, child: const Icon(Icons.more_time)),
          body: TabBarView(children: [
            ListView(children: [
              _futureList(
                _clubs,
                (c) => ListTile(
                  title: Text('${c['name']}'),
                  subtitle: Text('${c['club_type']} · ${c['members']} members'),
                  trailing: c['my_role'] != null ? Chip(label: Text('${c['my_role']}')) : TextButton(onPressed: () => _act(context, () => _repo.join('${c['id']}'), 'Request sent', _refresh), child: const Text('Join')),
                ),
              ),
            ]),
            FutureBuilder<Map<String, dynamic>>(
              future: _ledger,
              builder: (context, snap) {
                if (snap.hasError) return Center(child: Text(_error(snap.error!)));
                final l = snap.data ?? const {};
                return ListView(children: [
                  ListTile(title: const Text('Total'), trailing: Text('${l['total'] ?? 0} h')),
                  ListTile(title: const Text('Verified'), trailing: Text('${l['verified'] ?? 0} h')),
                  ListTile(title: const Text('Pending'), trailing: Text('${l['pending'] ?? 0} h')),
                  for (final e in ((l['entries'] as List?) ?? const []).cast<Map<String, dynamic>>())
                    ListTile(title: Text('${e['activity_type']} · ${e['hours']} h'), subtitle: Text(_day(e['on_date'])), trailing: Text('${e['status']}')),
                ]);
              },
            ),
            ListView(children: [
              Padding(
                padding: const EdgeInsets.all(8),
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.emoji_events_outlined),
                  label: const Text('Submit an achievement'),
                  onPressed: () async {
                    final t = await _ask(context, 'Achievement title');
                    if (t == null || t.length < 2 || !context.mounted) return;
                    await _act(context, () => _repo.submitAchievement({'category': 'other', 'title': t}), 'Submitted for verification', _refresh);
                  },
                ),
              ),
              _futureList(_ach, (a) => ListTile(title: Text('${a['title']}'), subtitle: Text('${a['category']} · ${a['level'] ?? ''}'), trailing: Icon(a['verified'] == true ? Icons.verified : Icons.hourglass_empty))),
            ]),
          ]),
        ),
      );
}

class HoursVerificationScreen extends ConsumerStatefulWidget {
  const HoursVerificationScreen({super.key});

  @override
  ConsumerState<HoursVerificationScreen> createState() => _HoursVerificationScreenState();
}

class _HoursVerificationScreenState extends ConsumerState<HoursVerificationScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.pendingHours();
  final Set<String> _picked = {};

  void _refresh() => setState(() {
        _picked.clear();
        _f = _repo.pendingHours();
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Hours verification'), actions: [
          IconButton(icon: const Icon(Icons.close), tooltip: 'Reject', onPressed: _picked.isEmpty ? null : () => _act(context, () => _repo.verifyHours(_picked.toList(), false), 'Rejected', _refresh)),
          IconButton(icon: const Icon(Icons.done_all), tooltip: 'Verify', onPressed: _picked.isEmpty ? null : () => _act(context, () => _repo.verifyHours(_picked.toList(), true), 'Verified', _refresh)),
        ]),
        body: ListView(children: [
          _futureList(
            _f,
            (h) => CheckboxListTile(
              value: _picked.contains('${h['id']}'),
              onChanged: (v) => setState(() => v == true ? _picked.add('${h['id']}') : _picked.remove('${h['id']}')),
              title: Text('${h['student_name'] ?? ''} · ${h['activity_type']} · ${h['hours']} h'),
              subtitle: Text('${_day(h['on_date'])} · ${h['description'] ?? ''}${h['evidence_url'] != null ? ' · evidence attached' : ''}'),
            ),
            empty: 'Queue is empty',
          ),
        ]),
      );
}

// ---- parent support ---------------------------------------------------------------------------------------------------------
class ParentSupportScreen extends ConsumerStatefulWidget {
  const ParentSupportScreen({super.key});

  @override
  ConsumerState<ParentSupportScreen> createState() => _ParentSupportScreenState();
}

class _ParentSupportScreenState extends ConsumerState<ParentSupportScreen> {
  late final SupportRepository _repo = ref.read(supportRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _mentors = _repo.wardMentors();
  late final Future<List<Map<String, dynamic>>> _notes = _repo.mySessions();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Mentoring & support')),
        body: ListView(children: [
          _futureList(
            _mentors,
            (m) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              ListTile(leading: const Icon(Icons.person_outline), title: Text('${m['mentor_name'] ?? 'No mentor assigned'}')),
              Wrap(spacing: 8, children: [
                for (final s in ((m['next_slots'] as List?) ?? const []).cast<Map<String, dynamic>>())
                  ActionChip(label: Text(_when(s['starts_at'])), onPressed: () => _act(context, () => _repo.book('${s['id']}'), 'Meeting booked', () => setState(() => _mentors = _repo.wardMentors()))),
              ]),
            ]),
          ),
          _header('Shared meeting notes'),
          _futureList(_notes, (s) => s['guardian_summary'] == null ? const SizedBox.shrink() : ListTile(title: Text(_day(s['held_on'])), subtitle: Text('${s['guardian_summary']}'))),
          ListTile(leading: const Icon(Icons.report_outlined), title: const Text('Ward grievances'), onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const GrievancesScreen(wards: true)))),
          ListTile(leading: const Icon(Icons.gavel_outlined), title: const Text('Disciplinary notices'), onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const DisciplineNoticesScreen()))),
          ListTile(leading: const Icon(Icons.poll_outlined), title: const Text('Parent survey'), onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SurveysScreen()))),
        ]),
      );
}

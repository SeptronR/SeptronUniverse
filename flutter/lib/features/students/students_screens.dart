import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/auth/auth_state.dart';
import '../../core/providers.dart';
import '../../core/router/routes.dart';
import '../../shared/widgets/placeholder_screen.dart';
import '../../shared/widgets/segmented_scope.dart';
import '../academic_structure/academic_structure_screens.dart';

/// Phase 07 mobile (Prompts/07 §07.10): student Home (profile card, holds banner, pending-undertakings gate),
/// More › Profile (self-update, photo), ID card (QR), Undertakings, Credit transfers (submit with a certificate photo),
/// My curriculum (through the enrolment); parent Home (ward switcher + ward dashboard); registrar / HOD / faculty
/// Students search → 360° (PII masked per role) with the Mine (advisees) | Dept | All segments from `meta.visibility`.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) {
      return '${(data['error'] as Map)['message']}';
    }
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _label(Object? s) => s == null
    ? '—'
    : '$s'
        .replaceAll('_', ' ')
        .replaceFirstMapped(RegExp(r'^\w'), (m) => m.group(0)!.toUpperCase());

class StudentsRepository {
  StudentsRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      });

  Future<Map<String, dynamic>> _one(String path) async {
    final res = await _dio.get<Map<String, dynamic>>(path);
    return (res.data?['data'] as Map?)?.cast<String, dynamic>() ?? {};
  }

  Future<List<Map<String, dynamic>>> _list(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((res.data?['data'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> dashboard() => _one('/students/me/dashboard');
  Future<Map<String, dynamic>> me() => _one('/students/me');
  Future<void> updateMe(Map<String, dynamic> body) =>
      _dio.put('/students/me', data: body);
  Future<void> photo(String studentId, XFile file) async {
    final form = FormData.fromMap(
        {'file': await MultipartFile.fromFile(file.path, filename: file.name)});
    await _dio.post('/students/$studentId/photo', data: form);
  }

  Future<Map<String, dynamic>> idCard() => _one('/students/me/id-card');
  Future<List<Map<String, dynamic>>> pendingUndertakings() =>
      _list('/students/me/undertakings/pending');
  Future<void> accept(Map<String, dynamic> u) =>
      _dio.post('/students/me/undertakings',
          data: {
            'undertaking_type': u['undertaking_type'],
            if (u['template_id'] != null) 'template_id': u['template_id'],
          },
          options: _once);
  Future<List<Map<String, dynamic>>> myCreditTransfers() =>
      _list('/credit-transfers/me');
  Future<void> submitCreditTransfer(
      Map<String, dynamic> body, XFile? certificate) async {
    final res = await _dio.post<Map<String, dynamic>>('/credit-transfers',
        data: body, options: _once);
    final id = (res.data?['data'] as Map?)?['id'];
    if (certificate != null && id != null) {
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(certificate.path,
            filename: certificate.name)
      });
      await _dio.post('/credit-transfers/$id/certificate', data: form);
    }
  }

  Future<List<Map<String, dynamic>>> wards() => _list('/guardians/me/wards');
  Future<Map<String, dynamic>> wardDashboard(String id) =>
      _one('/guardians/me/wards/$id/dashboard');

  Future<({List<Map<String, dynamic>> rows, VisibilityMeta? visibility})>
      search(String q, String? scope) async {
    final res =
        await _dio.get<Map<String, dynamic>>('/students', queryParameters: {
      if (q.isNotEmpty) 'q': q,
      if (scope != null) 'scope': scope,
      'page_size': 50,
    });
    final vis = (res.data?['meta'] as Map?)?['visibility'];
    return (
      rows: ((res.data?['data'] as List?) ?? const [])
          .cast<Map<String, dynamic>>(),
      visibility:
          vis is Map<String, dynamic> ? VisibilityMeta.fromJson(vis) : null,
    );
  }

  Future<Map<String, dynamic>> student(String id) => _one('/students/$id');
  Future<Map<String, dynamic>> verify(String token) =>
      _one('/verify/${Uri.encodeComponent(token)}');
}

final studentsRepositoryProvider = Provider<StudentsRepository>(
    (ref) => StudentsRepository(ref.watch(dioProvider)));

Widget _errorView(Object e, VoidCallback retry) => Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error(e), textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: retry, child: const Text('Retry')),
        ]),
      ),
    );

/// Loads a future and rebuilds on pull-to-refresh.
class _Loader<T> extends StatefulWidget {
  const _Loader({super.key, required this.load, required this.builder});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, VoidCallback reload)
      builder;

  @override
  State<_Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<_Loader<T>> {
  late Future<T> _future = widget.load();

  void _reload() => setState(() => _future = widget.load());

  @override
  Widget build(BuildContext context) => FutureBuilder<T>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return _errorView(snap.error!, _reload);
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: widget.builder(context, snap.data as T, _reload),
          );
        },
      );
}

/// Home tab: the student / parent dashboards; other roles keep the placeholder until their phases fill Home.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authStateProvider);
    if (auth.roles.contains('student') && auth.hasFeature('portals.student')) {
      return const StudentHomeScreen();
    }
    if (auth.roles.contains('parent') && auth.hasFeature('portals.parent')) {
      return const ParentHomeScreen();
    }
    return const PlaceholderScreen(title: 'Home');
  }
}

class _HoldsBanner extends StatelessWidget {
  const _HoldsBanner(this.holds);

  final List<Map<String, dynamic>> holds;

  @override
  Widget build(BuildContext context) {
    final open = holds.where((h) => h['is_open'] == true).toList();
    if (open.isEmpty) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Card(
      color: scheme.errorContainer,
      child: ListTile(
        leading: Icon(Icons.block, color: scheme.onErrorContainer),
        title: Text('${open.length} active hold(s)',
            style: TextStyle(color: scheme.onErrorContainer)),
        subtitle: Text(
          open
              .map((h) => '${_label(h['hold_type'])}: ${h['reason']}')
              .join('\n'),
          style: TextStyle(color: scheme.onErrorContainer),
        ),
      ),
    );
  }
}

/// Profile card, enrolment, standing, holds banner — shared by the student Home and the parent ward view.
class _DashboardBody extends StatelessWidget {
  const _DashboardBody(this.d, {this.trailing = const []});

  final Map<String, dynamic> d;
  final List<Widget> trailing;

  @override
  Widget build(BuildContext context) {
    final s = (d['student'] as Map?)?.cast<String, dynamic>() ?? {};
    final e = (d['enrollment'] as Map?)?.cast<String, dynamic>();
    final holds =
        ((d['holds'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return ListView(padding: const EdgeInsets.all(12), children: [
      Card(
        child: ListTile(
          leading: CircleAvatar(
            backgroundImage: s['photo_url'] != null
                ? NetworkImage('${s['photo_url']}')
                : null,
            child: s['photo_url'] == null
                ? Text('${s['first_name'] ?? '?'}'.substring(0, 1))
                : null,
          ),
          title: Text('${s['full_name'] ?? ''}'),
          subtitle: Text(
              '${s['registration_number'] ?? ''}\n${e == null ? 'No open enrolment' : '${e['program_code']} · ${e['batch_code']}${e['section_name'] != null ? ' · ${e['section_name']}' : ''}'}'),
          isThreeLine: true,
          trailing: Chip(label: Text(_label(s['status']))),
        ),
      ),
      _HoldsBanner(holds),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Wrap(spacing: 24, runSpacing: 12, children: [
            _Stat('Term', '${e?['current_term_number'] ?? '—'}'),
            _Stat('CGPA', '${e?['cgpa'] ?? '—'}'),
            _Stat('Credits', '${e?['credits_earned'] ?? 0}'),
            _Stat('Standing', _label(d['standing'])),
          ]),
        ),
      ),
      ...trailing,
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.k, this.v);

  final String k;
  final String v;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(k, style: Theme.of(context).textTheme.labelSmall),
          Text(v, style: Theme.of(context).textTheme.titleMedium),
        ],
      );
}

/// Student Home: pending required undertakings gate everything else until accepted.
class StudentHomeScreen extends ConsumerWidget {
  const StudentHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Home')),
      body: _Loader<Map<String, dynamic>>(
        load: repo.dashboard,
        builder: (context, d, reload) {
          final pending = ((d['undertakings_pending'] as List?) ?? const [])
              .cast<Map<String, dynamic>>()
              .where((u) => u['required'] == true)
              .toList();
          if (pending.isNotEmpty) {
            return ListView(padding: const EdgeInsets.all(12), children: [
              Card(
                child: ListTile(
                  leading: const Icon(Icons.assignment_late_outlined),
                  title: const Text('Accept your undertakings'),
                  subtitle: Text(
                      '${pending.map((u) => u['name']).join(', ')} must be accepted for this academic year before you continue.'),
                ),
              ),
              for (final u in pending) _UndertakingCard(u: u, onDone: reload),
            ]);
          }
          final links = ((d['quick_links'] as List?) ?? const [])
              .cast<Map<String, dynamic>>();
          return _DashboardBody(d, trailing: [
            for (final l in links)
              if (_mobileRoute(l['key']) != null)
                ListTile(
                  leading: const Icon(Icons.chevron_right),
                  title: Text('${l['label']}'),
                  onTap: () => context.push(_mobileRoute(l['key'])!),
                ),
          ]);
        },
      ),
    );
  }
}

String? _mobileRoute(Object? key) => switch (key) {
      'profile' => AppRoutes.studentProfile,
      'undertakings' => AppRoutes.studentUndertakings,
      'id_card' => AppRoutes.studentIdCard,
      'curriculum' => AppRoutes.academicCurriculum,
      'credit_transfers' => AppRoutes.studentCreditTransfers,
      _ => null,
    };

class _UndertakingCard extends ConsumerStatefulWidget {
  const _UndertakingCard({required this.u, required this.onDone});

  final Map<String, dynamic> u;
  final VoidCallback onDone;

  @override
  ConsumerState<_UndertakingCard> createState() => _UndertakingCardState();
}

class _UndertakingCardState extends ConsumerState<_UndertakingCard> {
  bool _agree = false;
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final u = widget.u;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${u['name']}', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 200),
            child: SingleChildScrollView(child: Text('${u['body'] ?? ''}')),
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: _agree,
            onChanged: (v) => setState(() => _agree = v ?? false),
            title: const Text('I have read and accept this undertaking'),
          ),
          FilledButton(
            onPressed: !_agree || _busy
                ? null
                : () async {
                    setState(() => _busy = true);
                    try {
                      await ref.read(studentsRepositoryProvider).accept(u);
                      widget.onDone();
                    } catch (e) {
                      if (context.mounted) {
                        ScaffoldMessenger.of(context)
                            .showSnackBar(SnackBar(content: Text(_error(e))));
                      }
                    } finally {
                      if (mounted) setState(() => _busy = false);
                    }
                  },
            child: const Text('Accept'),
          ),
        ]),
      ),
    );
  }
}

/// More › Undertakings — pending for this academic year.
class StudentUndertakingsScreen extends ConsumerWidget {
  const StudentUndertakingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Undertakings')),
      body: _Loader<List<Map<String, dynamic>>>(
        load: repo.pendingUndertakings,
        builder: (context, rows, reload) => rows.isEmpty
            ? ListView(children: const [
                ListTile(
                    leading: Icon(Icons.check_circle_outline),
                    title: Text('Nothing pending for this academic year.'))
              ])
            : ListView(padding: const EdgeInsets.all(12), children: [
                for (final u in rows) _UndertakingCard(u: u, onDone: reload),
              ]),
      ),
    );
  }
}

/// More › Profile — phone, e-mail, current address, emergency contact and photo.
class StudentProfileScreen extends ConsumerStatefulWidget {
  const StudentProfileScreen({super.key});

  @override
  ConsumerState<StudentProfileScreen> createState() => _StudentProfileState();
}

class _StudentProfileState extends ConsumerState<StudentProfileScreen> {
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _address = TextEditingController();
  final _ecName = TextEditingController();
  final _ecPhone = TextEditingController();
  Map<String, dynamic>? _me;
  Object? _err;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final me = await ref.read(studentsRepositoryProvider).me();
      final ec = (me['emergency_contact'] as Map?) ?? {};
      _phone.text = '${me['phone'] ?? ''}';
      _email.text = '${me['email'] ?? ''}';
      _address.text = '${(me['current_address'] as Map?)?['line1'] ?? ''}';
      _ecName.text = '${ec['name'] ?? ''}';
      _ecPhone.text = '${ec['phone'] ?? ''}';
      if (mounted) setState(() => _me = me);
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _run(Future<void> Function() action, String done) async {
    setState(() => _busy = true);
    try {
      await action();
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(done)));
      }
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = _me;
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('My profile')),
      body: _err != null
          ? _errorView(_err!, () {
              setState(() => _err = null);
              _load();
            })
          : me == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(padding: const EdgeInsets.all(16), children: [
                  Center(
                    child: CircleAvatar(
                      radius: 40,
                      backgroundImage: me['photo_url'] != null
                          ? NetworkImage('${me['photo_url']}')
                          : null,
                    ),
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: const Text('Change photo'),
                    onPressed: _busy
                        ? null
                        : () async {
                            final f = await ImagePicker().pickImage(
                                source: ImageSource.camera,
                                maxWidth: 800,
                                imageQuality: 85);
                            if (f != null) {
                              await _run(() => repo.photo('${me['id']}', f),
                                  'Photo updated');
                            }
                          },
                  ),
                  ListTile(
                      title: Text('${me['full_name']}'),
                      subtitle: Text(
                          '${me['registration_number']} · ${me['program_code'] ?? ''} ${me['batch_code'] ?? ''}')),
                  const Text(
                      'Name, date of birth and identity numbers are changed by the office.'),
                  TextField(
                      controller: _phone,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(labelText: 'Phone')),
                  TextField(
                      controller: _email,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(labelText: 'E-mail')),
                  TextField(
                      controller: _address,
                      decoration:
                          const InputDecoration(labelText: 'Current address')),
                  TextField(
                      controller: _ecName,
                      decoration: const InputDecoration(
                          labelText: 'Emergency contact name')),
                  TextField(
                      controller: _ecPhone,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(
                          labelText: 'Emergency contact phone')),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _busy
                        ? null
                        : () => _run(
                            () => repo.updateMe({
                                  if (_phone.text.isNotEmpty)
                                    'phone': _phone.text.trim(),
                                  if (_email.text.isNotEmpty)
                                    'email': _email.text.trim(),
                                  if (_address.text.isNotEmpty)
                                    'current_address': {
                                      ...((me['current_address'] as Map?)
                                              ?.cast<String, dynamic>() ??
                                          {}),
                                      'line1': _address.text.trim(),
                                    },
                                  if (_ecName.text.isNotEmpty &&
                                      _ecPhone.text.isNotEmpty)
                                    'emergency_contact': {
                                      'name': _ecName.text.trim(),
                                      'phone': _ecPhone.text.trim(),
                                    },
                                }),
                            'Profile updated'),
                    child: const Text('Save'),
                  ),
                ]),
    );
  }
}

/// More › ID card — QR opens the public /verify page.
class StudentIdCardScreen extends ConsumerWidget {
  const StudentIdCardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('ID card')),
      body: _Loader<Map<String, dynamic>>(
        load: repo.idCard,
        builder: (context, c, _) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text('${c['institution'] ?? ''}',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium),
            Text('${c['college'] ?? ''}', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            Center(
              child: CircleAvatar(
                radius: 44,
                backgroundImage: c['photo_url'] != null
                    ? NetworkImage('${c['photo_url']}')
                    : null,
              ),
            ),
            const SizedBox(height: 8),
            Text('${c['name']}',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleLarge),
            Text('${c['registration_number']}', textAlign: TextAlign.center),
            Text(
                '${c['program'] ?? ''} · ${c['batch'] ?? ''}${c['blood_group'] != null ? ' · ${c['blood_group']}' : ''}',
                textAlign: TextAlign.center),
            const SizedBox(height: 16),
            Center(
              child: Container(
                color: Colors.white,
                padding: const EdgeInsets.all(8),
                child: QrImageView(data: '${c['verify_url']}', size: 180),
              ),
            ),
            const SizedBox(height: 8),
            Text('Valid until ${c['valid_until'] ?? '—'}',
                textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// More › Credit transfers — submit with a certificate photo; list with status.
class StudentCreditTransfersScreen extends ConsumerStatefulWidget {
  const StudentCreditTransfersScreen({super.key});

  @override
  ConsumerState<StudentCreditTransfersScreen> createState() =>
      _StudentCreditTransfersState();
}

class _StudentCreditTransfersState
    extends ConsumerState<StudentCreditTransfersScreen> {
  int _reloadKey = 0;

  Future<void> _submit() async {
    final title = TextEditingController();
    final code = TextEditingController();
    final credits = TextEditingController();
    final score = TextEditingController();
    var source = 'nptel';
    XFile? cert;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => Padding(
          padding: EdgeInsets.fromLTRB(
              16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(
              initialValue: source,
              decoration: const InputDecoration(labelText: 'Source'),
              items: const [
                'nptel',
                'swayam',
                'coursera',
                'other_mooc',
                'abc',
                'other_university'
              ]
                  .map(
                      (s) => DropdownMenuItem(value: s, child: Text(_label(s))))
                  .toList(),
              onChanged: (v) => setSheet(() => source = v ?? source),
            ),
            TextField(
                controller: code,
                decoration: const InputDecoration(labelText: 'Course code')),
            TextField(
                controller: title,
                decoration: const InputDecoration(labelText: 'Course title')),
            TextField(
                controller: credits,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Credits')),
            TextField(
                controller: score,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Score %')),
            TextButton.icon(
              icon: const Icon(Icons.photo_camera_outlined),
              label: Text(cert == null ? 'Certificate photo' : cert!.name),
              onPressed: () async {
                final f = await ImagePicker()
                    .pickImage(source: ImageSource.camera, imageQuality: 85);
                if (f != null) setSheet(() => cert = f);
              },
            ),
            FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Submit')),
          ]),
        ),
      ),
    );
    if (ok != true || title.text.trim().isEmpty || credits.text.isEmpty) {
      return;
    }
    try {
      await ref.read(studentsRepositoryProvider).submitCreditTransfer({
        'source': source,
        'source_title': title.text.trim(),
        if (code.text.isNotEmpty) 'source_course_code': code.text.trim(),
        'credits': credits.text.trim(),
        if (score.text.isNotEmpty) 'source_score_pct': score.text.trim(),
      }, cert);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Submitted for verification')));
        setState(() => _reloadKey++);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Credit transfers')),
      floatingActionButton: FloatingActionButton(
          onPressed: _submit, child: const Icon(Icons.add)),
      body: _Loader<List<Map<String, dynamic>>>(
        key: ValueKey(_reloadKey),
        load: repo.myCreditTransfers,
        builder: (context, rows, _) => ListView(children: [
          if (rows.isEmpty) const ListTile(title: Text('No submissions yet.')),
          for (final c in rows)
            ListTile(
              title:
                  Text('${c['source_course_code'] ?? ''} ${c['source_title']}'),
              subtitle: Text(
                  '${_label(c['source'])} · ${c['credits']} credits${c['equivalent_course'] != null ? ' · ≡ ${c['equivalent_course']}' : ''}'),
              trailing: Chip(label: Text(_label(c['status']))),
            ),
        ]),
      ),
    );
  }
}

/// My curriculum for students: the enrolled programme regulation, read through the enrolment link.
class StudentCurriculumScreen extends ConsumerWidget {
  const StudentCurriculumScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return FutureBuilder<Map<String, dynamic>>(
      future: repo.me(),
      builder: (context, snap) {
        if (!snap.hasData && !snap.hasError) {
          return const Scaffold(
              body: Center(child: CircularProgressIndicator()));
        }
        final pr = (snap.data?['enrollment'] as Map?)?['program_regulation_id'];
        return CurriculumScreen(programRegulationId: pr?.toString());
      },
    );
  }
}

/// Parent Home: ward switcher + ward dashboard (wards whose consent is withdrawn are not returned).
class ParentHomeScreen extends ConsumerStatefulWidget {
  const ParentHomeScreen({super.key});

  @override
  ConsumerState<ParentHomeScreen> createState() => _ParentHomeState();
}

class _ParentHomeState extends ConsumerState<ParentHomeScreen> {
  String? _ward;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('My wards')),
      body: _Loader<List<Map<String, dynamic>>>(
        load: repo.wards,
        builder: (context, wards, _) {
          if (wards.isEmpty) {
            return ListView(children: const [
              ListTile(
                  title: Text('No wards to show'),
                  subtitle: Text(
                      'Your ward appears here once the institution links you and portal access is consented.')),
            ]);
          }
          final active = wards.any((w) => w['student_id'] == _ward)
              ? _ward!
              : '${wards.first['student_id']}';
          return Column(children: [
            if (wards.length > 1)
              Padding(
                padding: const EdgeInsets.all(8),
                child: SegmentedButton<String>(
                  segments: [
                    for (final w in wards)
                      ButtonSegment(
                          value: '${w['student_id']}',
                          label: Text('${w['name']}'))
                  ],
                  selected: {active},
                  showSelectedIcon: false,
                  onSelectionChanged: (s) => setState(() => _ward = s.first),
                ),
              ),
            Expanded(
              child: _Loader<Map<String, dynamic>>(
                key: ValueKey(active),
                load: () => repo.wardDashboard(active),
                builder: (context, d, _) => _DashboardBody(d),
              ),
            ),
          ]);
        },
      ),
    );
  }
}

/// Students (registrar / HOD / advisors / faculty): search with scope segments → 360° (PII masked per role).
class StudentsSearchScreen extends ConsumerStatefulWidget {
  const StudentsSearchScreen({super.key});

  @override
  ConsumerState<StudentsSearchScreen> createState() => _StudentsSearchState();
}

class _StudentsSearchState extends ConsumerState<StudentsSearchScreen> {
  final _q = TextEditingController();
  String? _scope;
  VisibilityMeta? _visibility;
  List<Map<String, dynamic>>? _rows;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _search();
  }

  Future<void> _search() async {
    try {
      final r = await ref
          .read(studentsRepositoryProvider)
          .search(_q.text.trim(), _scope);
      if (mounted) {
        setState(() {
          _rows = r.rows;
          _visibility = r.visibility;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Students')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _search(),
            decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Name or registration no.'),
          ),
        ),
        if (_visibility != null)
          Padding(
            padding: const EdgeInsets.all(8),
            child: SegmentedScope(
              visibility: _visibility!,
              value: _scope ?? _visibility!.defaultScope,
              onChanged: (s) {
                setState(() => _scope = s);
                _search();
              },
            ),
          ),
        Expanded(
          child: _err != null
              ? _errorView(_err!, _search)
              : _rows == null
                  ? const Center(child: CircularProgressIndicator())
                  : _rows!.isEmpty
                      ? const Center(child: Text('No students.'))
                      : ListView(children: [
                          for (final s in _rows!)
                            ListTile(
                              title: Text(
                                  '${s['registration_number']} · ${s['full_name']}'),
                              subtitle: Text(
                                  '${s['program_code'] ?? '—'} · ${s['batch_code'] ?? ''}${s['section_name'] != null ? ' · ${s['section_name']}' : ''} · ${_label(s['status'])}${((s['open_holds'] as num?) ?? 0) > 0 ? ' · ${s['open_holds']} hold(s)' : ''}'),
                              onTap: () => context.push(
                                  '${AppRoutes.studentDetail}?id=${s['id']}'),
                            ),
                        ]),
        ),
      ]),
    );
  }
}

/// Student 360° (read-only on mobile): profile, enrolment, holds, guardians — values arrive masked without PII rights.
class StudentDetailScreen extends ConsumerWidget {
  const StudentDetailScreen({super.key, required this.id});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Student')),
      body: _Loader<Map<String, dynamic>>(
        load: () => repo.student(id),
        builder: (context, s, _) {
          final e = (s['enrollment'] as Map?)?.cast<String, dynamic>();
          final guardians = ((s['guardians'] as List?) ?? const [])
              .cast<Map<String, dynamic>>();
          Widget row(String k, Object? v) => ListTile(
              dense: true, title: Text(k), trailing: Text('${v ?? '—'}'));
          return ListView(padding: const EdgeInsets.all(8), children: [
            ListTile(
              title: Text('${s['full_name']}',
                  style: Theme.of(context).textTheme.titleLarge),
              subtitle: Text('${s['registration_number']}'),
              trailing: Chip(label: Text(_label(s['status']))),
            ),
            _HoldsBanner(((s['holds'] as List?) ?? const [])
                .cast<Map<String, dynamic>>()),
            row('Programme', e?['program_code']),
            row('Batch / section',
                '${e?['batch_code'] ?? '—'} ${e?['section_name'] ?? ''}'),
            row('Term', e?['current_term_number']),
            row('CGPA', e?['cgpa']),
            row('Standing', _label(s['academic_standing'])),
            row('Phone', s['phone']),
            row('E-mail', s['email']),
            row('Aadhaar', s['aadhaar']),
            const Divider(),
            for (final g in guardians)
              ListTile(
                  dense: true,
                  leading: const Icon(Icons.family_restroom),
                  title: Text('${g['name']} (${_label(g['relation'])})'),
                  subtitle: Text('${g['phone'] ?? ''}')),
          ]);
        },
      ),
    );
  }
}

/// Universal link /verify/:token — public check of an ID card / document QR.
class VerifyScreen extends ConsumerWidget {
  const VerifyScreen({super.key, required this.token});

  final String token;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(studentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Verify')),
      body: _Loader<Map<String, dynamic>>(
        load: () => repo.verify(token),
        builder: (context, r, _) => ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Icon(r['valid'] == true ? Icons.verified : Icons.gpp_bad_outlined,
                size: 64,
                color: r['valid'] == true ? Colors.green : Colors.red),
            Text(
                r['valid'] == true
                    ? 'Valid ${_label(r['document_type'])}'
                    : 'Not valid',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleLarge),
            if (r['valid'] == true) ...[
              ListTile(
                  title: const Text('Name'),
                  trailing: Text('${r['holder_name']}')),
              ListTile(
                  title: const Text('Registration no.'),
                  trailing: Text('${r['registration_number']}')),
              ListTile(
                  title: const Text('Programme'),
                  trailing: Text('${r['program'] ?? '—'}')),
              ListTile(
                  title: const Text('Status'),
                  trailing: Text(_label(r['status']))),
            ] else
              Text('${r['message'] ?? ''}', textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 18 mobile (Prompts/18 §18.10): student / alumni **Degree** (eligibility with reasons, convocation
/// registration, QR invitation, certificate download, credential status), registrar **Eligibility** (read + override),
/// **Award approvals** and the convocation-day **attendance scanner** (QR from the student app). Rules and visibility
/// live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class DegreeRepository {
  DegreeRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> eligibilityMe() async => _list(await _get('/degree-eligibility/me'));
  Future<List<Map<String, dynamic>>> convocations() async {
    try {
      return _list(await _get('/convocations'));
    } catch (_) {
      return const [];
    }
  }

  Future<List<Map<String, dynamic>>> myConvocations() async => _list(await _get('/convocations/me'));
  Future<void> register(String id, Map<String, dynamic> body) => _post('/convocations/$id/register', body);
  Future<List<Map<String, dynamic>>> myDegrees() async => _list(await _get('/degrees/me'));
  String certificateUrl(String id) => '${_dio.options.baseUrl}/degrees/$id/certificate.pdf';
  Future<List<Map<String, dynamic>>> myCredentials() async {
    try {
      return _list(await _get('/credentials/me'));
    } catch (_) {
      return const [];
    }
  }

  Future<List<Map<String, dynamic>>> eligibility({bool? eligible}) async =>
      _list(await _get('/degree-eligibility', {if (eligible != null) 'eligible': eligible}));
  Future<void> override(String id, String decision, String reason) =>
      _post('/degree-eligibility/$id/override', {'decision': decision, 'reason': reason});
  Future<List<Map<String, dynamic>>> awards(String status) async => _list(await _get('/degrees', {'status': status}));
  Future<void> approve(String id) => _post('/degrees/$id/approve', {});
  Future<Map<String, dynamic>> attendance(String convocationId, String token) async =>
      ((await _post('/convocations/$convocationId/attendance', {'token': token})) as Map).cast<String, dynamic>();
}

final degreeRepositoryProvider = Provider<DegreeRepository>((ref) => DegreeRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, Object e) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));

// ---- student / alumni ---------------------------------------------------------------------------------------------------------------
class StudentDegreeScreen extends ConsumerStatefulWidget {
  const StudentDegreeScreen({super.key});

  @override
  ConsumerState<StudentDegreeScreen> createState() => _StudentDegreeScreenState();
}

class _StudentDegreeScreenState extends ConsumerState<StudentDegreeScreen> {
  late Future<List<List<Map<String, dynamic>>>> _f = _load();

  Future<List<List<Map<String, dynamic>>>> _load() {
    final r = ref.read(degreeRepositoryProvider);
    return Future.wait([r.eligibilityMe(), r.convocations(), r.myConvocations(), r.myDegrees(), r.myCredentials()]);
  }

  Future<void> _register(Map<String, dynamic> c) async {
    var mode = 'in_person';
    var gown = 'M';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: Text('Register — ${c['name']}'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            SegmentedButton<String>(
              segments: const [ButtonSegment(value: 'in_person', label: Text('In person')), ButtonSegment(value: 'absentia', label: Text('Absentia'))],
              selected: {mode},
              onSelectionChanged: (s) => set(() => mode = s.first),
            ),
            if (mode == 'in_person')
              DropdownButton<String>(
                value: gown,
                items: [for (final g in const ['XS', 'S', 'M', 'L', 'XL', 'XXL']) DropdownMenuItem(value: g, child: Text('Gown $g'))],
                onChanged: (v) => set(() => gown = v ?? 'M'),
              ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Register')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await ref.read(degreeRepositoryProvider).register('${c['id']}', {'mode': mode, if (mode == 'in_person') 'gown_size': gown, 'guests': 1});
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Registered — pay the fee under Fees')));
      setState(() => _f = _load());
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(degreeRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Degree')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<List<Map<String, dynamic>>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final elig = snap.data![0];
            final convs = snap.data![1].where((c) => c['status'] == 'registration_open').toList();
            final mine = snap.data![2];
            final degrees = snap.data![3];
            final creds = snap.data![4];
            final registered = {for (final r in mine) r['convocation_id']};
            return ListView(padding: const EdgeInsets.all(12), children: [
              const Text('Eligibility', style: TextStyle(fontWeight: FontWeight.w600)),
              if (elig.isEmpty) const ListTile(title: Text('Not checked yet.')),
              for (final c in elig)
                Card(
                  child: ListTile(
                    leading: Icon(c['is_eligible'] == true ? Icons.verified : Icons.pending_actions, color: c['is_eligible'] == true ? Colors.green : Colors.orange),
                    title: Text('Credits ${c['credits_earned']} / ${c['credits_required']} · CGPA ${c['cgpa'] ?? '—'}'),
                    subtitle: Text(((c['reasons'] as List?) ?? const []).isEmpty ? 'Eligible' : ((c['reasons'] as List).join(', '))),
                  ),
                ),
              const SizedBox(height: 12),
              const Text('Convocation', style: TextStyle(fontWeight: FontWeight.w600)),
              for (final c in convs.where((c) => !registered.contains(c['id'])))
                ListTile(title: Text('${c['name']}'), subtitle: Text('Register by ${c['registration_deadline'] ?? '—'}'), trailing: FilledButton(onPressed: () => _register(c), child: const Text('Register'))),
              for (final r in mine)
                Card(
                  child: Column(children: [
                    ListTile(title: Text('${r['convocation']}'), subtitle: Text('${r['mode']} · ${r['status']}${r['gown_size'] != null ? ' · gown ${r['gown_size']}' : ''}')),
                    if (r['attendance_token'] != null) Padding(padding: const EdgeInsets.all(8), child: QrImageView(data: '${r['attendance_token']}', size: 180)),
                  ]),
                ),
              const SizedBox(height: 12),
              const Text('Certificates', style: TextStyle(fontWeight: FontWeight.w600)),
              if (degrees.isEmpty) const ListTile(title: Text('No awards yet.')),
              for (final d in degrees)
                ListTile(
                  title: Text('${d['degree_name']}'),
                  subtitle: Text('${d['status']} · ${d['certificate_number'] ?? ''}'),
                  trailing: d['status'] == 'issued'
                      ? IconButton(icon: const Icon(Icons.download), onPressed: () => launchUrl(Uri.parse(repo.certificateUrl('${d['id']}'))))
                      : null,
                ),
              const SizedBox(height: 12),
              const Text('Digital credentials', style: TextStyle(fontWeight: FontWeight.w600)),
              if (creds.isEmpty) const ListTile(title: Text('Nothing pushed yet.')),
              for (final c in creds) ListTile(title: Text('${c['entity_type']} · ${c['channel']}'), trailing: Text('${c['status']}')),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- registrar ------------------------------------------------------------------------------------------------------------------------
class DegreeEligibilityScreen extends ConsumerStatefulWidget {
  const DegreeEligibilityScreen({super.key});

  @override
  ConsumerState<DegreeEligibilityScreen> createState() => _DegreeEligibilityScreenState();
}

class _DegreeEligibilityScreenState extends ConsumerState<DegreeEligibilityScreen> {
  bool? _eligible = false;
  late Future<List<Map<String, dynamic>>> _f = ref.read(degreeRepositoryProvider).eligibility(eligible: _eligible);

  void _reload() => setState(() => _f = ref.read(degreeRepositoryProvider).eligibility(eligible: _eligible));

  Future<void> _override(Map<String, dynamic> c) async {
    final ctrl = TextEditingController();
    final decision = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Override — ${c['enrollment']?['student_name'] ?? ''}'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Reason'), maxLines: 3),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, 'ineligible'), child: const Text('Ineligible')),
          FilledButton(onPressed: () => Navigator.pop(ctx, 'eligible'), child: const Text('Eligible')),
        ],
      ),
    );
    if (decision == null) return;
    try {
      await ref.read(degreeRepositoryProvider).override('${c['id']}', decision, ctrl.text);
      _reload();
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Degree eligibility'), actions: [
        PopupMenuButton<bool?>(
          onSelected: (v) {
            _eligible = v;
            _reload();
          },
          itemBuilder: (_) => const [
            PopupMenuItem(value: false, child: Text('Not eligible')),
            PopupMenuItem(value: true, child: Text('Eligible')),
            PopupMenuItem(value: null, child: Text('All')),
          ],
        ),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => _reload(),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            return ListView(children: [
              for (final c in snap.data!)
                ListTile(
                  title: Text('${c['enrollment']?['registration_number']} · ${c['enrollment']?['student_name']}'),
                  subtitle: Text(((c['reasons'] as List?) ?? const []).isEmpty ? 'Eligible' : (c['reasons'] as List).join(', ')),
                  trailing: IconButton(icon: const Icon(Icons.gavel_outlined), onPressed: () => _override(c)),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

class AwardApprovalsScreen extends ConsumerStatefulWidget {
  const AwardApprovalsScreen({super.key});

  @override
  ConsumerState<AwardApprovalsScreen> createState() => _AwardApprovalsScreenState();
}

class _AwardApprovalsScreenState extends ConsumerState<AwardApprovalsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(degreeRepositoryProvider).awards('recommended');

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(degreeRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Award approvals')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          if (snap.data!.isEmpty) return const Center(child: Text('Nothing to approve.'));
          return ListView(children: [
            for (final a in snap.data!)
              ListTile(
                title: Text('${a['enrollment']?['student_name']} · ${a['degree_name']}'),
                subtitle: Text('${a['result_class'] ?? ''} · CGPA ${a['cgpa'] ?? '—'}'),
                trailing: FilledButton(
                  onPressed: () async {
                    try {
                      await repo.approve('${a['id']}');
                      setState(() => _f = repo.awards('recommended'));
                    } catch (e) {
                      if (context.mounted) _snack(context, e);
                    }
                  },
                  child: const Text('Approve'),
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class ConvocationScannerScreen extends ConsumerStatefulWidget {
  const ConvocationScannerScreen({super.key});

  @override
  ConsumerState<ConvocationScannerScreen> createState() => _ConvocationScannerScreenState();
}

class _ConvocationScannerScreenState extends ConsumerState<ConvocationScannerScreen> {
  String? _convocation;
  String? _last;
  String _status = 'Pick a convocation, then scan the invitation QR.';
  late final Future<List<Map<String, dynamic>>> _convs = ref.read(degreeRepositoryProvider).convocations();

  Future<void> _onDetect(BarcodeCapture cap) async {
    final code = cap.barcodes.isNotEmpty ? cap.barcodes.first.rawValue : null;
    if (code == null || code == _last || _convocation == null) return;
    _last = code;
    try {
      final r = await ref.read(degreeRepositoryProvider).attendance(_convocation!, code);
      setState(() => _status = '✓ ${r['enrollment']?['student_name']} (${r['enrollment']?['registration_number']}) marked attended');
    } catch (e) {
      setState(() => _status = '✗ ${_error(e)}');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Convocation attendance')),
      body: Column(children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _convs,
          builder: (context, snap) => Padding(
            padding: const EdgeInsets.all(12),
            child: DropdownButton<String>(
              isExpanded: true,
              hint: const Text('Convocation'),
              value: _convocation,
              items: [for (final c in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${c['id']}', child: Text('${c['name']}'))],
              onChanged: (v) => setState(() => _convocation = v),
            ),
          ),
        ),
        Expanded(child: _convocation == null ? const SizedBox() : MobileScanner(onDetect: _onDetect)),
        Padding(padding: const EdgeInsets.all(16), child: Text(_status, textAlign: TextAlign.center)),
      ]),
    );
  }
}

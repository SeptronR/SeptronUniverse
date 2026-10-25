import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/providers.dart';

/// Phase 26 mobile (Prompts/26 §26.10): **Documents** for students / staff / alumni (my documents → share a signed
/// link; request wizard with fee and delivery; request timeline; pickup notice) and guardians (ward documents),
/// office **Certificate queue** (approve / generate / issue / collected) and **Verify** (QR scan or token entry →
/// unified `/verify/{token}`).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _rupees(dynamic p) => '₹${(((p ?? 0) as num) / 100).toStringAsFixed(0)}';
String _day(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month}/${d.year}';
}

class DocumentsRepository {
  DocumentsRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> mine({bool wards = false}) async => _list(await _get(wards ? '/documents/wards' : '/documents/me'));
  Future<List<Map<String, dynamic>>> myRequests({bool wards = false}) async =>
      _list(await _get(wards ? '/certificate-requests/wards' : '/certificate-requests/me'));
  Future<List<Map<String, dynamic>>> types() async => _list(await _get('/certificate-requests/types'));
  Future<String> signedLink(String id) async => '${((await _post('/documents/issued/$id/signed-link', {})) as Map)['url']}';
  Future<void> request(Map<String, dynamic> body) => _post('/certificate-requests', body);
  Future<void> cancel(String id) => _dio.delete<dynamic>('/certificate-requests/$id');
  Future<List<Map<String, dynamic>>> queue(String status) async => _list(await _get('/certificate-requests', {'status': status}));
  Future<void> decide(String id, String action) => _post('/certificate-requests/$id/decide', {'action': action});
  Future<void> generate(String id) => _post('/certificate-requests/$id/generate', {});
  Future<void> issue(String id) => _post('/certificate-requests/$id/issue', {});
  Future<void> collected(String id, String by) => _post('/certificate-requests/$id/collected', {'collected_by': by});
  Future<Map<String, dynamic>?> verify(String token) async => (await _get('/verify/$token') as Map?)?.cast<String, dynamic>();
}

final documentsRepositoryProvider = Provider<DocumentsRepository>((ref) => DocumentsRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Widget _futureList(Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing yet'}) => FutureBuilder<List<Map<String, dynamic>>>(
      future: f,
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        if (snap.data!.isEmpty) return Padding(padding: const EdgeInsets.all(16), child: Text(empty));
        return Column(children: [for (final r in snap.data!) row(r)]);
      },
    );

// ---- my documents + requests --------------------------------------------------------------------------------------------
class MyDocumentsScreen extends ConsumerStatefulWidget {
  const MyDocumentsScreen({super.key, this.wards = false});

  final bool wards;

  @override
  ConsumerState<MyDocumentsScreen> createState() => _MyDocumentsScreenState();
}

class _MyDocumentsScreenState extends ConsumerState<MyDocumentsScreen> {
  late DocumentsRepository _repo = ref.read(documentsRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _docs = _repo.mine(wards: widget.wards);
  late Future<List<Map<String, dynamic>>> _reqs = _repo.myRequests(wards: widget.wards);

  void _reload() => setState(() {
        _repo = ref.read(documentsRepositoryProvider);
        _docs = _repo.mine(wards: widget.wards);
        _reqs = _repo.myRequests(wards: widget.wards);
      });

  Future<void> _share(Map<String, dynamic> d) async {
    try {
      final url = await _repo.signedLink('${d['id']}');
      final base = ref.read(dioProvider).options.baseUrl.replaceAll(RegExp(r'/api/v1/?$'), '');
      await Share.share('${d['template_type']} ${d['document_number']}: $base$url (valid 15 min)');
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.wards ? 'Ward documents' : 'Documents')),
        floatingActionButton: FloatingActionButton.extended(
          icon: const Icon(Icons.add),
          label: const Text('Request'),
          onPressed: () async {
            final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const RequestWizardScreen()));
            if (ok == true) _reload();
          },
        ),
        body: RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(children: [
            const ListTile(title: Text('My documents', style: TextStyle(fontWeight: FontWeight.bold))),
            _futureList(
              _docs,
              (d) => ListTile(
                leading: Icon(d['revoked'] == true ? Icons.block : Icons.description_outlined),
                title: Text('${d['template_type']} · ${d['document_number']}'),
                subtitle: Text(d['revoked'] == true ? 'Revoked' : 'Issued ${_day(d['issued_at'])}'),
                trailing: d['revoked'] == true ? null : IconButton(icon: const Icon(Icons.share), onPressed: () => _share(d)),
              ),
              empty: 'No documents yet',
            ),
            const ListTile(title: Text('My requests', style: TextStyle(fontWeight: FontWeight.bold))),
            _futureList(
              _reqs,
              (r) => ExpansionTile(
                leading: Icon(r['stage'] == 'pickup_ready' ? Icons.storefront : Icons.pending_actions),
                title: Text('${r['template_type']} × ${r['copies']}'),
                subtitle: Text(r['stage'] == 'pickup_ready'
                    ? 'Ready for pickup on ${(r['pickup'] as Map?)?['on'] ?? ''} — show this screen at the office'
                    : '${r['status']}${((r['fee_paise'] ?? 0) as num) > 0 ? ' · ${_rupees(r['fee_paise'])} ${r['fee_status'] ?? ''}' : ''}'),
                children: [
                  for (final t in ((r['timeline'] as List?) ?? const []).cast<Map<String, dynamic>>())
                    ListTile(dense: true, title: Text('${t['action']}'), subtitle: Text(_day(t['at']))),
                  if (r['status'] == 'requested' || r['status'] == 'fee_pending')
                    TextButton(
                      onPressed: () async {
                        try {
                          await _repo.cancel('${r['id']}');
                          _reload();
                        } catch (e) {
                          if (context.mounted) _snack(context, _error(e));
                        }
                      },
                      child: const Text('Cancel request'),
                    ),
                ],
              ),
              empty: 'No requests',
            ),
          ]),
        ),
      );
}

class WardDocumentsScreen extends StatelessWidget {
  const WardDocumentsScreen({super.key});

  @override
  Widget build(BuildContext context) => const MyDocumentsScreen(wards: true);
}

class RequestWizardScreen extends ConsumerStatefulWidget {
  const RequestWizardScreen({super.key});

  @override
  ConsumerState<RequestWizardScreen> createState() => _RequestWizardScreenState();
}

class _RequestWizardScreenState extends ConsumerState<RequestWizardScreen> {
  late final Future<List<Map<String, dynamic>>> _types = ref.read(documentsRepositoryProvider).types();
  String? _type;
  int _copies = 1;
  String _delivery = 'digital';
  final _purpose = TextEditingController();
  final _address = TextEditingController();
  final _regNo = TextEditingController();
  bool _busy = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Request a certificate')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _types,
          builder: (context, snap) {
            if (snap.hasError) return Center(child: Text(_error(snap.error!)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final allowed = snap.data!.where((t) => t['allowed'] == true).toList();
            final sel = allowed.where((t) => t['template_type'] == _type).firstOrNull;
            final fee = sel == null ? 0 : (sel['fee_paise'] as num) + (sel['copies_fee_paise'] as num) * (_copies - 1);
            return ListView(padding: const EdgeInsets.all(16), children: [
              DropdownButtonFormField<String>(
                initialValue: _type,
                decoration: const InputDecoration(labelText: 'Certificate'),
                items: [for (final t in allowed) DropdownMenuItem(value: '${t['template_type']}', child: Text('${t['label']} (${_rupees(t['fee_paise'])})'))],
                onChanged: (v) => setState(() => _type = v),
              ),
              Row(children: [
                const Text('Copies'),
                IconButton(icon: const Icon(Icons.remove), onPressed: _copies > 1 ? () => setState(() => _copies--) : null),
                Text('$_copies'),
                IconButton(icon: const Icon(Icons.add), onPressed: _copies < 10 ? () => setState(() => _copies++) : null),
              ]),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'digital', label: Text('Digital')),
                  ButtonSegment(value: 'pickup', label: Text('Pickup')),
                  ButtonSegment(value: 'post', label: Text('Post')),
                ],
                selected: {_delivery},
                onSelectionChanged: (s) => setState(() => _delivery = s.first),
              ),
              TextField(controller: _purpose, decoration: const InputDecoration(labelText: 'Purpose')),
              if (_delivery == 'post') TextField(controller: _address, decoration: const InputDecoration(labelText: 'Postal address'), maxLines: 3),
              TextField(controller: _regNo, decoration: const InputDecoration(labelText: 'Registration no. (alumni only)')),
              const SizedBox(height: 12),
              if (sel != null)
                Text('Fee ${_rupees(fee)} · SLA ${sel['sla_days']} days${sel['requires_no_dues'] == true ? ' · needs no-dues clearance' : ''}'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _type == null || _busy
                    ? null
                    : () async {
                        setState(() => _busy = true);
                        try {
                          await ref.read(documentsRepositoryProvider).request({
                            'template_type': _type,
                            'copies': _copies,
                            'delivery': _delivery,
                            if (_purpose.text.isNotEmpty) 'purpose': _purpose.text,
                            if (_address.text.isNotEmpty) 'address': _address.text,
                            if (_regNo.text.isNotEmpty) 'registration_number': _regNo.text,
                          });
                          if (context.mounted) {
                            _snack(context, fee > 0 ? 'Requested — pay the fee under Fees' : 'Requested');
                            Navigator.of(context).pop(true);
                          }
                        } catch (e) {
                          if (context.mounted) _snack(context, _error(e));
                        } finally {
                          if (mounted) setState(() => _busy = false);
                        }
                      },
                child: const Text('Submit request'),
              ),
            ]);
          },
        ),
      );
}

// ---- office queue -----------------------------------------------------------------------------------------------------------
class CertificateQueueScreen extends ConsumerStatefulWidget {
  const CertificateQueueScreen({super.key});

  @override
  ConsumerState<CertificateQueueScreen> createState() => _CertificateQueueScreenState();
}

class _CertificateQueueScreenState extends ConsumerState<CertificateQueueScreen> {
  String _status = 'requested';
  late Future<List<Map<String, dynamic>>> _rows = ref.read(documentsRepositoryProvider).queue(_status);

  void _load(String s) => setState(() {
        _status = s;
        _rows = ref.read(documentsRepositoryProvider).queue(s);
      });

  Future<void> _act(Future<void> Function() fn, String msg) async {
    try {
      await fn();
      if (mounted) _snack(context, msg);
      _load(_status);
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(documentsRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Certificate queue')),
      body: Column(children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final s in const ['requested', 'fee_pending', 'approved', 'generated', 'issued', 'rejected'])
              Padding(padding: const EdgeInsets.all(4), child: ChoiceChip(label: Text(s), selected: _status == s, onSelected: (_) => _load(s))),
          ]),
        ),
        Expanded(
          child: SingleChildScrollView(
            child: _futureList(
              _rows,
              (r) => Card(
                child: ListTile(
                  title: Text('${r['template_type']} · ${r['person_name'] ?? ''}'),
                  subtitle: Text('${r['delivery']} · ${r['stage'] ?? r['status']}${r['sla_breached'] == true ? ' · SLA breached' : ''}'),
                  trailing: PopupMenuButton<String>(
                    onSelected: (a) async {
                      final id = '${r['id']}';
                      if (a == 'approve' || a == 'reject') return _act(() => repo.decide(id, a), a == 'approve' ? 'Approved' : 'Rejected');
                      if (a == 'generate') return _act(() => repo.generate(id), 'Generated');
                      if (a == 'issue') return _act(() => repo.issue(id), 'Issued');
                      if (a == 'collected') {
                        final c = TextEditingController();
                        final by = await showDialog<String>(
                          context: context,
                          builder: (_) => AlertDialog(
                            title: const Text('Collected by'),
                            content: TextField(controller: c),
                            actions: [TextButton(onPressed: () => Navigator.pop(context, c.text), child: const Text('Save'))],
                          ),
                        );
                        if (by != null && by.isNotEmpty) return _act(() => repo.collected(id, by), 'Collected');
                      }
                    },
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'approve', child: Text('Approve')),
                      PopupMenuItem(value: 'reject', child: Text('Reject')),
                      PopupMenuItem(value: 'generate', child: Text('Generate')),
                      PopupMenuItem(value: 'issue', child: Text('Issue')),
                      PopupMenuItem(value: 'collected', child: Text('Pickup collected')),
                    ],
                  ),
                ),
              ),
              empty: 'Queue is empty',
            ),
          ),
        ),
      ]),
    );
  }
}

// ---- verify (QR scan / token) -------------------------------------------------------------------------------------------
class DocumentVerifyScreen extends ConsumerStatefulWidget {
  const DocumentVerifyScreen({super.key});

  @override
  ConsumerState<DocumentVerifyScreen> createState() => _DocumentVerifyScreenState();
}

class _DocumentVerifyScreenState extends ConsumerState<DocumentVerifyScreen> {
  final _token = TextEditingController();
  Map<String, dynamic>? _result;
  String? _err;
  bool _scan = false;

  Future<void> _check(String raw) async {
    final token = raw.contains('/verify/') ? raw.split('/verify/').last.split('?').first : raw.trim();
    setState(() {
      _scan = false;
      _result = null;
      _err = null;
    });
    try {
      final r = await ref.read(documentsRepositoryProvider).verify(token);
      setState(() => _result = r);
    } catch (e) {
      setState(() => _err = _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Verify a document')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          if (_scan)
            SizedBox(
              height: 280,
              child: MobileScanner(onDetect: (cap) {
                final v = cap.barcodes.firstOrNull?.rawValue;
                if (v != null) _check(v);
              }),
            )
          else
            OutlinedButton.icon(onPressed: () => setState(() => _scan = true), icon: const Icon(Icons.qr_code_scanner), label: const Text('Scan QR')),
          TextField(controller: _token, decoration: const InputDecoration(labelText: 'or enter the token')),
          FilledButton(onPressed: () => _check(_token.text), child: const Text('Verify')),
          const SizedBox(height: 16),
          if (_err != null) Text(_err!, style: const TextStyle(color: Colors.red)),
          if (_result != null)
            Card(
              child: ListTile(
                leading: Icon(_result!['valid'] == true ? Icons.verified : Icons.gpp_bad, color: _result!['valid'] == true ? Colors.green : Colors.red),
                title: Text(_result!['valid'] == true ? 'Valid ${_result!['template_type'] ?? ''}' : (_result!['revoked'] == true ? 'Revoked' : 'Not valid')),
                subtitle: Text([
                  if (_result!['document_number'] != null) 'No. ${_result!['document_number']}',
                  if (_result!['holder_masked'] != null) 'Holder ${_result!['holder_masked']}',
                  if (_result!['institution'] != null) '${_result!['institution']}',
                  if (_result!['issued_at'] != null) 'Issued ${_day(_result!['issued_at'])}',
                  if (_result!['superseded_by'] != null) 'Superseded by ${_result!['superseded_by']}',
                  if (_result!['revoke_reason'] != null) 'Reason: ${_result!['revoke_reason']}',
                ].join('\n')),
              ),
            ),
        ]),
      );
}

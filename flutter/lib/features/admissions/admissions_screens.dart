import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';
import '../../core/router/routes.dart';

/// Phase 08 mobile (Prompts/08 §08.10): applicant flows stay on the responsive web portal (`/apply/:cycle` deep link);
/// the admissions-office shell gets **Applicants** (search → detail with documents: open the scan full screen and
/// verify / reject with remarks) and **Enquiries** (assigned to me, call / WhatsApp, stage update). PII masking and
/// row visibility are decided by the API (`admissions:view_pii`, HOD / college slices).
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

const _stages = [
  'new',
  'contacted',
  'counselled',
  'applied',
  'admitted',
  'lost'
];

class AdmissionsRepository {
  AdmissionsRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      });

  Future<List<Map<String, dynamic>>> _list(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((res.data?['data'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> applicants(String search) =>
      _list('/admissions/applicants', {
        if (search.isNotEmpty) 'search': search,
        'page_size': 50,
      });

  Future<Map<String, dynamic>> applicant(String id) async {
    final res =
        await _dio.get<Map<String, dynamic>>('/admissions/applicants/$id');
    return (res.data?['data'] as Map?)?.cast<String, dynamic>() ?? {};
  }

  Future<void> verify(
          String id, String docType, String status, String? remarks) =>
      _dio.post('/admissions/applicants/$id/documents/$docType/verify',
          data: {
            'status': status,
            if (remarks != null && remarks.isNotEmpty) 'remarks': remarks
          },
          options: _once);

  Future<List<Map<String, dynamic>>> enquiries({bool mine = false}) => _list(
      '/admissions/enquiries', {'page_size': 100, if (mine) 'scope': 'self'});

  Future<void> setStage(String id, String stage) =>
      _dio.put('/admissions/enquiries/$id', data: {'stage': stage});
}

final admissionsRepositoryProvider = Provider<AdmissionsRepository>(
    (ref) => AdmissionsRepository(ref.watch(dioProvider)));

// ---- applicants ---------------------------------------------------------------------------------------------------------
class ApplicantsSearchScreen extends ConsumerStatefulWidget {
  const ApplicantsSearchScreen({super.key});

  @override
  ConsumerState<ApplicantsSearchScreen> createState() =>
      _ApplicantsSearchState();
}

class _ApplicantsSearchState extends ConsumerState<ApplicantsSearchScreen> {
  final _q = TextEditingController();
  List<Map<String, dynamic>>? _rows;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _search();
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    try {
      final rows = await ref
          .read(admissionsRepositoryProvider)
          .applicants(_q.text.trim());
      if (mounted) {
        setState(() {
          _rows = rows;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    return Scaffold(
      appBar: AppBar(title: const Text('Applicants')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          child: TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _search(),
            decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Application no., name or phone'),
          ),
        ),
        Expanded(
          child: _err != null
              ? Center(child: Text(_error(_err!)))
              : rows == null
                  ? const Center(child: CircularProgressIndicator())
                  : RefreshIndicator(
                      onRefresh: _search,
                      child: ListView.separated(
                        itemCount: rows.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (_, i) {
                          final a = rows[i];
                          return ListTile(
                            title: Text('${a['name']}'),
                            subtitle: Text(
                                '${a['application_number']} · ${a['category'] ?? '—'} · ${a['first_preference'] ?? '—'}'),
                            trailing: Chip(label: Text(_label(a['status']))),
                            onTap: () => context.push(
                                '${AppRoutes.applicantDetail}?id=${a['id']}'),
                          );
                        },
                      ),
                    ),
        ),
      ]),
    );
  }
}

class ApplicantDetailScreen extends ConsumerStatefulWidget {
  const ApplicantDetailScreen({super.key, required this.id});

  final String id;

  @override
  ConsumerState<ApplicantDetailScreen> createState() => _ApplicantDetailState();
}

class _ApplicantDetailState extends ConsumerState<ApplicantDetailScreen> {
  Map<String, dynamic>? _a;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final a =
          await ref.read(admissionsRepositoryProvider).applicant(widget.id);
      if (mounted) setState(() => _a = a);
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _decide(String docType, String status) async {
    final remarks = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('${_label(status)} ${_label(docType)}'),
        content: TextField(
            controller: remarks,
            decoration: const InputDecoration(labelText: 'Remarks')),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Save')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref
          .read(admissionsRepositoryProvider)
          .verify(widget.id, docType, status, remarks.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_label(status))));
      }
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(e))));
      }
    }
  }

  void _preview(String url) {
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => Scaffold(
        appBar: AppBar(title: const Text('Document')),
        body: InteractiveViewer(
          child: Center(
            child: Image.network(url,
                errorBuilder: (_, __, ___) => Padding(
                      padding: const EdgeInsets.all(24),
                      child: TextButton(
                          onPressed: () => launchUrl(Uri.parse(url)),
                          child: const Text('Open the file')),
                    )),
          ),
        ),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final a = _a;
    if (_err != null) {
      return Scaffold(
          appBar: AppBar(), body: Center(child: Text(_error(_err!))));
    }
    if (a == null) {
      return Scaffold(
          appBar: AppBar(),
          body: const Center(child: CircularProgressIndicator()));
    }
    final docs =
        ((a['documents'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final prefs =
        ((a['preferences'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return Scaffold(
      appBar: AppBar(title: Text('${a['application_number']}')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(12), children: [
          Card(
            child: ListTile(
              title: Text('${a['name']}'),
              subtitle: Text(
                  '${a['category'] ?? '—'}${a['is_pwd'] == true ? ' · PwD' : ''} · ${_label(a['entry_type'])} · ${a['phone'] ?? '—'}\n'
                  'Preferences: ${prefs.map((p) => p['program_code']).join(' › ')}'),
              trailing: Chip(label: Text(_label(a['status']))),
              isThreeLine: true,
            ),
          ),
          const SizedBox(height: 8),
          Text('Documents', style: Theme.of(context).textTheme.titleMedium),
          for (final d in docs)
            Card(
              child: ListTile(
                leading: const Icon(Icons.description_outlined),
                title: Text(_label(d['doc_type'])),
                subtitle: Text(
                    '${_label(d['status'])}${d['remarks'] != null ? ' — ${d['remarks']}' : ''}'),
                onTap: d['file_url'] is String &&
                        !(d['file_url'] as String).startsWith('demo://')
                    ? () => _preview(d['file_url'] as String)
                    : null,
                trailing: d['status'] == 'verified'
                    ? const Icon(Icons.verified, color: Colors.green)
                    : Wrap(children: [
                        IconButton(
                            tooltip: 'Verify',
                            icon: const Icon(Icons.check_circle_outline),
                            onPressed: () =>
                                _decide('${d['doc_type']}', 'verified')),
                        IconButton(
                            tooltip: 'Reject',
                            icon: const Icon(Icons.cancel_outlined),
                            onPressed: () =>
                                _decide('${d['doc_type']}', 'rejected')),
                      ]),
              ),
            ),
          if (docs.isEmpty) const Text('No documents uploaded.'),
        ]),
      ),
    );
  }
}

// ---- enquiries ----------------------------------------------------------------------------------------------------------
class EnquiriesScreen extends ConsumerStatefulWidget {
  const EnquiriesScreen({super.key});

  @override
  ConsumerState<EnquiriesScreen> createState() => _EnquiriesState();
}

class _EnquiriesState extends ConsumerState<EnquiriesScreen> {
  bool _mine = true;
  List<Map<String, dynamic>>? _rows;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows =
          await ref.read(admissionsRepositoryProvider).enquiries(mine: _mine);
      if (mounted) {
        setState(() {
          _rows = rows;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _stage(Map<String, dynamic> e, String stage) async {
    try {
      await ref
          .read(admissionsRepositoryProvider)
          .setStage('${e['id']}', stage);
      await _load();
    } catch (err) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(err))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    return Scaffold(
      appBar: AppBar(title: const Text('Enquiries'), actions: [
        Row(children: [
          const Text('Mine'),
          Switch(
              value: _mine,
              onChanged: (v) {
                setState(() => _mine = v);
                _load();
              }),
        ]),
      ]),
      body: _err != null
          ? Center(child: Text(_error(_err!)))
          : rows == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.builder(
                    itemCount: rows.length,
                    itemBuilder: (_, i) {
                      final e = rows[i];
                      final phone = e['phone'] as String?;
                      final dial = phone?.replaceAll(RegExp(r'[^0-9+]'), '');
                      return Card(
                        margin: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 4),
                        child: Padding(
                          padding: const EdgeInsets.all(8),
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${e['name']}',
                                    style:
                                        Theme.of(context).textTheme.titleSmall),
                                Text(
                                    '${_label(e['source'])} · follow up ${e['follow_up_on'] ?? '—'}'),
                                Row(children: [
                                  if (dial != null && !dial.contains('*')) ...[
                                    IconButton(
                                        tooltip: 'Call',
                                        icon: const Icon(Icons.call),
                                        onPressed: () =>
                                            launchUrl(Uri.parse('tel:$dial'))),
                                    IconButton(
                                        tooltip: 'WhatsApp',
                                        icon: const Icon(Icons.chat),
                                        onPressed: () => launchUrl(
                                            Uri.parse(
                                                'https://wa.me/${dial.replaceAll('+', '')}'),
                                            mode: LaunchMode
                                                .externalApplication)),
                                  ],
                                  const Spacer(),
                                  DropdownButton<String>(
                                    value: '${e['stage']}',
                                    items: [
                                      for (final s in _stages)
                                        DropdownMenuItem(
                                            value: s, child: Text(_label(s)))
                                    ],
                                    onChanged: (s) {
                                      if (s != null && s != e['stage']) {
                                        _stage(e, s);
                                      }
                                    },
                                  ),
                                ]),
                              ]),
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

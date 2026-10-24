import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 19 mobile (Prompts/19 §19.10): **Library** for students / faculty / scholars / alumni (my books with due dates
/// and renew, reservations, fines, OPAC search with availability), parents (ward card) and the librarian
/// **Circulation** scanner (camera barcode → issue / return / renew) with an offline return queue flushed when the
/// network is back. Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _rupees(dynamic p) => '₹${(((p as num?) ?? 0) / 100).toStringAsFixed(2)}';

class LibraryRepository {
  LibraryRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;
  static const _queueKey = 'library.return_queue';

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) {
    if (v is Map && v['items'] is List) return (v['items'] as List).cast<Map<String, dynamic>>();
    return ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> me() async => ((await _get('/library/members/me')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> wards() async => _list(await _get('/library/members/wards'));
  Future<List<Map<String, dynamic>>> myIssues() async => _list(await _get('/library/members/me/issues'));
  Future<List<Map<String, dynamic>>> myFines() async => _list(await _get('/library/members/me/fines'));
  Future<List<Map<String, dynamic>>> myReservations() async => _list(await _get('/library/reservations', {'mine': true}));
  Future<void> renew(String issueId) => _post('/library/circulation/self-renew', {'issue_id': issueId});
  Future<void> reserve(String bookId) => _post('/library/reservations', {'book_id': bookId});
  Future<Map<String, dynamic>> opac(String institution, String q) async =>
      ((await _get('/opac/search', {'institution': institution, 'q': q})) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> stats() async => ((await _get('/library/stats')) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> issue(String memberCode, String barcode) async =>
      ((await _post('/library/circulation/issue', {'member_code': memberCode, 'barcode': barcode})) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> returnCopy(String barcode) async =>
      ((await _post('/library/circulation/return', {'barcode': barcode})) as Map).cast<String, dynamic>();

  // ---- offline return queue -----------------------------------------------------------------------------------------
  Future<List<String>> queued() async {
    final hit = await _cache.read(_queueKey);
    return hit == null ? [] : (jsonDecode(hit.json) as List).cast<String>();
  }

  Future<void> enqueueReturn(String barcode) async {
    final q = await queued()..add(barcode);
    await _cache.write(_queueKey, jsonEncode(q), ttl: const Duration(days: 7));
  }

  /// Sends queued returns in order; failures stay queued.
  Future<int> flush() async {
    final q = await queued();
    final left = <String>[];
    var sent = 0;
    for (final b in q) {
      try {
        await returnCopy(b);
        sent++;
      } on DioException catch (e) {
        if (e.response == null) left.add(b); // still offline
      }
    }
    await _cache.write(_queueKey, jsonEncode(left), ttl: const Duration(days: 7));
    return sent;
  }
}

final libraryRepositoryProvider = Provider<LibraryRepository>((ref) => LibraryRepository(ref.watch(dioProvider), CacheRepository()));

void _snack(BuildContext context, String msg) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

// ---- member: my library -----------------------------------------------------------------------------------------------------------
class MyLibraryScreen extends ConsumerStatefulWidget {
  const MyLibraryScreen({super.key, this.ward = false});

  final bool ward;

  @override
  ConsumerState<MyLibraryScreen> createState() => _MyLibraryScreenState();
}

class _MyLibraryScreenState extends ConsumerState<MyLibraryScreen> {
  late Future<List<dynamic>> _f = _load();

  Future<List<dynamic>> _load() {
    final r = ref.read(libraryRepositoryProvider);
    if (widget.ward) return Future.wait([r.wards()]);
    return Future.wait([r.me(), r.myIssues(), r.myReservations(), r.myFines()]);
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(libraryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: Text(widget.ward ? "Ward's library" : 'Library'), actions: [
        if (!widget.ward)
          IconButton(icon: const Icon(Icons.search), onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const OpacScreen()))),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<dynamic>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            if (widget.ward) {
              final cards = (snap.data![0] as List).cast<Map<String, dynamic>>();
              return ListView(children: [
                if (cards.isEmpty) const ListTile(title: Text('No library card.')),
                for (final m in cards) _MemberCard(m: m),
              ]);
            }
            final me = snap.data![0] as Map<String, dynamic>;
            final issues = (snap.data![1] as List).cast<Map<String, dynamic>>().where((i) => i['status'] == 'issued' || i['status'] == 'overdue').toList();
            final res = (snap.data![2] as List).cast<Map<String, dynamic>>().where((r) => r['status'] == 'waiting' || r['status'] == 'available').toList();
            final fines = (snap.data![3] as List).cast<Map<String, dynamic>>();
            return ListView(padding: const EdgeInsets.all(8), children: [
              _MemberCard(m: me),
              const Padding(padding: EdgeInsets.all(8), child: Text('My books', style: TextStyle(fontWeight: FontWeight.w600))),
              if (issues.isEmpty) const ListTile(title: Text('No books on loan.')),
              for (final i in issues)
                ListTile(
                  title: Text('${i['title']}'),
                  subtitle: Text((i['days_overdue'] as num? ?? 0) > 0 ? 'Overdue by ${i['days_overdue']} day(s)' : 'Due ${i['due_on']} · renewals ${i['renewals']}'),
                  trailing: TextButton(
                    onPressed: () async {
                      try {
                        await repo.renew('${i['id']}');
                        if (context.mounted) _snack(context, 'Renewed');
                        setState(() => _f = _load());
                      } catch (e) {
                        if (context.mounted) _snack(context, _error(e));
                      }
                    },
                    child: const Text('Renew'),
                  ),
                ),
              const Padding(padding: EdgeInsets.all(8), child: Text('Reservations', style: TextStyle(fontWeight: FontWeight.w600))),
              if (res.isEmpty) const ListTile(title: Text('No reservations.')),
              for (final r in res)
                ListTile(title: Text('${r['title']}'), subtitle: Text(r['status'] == 'available' ? 'Ready — collect by ${r['expires_at']}' : 'Position ${r['position']}')),
              const Padding(padding: EdgeInsets.all(8), child: Text('Fines', style: TextStyle(fontWeight: FontWeight.w600))),
              if (fines.isEmpty) const ListTile(title: Text('No fines.')),
              for (final f in fines) ListTile(title: Text('${f['title']}'), subtitle: Text('${f['invoice_status']}'), trailing: Text(_rupees(f['balance_paise']))),
            ]);
          },
        ),
      ),
    );
  }
}

class _MemberCard extends StatelessWidget {
  const _MemberCard({required this.m});

  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final reasons = ((m['block_reasons'] as List?) ?? const []).cast<String>();
    return Card(
      child: ListTile(
        leading: Icon(reasons.isEmpty ? Icons.local_library : Icons.block, color: reasons.isEmpty ? Colors.green : Colors.red),
        title: Text('${m['name'] ?? ''} · ${m['member_code']}'),
        subtitle: Text('${m['active_issues']} / ${m['max_books_allowed']} books · fines ${_rupees(m['outstanding_fine_paise'])}${reasons.isEmpty ? '' : '\nBlocked: ${reasons.join(', ')}'}'),
      ),
    );
  }
}

// ---- OPAC -----------------------------------------------------------------------------------------------------------------------------
class OpacScreen extends ConsumerStatefulWidget {
  const OpacScreen({super.key});

  @override
  ConsumerState<OpacScreen> createState() => _OpacScreenState();
}

class _OpacScreenState extends ConsumerState<OpacScreen> {
  final _q = TextEditingController();
  final _inst = TextEditingController();
  Future<Map<String, dynamic>>? _f;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(libraryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Catalogue')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(8),
          child: Row(children: [
            SizedBox(width: 90, child: TextField(controller: _inst, decoration: const InputDecoration(labelText: 'Institution'))),
            const SizedBox(width: 8),
            Expanded(child: TextField(controller: _q, decoration: const InputDecoration(labelText: 'Title, author, ISBN'), onSubmitted: (_) => setState(() => _f = repo.opac(_inst.text, _q.text)))),
            IconButton(icon: const Icon(Icons.search), onPressed: () => setState(() => _f = repo.opac(_inst.text, _q.text))),
          ]),
        ),
        Expanded(
          child: _f == null
              ? const SizedBox()
              : FutureBuilder<Map<String, dynamic>>(
                  future: _f,
                  builder: (context, snap) {
                    if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
                    if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                    final items = ((snap.data!['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
                    return ListView(children: [
                      for (final b in items)
                        ListTile(
                          title: Text('${b['title']}'),
                          subtitle: Text('${((b['authors'] as List?) ?? const []).join(', ')} · ${b['available_copies']}/${b['total_copies']} available'),
                          trailing: (b['available_copies'] as num? ?? 0) == 0
                              ? TextButton(
                                  onPressed: () async {
                                    try {
                                      await repo.reserve('${b['id']}');
                                      if (context.mounted) _snack(context, 'Reserved');
                                    } catch (e) {
                                      if (context.mounted) _snack(context, _error(e));
                                    }
                                  },
                                  child: const Text('Reserve'),
                                )
                              : null,
                        ),
                    ]);
                  },
                ),
        ),
      ]),
    );
  }
}

// ---- librarian: circulation scanner ------------------------------------------------------------------------------------------------
class LibraryCirculationScreen extends ConsumerStatefulWidget {
  const LibraryCirculationScreen({super.key});

  @override
  ConsumerState<LibraryCirculationScreen> createState() => _LibraryCirculationScreenState();
}

class _LibraryCirculationScreenState extends ConsumerState<LibraryCirculationScreen> {
  final _member = TextEditingController();
  String _mode = 'return';
  String? _last;
  String _status = 'Scan a copy barcode.';
  int _queued = 0;

  @override
  void initState() {
    super.initState();
    ref.read(libraryRepositoryProvider).queued().then((q) => mounted ? setState(() => _queued = q.length) : null);
  }

  Future<void> _onDetect(BarcodeCapture cap) async {
    final code = cap.barcodes.isNotEmpty ? cap.barcodes.first.rawValue : null;
    if (code == null || code == _last) return;
    _last = code;
    final repo = ref.read(libraryRepositoryProvider);
    try {
      if (_mode == 'issue') {
        if (_member.text.trim().isEmpty) {
          setState(() => _status = 'Enter the member code first');
          return;
        }
        final r = await repo.issue(_member.text.trim(), code);
        setState(() => _status = '✓ Issued ${r['title']} — due ${r['due_on']}');
      } else {
        final r = await repo.returnCopy(code);
        final fine = (r['fine_paise'] as num? ?? 0);
        setState(() => _status = '✓ Returned ${r['issue']?['title']}${fine > 0 ? ' — fine ${_rupees(fine)}' : ''}');
      }
    } on DioException catch (e) {
      if (e.response == null && _mode == 'return') {
        await repo.enqueueReturn(code);
        final q = await repo.queued();
        setState(() {
          _queued = q.length;
          _status = 'Offline — return queued ($code)';
        });
      } else {
        setState(() => _status = '✗ ${_error(e)}');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(libraryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Circulation'), actions: [
        if (_queued > 0)
          TextButton.icon(
            icon: const Icon(Icons.cloud_upload_outlined),
            label: Text('$_queued queued'),
            onPressed: () async {
              final sent = await repo.flush();
              final q = await repo.queued();
              setState(() {
                _queued = q.length;
                _status = 'Synced $sent queued return(s)';
              });
            },
          ),
      ]),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(8),
          child: SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'return', label: Text('Return')), ButtonSegment(value: 'issue', label: Text('Issue'))],
            selected: {_mode},
            onSelectionChanged: (s) => setState(() => _mode = s.first),
          ),
        ),
        if (_mode == 'issue')
          Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: TextField(controller: _member, decoration: const InputDecoration(labelText: 'Member code (LM…)'))),
        Expanded(child: MobileScanner(onDetect: _onDetect)),
        Padding(padding: const EdgeInsets.all(16), child: Text(_status, textAlign: TextAlign.center)),
      ]),
    );
  }
}

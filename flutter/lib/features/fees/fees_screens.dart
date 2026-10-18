import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 12 mobile (Prompts/12 §12.10): student / parent **Fees** (dues by invoice, pay through the UPI intent,
/// declare an offline payment with UTR, receipts share, scholarships, refunds, no-dues status), accountant **Collect**
/// (search → dues → collect → ESC/POS thermal payload, previewed when no printer is paired), **Reconciliation**
/// review (confirm / ignore proposed matches) and **No-dues sign-off** cards for the offices that own a department
/// (librarian, warden, HOD, accounts …). Rules and visibility live in the API.
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

String inr(Object? paise) => '₹${(((paise as num?) ?? 0) / 100).toStringAsFixed(2)}';
int toPaise(String rupees) => ((double.tryParse(rupees) ?? 0) * 100).round();

Color _statusColor(String s) => switch (s) {
      'paid' || 'cleared' || 'success' || 'reconciled' || 'disbursed' => Colors.green,
      'partial' || 'pending' || 'in_progress' || 'initiated' => Colors.orange,
      'overdue' || 'blocked' || 'dues_pending' || 'bounced' || 'failed' => Colors.red,
      _ => Colors.grey,
    };

class FeesRepository {
  FeesRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()});

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async =>
      (await _dio.post<Map<String, dynamic>>(path, data: body ?? {}, options: _once)).data?['data'];

  Future<Map<String, dynamic>> myDues() async => ((await _get('/fees/me/dues')) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> wardDues(String id) async =>
      ((await _get('/fees/wards/$id/dues')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> wards() async =>
      (((await _get('/guardians/me/wards')) as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<List<Map<String, dynamic>>> receipts() async =>
      (((await _get('/fees/me/receipts')) as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<List<Map<String, dynamic>>> noDues() async =>
      (((await _get('/no-dues/me')) as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<List<Map<String, dynamic>>> scholarships() async =>
      (((await _get('/scholarship-applications/me')) as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<Map<String, dynamic>> upiQr(String invoiceId) async =>
      ((await _post('/fees/upi-qr', {'invoice_id': invoiceId})) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> upiStatus(String ref) async =>
      ((await _get('/fees/upi-qr/$ref/status')) as Map).cast<String, dynamic>();
  Future<void> declare(Map<String, dynamic> body) => _post('/fees/offline/declare', body);
  Future<List<Map<String, dynamic>>> search(String q) async =>
      (((await _get('/fees/invoices', {'q': q, 'scope': 'all', 'page_size': 50})) as List?) ?? const [])
          .cast<Map<String, dynamic>>();
  Future<Map<String, dynamic>> collect(Map<String, dynamic> body) async =>
      ((await _post('/fees/collect', body)) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> thermal(String paymentId) async =>
      ((await _get('/fees/payments/$paymentId/thermal')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> reconcile() async =>
      (((await _get('/fees/reconcile', {'status': 'unmatched'})) as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<void> match(String id, String paymentId) => _post('/fees/reconcile/$id/match', {'payment_id': paymentId});
  Future<void> ignore(String id) => _post('/fees/reconcile/$id/ignore');
  Future<List<Map<String, dynamic>>> signoffQueue() async =>
      (((await _get('/no-dues', {'scope': 'department', 'status': 'in_progress'})) as List?) ?? const [])
          .cast<Map<String, dynamic>>();
  Future<void> signoff(String id, Map<String, dynamic> body) => _post('/no-dues/$id/signoff', body);
}

final feesRepositoryProvider = Provider<FeesRepository>((ref) => FeesRepository(ref.watch(dioProvider)));

// ---- student / parent ------------------------------------------------------------------------------------------------
class StudentFeesScreen extends ConsumerStatefulWidget {
  const StudentFeesScreen({super.key});

  @override
  ConsumerState<StudentFeesScreen> createState() => _StudentFeesScreenState();
}

class _StudentFeesScreenState extends ConsumerState<StudentFeesScreen> {
  String? _ward;
  List<Map<String, dynamic>> _wards = const [];
  late Future<Map<String, dynamic>> _dues;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final repo = ref.read(feesRepositoryProvider);
    _dues = _ward == null
        ? repo.myDues().catchError((Object err) async {
            _wards = await repo.wards();
            if (_wards.isEmpty) throw err;
            _ward = '${_wards.first['student_id']}';
            return repo.wardDues(_ward!);
          })
        : repo.wardDues(_ward!);
  }

  Future<void> _payUpi(Map<String, dynamic> inv) async {
    final repo = ref.read(feesRepositoryProvider);
    try {
      final qr = await repo.upiQr('${inv['id']}');
      final uri = Uri.parse('${qr['upi_uri']}');
      final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!mounted) return;
      if (!launched) {
        await showDialog<void>(
            context: context,
            builder: (_) => AlertDialog(
                title: const Text('UPI'), content: SelectableText('${qr['upi_uri']}\nRef ${qr['ref']}')));
      }
      final st = await repo.upiStatus('${qr['ref']}');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('UPI status: ${st['status']}')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  Future<void> _declare(Map<String, dynamic> inv) async {
    final utr = TextEditingController();
    final amount = TextEditingController(text: '${((inv['balance_paise'] as num) / 100)}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Declare NEFT / challan'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: amount, decoration: const InputDecoration(labelText: 'Amount ₹'), keyboardType: TextInputType.number),
          TextField(controller: utr, decoration: const InputDecoration(labelText: 'UTR / reference')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Submit')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(feesRepositoryProvider).declare(
          {'invoice_id': inv['id'], 'amount_paise': toPaise(amount.text), 'mode': 'neft', 'utr': utr.text});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Declared — pending reconciliation')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(feesRepositoryProvider);
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Fees'),
          bottom: const TabBar(isScrollable: true, tabs: [
            Tab(text: 'Dues'),
            Tab(text: 'Receipts'),
            Tab(text: 'Scholarships'),
            Tab(text: 'No-dues'),
          ]),
        ),
        body: TabBarView(children: [
          RefreshIndicator(
            onRefresh: () async => setState(_load),
            child: FutureBuilder<Map<String, dynamic>>(
              future: _dues,
              builder: (context, snap) {
                if (snap.hasError) return ListView(children: [ListTile(title: Text(_error(snap.error!)))]);
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                final d = snap.data!;
                final invoices = ((d['invoices'] as List?) ?? const []).cast<Map<String, dynamic>>();
                return ListView(padding: const EdgeInsets.all(12), children: [
                  if (_wards.length > 1)
                    DropdownButton<String>(
                      value: _ward,
                      items: [
                        for (final w in _wards)
                          DropdownMenuItem(value: '${w['student_id']}', child: Text('${w['name']}'))
                      ],
                      onChanged: (v) => setState(() {
                        _ward = v;
                        _load();
                      }),
                    ),
                  Card(
                    child: ListTile(
                      title: Text('Total due ${inr(d['total_due'])}'),
                      subtitle: Text('Overdue ${inr(d['overdue'])} · next due ${d['next_due'] ?? '—'}'),
                    ),
                  ),
                  for (final inv in invoices)
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            Expanded(child: Text('${inv['description'] ?? inv['invoice_number']}', style: Theme.of(context).textTheme.titleSmall)),
                            Chip(
                                label: Text('${inv['status']}'),
                                backgroundColor: _statusColor('${inv['status']}').withValues(alpha: 0.15)),
                          ]),
                          for (final it in ((inv['items'] as List?) ?? const []).cast<Map<String, dynamic>>())
                            Text('${it['description']} · ${it['due_date'] ?? ''} · ${inr(it['amount_paise'])}'),
                          const SizedBox(height: 6),
                          Text('Balance ${inr(inv['balance_paise'])}', style: const TextStyle(fontWeight: FontWeight.bold)),
                          if ((inv['balance_paise'] as num) > 0 && inv['status'] != 'cancelled')
                            Wrap(spacing: 8, children: [
                              FilledButton.icon(
                                  onPressed: () => _payUpi(inv), icon: const Icon(Icons.qr_code), label: const Text('Pay by UPI')),
                              OutlinedButton(onPressed: () => _declare(inv), child: const Text('Paid by NEFT')),
                            ]),
                        ]),
                      ),
                    ),
                ]);
              },
            ),
          ),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.receipts(),
            builder: (context, snap) => !snap.hasData
                ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
                : ListView(children: [
                    for (final p in snap.data!)
                      ListTile(
                        title: Text('${p['receipt_number']} · ${inr(p['amount_paise'])}'),
                        subtitle: Text('${p['payment_date']} · ${p['payment_mode']} · ${p['status']}'),
                        trailing: IconButton(
                          icon: const Icon(Icons.share),
                          onPressed: () => Share.share(
                              'Fee receipt ${p['receipt_number']} — ${inr(p['amount_paise'])} on ${p['payment_date']}'),
                        ),
                      ),
                  ]),
          ),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.scholarships(),
            builder: (context, snap) => !snap.hasData
                ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
                : ListView(children: [
                    for (final a in snap.data!)
                      ListTile(
                        title: Text('${a['scholarship_name']}'),
                        subtitle: Text('${a['status']}${a['sanctioned_paise'] != null ? ' · ${inr(a['sanctioned_paise'])}' : ''}'),
                      ),
                    if (snap.data!.isEmpty) const ListTile(title: Text('Apply for scholarships on the web portal.')),
                  ]),
          ),
          FutureBuilder<List<Map<String, dynamic>>>(
            future: repo.noDues(),
            builder: (context, snap) => !snap.hasData
                ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
                : ListView(children: [
                    for (final r in snap.data!)
                      Card(
                        child: ListTile(
                          title: Text('${r['purpose']} · ${r['status']}'),
                          subtitle: Wrap(spacing: 4, children: [
                            for (final s in ((r['signoffs'] as List?) ?? const []).cast<Map<String, dynamic>>())
                              Chip(
                                  label: Text('${s['department_key']}'),
                                  backgroundColor: _statusColor('${s['status']}').withValues(alpha: 0.15)),
                          ]),
                        ),
                      ),
                    if (snap.data!.isEmpty) const ListTile(title: Text('No no-dues requests.')),
                  ]),
          ),
        ]),
      ),
    );
  }
}

// ---- accountant collect ------------------------------------------------------------------------------------------------
class CollectScreen extends ConsumerStatefulWidget {
  const CollectScreen({super.key});

  @override
  ConsumerState<CollectScreen> createState() => _CollectScreenState();
}

class _CollectScreenState extends ConsumerState<CollectScreen> {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _open = const [];
  final Map<String, TextEditingController> _alloc = {};
  String _mode = 'cash';
  bool _busy = false;

  Future<void> _search() async {
    try {
      final rows = await ref.read(feesRepositoryProvider).search(_q.text.trim());
      setState(() {
        _open = rows.where((r) => ['pending', 'partial', 'overdue'].contains(r['status'])).toList();
        _alloc
          ..clear()
          ..addEntries(_open.map((r) => MapEntry('${r['id']}', TextEditingController())));
      });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  Future<void> _collect() async {
    final allocation = [
      for (final e in _alloc.entries)
        if (toPaise(e.value.text) > 0) {'invoice_id': e.key, 'amount_paise': toPaise(e.value.text)}
    ];
    final total = allocation.fold<int>(0, (a, x) => a + (x['amount_paise'] as int));
    if (total <= 0) return;
    setState(() => _busy = true);
    try {
      final repo = ref.read(feesRepositoryProvider);
      final r = await repo.collect({'allocation': allocation, 'amount_paise': total, 'mode': _mode, 'counter': 'mobile'});
      final pays = ((r['payments'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final thermal = pays.isEmpty ? null : await repo.thermal('${pays.first['id']}');
      if (!mounted) return;
      // no paired ESC/POS printer: preview the 32-column payload (Phase 42 adds the Bluetooth driver)
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text('Receipt ${(r['receipt_numbers'] as List).join(', ')}'),
          content: SingleChildScrollView(
              child: Text('${thermal?['text'] ?? ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12))),
          actions: [
            TextButton(
                onPressed: () => Share.share('${thermal?['text'] ?? ''}'),
                child: const Text('Share')),
          ],
        ),
      );
      await _search();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Collect')),
        body: ListView(padding: const EdgeInsets.all(12), children: [
          Row(children: [
            Expanded(
                child: TextField(
                    controller: _q,
                    decoration: const InputDecoration(labelText: 'Registration no. / name'),
                    onSubmitted: (_) => _search())),
            IconButton(onPressed: _search, icon: const Icon(Icons.search)),
          ]),
          for (final inv in _open)
            Card(
              child: ListTile(
                title: Text('${inv['invoice_number']} · ${inv['payer_name'] ?? ''}'),
                subtitle: Text('Balance ${inr(inv['balance_paise'])} · due ${inv['due_date'] ?? '—'}'),
                trailing: SizedBox(
                  width: 100,
                  child: TextField(
                    controller: _alloc['${inv['id']}'],
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                        hintText: '₹',
                        suffixIcon: IconButton(
                            icon: const Icon(Icons.done_all, size: 16),
                            onPressed: () => _alloc['${inv['id']}']!.text = '${(inv['balance_paise'] as num) / 100}')),
                  ),
                ),
              ),
            ),
          if (_open.isNotEmpty) ...[
            DropdownButton<String>(
              value: _mode,
              items: [for (final m in const ['cash', 'upi', 'card']) DropdownMenuItem(value: m, child: Text(m))],
              onChanged: (v) => setState(() => _mode = v ?? 'cash'),
            ),
            FilledButton(onPressed: _busy ? null : _collect, child: const Text('Collect & print')),
          ],
        ]),
      );
}

// ---- reconciliation review -----------------------------------------------------------------------------------------------
class ReconcileReviewScreen extends ConsumerStatefulWidget {
  const ReconcileReviewScreen({super.key});

  @override
  ConsumerState<ReconcileReviewScreen> createState() => _ReconcileReviewScreenState();
}

class _ReconcileReviewScreenState extends ConsumerState<ReconcileReviewScreen> {
  late Future<List<Map<String, dynamic>>> _rows = ref.read(feesRepositoryProvider).reconcile();

  Future<void> _act(Future<void> Function() f) async {
    try {
      await f();
      setState(() => _rows = ref.read(feesRepositoryProvider).reconcile());
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(feesRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Reconciliation')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _rows,
        builder: (context, snap) => !snap.hasData
            ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
            : ListView(children: [
                for (final r in snap.data!)
                  ListTile(
                    title: Text('${r['utr'] ?? '—'} · ${inr(r['amount_paise'])}'),
                    subtitle: Text('${r['statement_date'] ?? ''} ${r['payer_hint'] ?? ''}'
                        '${r['proposed_receipt'] != null ? '\nProposed: ${r['proposed_receipt']}' : ''}'),
                    isThreeLine: r['proposed_receipt'] != null,
                    trailing: Wrap(children: [
                      if (r['proposed_payment_id'] != null)
                        IconButton(
                            icon: const Icon(Icons.check_circle, color: Colors.green),
                            onPressed: () => _act(() => repo.match('${r['id']}', '${r['proposed_payment_id']}'))),
                      IconButton(icon: const Icon(Icons.block), onPressed: () => _act(() => repo.ignore('${r['id']}'))),
                    ]),
                  ),
                if (snap.data!.isEmpty) const ListTile(title: Text('Nothing to reconcile.')),
              ]),
      ),
    );
  }
}

// ---- no-dues sign-off cards ------------------------------------------------------------------------------------------------
class NoDuesSignoffScreen extends ConsumerStatefulWidget {
  const NoDuesSignoffScreen({super.key});

  @override
  ConsumerState<NoDuesSignoffScreen> createState() => _NoDuesSignoffScreenState();
}

class _NoDuesSignoffScreenState extends ConsumerState<NoDuesSignoffScreen> {
  late Future<List<Map<String, dynamic>>> _rows = ref.read(feesRepositoryProvider).signoffQueue();

  Future<void> _sign(String id, String key, String status) async {
    var dues = 0;
    if (status == 'dues_pending') {
      final c = TextEditingController();
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Dues pending'),
          content: TextField(controller: c, decoration: const InputDecoration(labelText: 'Amount ₹'), keyboardType: TextInputType.number),
          actions: [FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save'))],
        ),
      );
      if (ok != true) return;
      dues = toPaise(c.text);
    }
    try {
      await ref.read(feesRepositoryProvider).signoff(id, {'department_key': key, 'status': status, 'dues_paise': dues});
      setState(() => _rows = ref.read(feesRepositoryProvider).signoffQueue());
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('No-dues sign-off')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _rows,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final r in snap.data!)
                    for (final s in ((r['signoffs'] as List?) ?? const [])
                        .cast<Map<String, dynamic>>()
                        .where((s) => s['can_sign'] == true && s['status'] != 'cleared'))
                      Card(
                        child: ListTile(
                          title: Text('${r['student_name']} (${r['registration_number']})'),
                          subtitle: Text('${r['purpose']} · ${s['department_key']} · ${s['status']}'),
                          trailing: Wrap(children: [
                            IconButton(
                                icon: const Icon(Icons.check, color: Colors.green),
                                onPressed: () => _sign('${r['id']}', '${s['department_key']}', 'cleared')),
                            IconButton(
                                icon: const Icon(Icons.money_off, color: Colors.red),
                                onPressed: () => _sign('${r['id']}', '${s['department_key']}', 'dues_pending')),
                          ]),
                        ),
                      ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('No pending sign-offs for your office.')),
                ]),
        ),
      );
}

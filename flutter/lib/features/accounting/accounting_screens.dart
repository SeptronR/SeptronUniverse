import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/providers.dart';

/// Phase 23 mobile (Prompts/23 §23.10): accountant **Accounting** (dashboard cards — bank / cash, receivables, budget
/// alerts, pending reconciliations — and the below-threshold expense approvals; workflow approvals stay in the generic
/// Approvals inbox), HOD **Budget** (own heads' utilisation, record an expense with a photo of the bill), faculty PI
/// **Grants** (balance per head, add an expense with a receipt photo, utilisation certificate request is the web PDF).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _rupees(dynamic p) => '₹${(((p ?? 0) as num) / 100).toStringAsFixed(0)}';
String _today() => DateTime.now().toIso8601String().substring(0, 10);

class AccountingRepository {
  AccountingRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> dashboard() async => ((await _get('/accounting/dashboard')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> pending() async => _list(await _get('/accounting/expenses', {'status': 'submitted', 'manual_only': true}));
  Future<void> decide(String id, String action) => _post('/accounting/expenses/$id/decide', {'action': action});
  Future<List<Map<String, dynamic>>> myBudgets() async => _list(await _get('/accounting/budgets/me'));
  Future<List<Map<String, dynamic>>> accounts() async => _list(await _get('/accounting/accounts'));
  Future<List<Map<String, dynamic>>> grants() async => _list(await _get('/accounting/grants'));

  Future<String?> upload(XFile file) async {
    final form = FormData.fromMap({'file': await MultipartFile.fromFile(file.path, filename: file.name)});
    final r = await _dio.post<Map<String, dynamic>>('/accounting/attachments', data: form);
    return (r.data?['data'] as Map?)?['document_url'] as String?;
  }

  Future<void> recordExpense(Map<String, dynamic> body) async {
    final r = (await _post('/accounting/expenses', body)) as Map;
    await _post('/accounting/expenses/${r['id']}/submit');
  }

  Future<void> grantExpense(String id, Map<String, dynamic> body) => _post('/accounting/grants/$id/expenses', body);
}

final accountingRepositoryProvider = Provider<AccountingRepository>((ref) => AccountingRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<Map<String, dynamic>?> _expenseDialog(BuildContext context, {List<String>? heads, List<Map<String, dynamic>>? budgetHeads}) async {
  final amount = TextEditingController();
  final payee = TextEditingController();
  final desc = TextEditingController();
  String? head = heads?.isNotEmpty == true ? heads!.first : null;
  String? budget = budgetHeads?.isNotEmpty == true ? '${budgetHeads!.first['id']}' : null;
  XFile? photo;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => AlertDialog(
        title: const Text('Record expense'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (heads != null)
              DropdownButton<String>(isExpanded: true, value: head, items: [for (final h in heads) DropdownMenuItem(value: h, child: Text(h))], onChanged: (v) => set(() => head = v)),
            if (budgetHeads != null)
              DropdownButton<String>(
                isExpanded: true,
                value: budget,
                items: [for (final b in budgetHeads) DropdownMenuItem(value: '${b['id']}', child: Text('${b['name']} · ${_rupees(b['available_paise'])} left'))],
                onChanged: (v) => set(() => budget = v),
              ),
            TextField(controller: amount, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Amount (₹)')),
            if (budgetHeads != null) TextField(controller: payee, decoration: const InputDecoration(labelText: 'Payee')),
            TextField(controller: desc, decoration: const InputDecoration(labelText: 'Description')),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.photo_camera_outlined),
              label: Text(photo == null ? 'Photo of the bill' : 'Photo attached'),
              onPressed: () async {
                final f = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 70);
                if (f != null) set(() => photo = f);
              },
            ),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save'))],
      ),
    ),
  );
  if (ok != true) return null;
  final paise = ((double.tryParse(amount.text) ?? 0) * 100).round();
  if (paise <= 0) return null;
  return {'amount_paise': paise, 'head': head, 'budget_head_id': budget, 'payee': payee.text, 'description': desc.text, 'photo': photo};
}

// ---- accountant ------------------------------------------------------------------------------------------------------------
class AccountingHomeScreen extends ConsumerStatefulWidget {
  const AccountingHomeScreen({super.key});

  @override
  ConsumerState<AccountingHomeScreen> createState() => _AccountingHomeScreenState();
}

class _AccountingHomeScreenState extends ConsumerState<AccountingHomeScreen> {
  late Future<List<dynamic>> _f = _load();

  Future<List<dynamic>> _load() {
    final r = ref.read(accountingRepositoryProvider);
    return Future.wait<dynamic>([r.dashboard(), r.pending()]);
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(accountingRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Accounting')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<dynamic>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final d = snap.data![0] as Map<String, dynamic>;
            final pending = (snap.data![1] as List).cast<Map<String, dynamic>>();
            final alerts = ((d['budget_alerts'] as List?) ?? const []).cast<Map<String, dynamic>>();
            return ListView(padding: const EdgeInsets.all(8), children: [
              Wrap(spacing: 8, runSpacing: 8, children: [
                Chip(label: Text('Bank ${_rupees(d['bank_paise'])}')),
                Chip(label: Text('Cash ${_rupees(d['cash_paise'])}')),
                Chip(label: Text('Receivable ${_rupees(d['receivables_paise'])}')),
                Chip(label: Text('${d['open_reconciliations']} open reconciliation(s)')),
                Chip(label: Text('${d['posting_gaps']} posting gap(s)')),
              ]),
              if (alerts.isNotEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('Budget alerts', style: TextStyle(fontWeight: FontWeight.w600))),
              for (final a in alerts.take(8)) ListTile(dense: true, leading: const Icon(Icons.warning_amber, color: Colors.orange), title: Text('${a['head']}'), trailing: Text('${a['pct']}%')),
              const Padding(padding: EdgeInsets.all(8), child: Text('Expenses awaiting approval', style: TextStyle(fontWeight: FontWeight.w600))),
              if (pending.isEmpty) const ListTile(title: Text('Nothing pending.')),
              for (final e in pending)
                Card(
                  child: ListTile(
                    title: Text('${e['payee']} · ${_rupees(e['amount_paise'])}'),
                    subtitle: Text('${e['description'] ?? ''}${e['budget_head'] != null ? '\n${e['budget_head']}' : ''}${e['workflow_instance_id'] != null ? ' · in workflow' : ''}'),
                    isThreeLine: e['budget_head'] != null,
                    trailing: e['workflow_instance_id'] != null
                        ? null
                        : Row(mainAxisSize: MainAxisSize.min, children: [
                            IconButton(
                              icon: const Icon(Icons.check, color: Colors.green),
                              onPressed: () async {
                                try {
                                  await repo.decide('${e['id']}', 'approve');
                                  setState(() => _f = _load());
                                } catch (err) {
                                  if (context.mounted) _snack(context, _error(err));
                                }
                              },
                            ),
                            IconButton(
                              icon: const Icon(Icons.close, color: Colors.red),
                              onPressed: () async {
                                try {
                                  await repo.decide('${e['id']}', 'reject');
                                  setState(() => _f = _load());
                                } catch (err) {
                                  if (context.mounted) _snack(context, _error(err));
                                }
                              },
                            ),
                          ]),
                  ),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- HOD ----------------------------------------------------------------------------------------------------------------------
class DepartmentBudgetScreen extends ConsumerStatefulWidget {
  const DepartmentBudgetScreen({super.key});

  @override
  ConsumerState<DepartmentBudgetScreen> createState() => _DepartmentBudgetScreenState();
}

class _DepartmentBudgetScreenState extends ConsumerState<DepartmentBudgetScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(accountingRepositoryProvider).myBudgets();

  Future<void> _record(List<Map<String, dynamic>> heads) async {
    final repo = ref.read(accountingRepositoryProvider);
    final approved = heads.where((h) => h['status'] == 'approved').toList();
    final v = await _expenseDialog(context, budgetHeads: approved);
    if (v == null) return;
    try {
      final head = approved.firstWhere((h) => '${h['id']}' == v['budget_head_id'], orElse: () => <String, dynamic>{});
      String? accountId = head['ledger_account_id'] as String?;
      accountId ??= (await repo.accounts()).firstWhere((a) => a['code'] == '5300', orElse: () => <String, dynamic>{})['id'] as String?;
      final doc = v['photo'] != null ? await repo.upload(v['photo'] as XFile) : null;
      await repo.recordExpense({
        'ledger_account_id': accountId,
        'budget_head_id': v['budget_head_id'],
        'amount_paise': v['amount_paise'],
        'spent_on': _today(),
        'payee': (v['payee'] as String).isEmpty ? 'Department expense' : v['payee'],
        'description': (v['description'] as String).isEmpty ? 'Department expense' : v['description'],
        'document_url': doc,
      });
      if (mounted) _snack(context, 'Submitted for approval');
      setState(() => _f = repo.myBudgets());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Department budget')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final heads = snap.data!;
          return Scaffold(
            floatingActionButton: FloatingActionButton.extended(onPressed: () => _record(heads), icon: const Icon(Icons.add), label: const Text('Expense')),
            body: ListView(children: [
              for (final h in heads)
                ListTile(
                  title: Text('${h['name']}'),
                  subtitle: LinearProgressIndicator(value: (((h['pct'] ?? 0) as num) / 100).clamp(0, 1).toDouble()),
                  trailing: Text('${_rupees(h['available_paise'])} left\n${h['pct']}%', textAlign: TextAlign.end),
                ),
            ]),
          );
        },
      ),
    );
  }
}

// ---- PI -------------------------------------------------------------------------------------------------------------------------
class MyGrantsScreen extends ConsumerStatefulWidget {
  const MyGrantsScreen({super.key});

  @override
  ConsumerState<MyGrantsScreen> createState() => _MyGrantsScreenState();
}

class _MyGrantsScreenState extends ConsumerState<MyGrantsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(accountingRepositoryProvider).grants();

  Future<void> _expense(Map<String, dynamic> g) async {
    final repo = ref.read(accountingRepositoryProvider);
    final heads = [for (final h in ((g['budget_heads'] as List?) ?? const []).cast<Map<String, dynamic>>()) '${h['name']}'];
    final v = await _expenseDialog(context, heads: heads);
    if (v == null) return;
    try {
      final doc = v['photo'] != null ? await repo.upload(v['photo'] as XFile) : null;
      await repo.grantExpense('${g['id']}', {
        'head': v['head'],
        'amount_paise': v['amount_paise'],
        'spent_on': _today(),
        'description': (v['description'] as String).isEmpty ? '${v['head']}' : v['description'],
        'document_url': doc,
      });
      if (mounted) _snack(context, 'Recorded');
      setState(() => _f = repo.grants());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My grants')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          if (snap.data!.isEmpty) return const ListTile(title: Text('No grant ledgers name you as PI.'));
          return ListView(children: [
            for (final g in snap.data!)
              Card(
                child: ExpansionTile(
                  title: Text('${g['name']}'),
                  subtitle: Text('${g['funding_agency'] ?? ''} · balance ${_rupees(g['balance_paise'])}'),
                  children: [
                    for (final h in ((g['budget_heads'] as List?) ?? const []).cast<Map<String, dynamic>>())
                      ListTile(dense: true, title: Text('${h['name']}'), trailing: Text('${_rupees(h['available_paise'])} of ${_rupees(h['allocated_paise'])}')),
                    if (g['status'] == 'active') TextButton.icon(onPressed: () => _expense(g), icon: const Icon(Icons.add), label: const Text('Add expense')),
                  ],
                ),
              ),
          ]);
        },
      ),
    );
  }
}

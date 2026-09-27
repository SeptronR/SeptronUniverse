import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/session.dart';
import '../providers.dart';

/// Institution / college picker and the current-term chip (Prompts/03 §03.10 `core/session`).
/// Multi-scope users pick a college (persisted in secure storage by [SessionNotifier.setTenant]); the chip shows
/// the current term from `GET /academic-terms/current?college_id=` (the college's, else the institution-wide one).

class CollegeOption {
  const CollegeOption({required this.id, required this.code, required this.name});

  factory CollegeOption.fromJson(Map<String, dynamic> j) =>
      CollegeOption(id: j['id'] as String, code: j['code'] as String, name: j['name'] as String);

  final String id;
  final String code;
  final String name;
}

class CurrentTerm {
  const CurrentTerm({required this.id, required this.name, required this.status, this.yearName});

  factory CurrentTerm.fromJson(Map<String, dynamic> j) => CurrentTerm(
        id: j['id'] as String,
        name: j['name'] as String,
        status: j['status'] as String,
        yearName: j['academic_year_name'] as String?,
      );

  final String id;
  final String name;
  final String status;
  final String? yearName;
}

class AcademicSessionRepository {
  AcademicSessionRepository(this._dio);

  final Dio _dio;

  Future<List<CollegeOption>> colleges() async {
    final res = await _dio.get<Map<String, dynamic>>('/colleges', queryParameters: {'scope': 'all', 'page_size': 200});
    final data = (res.data?['data'] as List?) ?? const [];
    return data.map((e) => CollegeOption.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<CurrentTerm?> currentTerm(String? collegeId) async {
    final res = await _dio.get<Map<String, dynamic>>('/academic-terms/current',
        queryParameters: {if (collegeId != null) 'college_id': collegeId});
    final data = res.data?['data'];
    return data is Map<String, dynamic> ? CurrentTerm.fromJson(data) : null;
  }
}

final academicSessionRepositoryProvider =
    Provider<AcademicSessionRepository>((ref) => AcademicSessionRepository(ref.watch(dioProvider)));

final collegeOptionsProvider = FutureProvider<List<CollegeOption>>(
    (ref) => ref.watch(academicSessionRepositoryProvider).colleges());

final currentTermProvider = FutureProvider<CurrentTerm?>((ref) {
  final collegeId = ref.watch(sessionProvider.select((s) => s.collegeId));
  return ref.watch(academicSessionRepositoryProvider).currentTerm(collegeId);
});

/// App-bar chip: current term (tap → college picker when the user can choose among several colleges).
class CurrentTermChip extends ConsumerWidget {
  const CurrentTermChip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final term = ref.watch(currentTermProvider);
    final label = term.when(
      data: (t) => t == null ? 'No current term' : '${t.yearName ?? ''} · ${t.name}',
      loading: () => '…',
      error: (_, __) => 'Term unavailable',
    );
    return ActionChip(
      avatar: const Icon(Icons.event_note_outlined, size: 18),
      label: Text(label, overflow: TextOverflow.ellipsis),
      onPressed: () => showCollegePicker(context, ref),
    );
  }
}

Future<void> showCollegePicker(BuildContext context, WidgetRef ref) async {
  final colleges = await ref.read(collegeOptionsProvider.future).catchError((_) => <CollegeOption>[]);
  if (!context.mounted || colleges.length < 2) return;
  final current = ref.read(sessionProvider).collegeId;
  final picked = await showModalBottomSheet<CollegeOption>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: ListView(
        shrinkWrap: true,
        children: [
          const ListTile(title: Text('Choose a college')),
          for (final c in colleges)
            ListTile(
              leading: Icon(c.id == current ? Icons.radio_button_checked : Icons.radio_button_off),
              title: Text(c.name),
              subtitle: Text(c.code),
              onTap: () => Navigator.of(ctx).pop(c),
            ),
        ],
      ),
    ),
  );
  if (picked != null) {
    await ref.read(sessionProvider.notifier).setTenant(collegeId: picked.id);
    ref.invalidate(currentTermProvider);
  }
}

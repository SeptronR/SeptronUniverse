import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Read-only academic structure (Prompts/05 §05.10): course browser + course detail with syllabus (staff — faculty see
/// the institution-wide catalogue of active courses), and the curriculum of a programme-regulation by term (students
/// open their own from Phase 07 via `?pr=<id>`). No editing on mobile.
double _num(Object? v) =>
    v == null ? 0 : (v is num ? v.toDouble() : double.tryParse('$v') ?? 0);
String _fmt(double v) =>
    v == v.roundToDouble() ? v.toInt().toString() : v.toString();

class CourseSummary {
  CourseSummary.fromJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        code = j['code'] as String,
        title = j['title'] as String,
        courseType = (j['course_type'] as String? ?? '').replaceAll('_', ' '),
        ltpc = j['ltpc'] as String? ?? '',
        regulation = j['regulation_code'] as String? ?? '',
        department = j['department_code'] as String? ?? '';

  final String id;
  final String code;
  final String title;
  final String courseType;
  final String ltpc;
  final String regulation;
  final String department;
}

class SyllabusUnit {
  SyllabusUnit.fromJson(Map<String, dynamic> j)
      : unit = (j['unit'] as num?)?.toInt() ?? 0,
        title = j['title'] as String? ?? '',
        topics = ((j['topics'] as List?) ?? const []).map((e) => '$e').toList(),
        hours = (j['hours'] as num?)?.toInt();

  final int unit;
  final String title;
  final List<String> topics;
  final int? hours;
}

class CourseDetail {
  CourseDetail.fromJson(Map<String, dynamic> j)
      : summary = CourseSummary.fromJson(j),
        credits = _num(j['credits']),
        contactHours = (j['contact_hours_per_week'] as num?)?.toInt(),
        scheme = j['scheme_code'] as String?,
        syllabus = ((j['syllabus'] as List?) ?? const [])
            .map((e) => SyllabusUnit.fromJson(e as Map<String, dynamic>))
            .toList(),
        textbooks =
            ((j['textbooks'] as List?) ?? const []).map((e) => '$e').toList(),
        prerequisites = ((j['prerequisites'] as List?) ?? const [])
            .map((e) => e as Map<String, dynamic>)
            .map((p) =>
                '${p['relation']}: ${p['related_code'] ?? ''} ${p['related_title'] ?? ''}'
                    .trim())
            .toList();

  final CourseSummary summary;
  final double credits;
  final int? contactHours;
  final String? scheme;
  final List<SyllabusUnit> syllabus;
  final List<String> textbooks;
  final List<String> prerequisites;
}

class TermCourse {
  TermCourse(
      this.term, this.courseId, this.code, this.title, this.ltpc, this.basket);

  final int term;
  final String courseId;
  final String code;
  final String title;
  final String ltpc;
  final String? basket;
}

class Curriculum {
  Curriculum.fromJson(Map<String, dynamic> j)
      : pattern = j['term_pattern'] as String? ?? 'semester',
        totalTerms = (j['total_terms'] as num?)?.toInt() ?? 0,
        required = _num(j['total_credits_required']),
        courses = ((j['courses'] as List?) ?? const []).map((e) {
          final c = e as Map<String, dynamic>;
          return TermCourse(
              (c['term_number'] as num).toInt(),
              c['course_id'] as String,
              c['course_code'] as String? ?? '',
              c['course_title'] as String? ?? '',
              c['ltpc'] as String? ?? '',
              c['basket_code'] as String?);
        }).toList();

  final String pattern;
  final int totalTerms;
  final double required;
  final List<TermCourse> courses;
}

class AcademicStructureRepository {
  AcademicStructureRepository(this._dio);

  final Dio _dio;

  Future<List<CourseSummary>> courses({String? q}) async {
    final res =
        await _dio.get<Map<String, dynamic>>('/courses', queryParameters: {
      'status': 'active',
      'page_size': 100,
      if (q != null && q.isNotEmpty) 'q': q,
    });
    return ((res.data?['data'] as List?) ?? const [])
        .map((e) => CourseSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<CourseDetail> course(String id) async {
    final res = await _dio.get<Map<String, dynamic>>('/courses/$id');
    return CourseDetail.fromJson(res.data?['data'] as Map<String, dynamic>);
  }

  Future<Curriculum> curriculum(String programRegulationId) async {
    final res = await _dio.get<Map<String, dynamic>>(
        '/program-regulations/$programRegulationId/structure');
    return Curriculum.fromJson(res.data?['data'] as Map<String, dynamic>);
  }
}

final academicStructureRepositoryProvider =
    Provider<AcademicStructureRepository>(
        (ref) => AcademicStructureRepository(ref.watch(dioProvider)));
final courseDetailProvider = FutureProvider.autoDispose
    .family<CourseDetail, String>(
        (ref, id) => ref.watch(academicStructureRepositoryProvider).course(id));
final curriculumProvider = FutureProvider.autoDispose
    .family<Curriculum, String>((ref, id) =>
        ref.watch(academicStructureRepositoryProvider).curriculum(id));

/// Course browser (active courses; search by code or title — typo-tolerant on the API).
class CoursesScreen extends ConsumerStatefulWidget {
  const CoursesScreen({super.key, this.openId});

  final String? openId;

  @override
  ConsumerState<CoursesScreen> createState() => _CoursesState();
}

class _CoursesState extends ConsumerState<CoursesScreen> {
  final _search = TextEditingController();
  List<CourseSummary>? _rows;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final rows = await ref
          .read(academicStructureRepositoryProvider)
          .courses(q: _search.text.trim());
      if (mounted) {
        setState(() {
          _rows = rows;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.openId != null) return CourseDetailScreen(id: widget.openId!);
    final rows = _rows;
    return Scaffold(
      appBar: AppBar(title: const Text('Courses')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _search,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _load(),
              decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search code or title',
                  border: OutlineInputBorder()),
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _load,
              child: _error != null
                  ? ListView(children: [ListTile(title: Text('$_error'))])
                  : rows == null
                      ? const Center(child: CircularProgressIndicator())
                      : ListView(
                          children: [
                            if (rows.isEmpty)
                              const ListTile(title: Text('No courses.')),
                            for (final c in rows)
                              ListTile(
                                leading: const Icon(Icons.menu_book_outlined),
                                title: Text('${c.code} · ${c.title}'),
                                subtitle: Text(
                                    '${c.courseType} · L-T-P-C ${c.ltpc} · ${c.regulation} · ${c.department}'),
                                onTap: () => Navigator.of(context).push(
                                    MaterialPageRoute<void>(
                                        builder: (_) =>
                                            CourseDetailScreen(id: c.id))),
                              ),
                          ],
                        ),
            ),
          ),
        ],
      ),
    );
  }
}

class CourseDetailScreen extends ConsumerWidget {
  const CourseDetailScreen({super.key, required this.id});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(courseDetailProvider(id));
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(detail.valueOrNull?.summary.code ?? 'Course')),
      body: detail.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [ListTile(title: Text('$e'))]),
        data: (c) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(c.summary.title, style: text.titleLarge),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 4, children: [
              Chip(label: Text(c.summary.courseType)),
              Chip(label: Text('L-T-P-C ${c.summary.ltpc}')),
              Chip(label: Text('${_fmt(c.credits)} credits')),
              if (c.contactHours != null)
                Chip(label: Text('${c.contactHours} h/week')),
              if (c.scheme != null) Chip(label: Text(c.scheme!)),
              Chip(label: Text(c.summary.regulation)),
            ]),
            if (c.prerequisites.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text('Prerequisites', style: text.titleMedium),
              for (final p in c.prerequisites)
                ListTile(
                    dense: true,
                    leading: const Icon(Icons.link),
                    title: Text(p)),
            ],
            const SizedBox(height: 16),
            Text('Syllabus', style: text.titleMedium),
            if (c.syllabus.isEmpty)
              const ListTile(title: Text('Syllabus not published.')),
            for (final u in c.syllabus)
              ExpansionTile(
                title: Text('Unit ${u.unit}: ${u.title}'),
                subtitle: u.hours != null ? Text('${u.hours} hours') : null,
                children: [
                  for (final t in u.topics)
                    ListTile(dense: true, title: Text(t))
                ],
              ),
            if (c.textbooks.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text('Textbooks', style: text.titleMedium),
              for (final t in c.textbooks)
                ListTile(
                    dense: true,
                    leading: const Icon(Icons.book_outlined),
                    title: Text(t)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Curriculum of a programme-regulation by term (`/app/academics/curriculum?pr=<id>`).
class CurriculumScreen extends ConsumerWidget {
  const CurriculumScreen({super.key, this.programRegulationId});

  final String? programRegulationId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = programRegulationId;
    if (id == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('My curriculum')),
        body: const Center(
            child: Text(
                'Your curriculum appears here once you are enrolled in a programme.')),
      );
    }
    final curriculum = ref.watch(curriculumProvider(id));
    return Scaffold(
      appBar: AppBar(title: const Text('Curriculum')),
      body: curriculum.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [ListTile(title: Text('$e'))]),
        data: (c) {
          final word = c.pattern == 'year'
              ? 'Year'
              : (c.pattern == 'trimester' ? 'Trimester' : 'Semester');
          return ListView(
            children: [
              ListTile(
                  title: Text(
                      '${c.totalTerms} terms · ${_fmt(c.required)} credits required')),
              for (var t = 1; t <= c.totalTerms; t++)
                ExpansionTile(
                  initiallyExpanded: t == 1,
                  title: Text('$word $t'),
                  children: [
                    for (final course in c.courses.where((x) => x.term == t))
                      ListTile(
                        dense: true,
                        title: Text('${course.code} · ${course.title}'),
                        subtitle: Text(
                            'L-T-P-C ${course.ltpc}${course.basket != null ? ' · ${course.basket}' : ''}'),
                        onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                                builder: (_) =>
                                    CourseDetailScreen(id: course.courseId))),
                      ),
                  ],
                ),
            ],
          );
        },
      ),
    );
  }
}

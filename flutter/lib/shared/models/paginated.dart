import '../../core/auth/auth_state.dart';

/// Server pagination meta from the envelope.
class PaginationMeta {
  const PaginationMeta(
      {required this.page,
      required this.pageSize,
      required this.total,
      required this.totalPages});

  factory PaginationMeta.fromJson(Map<String, dynamic> json) => PaginationMeta(
        page: json['page'] as int? ?? 1,
        pageSize: json['page_size'] as int? ?? 25,
        total: json['total'] as int? ?? 0,
        totalPages: json['total_pages'] as int? ?? 1,
      );

  final int page;
  final int pageSize;
  final int total;
  final int totalPages;

  bool get hasNext => page < totalPages;
}

/// A list response with `meta.visibility` so screens can render `SegmentedScope`.
class Paginated<T> {
  const Paginated(
      {required this.items,
      required this.pagination,
      required this.visibility,
      this.message});

  factory Paginated.fromEnvelope(Map<String, dynamic> envelope,
      T Function(Map<String, dynamic>) fromJson) {
    final meta = envelope['meta'] as Map<String, dynamic>? ?? const {};
    final data = envelope['data'] as List<dynamic>? ?? const [];
    return Paginated(
      items: data.cast<Map<String, dynamic>>().map(fromJson).toList(),
      pagination: PaginationMeta.fromJson(
          meta['pagination'] as Map<String, dynamic>? ?? const {}),
      visibility: VisibilityMeta.fromJson(
          meta['visibility'] as Map<String, dynamic>? ?? const {}),
      message: envelope['message'] as String?,
    );
  }

  final List<T> items;
  final PaginationMeta pagination;
  final VisibilityMeta visibility;
  final String? message;
}

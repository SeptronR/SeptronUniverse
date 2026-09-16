import '../../core/config/env.dart';

/// Resolve `/uploads/...` signed paths returned by the API against the API origin.
String mediaUrl(String? pathOrUrl) {
  if (pathOrUrl == null || pathOrUrl.isEmpty) return '';
  if (pathOrUrl.startsWith('http')) return pathOrUrl;
  final origin =
      Uri.parse(Env.apiUrl).replace(path: '', query: null).toString();
  return '$origin$pathOrUrl';
}

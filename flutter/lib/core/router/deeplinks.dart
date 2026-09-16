import 'routes.dart';

/// Push payload `{route, params}` and universal links (`/verify/:token`, `/apply/:cycle`) → in-app navigation.
class DeepLink {
  const DeepLink(this.location);

  final String location;

  /// From an FCM data payload.
  static DeepLink? fromPushData(Map<String, dynamic> data) {
    final route = data['route'] as String?;
    if (route == null || route.isEmpty) return null;
    final params = data['params'];
    var location = route;
    if (params is Map<String, dynamic> && params.isNotEmpty) {
      location = Uri(
          path: route,
          queryParameters: params.map((k, v) => MapEntry(k, '$v'))).toString();
    }
    return DeepLink(location);
  }

  /// From a universal link URI (https://<host>/verify/<token>, https://<host>/apply/<cycle>).
  static DeepLink? fromUri(Uri uri) {
    final segments = uri.pathSegments;
    if (segments.isEmpty) return null;
    switch (segments.first) {
      case 'verify':
        if (segments.length >= 2) {
          return DeepLink(AppRoutes.verify.replaceFirst(':token', segments[1]));
        }
      case 'apply':
        if (segments.length >= 2) {
          return DeepLink(AppRoutes.apply.replaceFirst(':cycle', segments[1]));
        }
    }
    if (uri.path.startsWith('/app/')) return DeepLink(uri.toString());
    return null;
  }
}

/// Cold-start links are parked here until authentication completes, then dispatched by the router.
class PendingDeepLink {
  PendingDeepLink._();

  static DeepLink? pending;
}

import 'dart:async';

/// Force-logout bus: the dio client publishes here when a refresh fails; the router listens and redirects to /login.
class AuthEvents {
  AuthEvents._();

  static final AuthEvents instance = AuthEvents._();

  final _controller = StreamController<String>.broadcast();

  Stream<String> get forceLogoutStream => _controller.stream;

  void forceLogout(String reason) => _controller.add(reason);
}

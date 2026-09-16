// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appName => 'SeptronUniverse';

  @override
  String get login => 'Sign in';

  @override
  String get identifier => 'Username, email or phone';

  @override
  String get password => 'Password';

  @override
  String get home => 'Home';

  @override
  String get more => 'More';

  @override
  String get approvals => 'Approvals';

  @override
  String get notifications => 'Notifications';

  @override
  String get profile => 'Profile';

  @override
  String get scopeMine => 'Mine';

  @override
  String get scopeDepartment => 'Department';

  @override
  String get scopeCollege => 'College';

  @override
  String get scopeAll => 'All';

  @override
  String get readOnlyBanner =>
      'The platform is in read-only mode. Changes are queued.';

  @override
  String get offlineBanner => 'You are offline. Showing cached data.';

  @override
  String get featureDisabled =>
      'This feature is not enabled for your institution.';

  @override
  String get accessDenied => 'You do not have permission to view this screen.';

  @override
  String get notFound => 'Screen not found';

  @override
  String get retry => 'Retry';
}

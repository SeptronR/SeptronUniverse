/// Form validators (IN pack formats; the backend re-validates through the regulatory pack).
class Validators {
  Validators._();

  static String? required(String? v, {String message = 'Required'}) =>
      (v == null || v.trim().isEmpty) ? message : null;

  static String? phoneIN(String? v) =>
      v != null && RegExp(r'^[6-9]\d{9}$').hasMatch(v)
          ? null
          : 'Enter a valid 10-digit mobile number';

  static String? email(String? v) =>
      v != null && RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(v)
          ? null
          : 'Enter a valid email';

  static String? aadhaar(String? v) =>
      v != null && RegExp(r'^[2-9]\d{11}$').hasMatch(v)
          ? null
          : 'Enter a valid Aadhaar';

  static String? pan(String? v) =>
      v != null && RegExp(r'^[A-Z]{5}\d{4}[A-Z]$').hasMatch(v)
          ? null
          : 'Enter a valid PAN';
}

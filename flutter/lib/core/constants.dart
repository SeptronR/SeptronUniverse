import 'package:flutter/material.dart';

const String kAppName = 'SeptronUniverse';

/// Role slugs (docs/Roles_and_Permissions.md §1) used by role_shells.dart.
class Roles {
  Roles._();

  static const superAdmin = 'super_admin';
  static const supportAgent = 'support_agent';
  static const institutionAdmin = 'institution_admin';
  static const registrar = 'registrar';
  static const controllerOfExaminations = 'controller_of_examinations';
  static const examCell = 'exam_cell';
  static const dean = 'dean';
  static const hod = 'hod';
  static const classAdvisor = 'class_advisor';
  static const faculty = 'faculty';
  static const guestFaculty = 'guest_faculty';
  static const externalExaminer = 'external_examiner';
  static const researchScholar = 'research_scholar';
  static const iqacCoordinator = 'iqac_coordinator';
  static const admissionsOfficer = 'admissions_officer';
  static const accountant = 'accountant';
  static const hrOfficer = 'hr_officer';
  static const placementOfficer = 'placement_officer';
  static const hostelWarden = 'hostel_warden';
  static const hostelGateStaff = 'hostel_gate_staff';
  static const librarian = 'librarian';
  static const driver = 'driver';
  static const recruiter = 'recruiter';
  static const student = 'student';
  static const parent = 'parent';
  static const alumni = 'alumni';
  static const applicant = 'applicant';

  static const portalOnly = {
    student,
    parent,
    alumni,
    applicant,
    driver,
    recruiter,
    researchScholar,
    externalExaminer,
    hostelWarden,
    hostelGateStaff,
  };
}

/// Status strings are VARCHAR(30) + Python enums; colours are fixed (never institution-themed).
class StatusColors {
  StatusColors._();

  static const present = Color(0xFF16A34A);
  static const absent = Color(0xFFDC2626);
  static const late = Color(0xFFD97706);
  static const leave = Color(0xFF7C3AED);
  static const paid = Color(0xFF16A34A);
  static const unpaid = Color(0xFFDC2626);
  static const partial = Color(0xFFD97706);
  static const pending = Color(0xFFD97706);
  static const approved = Color(0xFF16A34A);
  static const rejected = Color(0xFFDC2626);
}

/// Module accent colours for the More grid.
class ModuleColors {
  ModuleColors._();

  static const academics = Color(0xFF4F46E5);
  static const examinations = Color(0xFF0891B2);
  static const fees = Color(0xFF16A34A);
  static const campus = Color(0xFFEA580C);
  static const engagement = Color(0xFFC026D3);
  static const admin = Color(0xFF64748B);
}

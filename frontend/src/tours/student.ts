import type { TourDefinition } from './types';

export const studentTours: TourDefinition[] = [
  {
    "key": "student.first_login",
    "route": "/student",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Welcome to your portal",
    "steps": [
      {
        "target": "[data-tour=\"portal-tabs\"]",
        "title": "Navigation",
        "body": "Your main sections live here — on a phone they sit at the bottom.",
        "placement": "bottom"
      },
      {
        "target": "[data-tour=\"portal-bell\"]",
        "title": "Notifications",
        "body": "Unread alerts by category; tap one to open the right page.",
        "placement": "bottom"
      },
      {
        "target": "[data-tour=\"portal-help\"]",
        "title": "Help",
        "body": "Help for the page you are on, plus a feedback form.",
        "placement": "bottom"
      },
      {
        "target": "[data-tour=\"portal-more\"]",
        "title": "More",
        "body": "Hostel, library, placement, certificates and settings.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.registration",
    "route": "/student/registration",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Course registration",
    "steps": [
      {
        "target": "[data-tour=\"page-title\"]",
        "title": "Registration",
        "body": "Pick your courses for the term here.",
        "placement": "bottom"
      },
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Your cart",
        "body": "Add or drop courses, then submit before the window closes.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.pay_fees",
    "route": "/student/fees",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Paying fees",
    "steps": [
      {
        "target": "[data-tour=\"page-title\"]",
        "title": "Fees",
        "body": "Open invoices and receipts.",
        "placement": "bottom"
      },
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Pay online",
        "body": "Choose an invoice and pay through the gateway; the receipt appears instantly.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.hall_ticket",
    "route": "/student/exams",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Hall ticket",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Exams",
        "body": "Register, pay the exam fee and download the hall ticket here.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.results",
    "route": "/student/results",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Results",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Results",
        "body": "Published results and grade cards; apply for revaluation within the window.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.outpass",
    "route": "/student/hostel",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Hostel out-pass",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Out-pass",
        "body": "Request leave; your guardian and warden approve it and you get a gate QR.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.attendance",
    "route": "/student/attendance",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Attendance",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Attendance",
        "body": "Course-wise attendance with shortfall warnings and on-duty requests.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.requests",
    "route": "/student/requests",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "My requests",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "All requests",
        "body": "Every certificate, grievance, out-pass and other request in one place.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.documents",
    "route": "/student/documents",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "My documents",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Documents",
        "body": "Download issued documents and share the verification QR.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "student.notifications",
    "route": "/student/notifications",
    "roles": [
      "student",
      "learner"
    ],
    "version": 1,
    "title": "Notification centre",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Inbox",
        "body": "Filter by category, mark read or snooze a category.",
        "placement": "bottom"
      }
    ]
  }
];

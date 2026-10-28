import type { TourDefinition } from './types';

export const facultyTours: TourDefinition[] = [
  {
    "key": "faculty.first_login",
    "route": "/faculty",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Welcome",
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
        "target": "[data-tour=\"portal-admin-switch\"]",
        "title": "Admin view",
        "body": "If you also hold an admin role, switch to the admin shell here.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "faculty.attendance",
    "route": "/faculty/attendance",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Marking attendance",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Sessions",
        "body": "Pick today's session and mark present / absent; QR mode is available.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "faculty.marks",
    "route": "/faculty/marks/:offeringId",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Entering marks",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Marks",
        "body": "Enter component marks; save drafts, then submit for approval.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "faculty.lms",
    "route": "/faculty/offerings/:id/lms",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Course LMS",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "LMS",
        "body": "Post materials, assignments and quizzes for the offering.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "faculty.approvals",
    "route": "/faculty/approvals",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Approvals",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Approvals",
        "body": "Steps assigned to you, oldest SLA first.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "faculty.mentees",
    "route": "/faculty/mentees",
    "roles": [
      "faculty",
      "guest_faculty"
    ],
    "version": 1,
    "title": "Mentees",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Mentees",
        "body": "Risk flags, meetings and interventions for your mentees.",
        "placement": "bottom"
      }
    ]
  }
];

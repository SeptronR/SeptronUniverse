import type { TourDefinition } from './types';

export const otherTours: TourDefinition[] = [
  {
    "key": "warden.outpass",
    "route": "/warden",
    "roles": [
      "hostel_warden"
    ],
    "version": 1,
    "title": "Warden portal",
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
      }
    ]
  },
  {
    "key": "warden.gate",
    "route": "/warden/gate",
    "roles": [
      "hostel_gate_staff",
      "hostel_warden"
    ],
    "version": 1,
    "title": "Gate scan",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Scan",
        "body": "Scan the out-pass QR to record exit and return.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "evaluator.entry",
    "route": "/evaluator",
    "roles": [
      "external_examiner"
    ],
    "version": 1,
    "title": "Evaluation",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Bundles",
        "body": "Assigned bundles show dummy numbers only; enter marks per script.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "scholar.progress",
    "route": "/scholar/progress",
    "roles": [
      "research_scholar"
    ],
    "version": 1,
    "title": "Progress reports",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Progress",
        "body": "Submit the six-monthly report for your guide and DC.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "applicant.apply",
    "route": "/apply",
    "roles": [
      "applicant"
    ],
    "version": 1,
    "title": "Your application",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Status",
        "body": "Track your application, allotment and payments here.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "recruiter.drives",
    "route": "/recruiter",
    "roles": [
      "recruiter"
    ],
    "version": 1,
    "title": "Recruiter portal",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Drives",
        "body": "Your drives, consented applicants, rounds and offers.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "alumni.home",
    "route": "/alumni",
    "roles": [
      "alumni"
    ],
    "version": 1,
    "title": "Alumni portal",
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
      }
    ]
  },
  {
    "key": "driver.home",
    "route": "/driver",
    "roles": [
      "driver"
    ],
    "version": 1,
    "title": "Driver",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Trip",
        "body": "Start the trip to share live location with students.",
        "placement": "bottom"
      }
    ]
  }
];

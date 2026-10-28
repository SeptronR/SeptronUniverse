import type { TourDefinition } from './types';

export const parentTours: TourDefinition[] = [
  {
    "key": "parent.first_login",
    "route": "/parent",
    "roles": [
      "parent"
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
        "target": "[data-tour=\"portal-ward\"]",
        "title": "Ward switcher",
        "body": "Switch between your children here.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "parent.ward_switch",
    "route": "/parent",
    "roles": [
      "parent"
    ],
    "version": 1,
    "title": "Switching wards",
    "steps": [
      {
        "target": "[data-tour=\"portal-ward\"]",
        "title": "Ward",
        "body": "Every page shows the selected ward.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "parent.pay",
    "route": "/parent/fees",
    "roles": [
      "parent"
    ],
    "version": 1,
    "title": "Paying fees",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Fees",
        "body": "Pay your ward's open invoices online.",
        "placement": "bottom"
      }
    ]
  },
  {
    "key": "parent.attendance",
    "route": "/parent/attendance",
    "roles": [
      "parent"
    ],
    "version": 1,
    "title": "Attendance",
    "steps": [
      {
        "target": "[data-tour=\"page-main\"]",
        "title": "Attendance",
        "body": "Your ward's attendance and shortfalls.",
        "placement": "bottom"
      }
    ]
  }
];

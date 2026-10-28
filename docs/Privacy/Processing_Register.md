# Record of processing activities (DPDP Act 2023)

Maintained by the privacy officer of each institution (the *Data Fiduciary*); SeptronUniverse acts as *Data Processor*
for the institution. Purposes match `platform_settings['privacy.purposes']` (`app/core/privacy_registry.py`); field-level
categories match the PII inventory (`app/core/pii_inventory.json`, 114 fields).

| Purpose | Legal basis | Data principals | Categories | Recipients | Retention | Cross-border |
|---|---|---|---|---|---|---|
| academic | contract / legitimate use (education) | students, applicants, alumni | identity, contact, academic, financial (fees), minor (DOB, guardians) | institution staff by role; affiliating university; regulators (AISHE, NIRF, NAD/ABC) | statutory: academic records ≥ 10 years after exit | none (India-hosted) |
| communication_transactional | contract | all users | contact | SMS / e-mail / WhatsApp providers (Phase 41 connections) | 12 months of message logs | provider-dependent — see connection region |
| communication_marketing | consent | students, alumni, parents | contact | campaign providers | until withdrawal | provider-dependent |
| photo_media | consent | students, staff | photographs, videos | website visitors, publications | until withdrawal / 5 years | none |
| health | consent | students, staff | health, counselling notes (encrypted) | medical officer, counsellor only | 5 years | none |
| third_party_placement | consent | students | profile, resume, academic summary | recruiters (consented fields only) | placement season + 1 year | recruiter-dependent |
| analytics_external | consent | website / app visitors | usage data (no identifiers) | analytics provider (Plausible / GA4) | provider default | provider-dependent |
| biometric | consent | students, staff | face / fingerprint templates | attendance device vendors | until withdrawal or exit | none |
| location | consent | students (geo attendance), drivers | device location | institution transport / attendance staff | 90 days | none |
| guardian_access | consent (student) / guardian consent (minor) | students | attendance, results, fees | linked guardians | while enrolled | none |

**Data-principal rights** (access, correction, erasure, grievance, nomination) are exercised through
`/profile/privacy` (DSR workflow, due 30 days, one 30-day extension). **Minors**: optional consents are recorded by a
linked guardian; students turning 18 are asked to re-consent (`privacy.minor_recompute`). **Breaches**: see
`docs/Runbooks/incident_dpdp_breach.md`.

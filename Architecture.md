# SeptronUniverse — Architecture Diagrams

Same stack and layering as SeptronOrbit; diagrams below show what is specific to higher education and to the hardened platform (tenancy hierarchy, four-layer authorization, feature flags, outbox, workflow engine, registration and exam lifecycles, result versioning).

---

## 1. System overview (infrastructure)

```mermaid
graph TB
    subgraph CLIENT["Clients"]
        WEB["Web app / PWA\n(React + TS)"]
        MOB["Mobile app\n(Flutter, offline-first)"]
        PUB["Public pages\n(apply, verify, catalogue, site)"]
        INT["Integrations\n(API keys, webhooks, LTI)"]
    end

    subgraph EDGE["Edge"]
        TR["Traefik / Nginx\nTLS · rate limits · security headers"]
    end

    subgraph APP["Application (Docker Compose)"]
        API["FastAPI (uvicorn/gunicorn)\nHTTP + WebSocket"]
        W1["Celery workers\nqueues: notifications · emails · documents · reports · integrations · scheduled"]
        BEAT["Celery Beat\n(outbox relay, reminders, eligibility, metrics, SLA, backups)"]
        FL["Flower"]
    end

    subgraph DATA["Data"]
        PG[("PostgreSQL 15\nRLS · partitions · materialized read models")]
        RD[("Redis 7\nbroker · cache · pub/sub · rate limits · idempotency · sessions")]
        S3[("Object storage\nS3 / MinIO · per-tenant prefixes · versioning")]
    end

    subgraph EXT["External adapters (mock + live)"]
        PAY["Payments / UPI"]
        MSG["SMS · WhatsApp · Email · Push"]
        GOV["DigiLocker/NAD · ABC · NSP · SWAYAM"]
        ACAD["LTI/Moodle · Zoom · Plagiarism · Scopus/ORCID · Koha/Shodhganga"]
        DEV["Biometric/RFID · Face verify · eSign · Tally"]
        IDP["SSO (OIDC/SAML)"]
    end

    WEB & MOB & PUB & INT --> TR --> API
    API <--> PG
    API <--> RD
    API <--> S3
    API -->|enqueue| RD
    W1 <-->|dequeue| RD
    W1 <--> PG
    W1 <--> S3
    BEAT --> RD
    FL --> W1
    W1 --> PAY & MSG & GOV & ACAD & DEV
    API --> IDP
    API -->|pub/sub fan-out| RD -->|WebSocket| WEB & MOB
```

---

## 2. Backend request pipeline

```mermaid
graph LR
    REQ["Request"] --> MW1["GZip"] --> MW2["CORS"] --> MW3["RequestLogger\n(request_id, tenant, user)"] --> MW4["InstitutionContext\nX-Institution-* / X-College-Id\nSET LOCAL app.institution_id"]
    MW4 --> RO["ReadOnlyMode gate"] --> AUTH["JWT + session check\n(get_current_user)"]
    AUTH --> F["feature_required(key)"] --> P["permission_required(module, action)"] --> SC["Scope\n(user_roles.scope_type/scope_id)"]
    SC --> ROUTE["Route\n(validate → service → ok())"]
    ROUTE --> SVC["Service\nrules · log_audit · events.emit"]
    SVC --> REPO["BaseRepository\ninstitution + scope + soft-delete + visible_to(user)"]
    REPO --> PG[("PostgreSQL (RLS)")]
    SVC --> OUT["domain_events (outbox)\nsame transaction"]
    OUT --> RELAY["Relay (Beat / LISTEN-NOTIFY)"] --> CEL["Celery consumers"]
    ROUTE --> ENV["Envelope\n{success, data, message, meta:{visibility, pagination}}"]
```

---

## 3. Tenancy hierarchy & scopes

```mermaid
graph TB
    SA["super_admin (platform)"]
    subgraph T1["institution: State University (type=university, pack=IN)"]
        C1["college: Constituent College A"]
        C2["college: Affiliated College B"]
        C3["college: Campus C"]
        C1 --> F1["faculty: Engineering"] --> D1["dept: CSE"] & D2["dept: ECE"]
        C2 --> D3["dept: Commerce"]
        C3 --> D4["dept: Law"]
    end
    subgraph T2["institution: Autonomous College (type=autonomous_college)"]
        C4["college: main (auto-created)"] --> D5["dept: Physics"]
    end
    SA -->|"impersonate (audited)"| T1 & T2
    R1["registrar @institution"] --> T1
    R2["college_admin @college B"] --> C2
    R3["dean @faculty Engineering"] --> F1
    R4["hod @dept CSE"] --> D1
    R5["faculty @self + ownership\n(own offerings, mentees)"] --> D1
    R6["hostel_warden @hostel"] --> C1
```

---

## 4. Four-layer authorization & visibility

```mermaid
flowchart TD
    A["Request for GET /leaves"] --> B{"feature hr.leaves enabled\nfor institution?"}
    B -- no --> X1["403 FEATURE_DISABLED"]
    B -- yes --> C{"has leaves:view or leaves:view_all?"}
    C -- no --> X2["403 PERMISSION_DENIED"]
    C -- yes --> D["Resolve scopes from user_roles\n(institution / college / department / …)"]
    D --> E["VisibilityResolver.predicate =\nself ∪ ownership ∪ (scope if view_all)"]
    E --> F["BaseRepository.list(predicate)\n+ RLS backstop"]
    F --> G["mask_pii unless leaves:view_pii"]
    G --> H["Envelope with meta.visibility\n{self:true, scopes:[department, all]}"]
    H --> I["UI renders tabs\nMine | Department | College | All"]
```

Accountant example: `leaves:view_all` @institution → predicate = own leaves ∪ all leaves; UI shows **Mine** and **All**.

---

## 5. Feature-flag flow

```mermaid
sequenceDiagram
    participant Reg as features.py registry
    participant SA as Super admin UI
    participant DB as institution_feature_flags
    participant RD as Redis cache
    participant API as feature_required()
    participant ME as /auth/me
    participant UI as Web / Mobile

    Reg->>DB: seed platform_features (deploy)
    SA->>DB: set platform_enabled for institution (plan defaults / override)
    DB-->>RD: event feature_flag.changed → invalidate
    UI->>ME: login
    ME->>RD: effective keys (platform_enabled AND institution_enabled)
    ME-->>UI: {permissions[], features[], scopes}
    UI->>UI: hide nav/routes/tabs for disabled keys
    UI->>API: GET /hostel/…
    API->>RD: is_enabled(institution, "hostel.core")?
    API-->>UI: 403 FEATURE_DISABLED (if off)
```

---

## 6. Transactional outbox

```mermaid
sequenceDiagram
    participant SVC as Service
    participant PG as PostgreSQL
    participant RELAY as Outbox relay (Beat)
    participant RD as Redis broker
    participant C1 as Notifications consumer
    participant C2 as Webhooks consumer
    participant C3 as ABC / DigiLocker consumer

    SVC->>PG: BEGIN; UPDATE result rows; INSERT domain_events(result.published); COMMIT
    RELAY->>PG: SELECT pending events FOR UPDATE SKIP LOCKED
    RELAY->>RD: publish to consumers
    RD->>C1: result.published → templates → SMS/push (idempotent by event_id)
    RD->>C2: result.published → signed webhook (retry, dead-letter)
    RD->>C3: push abc_credit_ledger rows (retry)
    C1-->>PG: message_logs
    C3-->>PG: abc_credit_ledger.status = pushed/acknowledged
```

---

## 7. Approval-workflow engine

```mermaid
stateDiagram-v2
    [*] --> pending: instance created by module (e.g. leave.approval)
    pending --> step_1: resolve approver (role + scope / delegation)
    step_1 --> step_2: approved (sequential) / all approved (parallel)
    step_1 --> rejected: rejected
    step_1 --> escalated: SLA breached (Beat) → escalate_to
    escalated --> step_1: acted
    step_2 --> approved: last step approved
    step_2 --> rejected: rejected
    approved --> [*]: module hook on_approved()
    rejected --> [*]: module hook on_rejected()
    pending --> cancelled: requester withdraws
```

---

## 8. Course registration flow

```mermaid
sequenceDiagram
    actor S as Student
    participant UI as Registration page / app
    participant API as /registration
    participant SVC as RegistrationService
    participant PG as PostgreSQL
    participant WF as Workflow
    participant FEE as Fees

    S->>UI: open cart (window open?)
    UI->>API: GET /registration/me/catalog?term_id
    API->>SVC: curriculum + arrears + baskets − holds
    SVC-->>UI: eligible offerings, credit limits
    S->>UI: add offerings, elective priorities
    UI->>API: POST /registration/me/items (Idempotency-Key)
    API->>SVC: prerequisite / co-requisite / anti-requisite / seat check
    SVC->>PG: SELECT course_offerings FOR UPDATE; enrolled_count++ or waitlist
    S->>UI: submit
    UI->>API: POST /registration/me/submit
    SVC->>PG: hold check (registration|all), fee clearance
    SVC->>WF: start advisor approval (if window requires)
    SVC->>FEE: invoice (tuition + arrear credits + late fee) source_type=course_registration
    WF-->>SVC: approved → items confirmed
    SVC->>PG: emit registration.approved (outbox)
    Note over PG: auto-lock at add_drop_end; later drops = W
```

---

## 9. Examination lifecycle

```mermaid
sequenceDiagram
    participant COE as COE / exam cell
    participant API as Exams API
    participant JOB as Jobs (documents queue)
    participant EV as Evaluator (dummy numbers)
    participant DEC as Decoder
    participant RUN as Result run
    actor S as Student

    COE->>API: create session, papers, date-sheet (clash check) → open registration
    S->>API: exam-registration/me → submit + fee
    COE->>API: eligibility/apply (attendance, CIA, fees, holds snapshot)
    COE->>JOB: hall-tickets/generate (photo + signed QR)
    COE->>API: seating/generate, invigilation/auto-assign, QP assignments (encrypted, watermarked print)
    COE->>API: hall attendance + booklet numbers
    COE->>API: bundles → code (dummy numbers), custody log
    COE->>API: valuation/assign (round 1, round 2)
    EV->>API: valuations (question-wise) — identity hidden
    COE->>API: reconcile → discrepancy > 15 % → third valuation → moderation (approve)
    DEC->>API: decode (audited) → ese_marks
    COE->>RUN: results/compute (config_snapshot, checksum) → grades, SGPA/CGPA, class, standing, arrears
    COE->>API: verify → approve → publish (versioned, immutable) → outbox → notify, ABC push
    S->>API: results/me, grade card, reval request (fee) → new version if |Δ| ≥ 5
```

---

## 10. Result versioning & immutability

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> computed: results/compute
    computed --> verified: exam cell checklist
    verified --> approved: COE
    approved --> published: publish (hash, checksum, outbox)
    computed --> rolled_back: rollback (only before publish)
    verified --> rolled_back
    published --> superseded: new version created (reval / grace / correction / malpractice)
    note right of published
        DB trigger rejects UPDATE on published rows
        except is_current / status→superseded.
        Withheld is a result_status, not an unpublish.
    end note
```

---

## 11. Module dependency map

```mermaid
graph TD
    P00["00 Prerequisite"] --> P01["01 Infra & platform"] --> P02["02 Auth · RBAC · Features · Visibility"] --> P03["03 Institution · Terms · Settings"] --> P04["04 Comms core · Workflow"] --> P05["05 Programmes · Regulations · Curriculum"] --> P06["06 Staff · HR · Recruitment"]
    P06 --> P07["07 Students · Enrolment · Holds"] --> P08["08 Admissions"] --> P09["09 Offerings · Registration"] --> P10["10 Timetable"] --> P11["11 Attendance · Eligibility"] --> P12["12 Fees · Scholarships"] --> P13["13 Internal assessment · OBE defs · LMS"]
    P13 --> P14["14 Exam administration"] --> P15["15 Evaluation · Results"] --> P16["16 Post-result"] --> P17["17 OBE attainment"] --> P18["18 Degrees · Credentials"]
    P07 & P12 --> P19["19 Library"] & P20["20 Hostel"] & P21["21 Transport"] & P22["22 Inventory · Procurement"] & P23["23 Accounting"]
    P04 --> P24["24 Comms advanced"] & P25["25 Calendar · Events · Facilities"] & P26["26 Documents · Certificates"]
    P07 & P15 --> P27["27 Mentoring · Grievances · Surveys"] & P28["28 Placement"] & P29["29 Alumni"] & P30["30 Research"] --> P31["31 PhD"] --> P32["32 Accreditation"]
    P04 --> P33["33 Governance"]
    P15 --> P34["34 Affiliation"]
    P32 & P34 --> P35["35 Dashboards · Analytics"] & P36["36 Reports"] & P37["37 Audit · Settings"] & P38["38 Super admin · SaaS"] & P39["39 Portals · PWA"] & P40["40 Website · Catalogue"] --> P41["41 Integrations · Migration"] --> P42["42 Mobile"] --> P43["43 Testing · Security"] --> P44["44 Deployment · Ops"]
```

---

## 12. Academic core ERD (key tables)

```mermaid
erDiagram
    institutions ||--o{ colleges : has
    colleges ||--o{ departments : has
    colleges ||--o{ programs : offers
    programs ||--o{ program_regulations : governed_by
    regulations ||--o{ program_regulations : applies
    program_regulations ||--o{ program_structure_terms : terms
    program_regulations ||--o{ curriculum_courses : lists
    courses ||--o{ curriculum_courses : placed_in
    regulations ||--o{ courses : owns
    programs ||--o{ batches : cohorts
    batches ||--o{ batch_sections : sections
    students ||--o{ student_program_enrollments : enrolled
    batches ||--o{ student_program_enrollments : contains
    student_program_enrollments ||--o{ student_term_records : per_term
    student_program_enrollments ||--o{ student_holds : blocked_by
    academic_terms ||--o{ course_offerings : offered_in
    courses ||--o{ course_offerings : instances
    course_offerings ||--o{ course_offering_faculty : taught_by
    student_term_records ||--o{ course_registrations : registers
    course_registrations ||--o{ course_registration_items : items
    course_offerings ||--o{ course_registration_items : selected
    course_offerings ||--o{ class_sessions : sessions
    class_sessions ||--o{ student_class_attendance : marks
    course_offerings ||--o{ offering_assessments : cia
    offering_assessments ||--o{ assessment_questions : questions
    course_outcomes ||--o{ assessment_questions : tagged
    offering_assessments ||--o{ internal_marks : marks
    exam_sessions ||--o{ exam_papers : papers
    exam_sessions ||--o{ exam_registrations : registrations
    exam_registrations ||--o{ exam_registration_items : items
    exam_registration_items ||--|| answer_scripts : script
    answer_scripts ||--o{ script_valuations : valued
    answer_scripts ||--|| script_final_marks : final
    result_processing_runs ||--o{ student_course_results : produces
    student_program_enrollments ||--o{ student_course_results : results
    student_term_records ||--o{ student_term_results : sgpa_cgpa
    student_course_results ||--o| abc_credit_ledger : pushed
    student_program_enrollments ||--o{ degrees_awarded : awarded
```

---

## 13. Docker Compose topology

```mermaid
graph TB
    subgraph VOL["Volumes"]
        VP[("postgres_data")]
        VR[("redis_data")]
        VU[("uploads")]
    end
    subgraph COMPOSE["docker-compose.yml"]
        PG["postgres:15-alpine"]
        RD["redis:7-alpine"]
        BE["backend (FastAPI)\nowns alembic upgrade head"]
        CW["celery_worker\n-Q notifications,emails,documents,reports,integrations,scheduled"]
        CB["celery_beat"]
        FL["flower :5555"]
        FE["frontend (Vite dev / static build)"]
        NG["nginx :80/:443"]
    end
    PG --- VP
    RD --- VR
    BE --- VU
    BE --> PG & RD
    CW --> PG & RD
    CB --> RD
    FL --> RD
    NG --> BE & FE
    ENV[".env.dev / .env.demo / .env.prod"] -.-> BE & CW & CB
    PROD["Production: orbit-infra\ncompose/apps/universe-{dev,demo,prod}-api.yml\nTraefik host rules · ghcr.io/septronr/universe-api"] -.-> COMPOSE
```

---

## 14. Mobile role shell

```mermaid
graph LR
    SPLASH["Splash"] --> LOGIN["Login\n(password · OTP · SSO)"] --> PICK["Institution / college picker\n(multi-scope users)"] --> SHELL["Role shell\n(bottom tabs ≤ 5 + More grid)"]
    SHELL --> TABS["Tabs per role\n(student · parent · faculty · HOD · registrar · COE · accountant · warden · librarian · …)"]
    SHELL --> MORE["More grid\n(permission + feature gated)"]
    SHELL --> INBOX["Approvals inbox\n(workflow engine)"]
    TABS --> SEG["SegmentedScope\nMine | Dept | College | All\n(from meta.visibility)"]
    OFF["Offline cache (drift)\n+ write queue"] --> SHELL
    PUSH["Push deep links"] --> SHELL
    RC["Remote config\n(force update, read-only)"] --> SHELL
```

---

*SeptronUniverse — College & University ERP · FastAPI · PostgreSQL · Redis · Celery · React 18 · TypeScript · Tailwind · Flutter*

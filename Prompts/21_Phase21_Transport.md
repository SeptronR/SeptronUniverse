# PHASE 21 — TRANSPORT

## Pre-Requisite
Phases 01–12 complete (students/guardians, staff incl. drivers, fee linkage, holidays, Redis pub/sub WebSocket channels from Phase 01, push channel from Phase 04). Round 3 sibling phases are not required.

## Objective
Campus transport as in SeptronOrbit, extended for higher education: fleet master with statutory expiries (insurance/fitness/permit/PUC), routes and stops with per-stop fees, **student and staff allocations** with capacity control and transport-fee invoices, scheduled trips (pickup/drop) driven by the academic calendar, **driver app** trip start/stop with GPS ingestion (device tokens or driver phone), **live fleet map** over WebSocket, stop arrival ETAs and guardian "bus approaching" notifications, passenger boarding/alighting by QR scan, maintenance and fuel logs with cost-per-km, and reports — with **My route** (student/parent/staff) vs transport manager (all) views.

## Feature keys
`transport.core` (off, standard); `transport.gps_live` (off, standard; depends `transport.core`); `transport.staff` (off, standard); `transport.fees` (off, standard; depends `fees.core`); `comms.push` for live alerts.

## Visibility rules
| Role | Fleet, routes, stops | Allocations | Trips & live map | Maintenance / fuel |
|---|---|---|---|---|
| student / staff passenger | own route & stops | **S** (my allocation, fee, change request) | S (my bus live, ETA at my stop) | — |
| parent | ward route | W | W (ward bus live, boarding events) | — |
| driver | own vehicle | own trip manifest (names + stops only, masked phones) | **S** (own trips: start/stop, stops, boarding scan) | own vehicle logs (add) |
| transport_manager | **A** (manage) | A (allocate, capacity, fees status) | A (all trips, live fleet, replay) | A |
| accountant | — | fee status | — | costs |
| hod / class_advisor | — | D/O (read allocations of own students) | — | — |
| college_admin | C | C | C | C |
| auditor | A (read) | A (read) | A (read) | A (read) |

## 21.1 Database tables
Section 20: `vehicles, transport_routes, transport_stops, transport_allocations, vehicle_maintenance, vehicle_fuel_log, gps_devices, transport_trips, vehicle_gps_logs` (range-partitioned by recorded time; monthly partitions created by Beat), `trip_stop_events, trip_passenger_events`; uses `fee_invoices` (§13), `staff` (§9), `students, student_guardians` (§8), `holidays, academic_terms` (§2, §7), `device_tokens` (§3, push). Expected delta migration: none.

## 21.2 Alembic migration
`0021_phase21_transport_seed.py` — data-only: settings defaults (`transport.trip_schedule: {pickup: "07:00", drop: "16:30"}`, `transport.gps_ping_interval_s: 15`, `transport.eta_notify_minutes: 5`, `transport.expiry_alert_days: 30`, `transport.capacity_hard_limit: true`), notification templates (`transport.allocated`, `transport.bus_approaching`, `transport.boarded/alighted`, `transport.trip_delayed`, `transport.document_expiring`, `transport.route_changed`), `number_sequences` scope `trip:{yyyymm}`. Demo seed `--only transport`: 12 vehicles (2 with expiring insurance), 10 routes × 8 stops with fees and coordinates around the campus, 700 student + 60 staff allocations, GPS devices for 8 vehicles, trips for the last 10 working days with GPS traces (simulated polyline), stop events and boarding events, maintenance/fuel logs for 6 months.

## 21.3 Models — `models/transport.py`
`Vehicle`, `TransportRoute`, `TransportStop`, `TransportAllocation`, `VehicleMaintenance`, `VehicleFuelLog`, `GpsDevice`, `TransportTrip`, `VehicleGpsLog` (partitioned; insert-only), `TripStopEvent`, `TripPassengerEvent`. Enums: `VehicleType`, `VehicleStatus` (active|maintenance|retired), `PersonType` (student|staff), `AllocationStatus` (active|suspended|closed), `TripDirection` (pickup|drop), `TripStatus` (scheduled|in_progress|completed|cancelled), `PassengerEvent` (board|alight).

## 21.4 Schemas — `app/schemas/transport.py`
`VehicleIn/Out` (+ compliance chips: expiring/expired), `RouteIn/Out` (+ stops, vehicle, capacity used), `StopIn` + `StopsReorder{stop_ids[]}`, `AllocationCreate{person_type, person_id, route_id, stop_id, academic_year_id, from_on, to_on?}` + `AllocationResponse{fee_paise, invoice_id, status}`, `AllocationBulk{route_id, stop_id, person_ids[]}` + partial-success report, `AllocationChange{new_route_id, new_stop_id, effective_on}`, `MyTransportResponse{route, stop, pickup_time, drop_time, vehicle, driver_name, live_available, today_trips[]}`, `TripScheduleRequest{date_from, date_to, route_ids?}` + `TripOut` (+ progress, next stop, delay minutes), `TripStartRequest{odometer?, vehicle_id?}`, `TripEndRequest{odometer?}`, `GpsPing{lat, lng, speed_kmh?, heading?, recorded_at}` + `GpsBatch{pings[]}`, `LiveVehicle{vehicle_id, route, trip_id, lat, lng, speed, heading, at, next_stop, eta_min}`, `StopEventIn`, `PassengerScanRequest{qr|person_id, event, stop_id?}` + `ManifestResponse{stops[{stop, passengers[{name, boarded}]}]}`, `MaintenanceIn/Out`, `FuelLogIn/Out`, `GpsDeviceIn/Out` (+ one-time token), `TransportReportQuery`, `RouteStatsResponse{occupancy_pct, cost_per_km, on_time_pct}`.

## 21.5 Repository
`transport_repository.py` (`module="transport"`; self predicate on allocations by `(person_type, person_id)` = principal student/staff; wards via `student_guardians`; department scope via enrolment/staff department; driver ownership `transport_trips.driver_staff_id = principal.staff_id` and `vehicles.driver_staff_id`; college scope via `vehicles.college_id/transport_routes.college_id`; `FOR UPDATE` on route capacity during allocation), `trip_repository.py` (today's trips, by driver, by route), `gps_repository.py` (latest position per vehicle from Redis with DB fallback; trace by trip; partition-aware queries), `fleet_repository.py`.

## 21.6 Services
- `fleet_service.py`: vehicles CRUD with document expiries → Beat alerts at `expiry_alert_days` and on expiry (vehicle auto `maintenance` status when `fitness|permit|insurance` expired and `transport.block_expired_vehicles`); driver assignment (`driver_staff_id` must hold `driver` role); maintenance and fuel logs; `cost_per_km` = (fuel + maintenance cost) / km from odometer deltas; retire.
- `route_service.py`: routes with ordered stops (`sequence` unique per route; reorder endpoint renumbers), per-stop `fee_paise` (falls back to route fee), coordinates, pickup/drop times; capacity = `vehicles.capacity`; route change notifications to allocated passengers; iCal/pdf route sheet.
- `allocation_service.py` (`transport.core`, `transport.staff` for staff, `transport.fees`)
  1. Allocate person to route+stop for a year/term: one active allocation per person (409 otherwise); capacity check `count(active) < vehicle.capacity` under `FOR UPDATE` on the route (hard limit when `capacity_hard_limit`, else warning); fee invoice `fee_service.create_invoice(payer=person, source_type='transport_allocation', source_id=allocation, items=[stop fee per term/year])` when `transport.fees` (staff: payroll deduction option → `payroll.deduction_requested`); bulk allocation from CSV with partial-success report; change stop/route effective date → close + new allocation with pro-rata fee difference (setting); suspend (fee unpaid after grace → `suspended`, boarding scan warns driver); close at year end job.
  2. Self-service: student/staff request allocation or change → manager approval (simple status, no workflow) when `transport.self_service_requests`.
- `trip_service.py`
  1. Scheduling job: for each working day (not holiday/weekend; term in progress) create `pickup` and `drop` trips per route with the route's vehicle/driver; ad-hoc trips (events, exams) created manually; cancellations notify passengers.
  2. Driver: `start` (sets `in_progress`, odometer), `end` (`completed`, odometer → km), `stop-arrived/departed` (manual or geofence auto from GPS within 100 m of stop coordinates), `passenger scan` (QR from ID card / app; records `board|alight` with stop; manifest per stop with masked contacts; boarding count vs manifest); trip `delay_minutes` = actual vs scheduled at each stop.
  3. Passenger/guardian notifications: `bus_approaching` when ETA to their stop ≤ `eta_notify_minutes` (once per trip per stop), `boarded/alighted` events to guardians (setting; students may opt-out for staff-type), `trip_delayed` when > 15 min.
- `gps_service.py` (`transport.gps_live`)
  1. Ingestion: `POST /gps/ingest` authenticated by device token (`gps_devices.token_hash`, `transport:gps_ingest`) or by the driver app JWT for the active trip; batches of pings (offline buffered; server ignores duplicates by `(vehicle_id, recorded_at)`); writes `vehicle_gps_logs` (partitioned) and publishes the latest position to Redis (`transport:live:{institution}`) → WebSocket channel `transport.live` (Phase 01 pub/sub) with per-tenant fan-out; consumer rate limits (1 ping/5 s per device).
  2. ETA: distance along the remaining polyline / moving average speed (fallback: scheduled times); geofence stop events; idle/route-deviation detection (> 500 m off the route polyline for 3 pings) → manager alert.
  3. Replay: trace for a trip (downsampled), export GPX; retention: raw pings 90 days (partition drop by Beat), trip summaries kept.
  4. Live map scope: manager/college admin see all vehicles; passengers/guardians only the vehicle of their route and only during their trip windows; drivers their own.
- `reports_service.py`: route occupancy, fee collection (Phase 12 data by `source_type='transport_allocation'`), on-time %, cost per km per vehicle, compliance register, fuel efficiency (km/l), trips per driver; NAAC/NIRF facility counts to Phase 32 (`transport_vehicles`, `transport_students`).

## 21.7 Events / jobs
Emits: `transport.vehicle_created/updated/retired`, `transport.document_expiring/expired`, `transport.route_changed`, `transport.allocated/changed/suspended/closed`, `transport.trip_scheduled/started/ended/cancelled/delayed`, `transport.stop_arrived/departed`, `transport.bus_approaching`, `transport.passenger_boarded/alighted`, `transport.route_deviation`, `payroll.deduction_requested` (staff fee via payroll). Consumers: notifications/push (passengers, guardians, manager), Phase 12 (invoices, `fees.payment_received` → un-suspend), Phase 06 payroll deductions, Phase 25 calendar (trip cancellations on holidays), Phase 32 metrics. Jobs: `transport.schedule_trips` (weekly ahead + daily top-up), `transport.bulk_allocate`, `transport.year_end_close`, `transport.reports_export`, `transport.gps_export`. Beat: `transport.document_expiry_scan` (daily), `transport.gps_partition_maintenance` (monthly: create next partition, drop > 90 days), `transport.trip_autoclose` (nightly: `in_progress` → `completed` with flag), `transport.fee_suspension` (nightly), `transport.live_cache_cleanup` (hourly). Workflows: none (allocation requests use a simple approve/reject status).

## 21.8 Endpoints
```
GET/POST /api/v1/transport/vehicles · GET/PUT/DELETE /transport/vehicles/{id} · POST /transport/vehicles/{id}/retire · GET /transport/vehicles/compliance [transport:manage|view_all] {transport.core}
GET/POST /api/v1/transport/vehicles/{id}/maintenance · GET/POST /transport/vehicles/{id}/fuel [transport:manage|driver (own vehicle, add)]
GET/POST /api/v1/transport/routes · GET/PUT/DELETE /transport/routes/{id} · GET/POST /transport/routes/{id}/stops · PUT /transport/stops/{id} · POST /transport/routes/{id}/stops/reorder · GET /transport/routes/{id}/sheet.pdf [transport:manage|view_all]
GET      /api/v1/transport/routes/public (names, stops, times; no vehicles) [transport:view] {transport.core}
GET/POST /api/v1/transport/allocations?route_id&status&person_type&department_id · POST /transport/allocations/bulk (job) · POST /transport/allocations/{id}/change|suspend|close [transport:manage|view_all] {transport.core; transport.staff for staff}
GET      /api/v1/transport/me · GET /transport/wards · POST /transport/me/request {route_id, stop_id} · GET /transport/me/requests [transport:view (self)]
GET      /api/v1/transport/requests?status · POST /transport/requests/{id}/decide [transport:manage]
POST     /api/v1/transport/trips/schedule (job) · GET /transport/trips?date&route_id&status · GET /transport/trips/{id} · POST /transport/trips (ad hoc) · POST /transport/trips/{id}/cancel [transport:manage|view_all]
GET      /api/v1/transport/driver/trips?date · POST /transport/trips/{id}/start · POST /transport/trips/{id}/end · POST /transport/trips/{id}/stop-event · GET /transport/trips/{id}/manifest · POST /transport/trips/{id}/passenger-scan (Idempotency-Key) [transport:driver (own trips)]
POST     /api/v1/transport/gps/ingest (device token or driver JWT; batch) [transport:gps_ingest|driver] {transport.gps_live}
GET      /api/v1/transport/live?route_id&vehicle_id · WS /ws/transport.live · GET /transport/trips/{id}/trace?format=json|gpx [transport:view_all|view (own route during trip)] {transport.gps_live}
GET/POST /api/v1/transport/gps-devices · POST /transport/gps-devices/{id}/rotate-token · DELETE /transport/gps-devices/{id} [transport:manage] {transport.gps_live}
GET      /api/v1/transport/reports/{occupancy|fees|on_time|cost_per_km|compliance|fuel|driver_trips}?format=xlsx (job) [transport:view_all|reports:export]
GET      /api/v1/transport/stats [transport:view_all]
```

## 21.9 Frontend
- `/admin/transport/fleet` (vehicles table with compliance chips, drawer: documents, driver, maintenance & fuel tabs with cost-per-km chart), `/admin/transport/routes` (route list, map editor with draggable stops + reorder, fees, route sheet PDF), `/admin/transport/allocations` (grid with route/stop/fee status; allocate dialog with capacity meter; bulk CSV; ScopeTabs Department | College | All; requests queue), `/admin/transport/trips` (day view per route: scheduled/in-progress/completed, delays; ad-hoc trip; cancel), `/admin/transport/live` (fleet map with vehicle markers, next stop/ETA, deviation alerts; trip replay slider; GPX export), `/admin/transport/devices` (GPS devices, tokens, last seen), `/admin/transport/reports`, `/admin/transport/settings`.
- Portals: `/student/transport` (my route/stop/times, fee & pay, live bus during trip windows with ETA, change request), `/parent/transport` (ward bus live, boarding timeline), `/staff/transport` (my allocation, payroll deduction consent), driver web fallback `/driver` (today's trips, start/end, manifest, scan).
- Nav: CAMPUS › Transport (Fleet, Routes, Allocations, Trips, Live map, Devices, Reports, Settings).

## 21.10 Mobile
Driver shell: Home (today's trips) · Route (start/stop trip, stop list with arrive/depart, passenger QR scan, GPS auto-ping while trip active with background location + offline buffer) · Settings (vehicle checks, fuel entry); Student/Staff: More › Transport (my route, live bus + ETA, fee pay, change request); Parent: Transport (ward bus live map, boarding/alighting push, ETA alerts); Transport manager: Home (fleet status, delays, compliance alerts) · Live map · Trips · More (allocations read, devices).

## 21.11 API verification — `scripts/verify/21_transport.ps1`
Roles: `transport.mgr`, `driver.1` (vehicle V1, route R1), `driver.2`, `accountant`, `hod.cse`, `student.r1` (allocated R1 stop S3), `student.none`, `staff.r2`, `parent.r1`, `college.admin.b`, `auditor.tmp`, device token `dev.V1`.
1. Seed `--only transport`; `GET /transport/vehicles` as `transport.mgr` → 12 with 2 `insurance_expiring` chips; as `student.r1` → 403; `GET /transport/vehicles/compliance` lists expiring docs; Beat expiry scan (dev) → `transport.document_expiring` notifications; set a fitness expiry in the past + `block_expired_vehicles` → vehicle `maintenance`, its trips for tomorrow unscheduled.
2. Routes: create route with 5 stops (fees), reorder → sequences renumbered 1..5; route sheet PDF; update pickup time → `transport.route_changed` notification to allocated passengers.
3. Allocation: allocate `student.none` to R1/S3 → invoice `source_type=transport_allocation` with stop fee; second active allocation → 409; fill R1 to `vehicle.capacity` (bulk) → next allocate → 409 `CAPACITY_FULL` (hard limit) / 201 with warning when soft; staff allocation with `transport.staff` off → 403; on → `staff.r2` allocated with payroll deduction option → `payroll.deduction_requested` event; change stop effective next month → old closed, new active, pro-rata difference invoice.
4. Self-service: `student.none` `POST /transport/me/request` → pending; manager decides approve → allocation + invoice; `GET /transport/me` shows route/stop/times, `live_available=false` outside trip windows.
5. Trips: schedule job for next 5 working days → pickup+drop per route, none on the seeded holiday; ad-hoc exam trip created; cancel a trip → passenger notifications.
6. Driver flow: `driver.1` `GET /transport/driver/trips?date=today` → own trips only; `driver.2` `POST /trips/{R1 trip}/start` → 403; `driver.1` start with odometer → `in_progress`; GPS pings via driver JWT batch (20 pings along polyline) → `vehicle_gps_logs` rows, Redis latest, WS `transport.live` message received by a `transport.mgr` client; `student.r1` WS subscribe → receives only V1 during window; `student.none` (different route) → no V1 messages; device-token ingest for `dev.V1` with duplicate `recorded_at` → ignored; 3 pings > 500 m off route → `transport.route_deviation` alert.
7. Stops & ETA: geofence ping within 100 m of S2 → `trip_stop_events.arrived_at` auto; ETA to S3 ≤ 5 min (simulated) → `transport.bus_approaching` push to `student.r1` and `parent.r1` once; second qualifying ping → no duplicate.
8. Boarding: manifest for the trip lists S3 passengers with masked phones; scan `student.r1` QR at S3 → `board` event, guardian `transport.boarded` notification; scan a `suspended` passenger → 200 with `warning=FEE_SUSPENDED`; scan a non-allocated student → 409 `NOT_ALLOCATED`; replay same Idempotency-Key → same event; end trip with odometer → `completed`, km recorded; trace endpoint returns downsampled points and GPX.
9. Fee suspension Beat: unpaid allocation past grace → `suspended`, notification; pay (Phase 12 dev) → `fees.payment_received` → `active`.
10. Maintenance/fuel: add fuel 60 l ₹6,000 and a service ₹12,000 for V1 with odometer deltas → `cost_per_km` and km/l in `GET /transport/reports/cost_per_km`; `driver.1` may add fuel for V1, not V2 (403).
11. Visibility: `hod.cse` `GET /transport/allocations?department_id=CSE` → CSE only; `parent.r1` `GET /transport/wards` → ward allocation; `college.admin.b` sees only college B vehicles/routes; `auditor.tmp` read OK, allocate → 403; `accountant` `GET /transport/allocations` → fee status columns, `POST` → 403.
12. Partition maintenance Beat (dev) → next-month partition exists; drop of > 90-day partition simulated in dev DB; year-end close job closes allocations and produces the summary.
13. Feature gating: `transport.gps_live` off → `/transport/live` 403 and driver pings 403 (trips still work); `transport.fees` off → allocation without invoice.

## 21.12 UI verification
1. Fleet page with compliance chips and vehicle drawer (documents, maintenance/fuel with cost chart); routes map editor with stop drag/reorder and route sheet PDF.
2. Allocations grid with capacity meter, bulk CSV report, change/suspend/close dialogs, ScopeTabs; requests queue.
3. Trips day view (schedule job, ad-hoc, cancel) and live map (markers, ETA, deviation alerts, replay slider, GPX export); devices page with token rotation.
4. Portals: student/staff transport page (route, pay, live bus during window, change request); parent live map and boarding timeline; driver web fallback.
5. Mobile: driver trip flow (start → auto GPS with offline buffer → stop events → passenger QR scan → end), parent ETA push and live map, student live bus.

## 21.13 Deliverables checklist
- [ ] Fleet with compliance alerts, routes/stops with fees and map, allocations (capacity, invoices/payroll deduction, changes, suspension, self-service requests), trip scheduling by calendar, driver flow (start/end, stop events, manifest, boarding scans), GPS ingestion (device/driver, batches, dedupe) → Redis/WS live map, ETA + approaching alerts, deviation detection, replay/GPX, retention partitions, maintenance/fuel + cost per km, reports/metrics
- [ ] Visibility registrations (self/wards/driver ownership/department/college/all; live-map scoping); events/jobs/Beat; demo seed `--only transport`
- [ ] Web + mobile (driver app); `scripts/verify/21_transport.ps1` passes; UI checklist done; guards green; commit `feat(phase-21): transport`

-- After registration_rush.js: no offering may hold more confirmed registrations than its capacity (expect 0 rows).
SELECT o.id, o.capacity, count(r.id) AS confirmed
FROM course_offerings o JOIN course_registrations r ON r.offering_id = o.id AND r.status IN ('confirmed', 'approved')
GROUP BY o.id, o.capacity HAVING count(r.id) > o.capacity;

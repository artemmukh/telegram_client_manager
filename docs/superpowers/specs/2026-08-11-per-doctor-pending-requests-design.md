# Per-Doctor Pending Requests Design

## Goal

Allow a client to keep one client-created `PENDING` booking request for each doctor in their clinic.

## Rules

- A client-created `PENDING` request to doctor A blocks only another client-created `PENDING` request to doctor A. The per-doctor cap is exactly one in both bot instances.
- A client-created `PENDING` request to doctor A does not block a request to doctor B.
- `CONFIRMED` and finalized appointments do not count toward this limit.
- The limit remains enforced by `AppointmentManagement` when the request is submitted; the handler must not impose a global pre-selection block.
- Existing cancellation cooldown and slot-availability rules are unchanged.

## Architecture

The client handler continues to select from the available doctors without a pending-request check. `AppointmentManagement.create_self_booking()` resolves the selected staff member first and then applies a doctor-scoped pending-request check against the explicit per-doctor cap of one. The existing appointment repository read is reused; no SQL, schema, or exception changes are needed.

The check is a service-level read-count-write sequence, like the existing global check. It is authoritative for ordinary requests but cannot make simultaneous submissions atomic without a database constraint; that broader concurrency work is outside this scoped change.

## Testing

- `test_create_self_booking_allows_pending_request_for_another_doctor` proves that a pending request for doctor A permits a client-created pending request for doctor B.
- `test_create_self_booking_blocks_second_pending_request_for_same_doctor` proves that a second client-created pending request for doctor A is rejected.
- `test_ensure_pending_limit_raises_with_existing_pending_self_booking` and `test_ensure_pending_limit_raises_when_proposal_outstanding` preserve the same-doctor pending guard, including an outstanding proposal.
- `test_ensure_pending_limit_allows_when_self_booking_is_finalized` and `test_ensure_pending_limit_ignores_admin_created_pending_appointment` retain the confirmed/finalized and admin-created exclusions.
- `test_start_booking_does_not_apply_pending_limit_before_doctor_choice` proves that the client wizard no longer invokes the obsolete global guard before listing doctors.
- `test_self_booking_pending_limit_is_scoped_per_doctor` covers the E2E regression with a real second ZB staff-seeded doctor (`226655040`) and proves that one client can keep pending requests for two different doctors while a second pending request for the first doctor is still rejected.

# Thronos EduPresence Architecture

## Event logic

- `lesson_opened`
- `student_self_confirmed`
- `attendance_qr_scanned`
- `attendance_manual_set`
- `lesson_closed`
- `attendance_finalized`
- `makeup_created`
- `makeup_completed`

## Core rule

Η απουσία και η αναπλήρωση είναι δύο διαφορετικά γεγονότα. Η αναπλήρωση δεν σβήνει την απουσία.

## On-chain data

Στο Thronos μπαίνουν μόνο hashes:

```json
{
  "event_type": "attendance_finalized",
  "lesson_hash": "...",
  "student_hash": "...",
  "teacher_hash": "...",
  "attendance_status": "present",
  "confirmation_method": "student_qr_teacher_scan",
  "finalized_at": "..."
}
```

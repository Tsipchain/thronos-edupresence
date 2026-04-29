# v4 Implementation Notes

## Domain model

- `Node`: Κόμβος / ΚΑΠΗ / εκπαιδευτικό κέντρο.
- `Classroom`: Τμήμα μέσα στον κόμβο.
- `Student`: Ωφελούμενος ή επιλαχών.
- `Enrollment`: Τοποθέτηση ωφελούμενου σε τμήμα.
- `UnableRequest`: Αδυναμία παρακολούθησης με approval flow.
- `Lesson`: Μάθημα/ημέρα παρουσιών.
- `Attendance`: Γραμμή παρουσίας ανά μαθητή.
- `Makeup`: Αναπλήρωση ως νέο γεγονός.

## Principles

1. The node is listed once even when it has multiple classes.
2. A selected beneficiary can be placed in one active class.
3. If inability to attend is approved, active enrollments are removed and a slot opens.
4. The next standby can be allocated into selected beneficiaries.
5. Attendance is final only when teacher confirms through QR scan or manual truth entry.
6. Old attendance is not overwritten for makeups.
7. Chain payloads are hash-only.

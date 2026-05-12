@app.get("/classes/{class_id}/history", response_class=HTMLResponse)
def class_history(request: Request, class_id: int, db: Annotated[Session, Depends(get_db)]):
    classroom = db.query(Classroom).options(
        joinedload(Classroom.node),
        joinedload(Classroom.lessons).joinedload(Lesson.attendance_rows).joinedload(Attendance.student),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(404, "Classroom not found")

    class HistoryEntry:
        def __init__(self, lesson, rows):
            self.lesson = lesson
            self.present_count = sum(1 for r in rows if r.status == "present")
            self.total = len(rows)
            self.digital_count = sum(
                1 for r in rows
                if r.status == "present" and (
                    r.student_confirmed_at or
                    r.confirmation_method == "student_qr_teacher_scan"
                )
            )
            self.manual_count = sum(
                1 for r in rows
                if r.status == "present" and r.confirmation_method == "teacher_manual"
            )
            self.hashes = [r.attestation_hash for r in rows if r.attestation_hash]

    history = [
        HistoryEntry(lesson, lesson.attendance_rows)
        for lesson in sorted(classroom.lessons, key=lambda l: l.starts_at, reverse=True)
    ]

    return render(request, "lesson_history.html", {
        "classroom": classroom,
        "history": history,
    })

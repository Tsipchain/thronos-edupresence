"""REST API endpoints for external integrations (gateway, Earn, university dashboards)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import get_db
from app.models import (
    Attendance, Classroom, Course, Enrollment, Grade, Lesson,
    Node, Student, University,
)
from app.security import hash_identity

router = APIRouter(prefix="/api/v1", tags=["api"])


def _require_api_key(x_api_key: str = Header(...)):
    if not settings.l2e_api_key or x_api_key != settings.l2e_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Node / Classroom stats ─────────────────────────────────────────────────

@router.get("/nodes", dependencies=[Depends(_require_api_key)])
def list_nodes(db: Annotated[Session, Depends(get_db)]):
    nodes = db.query(Node).filter(Node.is_active.is_(True)).order_by(Node.id.asc()).all()
    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "municipality": n.municipality,
                "capacity": n.capacity,
            }
            for n in nodes
        ]
    }


@router.get("/nodes/{node_id}/stats", dependencies=[Depends(_require_api_key)])
def node_stats(node_id: int, db: Annotated[Session, Depends(get_db)]):
    node = db.query(Node).options(
        joinedload(Node.classrooms).joinedload(Classroom.lessons),
        joinedload(Node.classrooms).joinedload(Classroom.enrollments),
        joinedload(Node.students),
    ).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")

    total_students = len([s for s in node.students if s.is_active])
    classrooms = []
    for c in node.classrooms:
        active_enr = sum(1 for e in c.enrollments if e.status == "active")
        closed_lessons = [l for l in c.lessons if l.status == "closed"]
        hours_done = sum(
            (l.teaching_hours or max(1, l.duration_minutes // 45))
            for l in closed_lessons
        )
        target = c.target_teaching_hours or 40
        classrooms.append({
            "id": c.id,
            "name": c.name,
            "enrolled": active_enr,
            "capacity": c.capacity,
            "lessons_closed": len(closed_lessons),
            "hours_done": hours_done,
            "target_hours": target,
            "completion_pct": min(100, round(hours_done / target * 100)) if target else 0,
        })

    return {
        "node_id": node.id,
        "name": node.name,
        "total_active_students": total_students,
        "classrooms": classrooms,
    }


# ─── Attendance analytics ────────────────────────────────────────────────────

@router.get("/classrooms/{class_id}/attendance-summary", dependencies=[Depends(_require_api_key)])
def attendance_summary(class_id: int, db: Annotated[Session, Depends(get_db)]):
    classroom = db.query(Classroom).options(
        joinedload(Classroom.lessons),
        joinedload(Classroom.enrollments).joinedload(Enrollment.student),
    ).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(404, "Classroom not found")

    closed_lessons = [l for l in classroom.lessons if l.status == "closed"]
    lesson_ids = [l.id for l in closed_lessons]
    all_att = (
        db.query(Attendance).filter(Attendance.lesson_id.in_(lesson_ids)).all()
        if lesson_ids else []
    )

    att_index: dict[tuple[int, int], Attendance] = {}
    for a in all_att:
        att_index[(a.lesson_id, a.student_id)] = a

    threshold = settings.l2e_attendance_threshold_pct or 80
    eligible = 0
    students = []

    for enr in classroom.enrollments:
        if enr.status != "active":
            continue
        present = sum(
            1 for l in closed_lessons
            if att_index.get((l.id, enr.student_id)) and att_index[(l.id, enr.student_id)].status == "present"
        )
        total = len(closed_lessons)
        pct = round(present / total * 100) if total else 0
        if pct >= threshold:
            eligible += 1
        students.append({
            "student_ref": hash_identity("student", enr.student_id),
            "present": present,
            "total": total,
            "attendance_pct": pct,
            "eligible": pct >= threshold,
        })

    hours_done = sum(
        (l.teaching_hours or max(1, l.duration_minutes // 45))
        for l in closed_lessons
    )
    target = classroom.target_teaching_hours or 40

    return {
        "classroom_id": classroom.id,
        "classroom_name": classroom.name,
        "lessons_closed": len(closed_lessons),
        "hours_done": hours_done,
        "target_hours": target,
        "completion_pct": min(100, round(hours_done / target * 100)) if target else 0,
        "threshold_pct": threshold,
        "eligible_count": eligible,
        "total_enrolled": len(students),
        "students": students,
    }


# ─── University course stats ────────────────────────────────────────────────

@router.get("/universities", dependencies=[Depends(_require_api_key)])
def list_universities(db: Annotated[Session, Depends(get_db)]):
    unis = db.query(University).filter(University.is_active.is_(True)).order_by(University.name.asc()).all()
    return {
        "universities": [
            {
                "id": u.id,
                "name": u.name,
                "slug": u.slug,
                "domain": u.domain,
                "l2e_tenant_id": u.l2e_tenant_id,
            }
            for u in unis
        ]
    }


@router.get("/universities/{uni_id}/courses", dependencies=[Depends(_require_api_key)])
def university_courses(uni_id: int, db: Annotated[Session, Depends(get_db)]):
    uni = db.query(University).filter(University.id == uni_id).first()
    if not uni:
        raise HTTPException(404, "University not found")

    courses = db.query(Course).options(
        joinedload(Course.assignments),
        joinedload(Course.grades),
    ).filter(Course.university_id == uni_id, Course.is_active.is_(True)).all()

    return {
        "university": uni.name,
        "courses": [
            {
                "id": c.id,
                "code": c.code,
                "title": c.title,
                "semester": c.semester,
                "credits": c.credits,
                "teacher_name": c.teacher_name,
                "assignments_count": len(c.assignments),
                "grades_count": len(c.grades),
                "passed_count": sum(1 for g in c.grades if g.passed),
                "status": c.status,
            }
            for c in courses
        ],
    }


@router.get("/courses/{course_id}/grades-summary", dependencies=[Depends(_require_api_key)])
def course_grades_summary(course_id: int, db: Annotated[Session, Depends(get_db)]):
    course = db.query(Course).options(
        joinedload(Course.grades),
        joinedload(Course.assignments),
    ).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")

    grades = course.grades
    scored = [g for g in grades if g.final_score is not None]

    return {
        "course_id": course.id,
        "title": course.title,
        "pass_grade": course.pass_grade,
        "total_graded": len(scored),
        "total_passed": sum(1 for g in scored if g.passed),
        "total_failed": sum(1 for g in scored if not g.passed),
        "average_score": round(sum(g.final_score for g in scored) / len(scored), 2) if scored else None,
        "assignments_count": len(course.assignments),
    }

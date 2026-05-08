from __future__ import annotations
from typing import Annotated
from fastapi import Depends, HTTPException, Header
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import Node, Classroom, Student, Enrollment, now_utc
from app.attestation import write_audit

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_admin_key(x_admin_key: str = Header(default="")) -> None:
    if not x_admin_key or x_admin_key != settings.token_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


class StudentIn(BaseModel):
    external_ref: str
    full_name: str
    phone: str = ""
    gender: str = ""


class ClassImport(BaseModel):
    node_name: str
    classroom_name: str
    teacher_name: str = ""
    teacher_phone: str = ""
    target_teaching_hours: int = 40
    students: list[StudentIn]


@router.post("/import-class")
def import_class(
    data: ClassImport,
    db: Annotated[Session, Depends(get_db)],
    _: None = Depends(_check_admin_key),
):
    """One-time bulk import: create node, classroom, students, enroll all."""
    # Node
    node = db.query(Node).filter(Node.name == data.node_name).first()
    if not node:
        node = Node(name=data.node_name, municipality="ΘΕΣΣΑΛΟΝΙΚΗΣ",
                    responsible_name=data.teacher_name)
        db.add(node); db.flush()

    # Classroom
    classroom = Classroom(
        node_id=node.id,
        name=data.classroom_name,
        teacher_name=data.teacher_name,
        teacher_phone=data.teacher_phone,
        location=data.node_name,
        target_teaching_hours=data.target_teaching_hours,
        l2e_tenant_id=settings.l2e_tenant_id,
    )
    db.add(classroom); db.flush()

    created = []
    for i, s in enumerate(data.students, 1):
        student = Student(
            node_id=node.id,
            full_name=s.full_name.strip(),
            phone=s.phone.strip(),
            external_ref=s.external_ref.strip(),
            gender=s.gender.strip(),
            status="selected",
            priority_order=i,
        )
        db.add(student); db.flush()
        db.add(Enrollment(classroom_id=classroom.id,
                          student_id=student.id, status="active"))
        created.append({"ref": s.external_ref, "name": s.full_name})

    db.commit()
    write_audit(db, "bulk_import", "classroom", classroom.id,
                actor="admin", detail={"students": len(created)})
    return {
        "ok": True,
        "node_id": node.id,
        "classroom_id": classroom.id,
        "students_created": len(created),
        "dashboard_url": f"{settings.public_base_url}/classes/{classroom.id}",
    }

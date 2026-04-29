from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def now_utc() -> datetime:
    return datetime.utcnow()

class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    municipality: Mapped[str] = mapped_column(String(160), default="ΘΕΣΣΑΛΟΝΙΚΗΣ")
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    responsible_name: Mapped[str] = mapped_column(String(200), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=15)
    address: Mapped[str] = mapped_column(String(250), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    classrooms = relationship("Classroom", back_populates="node", cascade="all, delete-orphan")
    students = relationship("Student", back_populates="node", cascade="all, delete-orphan")

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    external_ref: Mapped[str] = mapped_column(String(120), default="")  # ΚΑΥΑΣ / external ref
    gender: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(60), default="selected")  # selected | standby | unable_pending | unable_approved | unable_rejected
    priority_order: Mapped[int] = mapped_column(Integer, default=0)
    inability_reason: Mapped[str] = mapped_column(String(250), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    node = relationship("Node", back_populates="students")
    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")

class Classroom(Base):
    __tablename__ = "classrooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    program_name: Mapped[str] = mapped_column(String(250), default="Ψηφιακή Ενδυνάμωση")
    teacher_name: Mapped[str] = mapped_column(String(200), default="")
    teacher_afm: Mapped[str] = mapped_column(String(20), default="")
    teacher_email: Mapped[str] = mapped_column(String(200), default="")
    teacher_phone: Mapped[str] = mapped_column(String(80), default="")
    location: Mapped[str] = mapped_column(String(250), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=15)
    target_teaching_hours: Mapped[int] = mapped_column(Integer, default=40)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    node = relationship("Node", back_populates="classrooms")
    enrollments = relationship("Enrollment", back_populates="classroom", cascade="all, delete-orphan")
    lessons = relationship("Lesson", back_populates="classroom", cascade="all, delete-orphan")

class Enrollment(Base):
    __tablename__ = "enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    classroom = relationship("Classroom", back_populates="enrollments")
    student = relationship("Student", back_populates="enrollments")

class UnableRequest(Base):
    __tablename__ = "unable_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(250), default="")
    status: Mapped[str] = mapped_column(String(40), default="pending")  # pending | approved | rejected
    requested_by: Mapped[str] = mapped_column(String(200), default="teacher")
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    node = relationship("Node")
    student = relationship("Student")

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="Μάθημα")
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)
    teaching_hours: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_by: Mapped[str] = mapped_column(String(200), default="teacher")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    classroom = relationship("Classroom", back_populates="lessons")
    attendance_rows = relationship("Attendance", back_populates="lesson", cascade="all, delete-orphan")

class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    confirmation_method: Mapped[str] = mapped_column(String(80), default="")
    manual_reason: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    student_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    teacher_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attestation_hash: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    lesson = relationship("Lesson", back_populates="attendance_rows")
    student = relationship("Student")
    makeup = relationship("Makeup", back_populates="original_attendance", uselist=False)

class Makeup(Base):
    __tablename__ = "makeups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_attendance_id: Mapped[int] = mapped_column(ForeignKey("attendance.id"), nullable=False)
    original_lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    makeup_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)
    teacher_name: Mapped[str] = mapped_column(String(200), default="")
    topic: Mapped[str] = mapped_column(String(250), default="")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    reason: Mapped[str] = mapped_column(String(250), default="Αναπλήρωση απουσίας")
    student_signature_note: Mapped[str] = mapped_column(String(250), default="")
    evidence_hash: Mapped[str] = mapped_column(String(128), default="")
    attestation_hash: Mapped[str] = mapped_column(String(128), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    original_attendance = relationship("Attendance", back_populates="makeup")
    original_lesson = relationship("Lesson")
    student = relationship("Student")

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(200), default="system")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

class Attestation(Base):
    __tablename__ = "attestations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(80), default="edu_presence")
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

class SmsMessage(Base):
    __tablename__ = "sms_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    attendance_id: Mapped[int | None] = mapped_column(ForeignKey("attendance.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    to_phone: Mapped[str] = mapped_column(String(80), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(80), default="mock")
    status: Mapped[str] = mapped_column(String(80), default="queued")
    provider_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lesson = relationship("Lesson")
    attendance = relationship("Attendance")
    student = relationship("Student")

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def now_utc() -> datetime:
    return datetime.utcnow()

class University(Base):
    __tablename__ = "universities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    contact_phone: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    l2e_tenant_id: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    courses = relationship("Course", back_populates="university", cascade="all, delete-orphan")
    nodes = relationship("Node", back_populates="university")


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int | None] = mapped_column(ForeignKey("universities.id"), nullable=True)
    municipality: Mapped[str] = mapped_column(String(160), default="ΘΕΣΣΑΛΟΝΙΚΗΣ")
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    responsible_name: Mapped[str] = mapped_column(String(200), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=15)
    address: Mapped[str] = mapped_column(String(250), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    university = relationship("University", back_populates="nodes")
    classrooms = relationship("Classroom", back_populates="node", cascade="all, delete-orphan")
    students = relationship("Student", back_populates="node", cascade="all, delete-orphan")

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    external_ref: Mapped[str] = mapped_column(String(120), default="")  # ΚΑΥΑΣ / εξωτερικός κωδικός
    tax_id: Mapped[str] = mapped_column(String(20), default="")          # ΑΦΜ για ταύτιση με L2E
    thr_wallet: Mapped[str] = mapped_column(String(120), default="")     # THR wallet για ανταμοιβές
    gender: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(60), default="selected")  # selected | standby | unable_*
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
    # L2E integration fields
    l2e_course_id: Mapped[str] = mapped_column(String(120), default="")    # ID στο main chain L2E
    l2e_tenant_id: Mapped[str] = mapped_column(String(120), default="")    # Tenant (ministry_edu)
    l2e_reported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # τελευταίο report
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

class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    attendance_id: Mapped[int | None] = mapped_column(ForeignKey("attendance.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    to_email: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(250), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="queued")
    provider_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lesson = relationship("Lesson")
    attendance = relationship("Attendance")
    student = relationship("Student")


# ---------------------------------------------------------------------------
# University Tenant: Courses, Assignments, Grading, Certificates, Live Sessions
# ---------------------------------------------------------------------------

class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), nullable=False)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    semester: Mapped[str] = mapped_column(String(40), default="")
    credits: Mapped[int] = mapped_column(Integer, default=0)
    max_students: Mapped[int] = mapped_column(Integer, default=100)
    teacher_name: Mapped[str] = mapped_column(String(200), default="")
    teacher_email: Mapped[str] = mapped_column(String(200), default="")
    pass_grade: Mapped[float] = mapped_column(Float, default=5.0)
    l2e_course_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    university = relationship("University", back_populates="courses")
    classroom = relationship("Classroom")
    assignments = relationship("Assignment", back_populates="course", cascade="all, delete-orphan")
    grades = relationship("Grade", back_populates="course", cascade="all, delete-orphan")
    certificates = relationship("Certificate", back_populates="course", cascade="all, delete-orphan")
    live_sessions = relationship("LiveSession", back_populates="course", cascade="all, delete-orphan")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    assignment_type: Mapped[str] = mapped_column(String(40), default="homework")  # homework | exam | project | quiz
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lock_on_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="draft")  # draft | published | closed | graded
    created_by: Mapped[str] = mapped_column(String(200), default="teacher")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    course = relationship("Course", back_populates="assignments")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    file_url: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="submitted")  # submitted | graded | returned
    graded_by: Mapped[str] = mapped_column(String(200), default="")
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attestation_hash: Mapped[str] = mapped_column(String(128), default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("Student")


class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    letter_grade: Mapped[str] = mapped_column(String(10), default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    attestation_hash: Mapped[str] = mapped_column(String(128), default="")
    graded_by: Mapped[str] = mapped_column(String(200), default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    course = relationship("Course", back_populates="grades")
    student = relationship("Student")


class Certificate(Base):
    __tablename__ = "certificates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    certificate_type: Mapped[str] = mapped_column(String(40), default="completion")  # completion | excellence | attendance
    title: Mapped[str] = mapped_column(String(250), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    issued_by: Mapped[str] = mapped_column(String(200), default="")
    tx_hash: Mapped[str] = mapped_column(String(128), default="")
    attestation_hash: Mapped[str] = mapped_column(String(128), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(40), default="issued")  # issued | revoked
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    course = relationship("Course", back_populates="certificates")
    student = relationship("Student")


class LiveSession(Base):
    __tablename__ = "live_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(250), default="Live Classroom")
    room_id: Mapped[str] = mapped_column(String(120), default="")
    join_url: Mapped[str] = mapped_column(String(500), default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=90)
    status: Mapped[str] = mapped_column(String(40), default="scheduled")  # scheduled | live | ended
    recording_url: Mapped[str] = mapped_column(String(500), default="")
    attendee_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    course = relationship("Course", back_populates="live_sessions")
    lesson = relationship("Lesson")

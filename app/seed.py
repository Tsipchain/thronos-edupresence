from sqlalchemy.orm import Session
from app.models import Classroom, Enrollment, Node, Student

DEMO_STUDENTS = [
    ("ΛΑΦΗ ΜΠΕΚΙΑΡΑΚΗ", "1494"), ("ΟΛΓΑ ΔΟΥΓΕΡΙΔΟΥ", "618"), ("ΒΑΓΙΑ ΦΥΤΙΛΗ", "559"),
    ("ΧΡΗΣΤΟΣ ΠΟΥΛΙΔΗΣ", "517"), ("ΣΩΤΗΡΙΟΣ ΧΑΤΖΗΛΑΚΟΣ", "452"), ("ΠΗΝΕΛΟΠΗ ΚΥΝΗΓΟΠΟΥΛΟΥ", "451"),
    ("ΕΛΕΝΗ ΔΑΝΙΟΠΟΥΛΟΥ", "412"), ("ΘΕΟΔΩΡΟΣ ΤΣΑΡΜΠΟΥΛΟΣ", "400"), ("ΚΑΛΛΙΟΠΗ ΚΕΡΑΜΙΔΑ", "367"),
    ("ΑΘΗΝΑ ΑΔΑΜΙΔΟΥ", "366"), ("ΕΛΕΝΗ ΚΑΡΑΠΕΤΡΙΔΟΥ", "296"), ("ΗΓΗΣΙΠΥΛΗ ΣΤΑΜΑΤΙΟΥ", "250"),
    ("ΑΝΝΑ ΛΕΟΝΤΑΡΙΔΟΥ", "220"), ("ΣΠΥΡΙΔΩΝ ΞΕΡΑΣ", "207"), ("ΡΕΑ ΠΑΠΑΔΗΜΗΤΡΟΠΟΥΛΟΥ", "60"),
]

STANDBY_STUDENTS = [
    ("ΝΙΚΟΛΑΟΣ ΠΑΠΑΔΟΠΟΥΛΟΣ", "8801"),
    ("ΜΑΡΙΑ ΓΕΩΡΓΙΟΥ", "8802"),
    ("ΔΗΜΗΤΡΑ ΙΩΑΝΝΟΥ", "8803"),
    ("ΑΝΑΣΤΑΣΙΟΣ ΚΩΝΣΤΑΝΤΙΝΟΥ", "8804"),
]

def seed_demo(db: Session) -> None:
    if db.query(Node).count() > 0:
        return

    node = Node(
        municipality="ΘΕΣΣΑΛΟΝΙΚΗΣ",
        name="1ο Παράρτημα ΚΑΠΗ Δήμου Θεσσαλονίκης",
        responsible_name="Διοικητικός Υπεύθυνος Demo",
        capacity=30,
        address="Θεσσαλονίκη",
    )
    db.add(node); db.flush()

    class_a = Classroom(
        node_id=node.id,
        name="Α",
        program_name="Ψηφιακή εκπαίδευση και ενδυνάμωση των ηλικιωμένων και των ατόμων με αναπηρία",
        teacher_name="ΓΙΩΡΓΟΣ ΔΗΜΟΠΟΥΛΟΣ",
        teacher_afm="demo",
        teacher_email="teacher@example.gr",
        location=node.name,
        capacity=15,
        target_teaching_hours=40,
    )
    class_b = Classroom(
        node_id=node.id,
        name="Β",
        program_name=class_a.program_name,
        teacher_name="ΓΙΩΡΓΟΣ ΔΗΜΟΠΟΥΛΟΣ",
        teacher_afm="demo",
        teacher_email="teacher@example.gr",
        location=node.name,
        capacity=15,
        target_teaching_hours=40,
    )
    db.add_all([class_a, class_b]); db.flush()

    for idx, (name, ref) in enumerate(DEMO_STUDENTS, start=1):
        phone = f"+306900000{idx:03d}"
        student = Student(node_id=node.id, full_name=name, external_ref=ref, phone=phone, status="selected", priority_order=idx)
        db.add(student); db.flush()
        db.add(Enrollment(classroom_id=class_a.id, student_id=student.id, status="active"))

    for idx, (name, ref) in enumerate(STANDBY_STUDENTS, start=1):
        student = Student(node_id=node.id, full_name=name, external_ref=ref, phone=f"+306911111{idx:03d}", status="standby", priority_order=idx)
        db.add(student)

    db.commit()

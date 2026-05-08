"""SMTP email notification service."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


def send_email(to_email: str, subject: str, body_html: str, body_text: str = "") -> tuple[bool, str]:
    """Send an email via SMTP. Returns (ok, message)."""
    if not settings.smtp_username or not settings.smtp_password:
        return False, "SMTP_USERNAME / SMTP_PASSWORD not configured"
    if not to_email:
        return False, "No recipient email"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)

        server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, to_email, msg.as_string())
        server.quit()
        return True, "sent"
    except Exception as exc:
        return False, str(exc)


def send_attendance_link_email(to_email: str, student_name: str, lesson_date: str, link: str) -> tuple[bool, str]:
    """Convenience wrapper: send attendance confirmation link by email."""
    subject = f"Επιβεβαίωση Παρουσίας - {lesson_date}"
    body_html = f"""
    <html><body>
    <p>Αγαπητέ/ή <strong>{student_name}</strong>,</p>
    <p>Το μάθημα της <strong>{lesson_date}</strong> ξεκίνησε.</p>
    <p>Πατήστε τον παρακάτω σύνδεσμο για να επιβεβαιώσετε την παρουσία σας:</p>
    <p><a href="{link}" style="font-size:1.2em;padding:10px 20px;background:#1a73e8;color:#fff;border-radius:4px;text-decoration:none;">✅ Επιβεβαίωση Παρουσίας</a></p>
    <p><small>Ο σύνδεσμος λήγει μετά από μερικές ώρες.<br>
    Thronos EduPresence | Υπουργείο Οικογένειας</small></p>
    </body></html>
    """
    body_text = f"Επιβεβαίωση παρουσίας μαθήματος {lesson_date}: {link}"
    return send_email(to_email, subject, body_html, body_text)

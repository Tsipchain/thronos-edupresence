"""SMTP email notification service with QR code support."""
from __future__ import annotations

import smtplib
import io
import base64
import qrcode
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from app.config import settings


def generate_qr_code_base64(data: str) -> str:
    """Generate QR code and return as base64-encoded PNG."""
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return encoded


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


def send_attendance_link_email(to_email: str, student_name: str, lesson_date: str, link: str, include_qr: bool = False) -> tuple[bool, str]:
    """Send attendance confirmation link by email, optionally with embedded QR code."""
    subject = f"Επιβεβαίωση Παρουσίας - {lesson_date}"

    qr_html = ""
    if include_qr:
        qr_b64 = generate_qr_code_base64(link)
        qr_html = f'<p style="text-align:center;"><img src="data:image/png;base64,{qr_b64}" alt="QR Code" style="width:200px;height:200px;"></p>'

    body_html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
    <p>Αγαπητέ/ή <strong>{student_name}</strong>,</p>
    <p>Το μάθημα της <strong>{lesson_date}</strong> ξεκίνησε.</p>
    <p>Πατήστε τον παρακάτω σύνδεσμο ή σκανάρετε το QR code για να επιβεβαιώσετε την παρουσία σας:</p>
    {qr_html}
    <p><a href="{link}" style="font-size:1.2em;padding:10px 20px;background:#1a73e8;color:#fff;border-radius:4px;text-decoration:none;display:inline-block;">✅ Επιβεβαίωση Παρουσίας</a></p>
    <hr style="border:none;border-top:1px solid #ddd;margin:20px 0;">
    <p><small>Ο σύνδεσμος και το QR code λήγουν μετά από μερικές ώρες.<br>
    <strong>Thronos EduPresence</strong> | Υπουργείο Οικογένειας</small></p>
    </body></html>
    """
    body_text = f"Επιβεβαίωση παρουσίας μαθήματος {lesson_date}: {link}"
    return send_email(to_email, subject, body_html, body_text)


def send_class_roster_email(to_email: str, class_name: str, roster_html: str) -> tuple[bool, str]:
    """Send class roster report by email."""
    subject = f"Κατάλογος Τμήματος - {class_name}"
    body_html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
    <p>Αγαπητέ/ή χρήστη,</p>
    <p>Ακολουθεί ο κατάλογος του τμήματος <strong>{class_name}</strong>:</p>
    {roster_html}
    <hr style="border:none;border-top:1px solid #ddd;margin:20px 0;">
    <p><small><strong>Thronos EduPresence</strong> | Υπουργείο Οικογένειας</small></p>
    </body></html>
    """
    return send_email(to_email, subject, body_html)

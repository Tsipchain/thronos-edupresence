# Thronos EduPresence

> Σύστημα Ψηφιακής Διαχείρισης Παρουσιών Σεμιναρίων — Υπουργείο Οικογένειας

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com)

---

## Περιγραφή

Το **Thronos EduPresence** είναι web εφαρμογή για τη **διαχείριση παρουσιών** σε σεμινάρια συγχρηματοδοτούμενων προγραμμάτων (Ψηφιακή Ενδυνάμωση Τρίτης Ηλικίας, Κυβερνοασφάλεια κ.ά.). Διασφαλίζει **πλήρη διαφάνεια και ελεγξιμότητα** μέσω:

- **Διπλής επιβεβαίωσης παρουσίας**: QR code μαθητή + scan καθηγητή
- **Ατομικών συνδέσμων** αποστολής μέσω SMS/Viber σε κάθε εκπαιδευόμενο
- **Blockchain-style attestation** (Thronos Chain) για κάθε καταχώρηση παρουσίας
- **Διαχείρισης αναπληρώσεων** με αλυσίδα αποδεικτικών
- **Audit log** για κάθε ενέργεια χρήστη

---

## Αρχιτεκτονική

```
┌─────────────────────────────────────────────────────┐
│               Railway (thronosEDu.thronoschain.org)  │
│                                                     │
│  FastAPI (Python 3.12)  ←→  SQLite / PostgreSQL     │
│  Jinja2 Templates              /app/data/           │
│  uvicorn (ASGI)                                     │
│                                                     │
│  Notifications:  SMS (Twilio) | Viber Business API  │
│                  Email (SMTP)                       │
└─────────────────────────────────────────────────────┘
         ↑ REST API (CORS-enabled)
    Flutter Mobile App / Browser
```

### Κύριες Οντότητες

| Οντότητα | Περιγραφή |
|---|---|
| **Node** | Κόμβος / τοποθεσία υλοποίησης |
| **Classroom** | Τμήμα σεμιναρίου (καθηγητής, χωρητικότητα) |
| **Student** | Εκπαιδευόμενος (επιλεχθείς / επιλαχών) |
| **Enrollment** | Εγγραφή μαθητή σε τμήμα |
| **Lesson** | Διδακτική συνεδρία |
| **Attendance** | Εγγραφή παρουσίας ανά μαθητή/μάθημα |
| **Makeup** | Αναπλήρωση απουσίας |
| **Attestation** | Κρυπτογραφική αποτύπωση αποτελέσματος |

---

## Ροή Επιβεβαίωσης Παρουσίας

```
1. Καθηγητής ανοίγει μάθημα  →  Lesson status: "open"
2. Σύστημα δημιουργεί Attendance row ανά εγγεγραμμένο μαθητή
3. Καθηγητής πατά "Αποστολή Links" (SMS/Viber)
4. Κάθε μαθητής λαμβάνει προσωπικό σύνδεσμο (TTL: 8 ώρες)
5a. Μαθητής ανοίγει link → εμφανίζει QR code (TTL: 70 δευτ.)
5b. Καθηγητής σκανάρει QR → Attendance: "present" (διπλή επιβ.)
   ή
5c. Καθηγητής καταχωρεί χειροκίνητα (παρών/απών/καθυστ.)
6. Καθηγητής κλείνει μάθημα  →  Attestation hash γράφεται
7. Εκτύπωση Κατάστασης Παρουσιών (PDF-ready)
```

---

## Εγκατάσταση & Εκτέλεση

### Τοπικά (Development)

```bash
git clone https://github.com/tsipchain/thronos-edupresence.git
cd thronos-edupresence

cp .env.example .env
# Επεξεργαστείτε το .env με τις τιμές σας

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Πλοηγηθείτε στο: http://localhost:8000

### Docker

```bash
docker build -t thronos-edupresence .
docker run -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  thronos-edupresence
```

---

## Deploy στο Railway

### 1. Δημιουργία Project

1. Πηγαίνετε στο [railway.com](https://railway.com) → New Project → Deploy from GitHub
2. Συνδέστε το repository `tsipchain/thronos-edupresence`
3. Railway θα ανιχνεύσει αυτόματα το `Dockerfile`

### 2. Volume για Persistent Database

Στο Railway dashboard:
- **Add Volume** → Mount path: `/app/data`
- Αυτό διασφαλίζει ότι η βάση δεδομένων **δεν χάνεται** σε redeploy

### 3. Environment Variables

Στο Railway dashboard → **Variables**, προσθέστε:

#### Βασικά (ΑΠΑΡΑΙΤΗΤΑ)

| Variable | Τιμή |
|---|---|
| `PUBLIC_BASE_URL` | `https://thronosEDu.thronoschain.org` |
| `TOKEN_SECRET` | *(τυχαίο string 32+ χαρακτήρων)* |
| `ENVIRONMENT` | `production` |
| `AUTO_SEED_DEMO` | `false` |
| `DATABASE_URL` | `sqlite:////app/data/edupresence_v4.db` |
| `CORS_ORIGINS` | `https://thronosEDu.thronoschain.org` |

> Δημιουργήστε TOKEN_SECRET: `python -c "import secrets; print(secrets.token_hex(32))"`

#### Viber Business Messages

| Variable | Τιμή |
|---|---|
| `SMS_PROVIDER` | `viber` |
| `VIBER_BOT_TOKEN` | *(από το Viber Partners dashboard)* |
| `VIBER_SENDER_NAME` | `ThrEDuPresence` |

> Αποκτήστε Viber Bot Token: https://partners.viber.com → Create Bot Account

#### SMTP Email

| Variable | Τιμή |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USE_TLS` | `true` |
| `SMTP_USERNAME` | `your@gmail.com` |
| `SMTP_PASSWORD` | *(App Password από Google Account)* |
| `SMTP_FROM_EMAIL` | `noreply@thronoschain.org` |

#### Αυθεντικοποίηση

| Variable | Τιμή |
|---|---|
| `AUTH_REQUIRED` | `true` |
| `AUTH_PROVIDER` | `mock` (ή `gov` για TaxisNet) |

### 4. Custom Domain

Στο Railway dashboard → **Settings → Domains**:
- Add custom domain: `thronosEDu.thronoschain.org`
- Προσθέστε CNAME record στο DNS: `thronosEDu.thronoschain.org → <your-app>.up.railway.app`

### 5. Επαλήθευση

```bash
curl https://thronosEDu.thronoschain.org/health
# Αναμενόμενη απάντηση:
# {"ok": true, "service": "Thronos EduPresence", "environment": "production"}
```

---

## Flutter App — Σύνδεση με Production API

Στο Flutter app, ορίστε το base URL:

```dart
const String apiBaseUrl = 'https://thronosEDu.thronoschain.org';
```

**CORS**: Το API επιτρέπει cross-origin αιτήματα από τα origins που ορίζονται στο `CORS_ORIGINS`.

Κύρια API endpoints:

| Method | Endpoint | Περιγραφή |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/lessons/{id}/student-links` | Σύνδεσμοι παρουσίας |
| POST | `/api/lessons/{id}/scan` | Scan QR μαθητή |
| GET | `/s/{token}` | Επιβεβαίωση παρουσίας μαθητή |
| GET | `/s/{token}/qr.png` | QR image |

---

## Ασφάλεια

- Όλα τα tokens υπογράφονται με HMAC-SHA256 (`TOKEN_SECRET`)
- Τα QR codes λήγουν σε **70 δευτερόλεπτα** (anti-replay)
- Οι σύνδεσμοι μαθητών λήγουν σε **8 ώρες**
- Session cookies: `httponly`, `samesite=lax`, `secure` (σε production)
- Τα PII δεδομένων αποθηκεύονται **μόνο εντός** της ελεγχόμενης υποδομής
- Κάθε παρουσία καταγράφεται με αμετάβλητο attestation hash

---

## Δομή Project

```
thronos-edupresence/
├── app/
│   ├── main.py          # FastAPI routes & middleware
│   ├── config.py        # Pydantic settings (env vars)
│   ├── models.py        # SQLAlchemy ORM models
│   ├── db.py            # Database session
│   ├── security.py      # JWT signing, QR generation
│   ├── attestation.py   # Thronos Chain integration
│   ├── seed.py          # Demo data seeding
│   ├── sms.py           # SMS/notification dispatcher
│   ├── viber.py         # Viber Business Messages API
│   ├── email_service.py # SMTP email notifications
│   ├── templates/       # Jinja2 HTML templates
│   └── static/          # CSS, JS, assets
├── data/                # SQLite database (Railway Volume)
├── Dockerfile
├── railway.toml
├── requirements.txt
└── .env.example
```

---

## Τεχνολογίες

| Layer | Τεχνολογία |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Templates | Jinja2 |
| Notifications | Viber Business API, Twilio, SMTP |
| Containerization | Docker |
| Hosting | Railway |
| Security | HMAC-SHA256, QR codes, Attestation |

---

## Υπουργείο Οικογένειας — Πρόγραμμα Ψηφιακής Ενδυνάμωσης

Αναπτύχθηκε για την υποστήριξη συγχρηματοδοτούμενων προγραμμάτων εκπαίδευσης
Τρίτης Ηλικίας και Κυβερνοασφάλειας, με έμφαση στη διαφάνεια και την ελεγξιμότητα
παρουσιών σύμφωνα με τις απαιτήσεις του ΕΣΠΑ.

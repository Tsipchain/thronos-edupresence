# Γρήγορο πλάνο για δοκιμή αύριο

## Πριν το μάθημα

```bash
cd thronos-edupresence
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Στο `.env`, για δοκιμή χωρίς πραγματικό SMS:

```txt
SMS_PROVIDER=mock
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

Για δοκιμή με κινητό από ίδιο Wi‑Fi, βάλε IP laptop:

```txt
PUBLIC_BASE_URL=http://192.168.x.x:8000
```

και τρέξε:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Μέσα στο μάθημα

- Άνοιξε `http://127.0.0.1:8000` στο laptop.
- Πήγαινε στον κόμβο / τμήμα.
- Πάτα `+ Προσθήκη` για νέο μάθημα.
- Πάτα `Αποστολή SMS links σε όλους`.
- Σε mock mode, κάνε copy link από `SMS outbox` ή από `Links μαθητών για δοκιμή χωρίς SMS`.
- Άνοιξε link σε κινητό μαθητή.
- Ο μαθητής δείχνει QR.
- Πάτα `Άνοιγμα κάμερας / Scanner` και σκάναρε.
- Όποιος δεν έχει κινητό: `Χειροκίνητα` → `Παρών` → αιτιολογία.
- Τέλος: `Κλείδωμα & εκτύπωση`.

## Βασικός κανόνας

Δεν αλλάζουμε παλιό μάθημα. Για απουσία φτιάχνουμε αναπλήρωση ως νέο γεγονός.

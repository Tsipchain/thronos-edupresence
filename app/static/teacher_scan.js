let html5QrCode = null;
let scanning = false;

async function submitScanToken(lessonId, token) {
  const result = document.getElementById('scan-result');
  result.textContent = 'Σάρωση...';
  const resp = await fetch(`/api/lessons/${lessonId}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token })
  });
  const data = await resp.json();
  if (!resp.ok) {
    result.textContent = 'Σφάλμα: ' + (data.detail || JSON.stringify(data));
    return;
  }
  result.textContent = `OK: ${data.student_name} -> ${data.status}`;
  setTimeout(() => location.reload(), 700);
}

async function startScanner(lessonId) {
  if (scanning) return;
  if (!window.Html5Qrcode) {
    alert('Δεν φορτώθηκε ο scanner. Κάνε επικόλληση token χειροκίνητα.');
    return;
  }
  scanning = true;
  html5QrCode = new Html5Qrcode('reader');
  await html5QrCode.start(
    { facingMode: 'environment' },
    { fps: 10, qrbox: { width: 250, height: 250 } },
    async (decodedText) => {
      await submitScanToken(lessonId, decodedText);
      await stopScanner();
    },
    () => {}
  );
}

async function stopScanner() {
  if (html5QrCode && scanning) {
    try { await html5QrCode.stop(); } catch (e) {}
    scanning = false;
  }
}

function manualScan(event, lessonId) {
  event.preventDefault();
  const input = document.getElementById('scan-token');
  const token = input.value.trim();
  if (!token) return;
  submitScanToken(lessonId, token);
}

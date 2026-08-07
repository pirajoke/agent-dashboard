const officeFrame = document.querySelector('#officeFrame');
const officeFallback = document.querySelector('#officeFallback');
const connection = document.querySelector('#connection');
const connectionText = document.querySelector('#connectionText');

let settled = false;

function showReady() {
  if (settled) return;
  settled = true;
  connection.classList.add('is-ready');
  connectionText.textContent = 'Офис подключён';
}

function showFallback() {
  if (settled) return;
  settled = true;
  connection.classList.add('is-offline');
  connectionText.textContent = 'Открыть отдельно';
  officeFallback.hidden = false;
}

officeFrame.addEventListener('load', showReady, { once: true });
officeFrame.addEventListener('error', showFallback, { once: true });

window.setTimeout(showFallback, 8000);

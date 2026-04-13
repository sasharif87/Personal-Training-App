/* frontend/src/components/toast.js */

let container = null;

function getContainer() {
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  return container;
}

export function toast(message, type = 'info', duration = 3500) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;

  const c = getContainer();
  c.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-visible'));

  setTimeout(() => {
    el.classList.remove('toast-visible');
    setTimeout(() => el.remove(), 300);
  }, duration);
}

export const showSuccess = (msg) => toast(msg, 'success');
export const showError   = (msg) => toast(msg, 'error', 5000);
export const showInfo    = (msg) => toast(msg, 'info');

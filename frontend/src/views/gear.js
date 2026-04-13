/* frontend/src/views/gear.js */
import { api } from '../api/client.js';
import { showSuccess, showError } from '../components/toast.js';

const GEAR_ICONS = {
  bike:      '🚴', running_shoes: '👟', wetsuit: '🏊', helmet: '⛑️',
  wheels:    '⚙️', pedals: '🔩', swimskin: '🏊', watch: '⌚',
  other:     '🔧',
};

const GEAR_TYPES = [
  'bike', 'running_shoes', 'wetsuit', 'helmet', 'wheels',
  'pedals', 'swimskin', 'watch', 'other',
];

function usageBar(used, max) {
  if (!max) return '';
  const pct  = Math.min(100, Math.round((used / max) * 100));
  const cls  = pct >= 90 ? 'danger' : pct >= 70 ? 'warn' : '';
  return `
    <div class="usage-bar">
      <div class="usage-fill ${cls}" style="width:${pct}%"></div>
    </div>
    <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px">${used?.toLocaleString() ?? 0} / ${max?.toLocaleString()} km (${pct}%)</div>`;
}

function gearItem(item) {
  const used    = item.distance_km ?? 0;
  const maxKm   = item.max_distance_km ?? null;
  const icon    = GEAR_ICONS[item.equipment_type] ?? GEAR_ICONS.other;
  const retired = !item.active;
  return `
    <div class="gear-item" style="${retired ? 'opacity:0.4' : ''}">
      <div class="gear-icon">${icon}</div>
      <div class="gear-info">
        <div class="gear-name">${item.name ?? item.item_id}</div>
        <div class="gear-meta">${item.equipment_type ?? ''} ${item.brand ? '· ' + item.brand : ''} ${retired ? '· <em>retired</em>' : ''}</div>
        ${maxKm ? usageBar(used, maxKm) : `<div style="font-size:0.72rem;color:var(--text-muted)">${used?.toLocaleString() ?? 0} km logged</div>`}
      </div>
      <div style="flex-shrink:0">
        ${maxKm && (used / maxKm) >= 0.9 ? `<span class="badge badge-error">Replace soon</span>` : ''}
      </div>
    </div>`;
}

function alertItem(alert) {
  return `
    <div class="list-item">
      <div class="list-item-main">
        <span class="badge badge-warning">${alert.equipment_type ?? 'gear'}</span>
        <span class="list-item-title">${alert.item_name ?? alert.item_id}</span>
      </div>
      <span class="list-item-meta">${alert.message ?? ''}</span>
    </div>`;
}

export async function render() {
  const data = await api.getGear().catch(() => ({ equipment: [], alerts: [] }));
  const equipment = data.equipment ?? [];
  const alerts    = data.alerts    ?? [];

  const activeGear  = equipment.filter(e => e.active !== false);
  const retiredGear = equipment.filter(e => e.active === false);

  return `
    <header class="view-header fade-in">
      <div>
        <h2>Gear Tracker</h2>
        <p>${activeGear.length} active items${alerts.length > 0 ? ` · ${alerts.length} alert${alerts.length > 1 ? 's' : ''}` : ''}</p>
      </div>
      <button class="btn btn-secondary" id="add-gear-btn">+ Add Item</button>
    </header>

    ${alerts.length > 0 ? `
      <div class="card fade-in" style="border-color:var(--warning)">
        <h3>⚠ Maintenance Alerts</h3>
        ${alerts.map(alertItem).join('')}
      </div>` : ''}

    <div class="card fade-in">
      <h3>Active Equipment</h3>
      ${activeGear.length === 0
        ? `<div class="empty-state"><div class="empty-icon">🚲</div><p>No equipment added yet.</p></div>`
        : activeGear.map(gearItem).join('')}
    </div>

    ${retiredGear.length > 0 ? `
      <div class="card fade-in">
        <h3>Retired Equipment</h3>
        ${retiredGear.map(gearItem).join('')}
      </div>` : ''}

    <!-- Add gear modal -->
    <div id="add-gear-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);z-index:100;align-items:center;justify-content:center">
      <div class="card" style="width:480px;max-width:95vw;max-height:90vh;overflow-y:auto">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-lg)">
          <h3 style="font-size:1rem;text-transform:none;color:var(--text-main)">Add Equipment</h3>
          <button class="btn btn-secondary" id="close-gear-modal" style="padding:6px 12px">✕</button>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Type</label>
            <select class="form-select" id="gear-type">
              ${GEAR_TYPES.map(t => `<option value="${t}">${GEAR_ICONS[t] ?? ''} ${t.replace('_', ' ')}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Name</label>
            <input class="form-input" id="gear-name" type="text" placeholder="e.g. Canyon CF SLX, Asics Nimbus">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Brand (optional)</label>
            <input class="form-input" id="gear-brand" type="text" placeholder="e.g. Shimano, Garmin">
          </div>
          <div class="form-group">
            <label class="form-label">Purchase Date</label>
            <input class="form-input" id="gear-purchase-date" type="date" value="${new Date().toISOString().slice(0,10)}">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Current Distance (km)</label>
            <input class="form-input" id="gear-distance" type="number" min="0" placeholder="0">
            <p class="form-hint">km already on this item at purchase</p>
          </div>
          <div class="form-group">
            <label class="form-label">Max Distance (km)</label>
            <input class="form-input" id="gear-max-distance" type="number" min="0" placeholder="e.g. 1500">
            <p class="form-hint">Leave blank to skip usage alerts</p>
          </div>
        </div>

        <button class="btn btn-primary" id="save-gear-btn" style="width:100%;justify-content:center;margin-top:8px">
          Save Equipment
        </button>
      </div>
    </div>
  `;
}

export function mount(container) {
  const modal    = container.querySelector('#add-gear-modal');
  const addBtn   = container.querySelector('#add-gear-btn');
  const closeBtn = container.querySelector('#close-gear-modal');
  const saveBtn  = container.querySelector('#save-gear-btn');

  addBtn?.addEventListener('click',  () => { modal.style.display = 'flex'; });
  closeBtn?.addEventListener('click', () => { modal.style.display = 'none'; });
  modal?.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

  saveBtn?.addEventListener('click', async () => {
    const name = container.querySelector('#gear-name').value.trim();
    if (!name) { showError('Please enter a name for this item.'); return; }

    const maxKm   = parseFloat(container.querySelector('#gear-max-distance').value) || null;
    const distKm  = parseFloat(container.querySelector('#gear-distance').value) || 0;

    const payload = {
      equipment_type:   container.querySelector('#gear-type').value,
      name,
      brand:            container.querySelector('#gear-brand').value.trim() || null,
      purchase_date:    container.querySelector('#gear-purchase-date').value,
      distance_km:      distKm,
      max_distance_km:  maxKm,
      active:           true,
      athlete_id:       'default',
    };

    saveBtn.textContent = 'Saving…';
    saveBtn.disabled = true;
    try {
      await api.saveGear(payload);
      showSuccess(`${name} added`);
      modal.style.display = 'none';
      // Reload the view by triggering a re-render via the router
      document.querySelector('[data-view="gear"]')?.click();
    } catch (err) {
      showError('Failed to save gear: ' + err.message);
    } finally {
      saveBtn.textContent = 'Save Equipment';
      saveBtn.disabled = false;
    }
  });
}

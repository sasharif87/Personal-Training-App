/* frontend/src/views/config.js */
import { api } from '../api/client.js';
import { showSuccess, showError, showInfo } from '../components/toast.js';

const BLOCK_PHASES = ['Base', 'Build', 'Peak', 'Taper', 'Recovery', 'Off-Season'];
const RACE_FORMATS = ['Ironman', '70.3', 'Olympic', 'Sprint', 'Marathon', 'Half Marathon', '10K', '5K', 'Other'];
const PRIORITIES   = ['A', 'B', 'C'];

function raceSection(key, label, race) {
  race = race ?? {};
  return `
    <div class="card" style="margin-top:0">
      <div class="form-section-title">${label}</div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Race Date</label>
          <input class="form-input" type="date" id="${key}-date" value="${race.date ?? ''}">
        </div>
        <div class="form-group">
          <label class="form-label">Format</label>
          <select class="form-select" id="${key}-format">
            <option value="">— Select —</option>
            ${RACE_FORMATS.map(f => `<option value="${f}"${race.format === f ? ' selected' : ''}>${f}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Priority</label>
          <select class="form-select" id="${key}-priority">
            ${PRIORITIES.map(p => `<option value="${p}"${(race.priority ?? 'C') === p ? ' selected' : ''}>${p === 'A' ? '🔴 A — Peak event' : p === 'B' ? '🟡 B — Important' : '🟢 C — Training race'}</option>`).join('')}
          </select>
        </div>
      </div>
    </div>`;
}

export async function render() {
  const [config] = await Promise.all([
    api.getConfig().catch(() => ({})),
  ]);

  const athlete = config.athlete ?? {};
  const block   = config.block   ?? {};
  const raceA   = config.race_a  ?? {};
  const raceB   = config.race_b  ?? {};

  return `
    <header class="view-header fade-in">
      <div>
        <h2>Settings</h2>
        <p>Athlete profile, training block and race configuration</p>
      </div>
      <div style="display:flex;gap:var(--space-sm)">
        <button class="btn btn-primary" id="save-all-btn">Save All</button>
      </div>
    </header>

    <!-- Thresholds -->
    <div class="card fade-in">
      <div class="form-section-title">Physiological Thresholds</div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Cycling FTP (W)</label>
          <input class="form-input" type="number" id="athlete-ftp" min="50" max="600" value="${athlete.ftp ?? ''}">
          <p class="form-hint">Functional Threshold Power — 60-min sustainable watts</p>
        </div>
        <div class="form-group">
          <label class="form-label">Run LTHR (BPM)</label>
          <input class="form-input" type="number" id="athlete-lthr" min="80" max="220" value="${athlete.lthr_run ?? ''}">
          <p class="form-hint">Lactate Threshold Heart Rate for running</p>
        </div>
        <div class="form-group">
          <label class="form-label">Critical Swim Speed (CSS)</label>
          <input class="form-input" type="text" id="athlete-css" placeholder="e.g. 1:28/100m" value="${athlete.css ?? ''}">
          <p class="form-hint">Pace per 100m at aerobic threshold</p>
        </div>
      </div>
    </div>

    <!-- Training block -->
    <div class="card fade-in">
      <div class="form-section-title">Training Block</div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Current Phase</label>
          <select class="form-select" id="block-phase">
            <option value="">— Select —</option>
            ${BLOCK_PHASES.map(p => `<option value="${p}"${block.phase === p ? ' selected' : ''}>${p}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Week in Block</label>
          <input class="form-input" type="number" id="block-week" min="1" max="52" value="${block.week_in_block ?? 1}">
          <p class="form-hint">Which week of the current mesocycle</p>
        </div>
      </div>
    </div>

    <!-- Races -->
    <div class="grid-half fade-in">
      ${raceSection('race-a', '🔴 A-Race — Primary Goal Event', raceA)}
      ${raceSection('race-b', '🟡 B-Race — Secondary Event', raceB)}
    </div>

    <!-- Notes -->
    <div class="card fade-in">
      <div class="form-section-title">Coaching Notes</div>
      <div class="form-group">
        <textarea class="form-textarea" id="config-notes" style="min-height:100px"
          placeholder="Any special considerations: injuries, travel, life stress…">${config.notes ?? ''}</textarea>
      </div>
    </div>

    <!-- API key management -->
    <div class="card fade-in">
      <div class="form-section-title">API Access</div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Stored API Key</label>
          <div style="display:flex;gap:var(--space-sm)">
            <input class="form-input" type="password" id="api-key-display"
              value="${localStorage.getItem('coaching_api_key') ?? ''}" style="flex:1">
            <button class="btn btn-secondary" id="clear-api-key-btn">Clear</button>
          </div>
          <p class="form-hint">Matches CONFIG_API_KEY set in your .env file</p>
        </div>
      </div>
    </div>
  `;
}

export function mount(container) {
  // ── Save all ──────────────────────────────────────────────────────────────
  container.querySelector('#save-all-btn')?.addEventListener('click', async () => {
    const btn = container.querySelector('#save-all-btn');
    btn.textContent = 'Saving…';
    btn.disabled = true;

    const ftp   = parseInt(container.querySelector('#athlete-ftp').value)  || null;
    const lthr  = parseInt(container.querySelector('#athlete-lthr').value) || null;
    const css   = container.querySelector('#athlete-css').value.trim()     || null;
    const phase = container.querySelector('#block-phase').value            || null;
    const week  = parseInt(container.querySelector('#block-week').value)   || 1;
    const notes = container.querySelector('#config-notes').value.trim()    || null;

    function racePayload(key) {
      const date     = container.querySelector(`#${key}-date`).value     || null;
      const format   = container.querySelector(`#${key}-format`).value   || null;
      const priority = container.querySelector(`#${key}-priority`).value || 'C';
      return date || format ? { date, format, priority } : null;
    }

    const payload = {
      athlete: { ftp, css, lthr_run: lthr },
      block:   { phase, week_in_block: week },
      notes,
    };
    const ra = racePayload('race-a');
    const rb = racePayload('race-b');
    if (ra) payload.race_a = ra;
    if (rb) payload.race_b = rb;

    try {
      await api.saveConfig(payload);
      showSuccess('Settings saved');
    } catch (err) {
      showError('Save failed: ' + err.message);
    } finally {
      btn.textContent = 'Save All';
      btn.disabled = false;
    }
  });

  // ── API key management ────────────────────────────────────────────────────
  const keyInput = container.querySelector('#api-key-display');
  const clearBtn = container.querySelector('#clear-api-key-btn');

  keyInput?.addEventListener('change', () => {
    const val = keyInput.value.trim();
    if (val) {
      localStorage.setItem('coaching_api_key', val);
      showSuccess('API key updated');
    }
  });

  clearBtn?.addEventListener('click', () => {
    localStorage.removeItem('coaching_api_key');
    if (keyInput) keyInput.value = '';
    showInfo('API key cleared — you will be prompted on next request');
  });
}

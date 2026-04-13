/* frontend/src/views/health.js */
import { api } from '../api/client.js';
import { showSuccess, showError } from '../components/toast.js';

const today = () => new Date().toISOString().slice(0, 10);
const SPORTS = ['Swim', 'Bike', 'Run', 'Strength', 'Rest'];

function rpeScale() {
  return `
    <div style="display:flex;gap:4px;flex-wrap:wrap">
      ${Array.from({ length: 10 }, (_, i) => i + 1).map(n => `
        <label style="cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:2px">
          <input type="radio" name="rpe" value="${n}" style="display:none">
          <span class="rpe-btn" data-val="${n}"
            style="width:32px;height:32px;border-radius:6px;display:flex;align-items:center;justify-content:center;
                   font-weight:700;font-size:0.85rem;border:1px solid var(--border);background:var(--bg-surface);
                   cursor:pointer;transition:all 0.15s;color:var(--text-dim)">
            ${n}
          </span>
        </label>`).join('')}
    </div>
    <p class="form-hint">1 = Very easy &nbsp;·&nbsp; 5 = Moderate &nbsp;·&nbsp; 10 = Maximal effort</p>`;
}

function feelScale(name, label) {
  return `
    <div class="form-group">
      <label class="form-label">${label}</label>
      <div style="display:flex;gap:6px">
        ${[1,2,3,4,5].map(n => `
          <label style="cursor:pointer">
            <input type="radio" name="${name}" value="${n}" style="display:none">
            <span class="feel-btn" data-name="${name}" data-val="${n}"
              style="display:inline-block;width:36px;height:36px;border-radius:8px;text-align:center;line-height:36px;
                     border:1px solid var(--border);background:var(--bg-surface);cursor:pointer;
                     font-size:0.85rem;font-weight:600;color:var(--text-dim);transition:all 0.15s">
              ${n}
            </span>
          </label>`).join('')}
      </div>
      <p class="form-hint">1 = Terrible &nbsp;·&nbsp; 5 = Great</p>
    </div>`;
}

export async function render() {
  return `
    <header class="view-header fade-in">
      <div>
        <h2>Health &amp; Wellness</h2>
        <p>Post-session log and health data entry</p>
      </div>
    </header>

    <div class="tab-bar fade-in" id="health-tabs">
      <button class="tab-btn active" data-tab="post-session">Post-Session Log</button>
      <button class="tab-btn" data-tab="health-data">Health Data</button>
    </div>

    <!-- Post-session log -->
    <div id="tab-post-session" class="fade-in">
      <div class="card">
        <div class="form-section-title">Session Details</div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Date</label>
            <input class="form-input" type="date" id="session-date" value="${today()}">
          </div>
          <div class="form-group">
            <label class="form-label">Sport</label>
            <select class="form-select" id="session-sport">
              ${SPORTS.map(s => `<option value="${s}">${s}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="form-section" style="margin-top:var(--space-lg)">
          <div class="form-section-title">Perceived Effort (RPE)</div>
          <div id="rpe-container">${rpeScale()}</div>
          <input type="hidden" id="rpe-value" value="">
        </div>

        <div class="form-row" style="margin-top:var(--space-lg)">
          ${feelScale('leg-feel', 'Leg Feel')}
          ${feelScale('motivation', 'Motivation')}
        </div>

        <div class="form-group" style="margin-top:var(--space-md)">
          <label class="form-label">Notes (pain, sensations, anomalies)</label>
          <textarea class="form-textarea" id="session-notes" placeholder="e.g. Left knee ached on hills, felt great in the water…"></textarea>
        </div>

        <div style="margin-top:var(--space-lg)">
          <button class="btn btn-primary" id="log-session-btn">Log Session</button>
        </div>
      </div>
    </div>

    <!-- Health data -->
    <div id="tab-health-data" style="display:none" class="fade-in">
      <div class="card">
        <div class="form-section-title">Quick Health Entry</div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Date</label>
            <input class="form-input" type="date" id="health-date" value="${today()}">
          </div>
          <div class="form-group">
            <label class="form-label">Data Type</label>
            <select class="form-select" id="health-type">
              <option value="medication">Medication</option>
              <option value="menstrual_cycle">Menstrual Cycle</option>
              <option value="supplement">Supplement</option>
              <option value="illness">Illness / Injury</option>
              <option value="nutrition">Nutrition note</option>
            </select>
          </div>
        </div>

        <div class="form-group" style="margin-top:var(--space-md)">
          <label class="form-label">Details</label>
          <textarea class="form-textarea" id="health-details"
            placeholder="e.g. 200mg ibuprofen post-race, day 1 of cycle, iron supplement, stomach virus…"></textarea>
        </div>

        <div class="form-group">
          <label class="form-label">Severity / Dose (optional)</label>
          <input class="form-input" type="text" id="health-severity" placeholder="e.g. Mild, 500mg, Day 2">
        </div>

        <div style="margin-top:var(--space-lg)">
          <button class="btn btn-primary" id="log-health-btn">Log Entry</button>
        </div>
      </div>
    </div>
  `;
}

export function mount(container) {
  // ── Tab switching ─────────────────────────────────────────────────────────
  container.querySelectorAll('#health-tabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('#health-tabs .tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.tab;
      container.querySelector('#tab-post-session').style.display = tab === 'post-session' ? '' : 'none';
      container.querySelector('#tab-health-data').style.display  = tab === 'health-data'  ? '' : 'none';
    });
  });

  // ── RPE selection ─────────────────────────────────────────────────────────
  const rpeHidden = container.querySelector('#rpe-value');
  container.querySelectorAll('.rpe-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.rpe-btn').forEach(b => {
        b.style.background = 'var(--bg-surface)';
        b.style.color = 'var(--text-dim)';
        b.style.borderColor = 'var(--border)';
      });
      btn.style.background = 'var(--accent-primary)';
      btn.style.color = '#fff';
      btn.style.borderColor = 'var(--accent-primary)';
      rpeHidden.value = btn.dataset.val;
    });
  });

  // ── Feel scale selection ──────────────────────────────────────────────────
  container.querySelectorAll('.feel-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.name;
      container.querySelectorAll(`.feel-btn[data-name="${name}"]`).forEach(b => {
        b.style.background = 'var(--bg-surface)';
        b.style.color = 'var(--text-dim)';
        b.style.borderColor = 'var(--border)';
      });
      btn.style.background = 'var(--accent-secondary)';
      btn.style.color = '#fff';
      btn.style.borderColor = 'var(--accent-secondary)';
    });
  });

  // ── Post-session submit ───────────────────────────────────────────────────
  container.querySelector('#log-session-btn')?.addEventListener('click', async () => {
    const rpe = parseInt(container.querySelector('#rpe-value').value);
    if (!rpe) { showError('Please select an RPE value.'); return; }

    const legFeel   = parseInt(container.querySelector('input[name="leg-feel"]:checked')?.value ?? 0) || null;
    const motivation = parseInt(container.querySelector('input[name="motivation"]:checked')?.value ?? 0) || null;

    const payload = {
      session_date: container.querySelector('#session-date').value,
      sport:        container.querySelector('#session-sport').value,
      rpe,
      leg_feel:     legFeel,
      motivation,
      notes:        container.querySelector('#session-notes').value.trim(),
      pain_entries: [],
    };

    const btn = container.querySelector('#log-session-btn');
    btn.textContent = 'Saving…';
    btn.disabled = true;
    try {
      await api.postSessionLog(payload);
      showSuccess('Session logged');
      // Reset form
      container.querySelector('#session-notes').value = '';
      container.querySelector('#rpe-value').value = '';
      container.querySelectorAll('.rpe-btn').forEach(b => {
        b.style.background = 'var(--bg-surface)';
        b.style.color = 'var(--text-dim)';
        b.style.borderColor = 'var(--border)';
      });
      container.querySelectorAll('.feel-btn').forEach(b => {
        b.style.background = 'var(--bg-surface)';
        b.style.color = 'var(--text-dim)';
        b.style.borderColor = 'var(--border)';
      });
    } catch (err) {
      showError('Failed to log session: ' + err.message);
    } finally {
      btn.textContent = 'Log Session';
      btn.disabled = false;
    }
  });

  // ── Health data submit ────────────────────────────────────────────────────
  container.querySelector('#log-health-btn')?.addEventListener('click', async () => {
    const details = container.querySelector('#health-details').value.trim();
    if (!details) { showError('Please enter health details.'); return; }

    const dateVal  = container.querySelector('#health-date').value;         // YYYY-MM-DD
    const typeVal  = container.querySelector('#health-type').value;
    const severity = container.querySelector('#health-severity').value.trim() || '';
    // HealthDataPost requires a timestamp; build ISO string from the selected date
    const timestamp = new Date(dateVal + 'T12:00:00').toISOString();

    // Build type-specific structured payload that satisfies HealthDataPost
    const payload = { athlete_id: 'default', timestamp };

    if (typeVal === 'medication') {
      payload.medication_entries = [{
        medication_name: details,
        taken: true,
        dose: severity,
        timestamp,
        notes: '',
      }];
    } else if (typeVal === 'menstrual_cycle') {
      payload.cycle_data = {
        phase: 'unknown',
        source_app: 'manual',
        timestamp,
      };
    } else if (typeVal === 'supplement') {
      payload.supplemental_metrics = [{
        metric_name: 'supplement',
        value: 1,
        unit: severity || 'dose',
        timestamp,
        source: details,
      }];
    } else {
      // illness / nutrition / other — embed as a supplemental free-text note
      payload.supplemental_metrics = [{
        metric_name: typeVal,
        value: 1,
        unit: severity || 'note',
        timestamp,
        source: details,
      }];
    }

    const btn = container.querySelector('#log-health-btn');
    btn.textContent = 'Saving…';
    btn.disabled = true;
    try {
      await api.postHealthData(payload);
      showSuccess('Health entry logged');
      container.querySelector('#health-details').value = '';
      container.querySelector('#health-severity').value = '';
    } catch (err) {
      showError('Failed to log health data: ' + err.message);
    } finally {
      btn.textContent = 'Log Entry';
      btn.disabled = false;
    }
  });
}

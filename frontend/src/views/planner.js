/* frontend/src/views/planner.js */
import { api } from '../api/client.js';
import { tssBarChart } from '../components/chart.js';
import { showSuccess, showError } from '../components/toast.js';

const PHASE_COLORS = {
  Base: 'badge-info', Build: 'badge-warning',
  Peak: 'badge-error', Taper: 'badge-success', Recovery: 'badge-success',
};

const PRIORITY_LABELS = { A: '🔴 A-Race', B: '🟡 B-Race', C: '🟢 C-Race' };

function weeksLabel(n) {
  if (n == null) return '';
  if (n === 0)   return 'Race week!';
  return `${n} week${n === 1 ? '' : 's'} out`;
}

export async function render() {
  const season = await api.getSeason().catch(() => null);
  const phase  = season?.current_phase ?? {};
  const arc    = season?.tss_arc ?? [];

  // Calculate phase summary from arc
  const phaseSummary = arc.reduce((acc, w) => {
    acc[w.phase] = (acc[w.phase] ?? 0) + 1;
    return acc;
  }, {});

  return `
    <header class="view-header fade-in">
      <div>
        <h2>Season Planner</h2>
        <p>${phase.phase ? `${phase.phase} phase · ` : ''}${arc.length} weeks mapped</p>
      </div>
      <button class="btn btn-secondary" id="add-race-btn">+ Add Race via URL</button>
    </header>

    <!-- Phase overview cards -->
    <section class="grid-thirds fade-in">
      <div class="card">
        <h3>Current Phase</h3>
        <div class="value" style="font-size:1.6rem;margin-top:8px">${phase.phase ?? '—'}</div>
        ${phase.a_race_name ? `<div class="trend stable" style="margin-top:6px">${phase.a_race_name}</div>` : ''}
      </div>
      <div class="card">
        <h3>A-Race Countdown</h3>
        <div class="race-countdown" style="margin-top:8px">
          <span class="value" style="font-size:1.8rem">${phase.weeks_to_a_race ?? '—'}</span>
          <span class="unit">${phase.weeks_to_a_race != null ? 'weeks' : 'no A-race set'}</span>
        </div>
        ${phase.a_race_date ? `<div class="race-target-date" style="margin-top:6px">${phase.a_race_date}</div>` : ''}
      </div>
      <div class="card">
        <h3>Phase Breakdown</h3>
        <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">
          ${Object.entries(phaseSummary).map(([p, n]) =>
            `<div style="display:flex;justify-content:space-between;font-size:0.85rem">
              <span class="badge ${PHASE_COLORS[p] ?? 'badge-info'}">${p}</span>
              <span style="color:var(--text-dim)">${n} week${n !== 1 ? 's' : ''}</span>
            </div>`).join('')}
          ${Object.keys(phaseSummary).length === 0 ? '<span style="color:var(--text-dim)">No races configured</span>' : ''}
        </div>
      </div>
    </section>

    <!-- Full TSS arc chart -->
    <div class="card fade-in">
      <h3>TSS Arc — 12 Weeks</h3>
      <div style="margin-top:16px">${tssBarChart(arc, { height: 200 })}</div>
      <div class="chart-legend">
        <span class="legend-dot" style="background:#4f7cff"></span>Base
        <span class="legend-dot" style="background:#f5a623"></span>Build
        <span class="legend-dot" style="background:#ff4f9a"></span>Peak
        <span class="legend-dot" style="background:#3dd68c"></span>Taper
        <span class="legend-dot" style="background:#7b7f9e"></span>Recovery
        <span style="margin-left:auto;color:var(--text-muted)">Faded = recovery week</span>
      </div>
    </div>

    <!-- Weekly arc table -->
    ${arc.length > 0 ? `
      <div class="card fade-in">
        <h3>Upcoming Weeks</h3>
        <div style="overflow-x:auto;margin-top:12px">
          <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
            <thead>
              <tr style="color:var(--text-dim);text-align:left">
                <th style="padding:8px 12px;border-bottom:1px solid var(--border)">Week</th>
                <th style="padding:8px 12px;border-bottom:1px solid var(--border)">Dates</th>
                <th style="padding:8px 12px;border-bottom:1px solid var(--border)">Phase</th>
                <th style="padding:8px 12px;border-bottom:1px solid var(--border);text-align:right">Target TSS</th>
                <th style="padding:8px 12px;border-bottom:1px solid var(--border)">Type</th>
              </tr>
            </thead>
            <tbody>
              ${arc.slice(0, 12).map(w => `
                <tr style="transition:background 0.15s" onmouseover="this.style.background='var(--bg-glass-bright)'" onmouseout="this.style.background=''">
                  <td style="padding:8px 12px;font-weight:600">W${w.week}</td>
                  <td style="padding:8px 12px;color:var(--text-dim)">${w.start_date}</td>
                  <td style="padding:8px 12px"><span class="badge ${PHASE_COLORS[w.phase] ?? 'badge-info'}">${w.phase}</span></td>
                  <td style="padding:8px 12px;text-align:right;font-weight:700">${w.target_tss}</td>
                  <td style="padding:8px 12px;color:var(--text-dim)">${w.is_recovery_week ? 'Recovery' : 'Load'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>` : ''}

    <!-- Add race modal (hidden by default) -->
    <div id="add-race-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);z-index:100;align-items:center;justify-content:center">
      <div class="card" style="width:480px;max-width:95vw;max-height:90vh;overflow-y:auto">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-lg)">
          <h3 style="font-size:1rem;text-transform:none;color:var(--text-main)">Add Race from URL</h3>
          <button class="btn btn-secondary" id="close-race-modal" style="padding:6px 12px">✕</button>
        </div>
        <div class="form-group">
          <label class="form-label">Race URL</label>
          <input class="form-input" id="race-url-input" type="url" placeholder="https://www.ironman.com/...">
          <p class="form-hint">Paste any race registration or event page URL. The LLM will extract the details.</p>
        </div>
        <div class="form-group">
          <label class="form-label">Priority</label>
          <select class="form-select" id="race-priority-select">
            <option value="A">🔴 A — Peak event, full taper</option>
            <option value="B">🟡 B — Important, partial taper</option>
            <option value="C" selected>🟢 C — Training race, no taper</option>
          </select>
        </div>
        <button class="btn btn-primary" id="extract-race-btn" style="width:100%;justify-content:center;margin-top:8px">
          Extract &amp; Add
        </button>
        <div id="race-extract-result" style="margin-top:16px"></div>
      </div>
    </div>
  `;
}

export function mount(container) {
  // Add race modal
  const addBtn   = container.querySelector('#add-race-btn');
  const modal    = container.querySelector('#add-race-modal');
  const closeBtn = container.querySelector('#close-race-modal');
  const extractBtn = container.querySelector('#extract-race-btn');

  if (addBtn) {
    addBtn.addEventListener('click', () => {
      modal.style.display = 'flex';
    });
  }
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      modal.style.display = 'none';
    });
  }
  modal?.addEventListener('click', (e) => {
    if (e.target === modal) modal.style.display = 'none';
  });

  if (extractBtn) {
    extractBtn.addEventListener('click', async () => {
      const url      = container.querySelector('#race-url-input').value.trim();
      const priority = container.querySelector('#race-priority-select').value;
      const result   = container.querySelector('#race-extract-result');

      if (!url) { showError('Please enter a URL.'); return; }

      extractBtn.textContent = 'Extracting…';
      extractBtn.disabled = true;
      result.innerHTML = '';

      try {
        const data = await api.extractEvent(url, priority);
        const ev = data.event ?? {};
        result.innerHTML = `
          <div class="card" style="background:var(--bg-glass-bright);border-color:var(--success)">
            <div style="font-weight:700;color:var(--success);margin-bottom:8px">✓ Event extracted</div>
            <div style="font-size:0.9rem;display:grid;gap:4px">
              ${ev.name   ? `<div><span style="color:var(--text-dim)">Name:</span> ${ev.name}</div>` : ''}
              ${ev.date   ? `<div><span style="color:var(--text-dim)">Date:</span> ${ev.date}</div>` : ''}
              ${ev.format ? `<div><span style="color:var(--text-dim)">Format:</span> ${ev.format}</div>` : ''}
              ${ev.location ? `<div><span style="color:var(--text-dim)">Location:</span> ${ev.location}</div>` : ''}
            </div>
          </div>`;
        showSuccess(`Added: ${ev.name ?? 'event'}`);
        modal.style.display = 'none';
      } catch (err) {
        result.innerHTML = `<div class="badge badge-error">Failed: ${err.message}</div>`;
        showError('Event extraction failed.');
      } finally {
        extractBtn.textContent = 'Extract & Add';
        extractBtn.disabled = false;
      }
    });
  }
}

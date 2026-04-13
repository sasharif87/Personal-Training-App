/* frontend/src/views/dashboard.js */
import { api } from '../api/client.js';
import { tssBarChart } from '../components/chart.js';

const PHASE_BADGE = {
  Base: 'badge-info', Build: 'badge-warning',
  Peak: 'badge-error', Taper: 'badge-success', Recovery: 'badge-success',
};

function healthBadge(status) {
  const cls = status === 'healthy' ? 'badge-success'
    : (status === 'model_missing' || status === 'no_tokens' || status === 'stale') ? 'badge-warning'
    : 'badge-error';
  return `<span class="badge ${cls}">${status}</span>`;
}

function tsbTrend(tsb) {
  if (tsb == null) return '';
  if (tsb > 15)  return '<div class="trend up">Peak form</div>';
  if (tsb > 5)   return '<div class="trend up">Fresh</div>';
  if (tsb < -25) return '<div class="trend down">High fatigue</div>';
  if (tsb < 0)   return '<div class="trend stable">Building</div>';
  return '<div class="trend stable">Balanced</div>';
}

function loadingCards() {
  return `<section class="grid-dashboard fade-in">
    ${Array(4).fill('<div class="card metric-card"><div class="skeleton" style="height:24px;width:60%;margin-bottom:12px"></div><div class="skeleton" style="height:48px;width:40%"></div></div>').join('')}
  </section>`;
}

export async function render() {
  // Fire all three in parallel; degrade gracefully on failure
  const [status, season, health] = await Promise.all([
    api.getStatus().catch(() => null),
    api.getSeason().catch(() => null),
    api.fetch('/api/health').catch(() => null),
  ]);

  const phase = season?.current_phase ?? {};
  const arc   = season?.tss_arc ?? [];
  const comp  = health?.components ?? {};
  const overall = health?.overall ?? 'unknown';

  const noData = !status && !season;

  return `
    <!-- System health strip -->
    <div class="health-strip fade-in">
      <div class="health-strip-label">
        System&nbsp;<span class="badge ${overall === 'healthy' ? 'badge-success' : overall === 'degraded' ? 'badge-warning' : 'badge-error'}">${overall}</span>
      </div>
      <div class="health-components">
        ${Object.entries(comp).map(([name, c]) => `
          <div class="health-comp">
            <span class="status-dot ${c.status === 'healthy' ? 'dot-green' : (c.status === 'model_missing' || c.status === 'no_tokens' || c.status === 'stale') ? 'dot-yellow' : 'dot-red'}"></span>
            <span>${name}</span>
          </div>`).join('')}
        ${Object.keys(comp).length === 0 ? '<span style="color:var(--text-muted)">Backend unreachable</span>' : ''}
      </div>
    </div>

    <header class="view-header fade-in">
      <div>
        <h2>Morning Readout</h2>
        <p>${new Date().toLocaleDateString('en-AU', { weekday: 'long', month: 'long', day: 'numeric' })}</p>
      </div>
      ${phase.phase ? `<div class="badge ${PHASE_BADGE[phase.phase] ?? 'badge-info'}">${phase.phase}</div>` : ''}
    </header>

    ${noData ? `<div class="card fade-in"><p style="color:var(--text-dim)">No fitness data yet — run a Garmin sync to populate your metrics.</p></div>` : ''}

    <!-- CTL / ATL / TSB / HRV cards -->
    <section class="grid-dashboard fade-in">
      <div class="card metric-card">
        <h3>Fitness (CTL)</h3>
        <div class="value">${status?.ctl ?? '—'}</div>
        <div class="unit">TSS/day</div>
        <div class="trend stable">Chronic load</div>
      </div>
      <div class="card metric-card">
        <h3>Fatigue (ATL)</h3>
        <div class="value">${status?.atl ?? '—'}</div>
        <div class="unit">TSS/day</div>
        <div class="trend ${(status?.atl ?? 0) > (status?.ctl ?? 0) ? 'down' : 'stable'}">Acute load</div>
      </div>
      <div class="card metric-card">
        <h3>Form (TSB)</h3>
        <div class="value ${status?.tsb != null ? (status.tsb < -20 ? 'value-warn' : status.tsb > 10 ? 'value-good' : '') : ''}">${status?.tsb ?? '—'}</div>
        <div class="unit">CTL − ATL</div>
        ${tsbTrend(status?.tsb ?? null)}
      </div>
      <div class="card metric-card">
        <h3>HRV Trend</h3>
        <div class="value" style="font-size:1rem;line-height:1.5">${status?.hrv_trend ?? 'No data'}</div>
        <div class="trend stable">14-day baseline</div>
      </div>
    </section>

    <!-- Season phase + pipeline status -->
    <section class="grid-half fade-in">
      <div class="card">
        <h3>Season Phase</h3>
        ${phase.a_race_name ? `
          <div class="race-target">
            <div class="race-target-name">${phase.a_race_name}</div>
            <div class="race-target-date">${phase.a_race_date ?? ''}</div>
            ${phase.weeks_to_a_race != null ? `
              <div class="race-countdown">
                <span class="value" style="font-size:1.8rem">${phase.weeks_to_a_race}</span>
                <span class="unit">weeks to A-race</span>
              </div>` : ''}
          </div>` : '<p style="color:var(--text-dim);margin-top:8px">No A-race configured — add one in the Planner.</p>'}
      </div>
      <div class="card">
        <h3>Component Status</h3>
        <div class="pipeline-list">
          ${Object.entries(comp).map(([name, c]) => `
            <div class="pipeline-item">
              <span>${name.charAt(0).toUpperCase() + name.slice(1)}</span>
              ${healthBadge(c.status)}
              <small>${c.planned_sessions != null ? c.planned_sessions + ' sessions' : c.token_age_hours != null ? c.token_age_hours + 'h token age' : c.models_available != null ? c.models_available + ' models' : ''}</small>
            </div>`).join('')}
          ${Object.keys(comp).length === 0 ? '<div class="pipeline-item"><span>Backend</span><span class="badge badge-error">unreachable</span></div>' : ''}
        </div>
      </div>
    </section>

    <!-- TSS arc chart -->
    ${arc.length > 0 ? `
      <div class="card fade-in">
        <h3>12-Week TSS Arc</h3>
        <div style="margin-top:16px">${tssBarChart(arc)}</div>
        <div class="chart-legend">
          <span class="legend-dot" style="background:#4f7cff"></span>Base
          <span class="legend-dot" style="background:#f5a623"></span>Build
          <span class="legend-dot" style="background:#ff4f9a"></span>Peak
          <span class="legend-dot" style="background:#3dd68c"></span>Taper / Recovery
          <span style="margin-left:auto;color:var(--text-muted)">Faded bars = recovery weeks</span>
        </div>
      </div>` : ''}
  `;
}

export function mount(_container) {
  // No stateful interactions on the dashboard — it's a read-only readout
}

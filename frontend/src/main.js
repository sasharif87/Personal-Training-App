/* frontend/src/main.js */
import './styles/layout.css';
import './styles/components.css';
import { api } from './api/client.js';

/**
 * Main App Controller
 * Handles routing and view switching.
 */

const app = document.getElementById('app');

const state = {
  activeView: 'dashboard',
  athleteData: null,
  fitnessStatus: null,
};

const views = {
  dashboard: {
    title: 'Dashboard',
    icon: '📊',
    render: async () => {
      const status = await api.getStatus();
      const season = await api.getSeason();
      
      return `
        <header class="view-header fade-in">
          <div>
            <h2>Readout</h2>
            <p>Training Readiness for ${new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</p>
          </div>
          <div class="badge badge-success">System Healthy</div>
        </header>

        <section class="grid-dashboard fade-in">
          <div class="card">
            <h3>Fitness (CTL)</h3>
            <div class="value">${status.ctl}</div>
            <div class="trend stable">↗ Trending up</div>
          </div>
          <div class="card">
            <h3>Fatigue (ATL)</h3>
            <div class="value">${status.atl}</div>
            <div class="trend down">↘ Dropping</div>
          </div>
          <div class="card">
            <h3>Form (TSB)</h3>
            <div class="value">${status.tsb}</div>
            <div class="trend ${status.tsb < 0 ? 'down' : 'up'}">${status.tsb < 0 ? 'Risk zone' : 'Prime form'}</div>
          </div>
          <div class="card">
            <h3>HRV Trend</h3>
            <div class="value" style="font-size: 1.2rem;">${status.hrv_trend || 'No Data'}</div>
            <p style="font-size: 0.8rem; color: var(--text-dim); margin-top: 8px;">Baseline established</p>
          </div>
        </section>

        <section class="card fade-in" style="min-height: 200px;">
          <h3>Today's Logic</h3>
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <h4 style="margin-bottom: 8px;">Morning Decision</h4>
              <p style="color: var(--text-dim); line-height: 1.6;">
                The LLM has reviewed your overnight metrics.
                Current phase: <strong>${season.current_phase || 'Base'}</strong>.
              </p>
            </div>
            <button class="btn btn-primary">Adjust Today's Session</button>
          </div>
        </section>
      `;
    }
  },
  planner: {
    title: 'Season Planner',
    icon: '🗓️',
    render: async () => {
       const season = await api.getSeason();
       return `
        <header class="view-header fade-in">
          <div>
            <h2>Season Planner</h2>
            <p>Active Phase: ${season.current_phase}</p>
          </div>
          <button class="btn btn-secondary">+ Add Race URL</button>
        </header>

        <section class="card fade-in">
          <h3>TSS Management Arc</h3>
          <div style="height: 300px; display: flex; align-items: center; justify-content: center; background: var(--bg-glass-bright); border-radius: 12px;">
            <p style="color: var(--text-dim);">[Chart.js Visualization Placeholder]</p>
          </div>
        </section>
       `;
    }
  },
  library: {
    title: 'Library',
    icon: '📚',
    render: async () => {
      const workouts = await api.getWorkouts();
      return `
        <header class="view-header fade-in">
          <div>
            <h2>Workout Library</h2>
            <p>${workouts.length} indexed sessions</p>
          </div>
          <button class="btn btn-secondary">Upload .zwo / .tcx</button>
        </header>
        <section class="card fade-in">
          <input type="text" class="btn-secondary" style="width: 100%; padding: 12px; margin-bottom: 20px; border-radius: 8px;" placeholder="Search by name or rationale...">
          <div style="display: grid; gap: 12px;">
            ${workouts.slice(0, 10).map(w => `
              <div style="display: flex; justify-content: space-between; padding: 12px; border-bottom: 1px solid var(--border);">
                <div>
                  <span class="badge badge-info">${w.sport}</span>
                  <strong style="margin-left: 8px;">${w.title}</strong>
                </div>
                <div style="color: var(--text-dim);">${w.estimated_tss} TSS</div>
              </div>
            `).join('')}
          </div>
        </section>
      `;
    }
  },
  config: {
    title: 'Settings',
    icon: '⚙️',
    render: async () => {
      const config = await api.getConfig();
      return `
        <header class="view-header fade-in">
          <div>
            <h2>Athlete Profile</h2>
            <p>Manage physiological thresholds</p>
          </div>
          <button class="btn btn-primary">Save Changes</button>
        </header>
        
        <section class="card fade-in">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;" id="config-form">
            <div>
              <label style="display: block; font-size: 0.8rem; color: var(--text-dim); margin-bottom: 8px;">Cycling FTP (W)</label>
              <input type="number" id="athlete-ftp" value="${config.athlete.ftp}" style="width: 100%; padding: 10px; background: var(--bg-surface); border: 1px solid var(--border); color: white; border-radius: 6px;">
            </div>
            <div>
              <label style="display: block; font-size: 0.8rem; color: var(--text-dim); margin-bottom: 8px;">Run LTHR (BPM)</label>
              <input type="number" id="athlete-lthr" value="${config.athlete.lthr_run}" style="width: 100%; padding: 10px; background: var(--bg-surface); border: 1px solid var(--border); color: white; border-radius: 6px;">
            </div>
          </div>
          <div style="margin-top: 20px;">
            <button class="btn btn-primary" id="save-config-btn">Save All Changes</button>
          </div>
        </section>
      `;
    }
  }
};

/**
 * Handle view-specific interactions after render
 */
function attachViewInteractions(viewKey) {
  if (viewKey === 'config') {
    const btn = document.getElementById('save-config-btn');
    if (btn) {
      btn.addEventListener('click', async () => {
        const ftp = document.getElementById('athlete-ftp').value;
        const lthr = document.getElementById('athlete-lthr').value;
        btn.innerText = 'Saving...';
        try {
          // Get full config first to preserve other fields
          const current = await api.getConfig();
          current.athlete.ftp = parseInt(ftp);
          current.athlete.lthr_run = parseInt(lthr);
          await api.saveConfig(current);
          btn.innerText = 'Saved!';
          setTimeout(() => btn.innerText = 'Save All Changes', 2000);
        } catch (err) {
          alert('Save failed: ' + err.message);
          btn.innerText = 'Save All Changes';
        }
      });
    }
  }
}

/**
 * Navigation initialization
 */
function initLayout() {
  app.innerHTML = `
    <aside class="sidebar">
      <div>
        <h1>Coaching.ai</h1>
        <nav class="nav">
          ${Object.keys(views).map(key => `
            <a class="nav-item ${state.activeView === key ? 'active' : ''}" data-view="${key}">
              <span>${views[key].icon}</span> ${views[key].title}
            </a>
          `).join('')}
        </nav>
      </div>
      <div style="margin-top: auto; color: var(--text-muted); font-size: 0.75rem;">
        v0.1.0-alpha
      </div>
    </aside>
    <main class="main-content" id="view-root">
      <!-- Dynamic View Injected Here -->
    </main>
  `;

  // Attach navigation listeners
  app.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
      const view = e.currentTarget.dataset.view;
      switchView(view);
    });
  });
}

/**
 * View switcher
 */
async function switchView(viewKey) {
  state.activeView = viewKey;
  
  // Update sidebar UI
  app.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === viewKey);
  });

  const viewRoot = document.getElementById('view-root');
  viewRoot.innerHTML = `<div class="card fade-in">Loading ${viewKey}...</div>`;
  
  try {
    const html = await views[viewKey].render();
    viewRoot.innerHTML = html;
    attachViewInteractions(viewKey);
  } catch (err) {
    viewRoot.innerHTML = `<div class="card badge-error">Failed to load view: ${err.message}</div>`;
  }
}

// Kick off the app
initLayout();
switchView('dashboard');

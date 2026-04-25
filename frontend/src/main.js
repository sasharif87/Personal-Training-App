/* frontend/src/main.js */
import * as Dashboard from './views/dashboard.js';
import * as Planner   from './views/planner.js';
import * as Library   from './views/library.js';
import * as Health    from './views/health.js';
import * as Gear      from './views/gear.js';
import * as Config    from './views/config.js';

// ---------------------------------------------------------------------------
// View registry
// ---------------------------------------------------------------------------
const VIEWS = {
  dashboard: { title: 'Dashboard',    icon: '⚡', module: Dashboard },
  planner:   { title: 'Planner',      icon: '📅', module: Planner },
  library:   { title: 'Library',      icon: '📚', module: Library },
  health:    { title: 'Health',       icon: '❤️',  module: Health },
  gear:      { title: 'Gear',         icon: '🚲', module: Gear },
  settings:  { title: 'Settings',     icon: '⚙️', module: Config },
};

// ---------------------------------------------------------------------------
// Router state
// ---------------------------------------------------------------------------
let activeView = 'dashboard';
const app = document.getElementById('app');

// ---------------------------------------------------------------------------
// Layout scaffold (rendered once)
// ---------------------------------------------------------------------------
function initLayout() {
  app.innerHTML = `
    <aside class="sidebar">
      <div>
        <h1>Coaching.ai</h1>
        <nav class="nav">
          ${Object.entries(VIEWS).map(([key, v]) => `
            <a class="nav-item" data-view="${key}" role="button" tabindex="0">
              <span aria-hidden="true">${v.icon}</span>
              <span>${v.title}</span>
            </a>`).join('')}
        </nav>
      </div>
      <div style="margin-top:auto;color:var(--text-muted);font-size:0.72rem;line-height:1.6">
        <div>Coaching.ai v0.2.0</div>
        <div id="sidebar-status" style="margin-top:4px"></div>
      </div>
    </aside>
    <main class="main-content" id="view-root" role="main"></main>
  `;

  // Navigation
  app.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => switchView(item.dataset.view));
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') switchView(item.dataset.view);
    });
  });
}

// ---------------------------------------------------------------------------
// View switcher
// ---------------------------------------------------------------------------
async function switchView(viewKey) {
  if (!VIEWS[viewKey]) return;
  activeView = viewKey;

  // Update sidebar active state
  app.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === viewKey);
  });

  const viewRoot = document.getElementById('view-root');

  // Show skeleton while loading
  viewRoot.innerHTML = `
    <div class="fade-in" style="display:flex;flex-direction:column;gap:var(--space-lg)">
      <div class="skeleton" style="height:40px;width:60%"></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:var(--space-lg)">
        ${Array(4).fill('<div class="skeleton" style="height:120px"></div>').join('')}
      </div>
      <div class="skeleton" style="height:200px"></div>
    </div>`;

  try {
    const html = await VIEWS[viewKey].module.render();
    viewRoot.innerHTML = html;
    VIEWS[viewKey].module.mount(viewRoot);
  } catch (err) {
    console.error(`View "${viewKey}" failed to render:`, err);
    viewRoot.innerHTML = `
      <div class="card" style="border-color:var(--error)">
        <h3 style="color:var(--error)">Failed to load ${VIEWS[viewKey].title}</h3>
        <p style="color:var(--text-dim);margin-top:8px">${err.message}</p>
        <button class="btn btn-secondary" style="margin-top:16px" onclick="window.__retry('${viewKey}')">Retry</button>
      </div>`;
    window.__retry = (k) => switchView(k);
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
initLayout();
switchView('dashboard');

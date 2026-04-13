/* frontend/src/views/library.js */
import { api } from '../api/client.js';
import { showSuccess, showError } from '../components/toast.js';

const SPORTS = ['All', 'Bike', 'Run', 'Swim', 'Strength'];
const SPORT_ICONS = { Bike: '🚴', Run: '🏃', Swim: '🏊', Strength: '🏋️', All: '📚' };

function workoutCard(w) {
  const sport = w.sport ?? 'Unknown';
  return `
    <div class="workout-card">
      <div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <span class="badge badge-info">${SPORT_ICONS[sport] ?? ''} ${sport}</span>
          <span class="workout-title">${w.title}</span>
        </div>
        <div class="workout-desc">${w.description ? w.description.slice(0, 120) + (w.description.length > 120 ? '…' : '') : '—'}</div>
        ${w.tags ? `<div style="margin-top:4px;font-size:0.75rem;color:var(--text-muted)">${w.tags}</div>` : ''}
      </div>
      <div class="workout-stats">
        <span class="badge badge-warning">${w.estimated_tss ?? '?'} TSS</span>
        <span style="font-size:0.75rem;color:var(--text-muted)">${w.steps} steps</span>
      </div>
    </div>`;
}

export async function render() {
  const workouts = await api.getWorkouts().catch(() => []);

  return `
    <header class="view-header fade-in">
      <div>
        <h2>Workout Library</h2>
        <p>${workouts.length} sessions indexed</p>
      </div>
      <button class="btn btn-secondary" id="upload-btn">↑ Upload .zwo / .tcx</button>
    </header>

    <!-- Sport tabs + search -->
    <div class="fade-in" style="display:flex;flex-direction:column;gap:var(--space-md)">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--space-sm)">
        <div class="tab-bar">
          ${SPORTS.map(s => `<button class="tab-btn${s === 'All' ? ' active' : ''}" data-sport="${s}">${SPORT_ICONS[s] ?? ''} ${s}</button>`).join('')}
        </div>
        <input class="form-input" id="search-input" type="search" placeholder="Search workouts…" style="max-width:260px">
      </div>
    </div>

    <!-- Workout list -->
    <div class="card fade-in" id="workout-list">
      ${workouts.length === 0
        ? `<div class="empty-state"><div class="empty-icon">📭</div><p>No workouts yet — upload a .zwo or .tcx file to get started.</p></div>`
        : workouts.map(workoutCard).join('')}
    </div>

    <!-- Upload modal -->
    <div id="upload-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);z-index:100;align-items:center;justify-content:center">
      <div class="card" style="width:440px;max-width:95vw">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-lg)">
          <h3 style="font-size:1rem;text-transform:none;color:var(--text-main)">Upload Workout File</h3>
          <button class="btn btn-secondary" id="close-upload-modal" style="padding:6px 12px">✕</button>
        </div>
        <label class="dropzone" id="dropzone">
          <input type="file" id="file-input" accept=".zwo,.tcx">
          <div>
            <div style="font-size:2rem;margin-bottom:8px">📁</div>
            <div style="font-weight:600;margin-bottom:4px">Drop a .zwo or .tcx file here</div>
            <div style="font-size:0.82rem;color:var(--text-muted)">or click to browse — max 10 MB</div>
          </div>
        </label>
        <div id="upload-status" style="margin-top:12px"></div>
      </div>
    </div>
  `;
}

export function mount(container) {
  let currentSport = 'All';
  let currentSearch = '';
  let debounceTimer = null;

  const listEl   = container.querySelector('#workout-list');
  const searchEl = container.querySelector('#search-input');
  const modal    = container.querySelector('#upload-modal');
  const uploadBtn = container.querySelector('#upload-btn');
  const closeBtn = container.querySelector('#close-upload-modal');
  const dropzone = container.querySelector('#dropzone');
  const fileInput = container.querySelector('#file-input');
  const statusEl = container.querySelector('#upload-status');

  // ── Search ────────────────────────────────────────────────────────────────
  async function loadWorkouts() {
    listEl.innerHTML = '<div class="skeleton" style="height:200px"></div>';
    try {
      const sport   = currentSport === 'All' ? '' : currentSport;
      const results = await api.getWorkouts(sport, currentSearch);
      listEl.innerHTML = results.length === 0
        ? `<div class="empty-state"><div class="empty-icon">🔍</div><p>No workouts match "${currentSearch || currentSport}"</p></div>`
        : results.map(workoutCard).join('');
    } catch {
      listEl.innerHTML = `<div class="badge badge-error">Failed to load workouts</div>`;
    }
  }

  searchEl?.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    currentSearch = searchEl.value.trim();
    debounceTimer = setTimeout(loadWorkouts, 350);
  });

  // ── Sport tabs ────────────────────────────────────────────────────────────
  container.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentSport = btn.dataset.sport;
      currentSearch = '';
      if (searchEl) searchEl.value = '';
      loadWorkouts();
    });
  });

  // ── Upload modal ──────────────────────────────────────────────────────────
  uploadBtn?.addEventListener('click', () => { modal.style.display = 'flex'; });
  closeBtn?.addEventListener('click', () => { modal.style.display = 'none'; });
  modal?.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

  async function handleFile(file) {
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['zwo', 'tcx'].includes(ext)) {
      showError('Only .zwo and .tcx files are supported.');
      return;
    }
    statusEl.innerHTML = `<div style="color:var(--text-dim)">Uploading ${file.name}…</div>`;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await api.uploadWorkout(formData);
      const data = await resp.json();
      statusEl.innerHTML = `<div class="badge badge-success">✓ Imported ${data.sessions_imported} session(s) from ${data.filename}</div>`;
      showSuccess(`${data.sessions_imported} session(s) imported`);
      setTimeout(() => { modal.style.display = 'none'; loadWorkouts(); }, 1500);
    } catch (err) {
      statusEl.innerHTML = `<div class="badge badge-error">Upload failed: ${err.message}</div>`;
      showError('Upload failed.');
    }
  }

  // Dropzone drag/drop
  dropzone?.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); });
  dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
  dropzone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    handleFile(e.dataTransfer.files[0]);
  });

  fileInput?.addEventListener('change', () => handleFile(fileInput.files[0]));
}

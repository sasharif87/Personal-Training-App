/* frontend/src/api/client.js */

/**
 * Standardized API client for the Personal Training App.
 * Interacts with the FastAPI backend endpoints.
 *
 * Auth: all /api/* routes require X-API-Key. The key is stored in
 * localStorage under 'coaching_api_key'. On first load (or after a 401),
 * the user is prompted to enter it.
 */

const API_BASE = window.location.origin;
const API_KEY_STORAGE = 'coaching_api_key';

function _getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE) || '';
}

function _promptApiKey(reason = '') {
  const msg = reason
    ? `${reason}\n\nEnter your API key (set via CONFIG_API_KEY in .env):`
    : 'Enter your API key (set via CONFIG_API_KEY in .env):';
  const key = window.prompt(msg);
  if (key && key.trim()) {
    localStorage.setItem(API_KEY_STORAGE, key.trim());
    return key.trim();
  }
  return null;
}

// Bootstrap: prompt on first visit if no key is stored
if (!_getApiKey()) {
  _promptApiKey('No API key found.');
}

class APIClient {
  async fetch(endpoint, options = {}) {
    const apiKey = _getApiKey();
    try {
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'X-API-Key': apiKey } : {}),
          ...options.headers,
        },
        ...options,
      });

      // If we get a 401, the stored key is wrong — prompt for a new one and retry once
      if (resp.status === 401) {
        const newKey = _promptApiKey('API key rejected (401). Please re-enter:');
        if (newKey) {
          const retry = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
              'Content-Type': 'application/json',
              'X-API-Key': newKey,
              ...options.headers,
            },
            ...options,
          });
          if (!retry.ok) {
            throw new Error(`API Error: ${retry.status} - ${retry.statusText}`);
          }
          return await retry.json();
        }
        throw new Error('API key required');
      }

      if (!resp.ok) {
        throw new Error(`API Error: ${resp.status} - ${resp.statusText}`);
      }

      return await resp.json();
    } catch (err) {
      console.error(`API Call failed [${endpoint}]:`, err);
      throw err;
    }
  }

  // --- Configuration ---
  async getConfig() { return this.fetch('/api/config'); }
  async saveConfig(data) { return this.fetch('/api/config', { method: 'POST', body: JSON.stringify(data) }); }

  // --- Fitness Status ---
  async getStatus() { return this.fetch('/status'); }

  // --- Season Planner ---
  async getSeason() { return this.fetch('/api/season'); }
  async extractEvent(url, priority = 'C') { return this.fetch('/api/extract-event', { method: 'POST', body: JSON.stringify({ url, priority }) }); }

  // --- Workout Library ---
  async getWorkouts(sport = '', search = '') { 
    return this.fetch(`/api/workouts?sport=${sport}&search=${search}`); 
  }
  
  async uploadWorkout(formData) {
    const apiKey = _getApiKey();
    const resp = await fetch(`${API_BASE}/workouts/upload`, {
      method: 'POST',
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
      body: formData,
    });
    if (!resp.ok) throw new Error('Upload failed');
    return resp;
  }

  // --- Health & Recovery ---
  async postHealthData(data) { return this.fetch('/api/health-data', { method: 'POST', body: JSON.stringify(data) }); }
  async postSessionLog(data) { return this.fetch('/api/post-session', { method: 'POST', body: JSON.stringify(data) }); }

  // --- Planning ---
  async getVacations() { return this.fetch('/api/vacations'); }
  async saveVacation(data) { return this.fetch('/api/vacations', { method: 'POST', body: JSON.stringify(data) }); }

  // --- Gear ---
  async getGear() { return this.fetch('/api/gear'); }
  async saveGear(data) { return this.fetch('/api/gear', { method: 'POST', body: JSON.stringify(data) }); }
}

export const api = new APIClient();

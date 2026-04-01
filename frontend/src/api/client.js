/* frontend/src/api/client.js */

/**
 * Standardized API client for the Personal Training App.
 * Interacts with the FastAPI backend endpoints.
 */

const API_BASE = window.location.origin;

class APIClient {
  async fetch(endpoint, options = {}) {
    try {
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
        ...options,
      });

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
    const resp = await fetch(`${API_BASE}/workouts/upload`, {
      method: 'POST',
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

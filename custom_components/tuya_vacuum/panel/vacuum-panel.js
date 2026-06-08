class VacuumPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._selectedRooms = new Set();
    this._suction = 2;
    this._water = 1;
    this._mapTimer = null;
  }

  set panel(panel) {
    this._config = panel.config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
    this._manageMapRefresh();
  }

  _manageMapRefresh() {
    if (!this._hass || !this._config.entity_id) return;
    const vacuumState = this._hass.states[this._config.entity_id];
    if (!vacuumState) return;

    const isCleaning = ["cleaning", "returning"].includes(vacuumState.state);
    
    if (isCleaning && !this._mapTimer) {
      this._mapTimer = setInterval(() => {
        const img = this.shadowRoot.querySelector("#vacuum-map");
        if (img) img.src = this._getMapUrl() + `&t=${Date.now()}`;
      }, 30000);
    } else if (!isCleaning && this._mapTimer) {
      clearInterval(this._mapTimer);
      this._mapTimer = null;
    }
  }

  _getMapUrl() {
    if (!this._hass || !this._config.map_entity) return "";
    const mapState = this._hass.states[this._config.map_entity];
    if (mapState && mapState.attributes.access_token) {
      return `/api/image_proxy/${mapState.entity_id}?token=${mapState.attributes.access_token}`;
    }
    return "";
  }

  _toggleRoom(id) {
    if (this._selectedRooms.has(id)) {
      this._selectedRooms.delete(id);
    } else {
      this._selectedRooms.add(id);
    }
    this._render();
  }

  _startCleaning() {
    const rooms = [...this._selectedRooms];
    if (rooms.length === 0) return;
    this._hass.callService("vacuum", "send_command", {
      entity_id: this._config.entity_id,
      command: "clean_rooms",
      params: {
        rooms: rooms.map(Number),
        suction: rooms.map(() => this._suction),
        water: rooms.map(() => this._water),
      }
    });
  }

  _callService(domain, service, data = {}) {
    if (!this._hass || !this._config.entity_id) return;
    const payload = { entity_id: this._config.entity_id, ...data };
    this._hass.callService(domain, service, payload);
  }

  _render() {
    if (!this._hass || !this._config.entity_id) return;

    const vacuumState = this._hass.states[this._config.entity_id];
    if (!vacuumState) return;

    const battery = this._hass.states["sensor.battery"]?.state || vacuumState.attributes.battery_level || "?";
    const status = vacuumState.state;
    const rooms = this._config.rooms || vacuumState.attributes.rooms || {};
    const mapUrl = this._getMapUrl();

    let roomsHtml = Object.entries(rooms).map(([id, name]) => {
      const selected = this._selectedRooms.has(id);
      return `<button class="room-btn ${selected ? 'selected' : ''}" data-id="${id}">${name} ${selected ? '✓' : ''}</button>`;
    }).join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 16px;
          background: var(--primary-background-color, #f0f0f0);
          color: var(--primary-text-color, #333);
          font-family: sans-serif;
          height: 100%;
          box-sizing: border-box;
        }
        .container {
          max-width: 800px;
          margin: 0 auto;
          background: var(--card-background-color, white);
          border-radius: 12px;
          box-shadow: 0 4px 8px rgba(0,0,0,0.1);
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .header {
          padding: 16px;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, white);
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 1.2em;
        }
        .map-container {
          width: 100%;
          background: #e5e5e5;
          display: flex;
          justify-content: center;
          align-items: center;
          min-height: 300px;
        }
        .map-container img {
          max-width: 100%;
          max-height: 50vh;
          object-fit: contain;
        }
        .controls {
          padding: 16px;
        }
        .rooms {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 16px;
        }
        .room-btn {
          padding: 8px 16px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--secondary-background-color, #f9f9f9);
          border-radius: 20px;
          cursor: pointer;
          color: var(--primary-text-color, #333);
        }
        .room-btn.selected {
          background: var(--primary-color, #03a9f4);
          color: white;
          border-color: var(--primary-color, #03a9f4);
        }
        .sliders {
          margin-bottom: 16px;
        }
        .slider-row {
          display: flex;
          align-items: center;
          margin-bottom: 8px;
        }
        .slider-row span {
          width: 100px;
        }
        .slider-row input {
          flex-grow: 1;
        }
        .actions {
          display: flex;
          gap: 8px;
          justify-content: center;
        }
        .action-btn {
          padding: 12px 24px;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-weight: bold;
          flex-grow: 1;
        }
        .btn-start { background: #4caf50; color: white; }
        .btn-pause { background: #ff9800; color: white; }
        .btn-dock { background: #2196f3; color: white; }
      </style>
      <div class="container">
        <div class="header">
          <span>🤖 Tuya Vacuum</span>
          <span>🔋 ${battery}% [${status}]</span>
        </div>
        <div class="map-container">
          ${mapUrl ? `<img id="vacuum-map" src="${mapUrl}&t=${Date.now()}" alt="Vacuum Map" />` : '<span>Map unavailable</span>'}
        </div>
        <div class="controls">
          <h3>Rooms</h3>
          <div class="rooms">
            ${roomsHtml}
          </div>
          <div class="sliders">
            <div class="slider-row">
              <span>Suction: ${this._suction}</span>
              <input type="range" id="suction" min="1" max="4" value="${this._suction}">
            </div>
            <div class="slider-row">
              <span>Water: ${this._water}</span>
              <input type="range" id="water" min="0" max="3" value="${this._water}">
            </div>
          </div>
          <div class="actions">
            <button class="action-btn btn-pause" id="btn-pause">⏸ Pause</button>
            <button class="action-btn btn-start" id="btn-start">▶ Start Selection</button>
            <button class="action-btn btn-dock" id="btn-dock">🏠 Dock</button>
          </div>
        </div>
      </div>
    `;

    // Attach listeners
    this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
      btn.addEventListener('click', (e) => this._toggleRoom(e.target.dataset.id));
    });

    this.shadowRoot.querySelector('#suction').addEventListener('input', (e) => {
      this._suction = parseInt(e.target.value);
      this._render(); // simple re-render to update text
    });

    this.shadowRoot.querySelector('#water').addEventListener('input', (e) => {
      this._water = parseInt(e.target.value);
      this._render();
    });

    this.shadowRoot.querySelector('#btn-start').addEventListener('click', () => this._startCleaning());
    this.shadowRoot.querySelector('#btn-pause').addEventListener('click', () => this._callService("vacuum", "pause"));
    this.shadowRoot.querySelector('#btn-dock').addEventListener('click', () => this._callService("vacuum", "return_to_base"));
  }
}

customElements.define("vacuum-panel", VacuumPanel);

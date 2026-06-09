class VacuumPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._selectedRooms = new Set();
    this._roomSettings = {};
    this._currentSuction = 2;
    this._currentWater = 1;
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
        const url = this._getMapUrl();
        if (url) {
          const newImg = new Image();
          newImg.onload = () => {
            const img = this.shadowRoot.querySelector("#vacuum-map");
            if (img) img.src = newImg.src;
          };
          newImg.src = url + `&t=${Date.now()}`;
        }
      }, 30000);
    } else if (!isCleaning && this._mapTimer) {
      clearInterval(this._mapTimer);
      this._mapTimer = null;
    }
  }

  _getMapUrl() {
    if (!this._hass || !this._config.map_entity) return "";
    const mapState = this._hass.states[this._config.map_entity];
    if (mapState) {
      const token = mapState.attributes.access_token;
      return `/api/image_proxy/${mapState.entity_id}` + (token ? `?token=${token}` : "");
    }
    return "";
  }

  _toggleRoom(id) {
    if (this._selectedRooms.has(id)) {
      this._selectedRooms.delete(id);
      delete this._roomSettings[id];
    } else {
      this._selectedRooms.add(id);
      this._roomSettings[id] = {
        suction: this._currentSuction,
        water: this._currentWater
      };
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
        suction: rooms.map(id => this._roomSettings[id]?.suction || 2),
        water: rooms.map(id => this._roomSettings[id]?.water || 0),
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

    const battery = vacuumState.attributes.battery_level ?? "?";
    const status = vacuumState.state;
    
    // Normalize rooms into an array of {id, name}
    let roomsData = this._config.rooms || vacuumState.attributes.rooms;
    let roomsArray = [];
    if (Array.isArray(roomsData)) {
        roomsArray = roomsData; 
    } else if (typeof roomsData === 'object' && roomsData !== null) {
        roomsArray = Object.entries(roomsData).map(([id, name]) => ({id: id, name: name}));
    }

    const mapUrl = this._getMapUrl();

    const suctionLabels = {1: "Eco", 2: "Norm", 3: "Max", 4: "Turbo"};
    const waterLabels = {0: "Off", 1: "Low", 2: "Med", 3: "High"};

    let roomsHtml = roomsArray.map(room => {
      const selected = this._selectedRooms.has(room.id);
      let details = "";
      if (selected && this._roomSettings[room.id]) {
         const s = this._roomSettings[room.id].suction;
         const w = this._roomSettings[room.id].water;
         details = `<div class="room-details">💨${suctionLabels[s]} 💧${waterLabels[w]}</div>`;
      }
      return `
        <button class="room-btn ${selected ? 'selected' : ''}" data-id="${room.id}">
            <div>${room.name} ${selected ? '✓' : ''}</div>
            ${details}
        </button>
      `;
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
          border-radius: 16px;
          cursor: pointer;
          color: var(--primary-text-color, #333);
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .room-btn.selected {
          background: var(--primary-color, #03a9f4);
          color: white;
          border-color: var(--primary-color, #03a9f4);
        }
        .room-details {
          font-size: 0.75em;
          margin-top: 4px;
          opacity: 0.9;
        }
        .sliders {
          margin-bottom: 16px;
          background: var(--secondary-background-color, #f9f9f9);
          padding: 12px;
          border-radius: 8px;
        }
        .slider-row {
          display: flex;
          align-items: center;
          margin-bottom: 8px;
        }
        .slider-row span {
          width: 80px;
          font-size: 0.9em;
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
          color: white;
          text-transform: uppercase;
        }
        .btn-start { background: #4caf50; }
        .btn-pause { background: #ff9800; }
        .btn-dock { background: #2196f3; }
        .help-text {
          font-size: 0.85em;
          color: var(--secondary-text-color, #666);
          margin-bottom: 8px;
          text-align: center;
        }
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
          
          <div class="sliders">
            <div class="help-text">1. Set power & water, then click a room</div>
            <div class="slider-row">
              <span>Suction: ${this._currentSuction}</span>
              <input type="range" id="suction" min="1" max="4" value="${this._currentSuction}">
            </div>
            <div class="slider-row">
              <span>Water: ${this._currentWater}</span>
              <input type="range" id="water" min="0" max="3" value="${this._currentWater}">
            </div>
          </div>

          <div style="font-size: 0.9em; margin-bottom: 8px; color: var(--secondary-text-color);">2. Select Rooms:</div>
          <div class="rooms">
            ${roomsHtml || '<span>No rooms configured</span>'}
          </div>
          
          <div class="actions">
            <button class="action-btn btn-pause" id="btn-pause">⏸ Pause</button>
            <button class="action-btn btn-start" id="btn-start">▶ Start</button>
            <button class="action-btn btn-dock" id="btn-dock">🏠 Dock</button>
          </div>
        </div>
      </div>
    `;

    // Attach listeners
    this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
      btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
    });

    this.shadowRoot.querySelector('#suction').addEventListener('change', (e) => {
      this._currentSuction = parseInt(e.target.value);
      this._render();
    });

    this.shadowRoot.querySelector('#water').addEventListener('change', (e) => {
      this._currentWater = parseInt(e.target.value);
      this._render();
    });

    this.shadowRoot.querySelector('#btn-start').addEventListener('click', () => this._startCleaning());
    this.shadowRoot.querySelector('#btn-pause').addEventListener('click', () => this._callService("vacuum", "pause"));
    this.shadowRoot.querySelector('#btn-dock').addEventListener('click', () => this._callService("vacuum", "return_to_base"));
  }
}

customElements.define("vacuum-panel", VacuumPanel);

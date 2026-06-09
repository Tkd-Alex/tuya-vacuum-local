class VacuumCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._selectedRooms = new Set();
    // Store settings per room ID
    this._roomSettings = {}; 
    // Current global sliders
    this._currentSuction = 2;
    this._currentWater = 1;
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("You need to define entity");
    }
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  static getConfigElement() {
    return document.createElement("vacuum-card-editor");
  }

  static getStubConfig() {
    return { entity: "vacuum.tuya_vacuum" };
  }

  _toggleRoom(id) {
    if (this._selectedRooms.has(id)) {
      this._selectedRooms.delete(id);
      delete this._roomSettings[id];
    } else {
      this._selectedRooms.add(id);
      // Capture current slider values for this room
      this._roomSettings[id] = {
        suction: this._currentSuction,
        water: this._currentWater
      };
    }
    this.render();
  }

  _startCleaning() {
    const rooms = [...this._selectedRooms];
    if (rooms.length === 0) return;
    this._hass.callService("vacuum", "send_command", {
      entity_id: this.config.entity,
      command: "clean_rooms",
      params: {
        rooms: rooms.map(Number),
        suction: rooms.map(id => this._roomSettings[id]?.suction || 2),
        water: rooms.map(id => this._roomSettings[id]?.water || 0),
      }
    });
  }

  _callService(domain, service, data = {}) {
    if (!this._hass || !this.config.entity) return;
    const payload = { entity_id: this.config.entity, ...data };
    this._hass.callService(domain, service, payload);
  }

  render() {
    if (!this._hass || !this.config.entity) return;

    const stateObj = this._hass.states[this.config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div class="not-found">Entity not found: ${this.config.entity}</div>
        </ha-card>
      `;
      return;
    }

    const battery = stateObj.attributes.battery_level ?? "?";
    const status = stateObj.state;
    
    // Check if rooms are provided via card config, otherwise fallback to entity attributes
    let roomsData = this.config.rooms || stateObj.attributes.rooms;
    
    // Normalize rooms into an array of {id, name}
    let roomsArray = [];
    if (Array.isArray(roomsData)) {
        roomsArray = roomsData; // Already an array from config
    } else if (typeof roomsData === 'object' && roomsData !== null) {
        // Convert object from attributes to array
        roomsArray = Object.entries(roomsData).map(([id, name]) => ({id: id, name: name}));
    }

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
        ha-card {
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-weight: bold;
          font-size: 1.2em;
        }
        .controls {
          display: flex;
          justify-content: center;
          gap: 12px;
        }
        .icon-btn {
          background: none;
          border: none;
          cursor: pointer;
          font-size: 24px;
          color: var(--primary-text-color);
          padding: 8px;
          border-radius: 50%;
          background-color: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .icon-btn:hover {
          background-color: var(--primary-color);
          color: white;
        }
        .rooms {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .room-btn {
          padding: 8px 12px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color);
          border-radius: 12px;
          cursor: pointer;
          color: var(--primary-text-color);
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .room-btn.selected {
          background: var(--primary-color);
          color: white;
          border-color: var(--primary-color);
        }
        .room-details {
          font-size: 0.75em;
          margin-top: 4px;
          opacity: 0.9;
        }
        .sliders {
          display: flex;
          flex-direction: column;
          gap: 8px;
          background: var(--secondary-background-color);
          padding: 12px;
          border-radius: 8px;
        }
        .slider-row {
          display: flex;
          align-items: center;
        }
        .slider-row span {
          width: 80px;
          font-size: 0.9em;
        }
        .slider-row input {
          flex-grow: 1;
        }
        .start-btn {
          padding: 12px;
          background: var(--primary-color);
          color: white;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-weight: bold;
          text-transform: uppercase;
          width: 100%;
        }
        .help-text {
          font-size: 0.8em;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
          text-align: center;
        }
      </style>
      <ha-card>
        <div class="header">
          <span>🤖 Vacuum</span>
          <span>[${status}] 🔋 ${battery}%</span>
        </div>
        
        <div class="controls">
          <button class="icon-btn" id="btn-pause" title="Pause">⏸</button>
          <button class="icon-btn" id="btn-dock" title="Dock">🏠</button>
          <button class="icon-btn" id="btn-locate" title="Locate">📍</button>
        </div>

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

        <div>
          <div style="font-size: 0.9em; margin-bottom: 8px; color: var(--secondary-text-color);">2. Select Rooms:</div>
          <div class="rooms">
            ${roomsHtml || '<span>No rooms configured</span>'}
          </div>
        </div>

        <button class="start-btn" id="btn-start">▶ Start Cleaning</button>
      </ha-card>
    `;

    // Attach events
    this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
      btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
    });

    this.shadowRoot.querySelector('#suction').addEventListener('change', (e) => {
      this._currentSuction = parseInt(e.target.value);
      this.render();
    });

    this.shadowRoot.querySelector('#water').addEventListener('change', (e) => {
      this._currentWater = parseInt(e.target.value);
      this.render();
    });

    this.shadowRoot.querySelector('#btn-start').addEventListener('click', () => this._startCleaning());
    this.shadowRoot.querySelector('#btn-pause').addEventListener('click', () => this._callService("vacuum", "pause"));
    this.shadowRoot.querySelector('#btn-dock').addEventListener('click', () => this._callService("vacuum", "return_to_base"));
    this.shadowRoot.querySelector('#btn-locate').addEventListener('click', () => this._callService("vacuum", "locate"));
  }
}

customElements.define("vacuum-card", VacuumCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "vacuum-card",
  name: "Tuya Vacuum Card",
  description: "Control your Tuya vacuum with room selection",
  preview: true,
});

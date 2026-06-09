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
    
    // Map pan/zoom state
    this._scale = 1;
    this._panning = false;
    this._pointX = 0;
    this._pointY = 0;
    this._startX = 0;
    this._startY = 0;
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
          const separator = url.includes("?") ? "&" : "?";
          const newImg = new Image();
          newImg.onload = () => {
            const img = this.shadowRoot.querySelector("#vacuum-map");
            if (img) img.src = newImg.src;
          };
          newImg.src = url + `${separator}t=${Date.now()}`;
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

  // PAN & ZOOM Handlers
  _setTransform() {
    const img = this.shadowRoot.querySelector("#vacuum-map");
    if (img) {
      img.style.transform = `translate(${this._pointX}px, ${this._pointY}px) scale(${this._scale})`;
    }
  }

  _handleWheel(e) {
    e.preventDefault();
    const xs = (e.clientX - this._pointX) / this._scale;
    const ys = (e.clientY - this._pointY) / this._scale;
    const delta = (e.wheelDelta ? e.wheelDelta : -e.deltaY);
    (delta > 0) ? (this._scale *= 1.2) : (this._scale /= 1.2);
    // Limit scale
    this._scale = Math.min(Math.max(0.5, this._scale), 5);
    this._pointX = e.clientX - xs * this._scale;
    this._pointY = e.clientY - ys * this._scale;
    this._setTransform();
  }

  _handlePointerDown(e) {
    e.preventDefault();
    this._startX = e.clientX - this._pointX;
    this._startY = e.clientY - this._pointY;
    this._panning = true;
  }

  _handlePointerUp(e) {
    e.preventDefault();
    this._panning = false;
  }

  _handlePointerMove(e) {
    if (!this._panning) return;
    e.preventDefault();
    this._pointX = e.clientX - this._startX;
    this._pointY = e.clientY - this._startY;
    this._setTransform();
  }

  _handlePresetChange(e) {
    const preset = e.target.value;
    if (!preset) return;
    
    // Find the select entity for presets
    const entryId = this._config.entity_id.split('_').slice(-1)[0]; // naive extraction, works if id contains entry_id
    const selectEntityId = Object.keys(this._hass.states).find(id => id.startsWith("select.") && id.includes("preset"));
    
    if (selectEntityId) {
      this._hass.callService("select", "select_option", {
        entity_id: selectEntityId,
        option: preset
      });
    }
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

    // Try to find the preset entity
    const presetEntityId = Object.keys(this._hass.states).find(id => id.startsWith("select.") && id.includes("preset"));
    const presetState = presetEntityId ? this._hass.states[presetEntityId] : null;
    let presetOptionsHtml = "";
    if (presetState && presetState.attributes.options) {
      presetOptionsHtml = `<div class="preset-selector">
        <label>Quick Preset: </label>
        <select id="preset-select">
          <option value="">(Select to apply globally)</option>
          ${presetState.attributes.options.map(opt => `<option value="${opt}" ${presetState.state === opt ? 'selected' : ''}>${opt}</option>`).join('')}
        </select>
      </div>`;
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

    // Prevent re-rendering the entire HTML if we are just updating state, to preserve map zoom/pan.
    // We'll use a fast update if the shell exists.
    if (this.shadowRoot.querySelector('.container')) {
        // Fast update (Rooms, Battery, Status)
        this.shadowRoot.querySelector('.header-status').innerText = `🔋 ${battery}% [${status}]`;
        this.shadowRoot.querySelector('.rooms').innerHTML = roomsHtml || '<span>No rooms configured</span>';
        
        // Re-attach room listeners
        this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
          btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
        });
        return;
    }

    // Initial render
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
        .map-wrapper {
          width: 100%;
          background: #333; /* Dark background looks better with transparent maps */
          display: flex;
          justify-content: center;
          align-items: center;
          height: 40vh;
          min-height: 300px;
          overflow: hidden;
          position: relative;
          cursor: grab;
        }
        .map-wrapper:active {
          cursor: grabbing;
        }
        #vacuum-map {
          transform-origin: 0 0;
          max-width: 100%;
          max-height: 100%;
          object-fit: contain;
          transition: transform 0.1s ease-out;
        }
        .controls {
          padding: 16px;
        }
        .preset-selector {
          margin-bottom: 12px;
          padding: 8px;
          background: var(--secondary-background-color, #f9f9f9);
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .preset-selector select {
          padding: 4px 8px;
          border-radius: 4px;
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
        .map-hint {
          position: absolute;
          bottom: 8px;
          right: 8px;
          background: rgba(0,0,0,0.5);
          color: white;
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 0.8em;
          pointer-events: none;
        }
      </style>
      <div class="container">
        <div class="header">
          <span>🤖 Tuya Vacuum</span>
          <span class="header-status">🔋 ${battery}% [${status}]</span>
        </div>
        <div class="map-wrapper" id="map-wrapper">
          ${mapUrl ? `<img id="vacuum-map" src="${mapUrl}${mapUrl.includes('?') ? '&' : '?'}t=${Date.now()}" alt="Vacuum Map" />` : '<span>Map unavailable</span>'}
          <div class="map-hint">Scroll to Zoom | Drag to Pan</div>
        </div>
        <div class="controls">
          
          ${presetOptionsHtml}

          <div class="sliders">
            <div class="help-text">1. Set power & water, then click a room</div>
            <div class="slider-row">
              <span>Suction: <span id="suc-val">${this._currentSuction}</span></span>
              <input type="range" id="suction" min="1" max="4" value="${this._currentSuction}">
            </div>
            <div class="slider-row">
              <span>Water: <span id="wat-val">${this._currentWater}</span></span>
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

    // Attach map pan/zoom listeners
    const wrapper = this.shadowRoot.querySelector('#map-wrapper');
    if (wrapper) {
      wrapper.addEventListener('wheel', (e) => this._handleWheel(e), { passive: false });
      wrapper.addEventListener('pointerdown', (e) => this._handlePointerDown(e));
      wrapper.addEventListener('pointerup', (e) => this._handlePointerUp(e));
      wrapper.addEventListener('pointerleave', (e) => this._handlePointerUp(e));
      wrapper.addEventListener('pointermove', (e) => this._handlePointerMove(e));
    }

    // Attach control listeners
    this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
      btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
    });

    const presetSelect = this.shadowRoot.querySelector('#preset-select');
    if (presetSelect) {
        presetSelect.addEventListener('change', (e) => this._handlePresetChange(e));
    }

    this.shadowRoot.querySelector('#suction').addEventListener('change', (e) => {
      this._currentSuction = parseInt(e.target.value);
      this.shadowRoot.querySelector('#suc-val').innerText = this._currentSuction;
    });

    this.shadowRoot.querySelector('#water').addEventListener('change', (e) => {
      this._currentWater = parseInt(e.target.value);
      this.shadowRoot.querySelector('#wat-val').innerText = this._currentWater;
    });

    this.shadowRoot.querySelector('#btn-start').addEventListener('click', () => this._startCleaning());
    this.shadowRoot.querySelector('#btn-pause').addEventListener('click', () => this._callService("vacuum", "pause"));
    this.shadowRoot.querySelector('#btn-dock').addEventListener('click', () => this._callService("vacuum", "return_to_base"));
  }
}

customElements.define("vacuum-panel", VacuumPanel);


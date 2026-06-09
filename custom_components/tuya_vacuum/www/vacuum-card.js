class VacuumCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._selectedRooms = [];
    this._roomSettings = {}; 
    this._currentSuction = 2;
    this._currentWater = 1;
    this._mapTimer = null;
    this._scale = 1;
    this._panning = false;
    this._pointX = 0;
    this._pointY = 0;
    this._startX = 0;
    this._startY = 0;
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
    this._manageMapRefresh();
  }

  static getConfigElement() {
    return document.createElement("vacuum-card-editor");
  }

  static getStubConfig() {
    return { entity: "vacuum.tuya_vacuum" };
  }

  _manageMapRefresh() {
    if (!this._hass || !this.config.entity) return;
    const vacuumState = this._hass.states[this.config.entity];
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
    if (!this._hass || !this.config.entity) return "";
    
    // Find the image entity associated with the integration
    for (const entityId in this._hass.states) {
      if (entityId.startsWith('image.')) {
        const stateObj = this._hass.states[entityId];
        // Guessing the map belongs to our integration if it has calibration_points
        if (stateObj.attributes && stateObj.attributes.calibration_points) {
             const token = stateObj.attributes.access_token;
             return `/api/image_proxy/${entityId}` + (token ? `?token=${token}` : "");
        }
      }
    }
    return "";
  }

  _toggleRoom(id) {
    const index = this._selectedRooms.indexOf(id);
    if (index !== -1) {
      this._selectedRooms.splice(index, 1);
      delete this._roomSettings[id];
    } else {
      this._selectedRooms.push(id);
      this._roomSettings[id] = {
        suction: this._currentSuction,
        water: this._currentWater
      };
    }
    this.render();
  }

  _startCleaning() {
    const rooms = this._selectedRooms;
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
    const selectEntityId = Object.keys(this._hass.states).find(id => id.startsWith("select.") && id.includes("preset"));
    
    if (selectEntityId) {
      this._hass.callService("select", "select_option", {
        entity_id: selectEntityId,
        option: preset
      });
    }
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

    const battery = this._hass.states["sensor.battery"]?.state || stateObj.attributes.battery_level || "?";
    const status = stateObj.state;
    
    let roomsData = this.config.rooms || stateObj.attributes.rooms;
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
      const orderIndex = this._selectedRooms.indexOf(room.id);
      const selected = orderIndex !== -1;
      let details = "";
      if (selected && this._roomSettings[room.id]) {
         const s = this._roomSettings[room.id].suction;
         const w = this._roomSettings[room.id].water;
         details = `<div class="room-details">💨${suctionLabels[s]} 💧${waterLabels[w]}</div>`;
      }
      return `
        <button class="room-btn ${selected ? 'selected' : ''}" data-id="${room.id}">
            <div>${room.name} ${selected ? `<span class="badge">${orderIndex + 1}</span>` : ''}</div>
            ${details}
        </button>
      `;
    }).join("");

    // Fast update check
    if (this.shadowRoot.querySelector('ha-card') && this.shadowRoot.querySelector('.header-status')) {
        this.shadowRoot.querySelector('.header-status').innerText = `[${status}] 🔋 ${battery}%`;
        this.shadowRoot.querySelector('.rooms').innerHTML = roomsHtml || '<span>No rooms configured</span>';
        
        this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
          btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
        });
        return;
    }

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
        .map-wrapper {
          width: 100%;
          background: #333;
          display: flex;
          justify-content: center;
          align-items: center;
          height: 35vh;
          min-height: 250px;
          overflow: hidden;
          position: relative;
          cursor: grab;
          border-radius: 8px;
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
        .preset-selector {
          margin-bottom: 8px;
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
        .badge {
          background: white;
          color: var(--primary-color);
          border-radius: 50%;
          padding: 2px 6px;
          font-size: 0.8em;
          font-weight: bold;
          margin-left: 4px;
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
      <ha-card>
        <div class="header">
          <span>🤖 Vacuum</span>
          <span class="header-status">[${status}] 🔋 ${battery}%</span>
        </div>
        
        <div class="map-wrapper" id="map-wrapper">
          ${mapUrl ? `<img id="vacuum-map" src="${mapUrl}${mapUrl.includes('?') ? '&' : '?'}t=${Date.now()}" alt="Vacuum Map" />` : '<span>Map unavailable</span>'}
          <div class="map-hint">Scroll to Zoom | Drag to Pan</div>
        </div>

        <div class="controls">
          <button class="icon-btn" id="btn-pause" title="Pause">⏸</button>
          <button class="icon-btn" id="btn-dock" title="Dock">🏠</button>
          <button class="icon-btn" id="btn-locate" title="Locate">📍</button>
        </div>
        
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

        <div>
          <div style="font-size: 0.9em; margin-bottom: 8px; color: var(--secondary-text-color);">2. Select Rooms:</div>
          <div class="rooms">
            ${roomsHtml || '<span>No rooms configured</span>'}
          </div>
        </div>

        <button class="start-btn" id="btn-start">▶ Start Cleaning</button>
      </ha-card>
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

    // Attach events
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

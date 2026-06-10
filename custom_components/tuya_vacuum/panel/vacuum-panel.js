const LABELS = {
  it: {
    vacuum: "Aspirapolvere",
    battery: "Batteria",
    status: "Stato",
    rooms: "Stanze",
    suction: "Aspirazione",
    water: "Umidità panno",
    passes: "Ripetizioni",
    carpet_boost: "Boost tappeti",
    start: "Avvia",
    pause: "Pausa",
    dock: "Base",
    locate: "Trova",
    eco: "Eco",
    normal: "Normal",
    strong: "Forte",
    max: "Max",
    off: "Off",
    low: "Basso",
    medium: "Medio",
    high: "Alto",
    map_hint_desktop: "🖱 Scroll zoom · Trascina mappa · Doppio-click reset",
    map_hint_mobile: "👌 Pinch zoom · Trascina mappa · Doppio-tap reset",
    set_power_hint: "1. Scegli potenza, poi clicca una stanza",
    select_rooms_hint: "2. Selezione stanze:",
    no_rooms: "Nessuna stanza configurata",
    maintenance: "Manutenzione & Statistiche",
    filter: "Filtro",
    main_brush: "Spazzola rotante",
    side_brush: "Spazzola laterale",
    total_area: "Area totale",
    total_time: "Tempo totale",
    clean_count: "Sessioni"
  },
  en: {
    vacuum: "Tuya Vacuum",
    battery: "Battery",
    status: "Status",
    rooms: "Rooms",
    suction: "Suction",
    water: "Mop Water",
    passes: "Passes",
    carpet_boost: "Carpet Boost",
    start: "Start",
    pause: "Pause",
    dock: "Dock",
    locate: "Locate",
    eco: "Eco",
    normal: "Normal",
    strong: "Strong",
    max: "Max",
    off: "Off",
    low: "Low",
    medium: "Medium",
    high: "High",
    map_hint_desktop: "🖱 Scroll zoom · Drag pan · Double-click reset",
    map_hint_mobile: "👌 Pinch zoom · Drag pan · Double-tap reset",
    set_power_hint: "1. Set power & water, then click a room",
    select_rooms_hint: "2. Select Rooms:",
    no_rooms: "No rooms configured",
    maintenance: "Maintenance & Stats",
    filter: "Filter",
    main_brush: "Main Brush",
    side_brush: "Side Brush",
    total_area: "Total Area",
    total_time: "Total Time",
    clean_count: "Clean Count"
  }
};

class VacuumPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._selectedRooms = [];
    this._roomSettings = {};
    this._currentSuction = 2;
    this._currentWater = 1;
    this._passes = 1;
    this._carpetBoost = false;
    this._activePreset = null;
    this._locked = false;
    this._mapTimer = null;
    this._scale = 1;
    this._pointX = 0;
    this._pointY = 0;
    this._startX = 0;
    this._startY = 0;
    this._isPanning = false;
    this._lastPinchDist = null;
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

  _getT() {
    const lang = (this._hass?.language || 'en').split('-')[0];
    return LABELS[lang] || LABELS['en'];
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
    const index = this._selectedRooms.indexOf(id);
    if (index !== -1) {
      this._selectedRooms.splice(index, 1);
      delete this._roomSettings[id];
    } else {
      this._selectedRooms.push(id);
      this._roomSettings[id] = {
        suction: this._currentSuction,
        water: this._currentWater,
        passes: this._passes,
        carpet_boost: this._carpetBoost
      };
    }
    this._render();
  }

  _applyPreset(presetName) {
    const t = this._getT();
    const PRESETS = [
      { name: "Eco", icon: "🌿", suction: 1, water: 0 },
      { name: "Standard", icon: "🏠", suction: 2, water: 1 },
      { name: "Turbo", icon: "🚀", suction: 4, water: 0 },
      { name: "Mocio", icon: "💧", suction: 2, water: 3 },
    ];
    const preset = PRESETS.find(p => p.name === presetName);
    if (!preset) return;
    this._activePreset = presetName;
    this._currentSuction = preset.suction;
    this._currentWater = preset.water;
    this._updateSegButtons();
  }

  _updateSegButtons() {
    this.shadowRoot.querySelectorAll('#suction-seg .seg-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.val) === this._currentSuction);
    });
    this.shadowRoot.querySelectorAll('#water-seg .seg-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.val) === this._currentWater);
    });
    this.shadowRoot.querySelectorAll('.preset-chip').forEach(c => {
      c.classList.toggle('active', c.dataset.preset === this._activePreset);
    });
  }

  _startCleaning() {
    const rooms = this._selectedRooms;
    if (rooms.length === 0) return;
    this._hass.callService("vacuum", "send_command", {
      entity_id: this._config.entity_id,
      command: "clean_rooms",
      params: {
        rooms: rooms.map(Number),
        suction: rooms.map(id => this._roomSettings[id]?.suction || this._currentSuction),
        water: rooms.map(id => this._roomSettings[id]?.water || this._currentWater),
        passes: rooms.map(id => this._roomSettings[id]?.passes || this._passes),
        carpet_boost: this._carpetBoost
      }
    });
  }

  _callService(domain, service, data = {}) {
    if (!this._hass || !this._config.entity_id) return;
    this._hass.callService(domain, service, { entity_id: this._config.entity_id, ...data });
  }

  _applyTransform() {
    const wrapper = this.shadowRoot.querySelector('#map-wrapper'), img = this.shadowRoot.querySelector('#vacuum-map');
    if (!wrapper || !img) return;
    const wW = wrapper.clientWidth, wH = wrapper.clientHeight;
    const iW = img.naturalWidth * this._scale, iH = img.naturalHeight * this._scale;
    const maxX = Math.max(0, (iW - wW) / 2), maxY = Math.max(0, (iH - wH) / 2);
    this._pointX = Math.max(-maxX, Math.min(maxX, this._pointX));
    this._pointY = Math.max(-maxY, Math.min(maxY, this._pointY));
    img.style.transformOrigin = 'center center';
    img.style.transform = `translate(${this._pointX}px, ${this._pointY}px) scale(${this._scale})`;
  }

  _handleWheel(e) {
    e.preventDefault();
    const wrapper = this.shadowRoot.querySelector('#map-wrapper'), rect = wrapper.getBoundingClientRect();
    const cursorX = e.clientX - rect.left - rect.width / 2, cursorY = e.clientY - rect.top - rect.height / 2;
    const zoomFactor = e.deltaY < 0 ? 1.15 : (1 / 1.15), newScale = Math.min(Math.max(0.5, this._scale * zoomFactor), 6);
    this._pointX = cursorX - (cursorX - this._pointX) * (newScale / this._scale);
    this._pointY = cursorY - (cursorY - this._pointY) * (newScale / this._scale);
    this._scale = newScale;
    const img = this.shadowRoot.querySelector('#vacuum-map');
    if (img) img.style.transition = 'transform 0.1s ease-out';
    this._applyTransform();
  }

  _handleDoubleClick() {
    this._scale = 1; this._pointX = 0; this._pointY = 0;
    const img = this.shadowRoot.querySelector('#vacuum-map');
    if (img) img.style.transition = 'transform 0.3s ease';
    this._applyTransform();
    setTimeout(() => { if (this.shadowRoot.querySelector('#vacuum-map')) this.shadowRoot.querySelector('#vacuum-map').style.transition = ''; }, 300);
  }

  _handlePointerDown(e) {
    if (e.pointerType === 'touch') return;
    e.preventDefault(); this._isPanning = true;
    this._startX = e.clientX - this._pointX; this._startY = e.clientY - this._pointY;
    const img = this.shadowRoot.querySelector('#vacuum-map'); if (img) img.style.transition = 'none';
  }
  _handlePointerUp() { this._isPanning = false; }
  _handlePointerMove(e) {
    if (!this._isPanning || e.pointerType === 'touch') return;
    e.preventDefault(); this._pointX = e.clientX - this._startX; this._pointY = e.clientY - this._startY;
    this._applyTransform();
  }

  _handleTouchStart(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX, dy = e.touches[0].clientY - e.touches[1].clientY;
      this._lastPinchDist = Math.hypot(dx, dy);
      this._pinchCenterX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
      this._pinchCenterY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    } else if (e.touches.length === 1) {
      this._isPanning = true; this._startX = e.touches[0].clientX - this._pointX; this._startY = e.touches[0].clientY - this._pointY;
      const img = this.shadowRoot.querySelector('#vacuum-map'); if (img) img.style.transition = 'none';
    }
  }

  _handleTouchMove(e) {
    if (e.touches.length === 2 && this._lastPinchDist) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX, dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy), zoomFactor = dist / this._lastPinchDist;
      const wrapper = this.shadowRoot.querySelector('#map-wrapper'), rect = wrapper.getBoundingClientRect();
      const cx = this._pinchCenterX - rect.left - rect.width / 2, cy = this._pinchCenterY - rect.top - rect.height / 2;
      const newScale = Math.min(Math.max(0.5, this._scale * zoomFactor), 6);
      this._pointX = cx - (cx - this._pointX) * (newScale / this._scale); this._pointY = cy - (cy - this._pointY) * (newScale / this._scale);
      this._scale = newScale; this._lastPinchDist = dist; this._applyTransform();
    } else if (e.touches.length === 1 && this._isPanning) {
      e.preventDefault();
      this._pointX = e.touches[0].clientX - this._startX; this._pointY = e.touches[0].clientY - this._startY;
      this._applyTransform();
    }
  }
  _handleTouchEnd() { this._lastPinchDist = null; this._isPanning = false; }

  _getStatsHtml(t) {
    if (!this._hass || !this._config.entity_id) return '';
    const stateObj = this._hass.states[this._config.entity_id];
    if (!stateObj || !stateObj.attributes) return '';

    let baseName = stateObj.attributes.tuya_local_base || this._config.entity_id.split('.')[1];
    // Strip trailing numeric suffix like "_2", "_3" to allow fuzzy matching
    baseName = baseName.replace(/_\d+$/, '');
    
    const states = this._hass.states;
    
    const findState = (keywords) => {
       const key = Object.keys(states).find(k => k.startsWith(`sensor.${baseName}`) && keywords.some(kw => k.includes(kw)));
       return key ? states[key].state + ' ' + (states[key].attributes.unit_of_measurement || '').trim() : null;
    };

    const filter = findState(['filter', 'filtro']);
    const mainBrush = findState(['roll_brush', 'main_brush', 'spazzola_rotante']);
    const sideBrush = findState(['edge_brush', 'side_brush', 'spazzola_laterale']);
    const area = findState(['total_clean_area', 'area']);
    const time = findState(['total_cleaning_time', 'time']);
    const count = findState(['number_of_cleans', 'count']);

    if (!filter && !mainBrush && !sideBrush && !area && !time && !count) {
        return `
          <details class="stats-accordion">
            <summary>🔧 ${t.maintenance}</summary>
            <div class="stats-content" style="padding: 12px; font-size: 0.85em; color: var(--error-color, #e53935);">
              [Debug] Nessun sensore TuyaLocal trovato. Nome base cercato: <b>sensor.${baseName}_*</b>. Verifica l'entità TuyaLocal.
            </div>
          </details>
        `;
    }

    return `
      <details class="stats-accordion">
        <summary>🔧 ${t.maintenance}</summary>
        <div class="stats-content">
          ${filter ? `<div class="stat-item"><ha-icon icon="mdi:air-filter"></ha-icon><span class="stat-label">${t.filter}</span><span class="stat-val">${filter}</span></div>` : ''}
          ${mainBrush ? `<div class="stat-item"><ha-icon icon="mdi:brush"></ha-icon><span class="stat-label">${t.main_brush}</span><span class="stat-val">${mainBrush}</span></div>` : ''}
          ${sideBrush ? `<div class="stat-item"><ha-icon icon="mdi:brush-variant"></ha-icon><span class="stat-label">${t.side_brush}</span><span class="stat-val">${sideBrush}</span></div>` : ''}
          ${(filter||mainBrush||sideBrush) && (area||time||count) ? `<div class="stat-divider"></div>` : ''}
          ${area ? `<div class="stat-item"><ha-icon icon="mdi:texture-box"></ha-icon><span class="stat-label">${t.total_area}</span><span class="stat-val">${area}</span></div>` : ''}
          ${time ? `<div class="stat-item"><ha-icon icon="mdi:timer-outline"></ha-icon><span class="stat-label">${t.total_time}</span><span class="stat-val">${time}</span></div>` : ''}
          ${count ? `<div class="stat-item"><ha-icon icon="mdi:counter"></ha-icon><span class="stat-label">${t.clean_count}</span><span class="stat-val">${count}</span></div>` : ''}
        </div>
      </details>
    `;
  }

  _render() {
    if (!this._hass || !this._config.entity_id) return;
    const vacuumState = this._hass.states[this._config.entity_id];
    if (!vacuumState) return;

    const t = this._getT();
    const battery = vacuumState.attributes.battery_level ?? "?";
    const status = vacuumState.state;
    
    let roomsData = this._config.rooms || vacuumState.attributes.rooms;
    let roomsArray = [];
    if (Array.isArray(roomsData)) { roomsArray = roomsData; } 
    else if (typeof roomsData === 'object' && roomsData !== null) {
        roomsArray = Object.entries(roomsData).map(([id, name]) => ({id: id, name: name}));
    }

    const suctionLabels = {1: t.eco, 2: t.normal, 3: t.strong, 4: t.max};
    const waterLabels = {0: t.off, 1: t.low, 2: t.medium, 3: t.high};
    const PRESETS = [
      { name: "Eco", icon: "🌿", suction: 1, water: 0 },
      { name: "Standard", icon: "🏠", suction: 2, water: 1 },
      { name: "Turbo", icon: "🚀", suction: 4, water: 0 },
      { name: "Mocio", icon: "💧", suction: 2, water: 3 },
    ];

    let roomsHtml = roomsArray.map(room => {
      const orderIndex = this._selectedRooms.indexOf(room.id);
      const selected = orderIndex !== -1;
      let details = "";
      if (selected && this._roomSettings[room.id]) {
         const r = this._roomSettings[room.id];
         const sIcon = {1:"🍃", 2:"💨", 3:"🌪️", 4:"🚀"}[r.suction];
         const wIcon = {0:"⭕", 1:"💧", 2:"💧💧", 3:"💧💧💧"}[r.water];
         const pText = r.passes > 1 ? ` · ${r.passes}×` : "";
         const bIcon = r.carpet_boost ? " · 🏔️" : "";
         
         const suctionLabelsShort = {1: t.eco, 2: t.normal.substring(0,3), 3: t.strong.substring(0,3), 4: t.max};
         const waterLabelsShort = {0: t.off, 1: t.low.substring(0,3), 2: t.medium.substring(0,3), 3: t.high.substring(0,3)};
         
         details = `<div class="room-details">
           <span>${sIcon} ${suctionLabelsShort[r.suction]}</span>
           <span>${wIcon} ${waterLabelsShort[r.water]}</span>
           ${pText}${bIcon}
         </div>`;
      }
      return `<button class="room-btn ${selected ? 'selected' : ''}" data-id="${room.id}">
          <div class="room-name">${room.name} ${selected ? `<span class="badge">${orderIndex + 1}</span>` : ''}</div>
          ${details}
      </button>`;
    }).join("");

    if (this.shadowRoot.querySelector('.container')) {
        this.shadowRoot.querySelector('.header-status').innerText = `🔋 ${battery}% [${status}]`;
        this.shadowRoot.querySelector('.rooms').innerHTML = roomsHtml || `<span>${t.no_rooms}</span>`;
        this.shadowRoot.querySelector('#map-wrapper').className = `map-wrapper ${this._locked ? 'locked' : ''}`;
        this.shadowRoot.querySelector('#btn-lock').innerText = this._locked ? '🔒' : '🔓';
        const startBtn = this.shadowRoot.querySelector('#btn-start');
        if (startBtn) startBtn.disabled = this._selectedRooms.length === 0;
        this._updateSegButtons();
        this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => {
          btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id));
        });
        return;
    }

    const mapUrl = this._getMapUrl();
    const isMobile = window.matchMedia('(pointer: coarse)').matches;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; padding: 16px; background: var(--primary-background-color, #f0f0f0); color: var(--primary-text-color, #333); font-family: sans-serif; height: 100%; box-sizing: border-box; }
        .container { max-width: 800px; margin: 0 auto; background: var(--card-background-color, white); border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); overflow: hidden; display: flex; flex-direction: column; }
        .header { padding: 16px; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, white); display: flex; justify-content: space-between; align-items: center; font-size: 1.2em; }
        .header-title { display: flex; align-items: center; gap: 8px; }
        .header-actions { display: flex; align-items: center; gap: 12px; }
        .back-btn { background: transparent; border: none; color: white; font-size: 1.2em; cursor: pointer; padding: 4px; margin-right: 8px; border-radius: 50%; display: flex; align-items: center; }
        .icon-btn { background: rgba(255,255,255,0.2); border: none; cursor: pointer; font-size: 18px; color: white; padding: 6px; border-radius: 50%; display: flex; align-items: center; justify-content: center; transition: background-color 0.2s; }
        .icon-btn:hover { background: rgba(255,255,255,0.4); }
        .interactive-area { display: flex; flex-direction: column; transition: opacity 0.3s; }
        .map-wrapper { width: 100%; background: #333; display: flex; justify-content: center; align-items: center; height: 40vh; min-height: 300px; overflow: hidden; position: relative; cursor: grab; transition: all 0.3s ease; touch-action: none; }
        .map-wrapper.locked { pointer-events: none; opacity: 0.5; filter: grayscale(100%); }
        .map-wrapper:active { cursor: grabbing; }
        #vacuum-map { transform-origin: center center; max-width: 100%; max-height: 100%; object-fit: contain; }
        .controls { padding: 16px; }
        .seg-group { margin-bottom: 14px; }
        .seg-label { font-size: 0.85em; color: var(--secondary-text-color, #666); margin-bottom: 6px; font-weight: 500; }
        .seg-buttons { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
        .seg-btn { padding: 8px 2px; border: 1.5px solid var(--divider-color, #ddd); border-radius: 10px; background: var(--secondary-background-color, #f5f5f5); color: var(--primary-text-color, #333); cursor: pointer; font-size: 1em; text-align: center; line-height: 1.2; transition: all 0.15s ease; }
        .seg-btn small { display: block; font-size: 0.8em; opacity: 0.8; }
        .seg-btn.active { background: var(--primary-color, #03a9f4); color: white; border-color: var(--primary-color, #03a9f4); font-weight: 600; }
        .presets-row { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
        .preset-chip { padding: 6px 14px; border-radius: 20px; border: 1.5px solid var(--divider-color, #ddd); background: var(--secondary-background-color, #f5f5f5); color: var(--primary-text-color); cursor: pointer; font-size: 0.9em; transition: all 0.15s; }
        .preset-chip.active { background: var(--primary-color, #03a9f4); color: white; border-color: var(--primary-color, #03a9f4); }
        .rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; margin-bottom: 16px; }
        .room-btn { padding: 8px 4px; border: 1px solid var(--divider-color, #ccc); background: var(--secondary-background-color, #f9f9f9); border-radius: 12px; cursor: pointer; color: var(--primary-text-color, #333); display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 65px; }
        .room-name { font-weight: 500; font-size: 0.95em; margin-bottom: 2px; }
        .room-btn.selected { background: var(--primary-color, #03a9f4); color: white; border-color: var(--primary-color, #03a9f4); }
        .badge { background: white; color: var(--primary-color, #03a9f4); border-radius: 50%; padding: 2px 6px; font-size: 0.8em; font-weight: bold; margin-left: 4px; }
        .room-details { font-size: 0.7em; opacity: 0.9; display: flex; flex-direction: column; line-height: 1.1; }
        .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-top: 1px solid var(--divider-color, #eee); margin-top: 8px; }
        .toggle-switch { position: relative; display: inline-block; width: 48px; height: 26px; }
        .toggle-switch input { display: none; }
        .toggle-slider { position: absolute; inset: 0; background: #ccc; border-radius: 26px; transition: 0.3s; cursor: pointer; }
        .toggle-slider:before { content: ''; position: absolute; width: 20px; height: 20px; left: 3px; top: 3px; background: white; border-radius: 50%; transition: 0.3s; }
        .toggle-switch input:checked + .toggle-slider { background: var(--primary-color, #03a9f4); }
        .toggle-switch input:checked + .toggle-slider:before { transform: translateX(22px); }
        .actions { display: flex; gap: 8px; justify-content: center; }
        .action-btn { padding: 10px 12px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; flex-grow: 1; color: white; text-transform: uppercase; font-size: 0.9em; }
        .btn-start { background: #4caf50; } .btn-pause { background: #ff9800; } .btn-dock { background: #2196f3; } .btn-locate { background: #9c27b0; }
        .btn-start:disabled { background: #a5d6a7; cursor: not-allowed; opacity: 0.6; }
        .map-hint { position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,0.5); color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; pointer-events: none; }
        .stats-accordion { margin-top: 8px; border: 1px solid var(--divider-color, #eee); border-radius: 8px; overflow: hidden; background: var(--secondary-background-color, #f9f9f9); margin-bottom: 16px; }
        .stats-accordion summary { padding: 12px; font-weight: 500; cursor: pointer; outline: none; user-select: none; display: flex; align-items: center; }
        .stats-content { padding: 0 12px 12px 12px; display: flex; flex-direction: column; gap: 8px; }
        .stat-item { display: flex; align-items: center; justify-content: space-between; font-size: 0.9em; color: var(--primary-text-color); }
        .stat-item ha-icon { margin-right: 8px; color: var(--secondary-text-color); --mdc-icon-size: 20px; }
        .stat-label { flex-grow: 1; }
        .stat-val { font-weight: bold; }
        .stat-divider { height: 1px; background: var(--divider-color, #eee); margin: 4px 0; }
      </style>
      <div class="container">
        <div class="header">
          <div class="header-title"><button class="back-btn" id="btn-back">←</button><span>🤖 ${t.vacuum}</span></div>
          <div class="header-actions">
            <span class="header-status">🔋 ${battery}% [${status}]</span>
            <button class="icon-btn" id="btn-lock" title="Lock">${this._locked ? '🔒' : '🔓'}</button>
          </div>
        </div>
        <div class="interactive-area">
          <div class="map-wrapper ${this._locked ? 'locked' : ''}" id="map-wrapper">
            ${mapUrl ? `<img id="vacuum-map" src="${mapUrl}${mapUrl.includes('?') ? '&' : '?'}t=${Date.now()}" alt="Map" />` : '<span>Map unavailable</span>'}
            <div class="map-hint">${isMobile ? t.map_hint_mobile : t.map_hint_desktop}</div>
          </div>
          <div class="controls">
            <div class="presets-row">${PRESETS.map(p => `<button class="preset-chip ${this._activePreset === p.name ? 'active' : ''}" data-preset="${p.name}">${p.icon} ${p.name}</button>`).join('')}</div>
            <div class="seg-group"><div class="seg-label">💨 ${t.suction}</div><div class="seg-buttons" id="suction-seg"><button class="seg-btn ${this._currentSuction===1?'active':''}" data-val="1">🍃<br><small>${t.eco}</small></button><button class="seg-btn ${this._currentSuction===2?'active':''}" data-val="2">💨<br><small>${t.normal}</small></button><button class="seg-btn ${this._currentSuction===3?'active':''}" data-val="3">🌪️<br><small>${t.strong}</small></button><button class="seg-btn ${this._currentSuction===4?'active':''}" data-val="4">🚀<br><small>${t.max}</small></button></div></div>
            <div class="seg-group"><div class="seg-label">💧 ${t.water}</div><div class="seg-buttons" id="water-seg"><button class="seg-btn ${this._currentWater===0?'active':''}" data-val="0">⭕<br><small>${t.off}</small></button><button class="seg-btn ${this._currentWater===1?'active':''}" data-val="1">💧<br><small>${t.low}</small></button><button class="seg-btn ${this._currentWater===2?'active':''}" data-val="2">💧💧<br><small>${t.medium}</small></button><button class="seg-btn ${this._currentWater===3?'active':''}" data-val="3">💧💧💧<br><small>${t.high}</small></button></div></div>
            <div class="seg-group"><div class="seg-label">🔄 ${t.passes}</div><div class="seg-buttons" id="passes-seg" style="grid-template-columns: repeat(3, 1fr);"><button class="seg-btn ${this._passes===1?'active':''}" data-val="1">1×</button><button class="seg-btn ${this._passes===2?'active':''}" data-val="2">2×</button><button class="seg-btn ${this._passes===3?'active':''}" data-val="3">3×</button></div></div>
            <div class="toggle-row"><span>🏔️ ${t.carpet_boost}</span><label class="toggle-switch"><input type="checkbox" id="carpet-boost" ${this._carpetBoost ? 'checked' : ''}><span class="toggle-slider"></span></label></div>
            <div style="font-size: 0.9em; margin-top: 12px; margin-bottom: 8px; color: var(--secondary-text-color);">${t.select_rooms_hint}</div>
            <div class="rooms">${roomsHtml || `<span>${t.no_rooms}</span>`}</div>
            ${this._getStatsHtml(t)}
            <div class="actions"><button class="action-btn btn-pause" id="btn-pause">⏸ ${t.pause}</button><button class="action-btn btn-start" id="btn-start" ${this._selectedRooms.length === 0 ? 'disabled' : ''}>▶ ${t.start}</button><button class="action-btn btn-dock" id="btn-dock">🏠 ${t.dock}</button><button class="action-btn btn-locate" id="btn-locate">📍 ${t.locate}</button></div>
          </div>
        </div>
      </div>
    `;
    const wrapper = this.shadowRoot.querySelector('#map-wrapper');
    if (wrapper) {
      wrapper.addEventListener('wheel', (e) => this._handleWheel(e), { passive: false });
      wrapper.addEventListener('pointerdown', (e) => this._handlePointerDown(e));
      wrapper.addEventListener('pointerup', () => this._handlePointerUp());
      wrapper.addEventListener('pointerleave', () => this._handlePointerUp());
      wrapper.addEventListener('pointermove', (e) => this._handlePointerMove(e));
      wrapper.addEventListener('dblclick', () => this._handleDoubleClick());
      wrapper.addEventListener('touchstart', (e) => this._handleTouchStart(e), { passive: false });
      wrapper.addEventListener('touchmove', (e) => this._handleTouchMove(e), { passive: false });
      wrapper.addEventListener('touchend', () => this._handleTouchEnd());
    }
    this.shadowRoot.querySelectorAll('.room-btn').forEach(btn => { btn.addEventListener('click', (e) => this._toggleRoom(e.currentTarget.dataset.id)); });
    this.shadowRoot.querySelectorAll('.preset-chip').forEach(chip => { chip.addEventListener('click', (e) => this._applyPreset(e.target.dataset.preset)); });
    this.shadowRoot.querySelector('#suction-seg').addEventListener('click', (e) => { const btn = e.target.closest('.seg-btn'); if (!btn) return; this._currentSuction = parseInt(btn.dataset.val); this._activePreset = null; this._updateSegButtons(); });
    this.shadowRoot.querySelector('#water-seg').addEventListener('click', (e) => { const btn = e.target.closest('.seg-btn'); if (!btn) return; this._currentWater = parseInt(btn.dataset.val); this._activePreset = null; this._updateSegButtons(); });
    this.shadowRoot.querySelector('#passes-seg').addEventListener('click', (e) => { const btn = e.target.closest('.seg-btn'); if (!btn) return; this._passes = parseInt(btn.dataset.val); this.shadowRoot.querySelectorAll('#passes-seg .seg-btn').forEach(b => { b.classList.toggle('active', parseInt(b.dataset.val) === this._passes); }); });
    this.shadowRoot.querySelector('#carpet-boost').addEventListener('change', (e) => { this._carpetBoost = e.target.checked; });
    this.shadowRoot.querySelector('#btn-back').addEventListener('click', () => history.back());
    this.shadowRoot.querySelector('#btn-start').addEventListener('click', () => this._startCleaning());
    this.shadowRoot.querySelector('#btn-pause').addEventListener('click', () => this._callService("vacuum", "pause"));
    this.shadowRoot.querySelector('#btn-dock').addEventListener('click', () => this._callService("vacuum", "return_to_base"));
    this.shadowRoot.querySelector('#btn-locate').addEventListener('click', () => this._callService("vacuum", "locate"));
    this.shadowRoot.querySelector('#btn-lock').addEventListener('click', () => { this._locked = !this._locked; this._render(); });
  }
}
customElements.define("vacuum-panel", VacuumPanel);

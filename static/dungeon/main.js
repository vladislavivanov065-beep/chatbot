(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/dungeon');

  const THEME_COLORS = {
    forest: { floor: '#3b5d3a', wall: '#20301f' },
    cave: { floor: '#4a4a52', wall: '#26262c' },
    ruins: { floor: '#6b5b3e', wall: '#3a3020' },
  };
  const SLOT_NAMES = { helmet: 'Шлем', armor: 'Доспехи', weapon: 'Оружие', shield: 'Щит' };
  const SLOT_EMOJI = { helmet: '🪖', armor: '🛡', weapon: '⚔️', shield: '🔰' };

  const waitingCard = document.getElementById('waiting-card');
  const waitingStatus = document.getElementById('waiting-status');
  const waitingPlayers = document.getElementById('waiting-players');
  const joinBtn = document.getElementById('join-btn');
  const startBtn = document.getElementById('start-btn');

  const finishedCard = document.getElementById('finished-card');
  const finishedBanner = document.getElementById('finished-banner');
  const finishedLog = document.getElementById('finished-log');

  const gameLayout = document.getElementById('game-layout');
  const hudPlayers = document.getElementById('hud-players');
  const hudStatus = document.getElementById('hud-status');
  const mapGrid = document.getElementById('map-grid');
  const hintText = document.getElementById('hint-text');
  const equipmentSlots = document.getElementById('equipment-slots');
  const inventoryList = document.getElementById('inventory-list');
  const eventLog = document.getElementById('event-log');

  const shopOverlay = document.getElementById('shop-overlay');
  const shopGold = document.getElementById('shop-gold');
  const shopItems = document.getElementById('shop-items');
  const shopCloseBtn = document.getElementById('shop-close-btn');
  const shopOpenBtn = document.getElementById('shop-open-btn');

  let lastState = null;
  let shopOpen = false;
  let hintTimer = null;

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/dungeon/';
  });

  socket.on('action_error', (data) => {
    window.__lastActionError = (data && data.message) || 'Действие невозможно';
    flashHint(window.__lastActionError, true);
  });

  socket.on('state', (state) => {
    lastState = state;
    window.__lastStateForTest = state;
    render();
  });

  function flashHint(text, isError) {
    hintText.textContent = text;
    hintText.style.color = isError ? '#ff9d98' : '';
    if (hintTimer) clearTimeout(hintTimer);
    hintTimer = setTimeout(() => {
      hintText.textContent = '';
      hintText.style.color = '';
    }, 3000);
  }

  function submitTurn(action) {
    socket.emit('submit_action', { token, lobby_id: lobbyId, action });
  }

  // ---------- top-level render ----------

  function render() {
    if (!lastState) return;

    if (!lastState.started) {
      waitingCard.hidden = false;
      finishedCard.hidden = true;
      gameLayout.hidden = true;
      renderWaiting();
      return;
    }

    waitingCard.hidden = true;

    if (lastState.finished) {
      finishedCard.hidden = false;
      gameLayout.hidden = true;
      renderFinished();
      return;
    }

    finishedCard.hidden = true;
    gameLayout.hidden = false;
    renderGame();
  }

  function renderWaiting() {
    const seats = lastState.seats || [];
    waitingStatus.innerHTML =
      `Карта: <b>${lastState.theme_name}</b> · Отряд: <b>${seats.length} / ${lastState.max_players}</b>`;
    waitingPlayers.textContent = seats.length ? seats.join(', ') : 'Пока никого нет';

    const alreadyIn = lastState.my_seat !== null && lastState.my_seat !== undefined;
    joinBtn.hidden = alreadyIn;
    joinBtn.disabled = seats.length >= lastState.max_players;
    startBtn.hidden = !(window.IS_CREATOR && lastState.can_start);
  }

  function renderFinished() {
    finishedBanner.textContent = lastState.victory
      ? '🏆 Отряд побеждает! Босс повержен.'
      : '💀 Отряд пал в подземелье.';
    finishedLog.innerHTML = (lastState.log || []).map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- game screen ----------

  function renderGame() {
    const s = lastState;
    const me = s.players.find((p) => p.token === token);

    hudStatus.innerHTML =
      `Карта: <b>${s.theme_name}</b> · Раунд: <b>${s.round}</b> · Золото отряда: <b>${s.gold}</b>💰`;

    renderHud();
    renderMap(me);
    renderEquipment(me);
    renderInventory(me);
    renderLog();
    renderShopButton(me);
    renderShop(me);

    if (me && me.status === 'downed') {
      flashHintPersistent(`Вы повержены! Осталось ${me.downed_remaining ?? '?'} сек, чтобы союзник вас оживил.`);
    } else if (!hintTimer) {
      const waitingOn = s.waiting_on || [];
      if (waitingOn.length && !waitingOn.includes(token)) {
        hintText.textContent = `Ждём ход: ${waitingOn.join(', ')}`;
      } else if (me && me.status === 'alive') {
        hintText.textContent = 'Кликните по соседней клетке: пусто — идти, враг — атаковать, союзник на земле — оживить.';
      }
    }
  }

  function flashHintPersistent(text) {
    hintText.textContent = text;
    hintText.style.color = '#ff9d98';
  }

  function renderHud() {
    hudPlayers.innerHTML = '';
    (lastState.players || []).forEach((p) => {
      const box = document.createElement('div');
      box.className = 'hud-player';
      if (p.token === token) box.classList.add('me');
      if (p.status === 'downed') box.classList.add('downed');
      if (p.status === 'dead') box.classList.add('dead');

      const name = document.createElement('div');
      name.className = 'hud-name';
      name.innerHTML = `<span>${p.token}${p.token === token ? ' (вы)' : ''}</span><span>${p.hp}/${p.max_hp}</span>`;
      box.appendChild(name);

      const track = document.createElement('div');
      track.className = 'hp-bar-track';
      const fill = document.createElement('div');
      fill.className = 'hp-bar-fill' + (p.hp / p.max_hp < 0.35 ? ' low' : '');
      fill.style.width = Math.max(0, Math.round((100 * p.hp) / p.max_hp)) + '%';
      track.appendChild(fill);
      box.appendChild(track);

      if (p.status === 'downed' && p.downed_remaining !== null) {
        const timer = document.createElement('div');
        timer.className = 'downed-timer';
        timer.textContent = `⏳ ${p.downed_remaining} сек на спасение`;
        box.appendChild(timer);
      } else if (p.status === 'dead') {
        const timer = document.createElement('div');
        timer.className = 'downed-timer';
        timer.textContent = 'выбыл из забега';
        box.appendChild(timer);
      }

      hudPlayers.appendChild(box);
    });
  }

  function renderMap(me) {
    const s = lastState;
    const colors = THEME_COLORS[s.theme] || THEME_COLORS.forest;
    mapGrid.style.setProperty('--floor-color', colors.floor);
    mapGrid.style.setProperty('--wall-color', colors.wall);
    mapGrid.innerHTML = '';

    const enemyAt = {};
    s.enemies.forEach((e) => (enemyAt[e.x + ',' + e.y] = e));
    const playersAt = {};
    s.players.forEach((p) => {
      if (p.status === 'dead') return;
      const key = p.x + ',' + p.y;
      (playersAt[key] = playersAt[key] || []).push(p);
    });
    const itemAt = {};
    s.floor_items.forEach((fi) => (itemAt[fi.x + ',' + fi.y] = fi.item));
    const shop = s.shop_tile;
    const canAct = me && me.status === 'alive';

    for (let y = 0; y < s.height; y++) {
      for (let x = 0; x < s.width; x++) {
        const ch = s.grid[y][x];
        const isFloor = ch === '.';
        const key = x + ',' + y;
        const tile = document.createElement('div');
        tile.className = 'tile ' + (isFloor ? 'floor' : 'wall');

        const isShop = isFloor && shop && shop[0] === x && shop[1] === y;
        if (isShop) tile.classList.add('shop');

        const enemy = enemyAt[key];
        const here = playersAt[key];

        if (enemy) {
          tile.textContent = enemy.emoji;
          const hpWrap = document.createElement('div');
          hpWrap.className = 'mini-hp';
          const hpFill = document.createElement('div');
          hpFill.className = 'mini-hp-fill';
          hpFill.style.width = Math.max(0, Math.round((100 * enemy.hp) / enemy.max_hp)) + '%';
          hpWrap.appendChild(hpFill);
          tile.appendChild(hpWrap);
          tile.title = `${enemy.name} (${enemy.hp}/${enemy.max_hp})`;
        } else if (here && here.length) {
          const anyDowned = here.some((p) => p.status === 'downed');
          tile.textContent = anyDowned ? '💀' : '🧑';
          tile.title = here.map((p) => `${p.token} (${p.status})`).join(', ');
          if (here.some((p) => p.token === token)) tile.classList.add('player-here');
        } else if (itemAt[key]) {
          tile.textContent = '✨';
          tile.title = itemAt[key].name;
        } else if (isShop) {
          tile.textContent = '🏪';
          tile.title = 'Магазин';
        }

        if (canAct && isFloor && Math.abs(me.x - x) + Math.abs(me.y - y) === 1) {
          if (enemy) {
            tile.classList.add('actionable');
            tile.addEventListener('click', () => submitTurn({ type: 'attack', target: [x, y] }));
          } else if (here && here.some((p) => p.status === 'downed')) {
            const ally = here.find((p) => p.status === 'downed');
            tile.classList.add('actionable');
            tile.addEventListener('click', () => submitTurn({ type: 'revive', target: ally.token }));
          } else {
            tile.classList.add('actionable');
            tile.addEventListener('click', () => submitTurn({ type: 'move', dx: x - me.x, dy: y - me.y }));
          }
        }

        mapGrid.appendChild(tile);
      }
    }
  }

  function itemLabel(item) {
    const parts = [];
    if (item.attack) parts.push(`⚔️${item.attack}`);
    if (item.defense) parts.push(`🛡${item.defense}`);
    if (item.hp) parts.push(`❤️${item.hp}`);
    return parts.join(' ');
  }

  function renderEquipment(me) {
    equipmentSlots.innerHTML = '';
    if (!me) return;
    ['helmet', 'armor', 'weapon', 'shield'].forEach((slot) => {
      const item = me.equipment[slot];
      const box = document.createElement('div');
      box.className = 'equip-slot';
      const title = document.createElement('div');
      title.className = 'slot-title';
      title.textContent = SLOT_EMOJI[slot] + ' ' + SLOT_NAMES[slot];
      box.appendChild(title);
      const body = document.createElement('div');
      if (item) {
        body.className = 'tier-' + item.tier;
        body.textContent = item.name;
        const stats = document.createElement('div');
        stats.textContent = itemLabel(item);
        box.appendChild(body);
        box.appendChild(stats);
      } else {
        body.textContent = 'пусто';
        body.style.color = '#7d6f95';
        box.appendChild(body);
      }
      equipmentSlots.appendChild(box);
    });
  }

  function renderInventory(me) {
    inventoryList.innerHTML = '';
    if (!me || !me.inventory.length) {
      const empty = document.createElement('p');
      empty.className = 'hint-text';
      empty.textContent = 'Инвентарь пуст.';
      inventoryList.appendChild(empty);
      return;
    }
    me.inventory.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'inv-item';
      const label = document.createElement('span');
      label.className = 'tier-' + item.tier;
      label.textContent = `${SLOT_EMOJI[item.slot]} ${item.name} ${itemLabel(item)}`;
      row.appendChild(label);

      const actions = document.createElement('div');
      actions.className = 'inv-actions';
      const equipBtn = document.createElement('button');
      equipBtn.className = 'btn btn-small';
      equipBtn.textContent = 'Надеть';
      equipBtn.onclick = () => socket.emit('equip_item', { token, lobby_id: lobbyId, item_id: item.id });
      const sellBtn = document.createElement('button');
      sellBtn.className = 'btn btn-ghost btn-small';
      sellBtn.textContent = `Продать (${Math.max(1, Math.floor(item.price / 2))}💰)`;
      sellBtn.onclick = () => socket.emit('sell_item', { token, lobby_id: lobbyId, item_id: item.id });
      actions.appendChild(equipBtn);
      actions.appendChild(sellBtn);
      row.appendChild(actions);

      inventoryList.appendChild(row);
    });
  }

  function renderLog() {
    eventLog.innerHTML = (lastState.log || [])
      .slice()
      .reverse()
      .map((l) => `<div>${l}</div>`)
      .join('');
  }

  function isOnShop(me) {
    const s = lastState;
    return !!(me && s.shop_tile && me.x === s.shop_tile[0] && me.y === s.shop_tile[1]);
  }

  function renderShopButton(me) {
    const s = lastState;
    const available = isOnShop(me) && s.shop_stock && s.shop_stock.length > 0;
    shopOpenBtn.hidden = !available;
    if (!available) shopOpen = false;
  }

  function renderShop(me) {
    const s = lastState;
    if (!shopOpen || !isOnShop(me) || !s.shop_stock || !s.shop_stock.length) {
      shopOverlay.hidden = true;
      return;
    }
    shopOverlay.hidden = false;
    shopGold.textContent = s.gold;
    shopItems.innerHTML = '';
    s.shop_stock.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'shop-item';
      const label = document.createElement('span');
      label.className = 'tier-' + item.tier;
      label.textContent = `${SLOT_EMOJI[item.slot]} ${item.name} ${itemLabel(item)}`;
      const buyBtn = document.createElement('button');
      buyBtn.className = 'btn btn-small';
      buyBtn.textContent = `Купить (${item.price}💰)`;
      buyBtn.disabled = s.gold < item.price;
      buyBtn.onclick = () => socket.emit('buy_item', { token, lobby_id: lobbyId, item_id: item.id });
      row.appendChild(label);
      row.appendChild(buyBtn);
      shopItems.appendChild(row);
    });
  }

  joinBtn.addEventListener('click', () => {
    socket.emit('join', { token, lobby_id: lobbyId });
  });

  startBtn.addEventListener('click', () => {
    socket.emit('start_game', { token, lobby_id: lobbyId });
  });

  shopCloseBtn.addEventListener('click', () => {
    shopOpen = false;
    shopOverlay.hidden = true;
  });

  shopOpenBtn.addEventListener('click', () => {
    shopOpen = true;
    const me = lastState && lastState.players.find((p) => p.token === token);
    renderShop(me);
  });
})();

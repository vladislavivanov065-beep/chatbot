(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/battleship');

  const waitingCard = document.getElementById('waiting-card');
  const waitingStatus = document.getElementById('waiting-status');
  const waitingPlayers = document.getElementById('waiting-players');
  const joinBtn = document.getElementById('join-btn');
  const startBtn = document.getElementById('start-btn');

  const placingCard = document.getElementById('placing-card');
  const placingStatus = document.getElementById('placing-status');
  const ownBoardGrid = document.getElementById('own-board-grid');
  const shipListEl = document.getElementById('ship-list');
  const rotateBtn = document.getElementById('rotate-btn');
  const randomizeBtn = document.getElementById('randomize-btn');
  const readyBtn = document.getElementById('ready-btn');
  const placingHint = document.getElementById('placing-hint');
  const othersReadyList = document.getElementById('others-ready-list');

  const finishedCard = document.getElementById('finished-card');
  const finishedBanner = document.getElementById('finished-banner');
  const finishedLog = document.getElementById('finished-log');

  const battleLayout = document.getElementById('battle-layout');
  const battleStatus = document.getElementById('battle-status');
  const targetsTabs = document.getElementById('targets-tabs');
  const myBoardGrid = document.getElementById('my-board-grid');
  const targetBoardTitle = document.getElementById('target-board-title');
  const targetBoardGrid = document.getElementById('target-board-grid');
  const battleHint = document.getElementById('battle-hint');
  const battleLog = document.getElementById('battle-log');

  let lastState = null;
  let heldShipSize = null;
  let orientation = true;   // true = horizontal
  let selectedTarget = null;
  let ownCellEls = [];

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/battleship/';
  });

  socket.on('action_error', (data) => {
    const msg = (data && data.message) || 'Действие невозможно';
    window.__lastActionError = msg;
    const el = lastState && lastState.phase === 'placing' ? placingHint : battleHint;
    if (el) {
      el.textContent = msg;
      el.style.color = '#ff9d90';
      setTimeout(() => {
        el.textContent = '';
        el.style.color = '';
      }, 3000);
    }
  });

  socket.on('state', (state) => {
    lastState = state;
    window.__lastStateForTest = state;
    render();
  });

  function submit(event, payload) {
    socket.emit(event, Object.assign({ token, lobby_id: lobbyId }, payload));
  }

  // ---------- top-level render ----------

  function render() {
    if (!lastState) return;
    waitingCard.hidden = true;
    placingCard.hidden = true;
    finishedCard.hidden = true;
    battleLayout.hidden = true;

    if (lastState.phase === 'waiting') {
      waitingCard.hidden = false;
      renderWaitingScreen();
    } else if (lastState.phase === 'placing') {
      placingCard.hidden = false;
      renderPlacingScreen();
    } else if (lastState.phase === 'finished') {
      finishedCard.hidden = false;
      renderFinishedScreen();
    } else {
      battleLayout.hidden = false;
      renderBattleScreen();
    }
  }

  function renderWaitingScreen() {
    const seats = lastState.seats || [];
    waitingStatus.innerHTML = `Игроков: <b>${seats.length} / ${lastState.max_players}</b>`;
    waitingPlayers.textContent = seats.length ? seats.join(', ') : 'Пока никого нет';

    const alreadyIn = lastState.my_seat !== null && lastState.my_seat !== undefined;
    joinBtn.hidden = alreadyIn;
    joinBtn.disabled = seats.length >= lastState.max_players;
    startBtn.hidden = !(window.IS_CREATOR && lastState.can_start);
  }

  function renderFinishedScreen() {
    const iWon = lastState.winner === token;
    finishedBanner.textContent = lastState.winner
      ? (iWon ? '🏆 Вы победили в морском бою!' : `🏆 Победил игрок: ${lastState.winner}`)
      : 'Бой завершён.';
    finishedLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- placement screen ----------

  function cellsFor(x, y, size, horizontal) {
    const cells = [];
    for (let i = 0; i < size; i++) cells.push(horizontal ? [x + i, y] : [x, y + i]);
    return cells;
  }

  function buildGridFromShips(ships) {
    const grid = Array.from({ length: 10 }, () => Array(10).fill('empty'));
    (ships || []).forEach((s) => s.cells.forEach(([x, y]) => {
      if (x >= 0 && x < 10 && y >= 0 && y < 10) grid[y][x] = 'ship';
    }));
    return grid;
  }

  function wouldFit(grid, cells) {
    for (const [cx, cy] of cells) {
      if (cx < 0 || cx >= 10 || cy < 0 || cy >= 10) return false;
      if (grid[cy][cx] === 'ship') return false;
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const nx = cx + dx, ny = cy + dy;
          if (nx >= 0 && nx < 10 && ny >= 0 && ny < 10 && grid[ny][nx] === 'ship') return false;
        }
      }
    }
    return true;
  }

  function groupSizes(sizes) {
    const counts = {};
    (sizes || []).forEach((s) => { counts[s] = (counts[s] || 0) + 1; });
    return Object.keys(counts).map(Number).sort((a, b) => b - a).map((size) => ({ size, count: counts[size] }));
  }

  function renderShipList() {
    shipListEl.innerHTML = '';
    groupSizes(lastState.remaining_sizes).forEach(({ size, count }) => {
      const opt = document.createElement('div');
      opt.className = 'ship-option' + (heldShipSize === size ? ' selected' : '');
      const dots = document.createElement('div');
      dots.className = 'ship-dots';
      for (let i = 0; i < size; i++) dots.appendChild(document.createElement('span'));
      opt.appendChild(dots);
      const countEl = document.createElement('div');
      countEl.className = 'ship-count';
      countEl.textContent = `×${count}`;
      opt.appendChild(countEl);
      opt.addEventListener('click', () => {
        heldShipSize = size;
        render();
      });
      shipListEl.appendChild(opt);
    });
  }

  function showGhost(x, y) {
    if (!heldShipSize) return;
    const grid = buildGridFromShips(lastState.my_ships);
    const cells = cellsFor(x, y, heldShipSize, orientation);
    const valid = wouldFit(grid, cells);
    cells.forEach(([cx, cy]) => {
      if (cx >= 0 && cx < 10 && cy >= 0 && cy < 10) {
        ownCellEls[cy][cx].classList.add(valid ? 'ghost-valid' : 'ghost-invalid');
      }
    });
  }

  function clearGhost() {
    ownCellEls.forEach((row) => row.forEach((c) => c && c.classList.remove('ghost-valid', 'ghost-invalid')));
  }

  function renderOwnBoardGrid() {
    ownBoardGrid.innerHTML = '';
    ownCellEls = [];
    const grid = buildGridFromShips(lastState.my_ships);
    const cellToShip = {};
    (lastState.my_ships || []).forEach((s) => s.cells.forEach(([x, y]) => { cellToShip[x + ',' + y] = s.id; }));

    for (let y = 0; y < 10; y++) {
      ownCellEls[y] = [];
      for (let x = 0; x < 10; x++) {
        const cell = document.createElement('div');
        cell.className = 'bs-cell';
        const key = x + ',' + y;
        if (grid[y][x] === 'ship') {
          cell.classList.add('ship', 'own-placed');
          cell.addEventListener('click', () => submit('remove_ship', { ship_id: cellToShip[key] }));
        } else if (heldShipSize && !lastState.ready) {
          cell.addEventListener('mouseenter', () => showGhost(x, y));
          cell.addEventListener('mouseleave', clearGhost);
          cell.addEventListener('click', () => submit('place_ship', { x, y, size: heldShipSize, horizontal: orientation }));
        }
        ownCellEls[y][x] = cell;
        ownBoardGrid.appendChild(cell);
      }
    }
  }

  function renderPlacingScreen() {
    const remaining = lastState.remaining_sizes || [];
    if (!remaining.includes(heldShipSize)) heldShipSize = remaining[0] || null;

    placingStatus.innerHTML = lastState.ready
      ? 'Вы готовы. Ожидаем остальных игроков…'
      : `Осталось расставить кораблей: <b>${remaining.length}</b> из 10`;

    renderShipList();
    renderOwnBoardGrid();

    readyBtn.disabled = remaining.length > 0 || lastState.ready;
    readyBtn.textContent = lastState.ready ? 'Готово ✅' : 'Готов к бою';

    othersReadyList.innerHTML = Object.entries(lastState.others_ready || {})
      .map(([t, r]) => `<div class="ready-row ${r ? 'ready' : ''}">${t}: ${r ? '✅ готов' : '⏳ расставляет'}</div>`)
      .join('');
  }

  // ---------- battle screen ----------

  function renderBattleScreen() {
    const s = lastState;
    battleStatus.innerHTML = s.is_my_turn ? '<b>Ваш ход! Выберите цель и клетку.</b>' : `Ход игрока: <b>${s.turn_token}</b>`;
    renderTargetsTabs();
    renderMyBoard();
    renderTargetBoard();
    renderBattleLog();
  }

  function renderTargetsTabs() {
    targetsTabs.innerHTML = '';
    const opponents = lastState.opponents || {};
    const keys = Object.keys(opponents);
    if (!selectedTarget || !opponents[selectedTarget]) {
      selectedTarget = (lastState.targets && lastState.targets[0]) || keys[0] || null;
    }
    keys.forEach((t) => {
      const opp = opponents[t];
      const tab = document.createElement('div');
      tab.className = 'target-tab' +
        (t === selectedTarget ? ' selected' : '') +
        (!opp.alive ? ' eliminated' : '') +
        (lastState.turn_token === t ? ' my-turn-target' : '');
      tab.textContent = t + (opp.alive ? '' : ' 💀');
      tab.addEventListener('click', () => {
        selectedTarget = t;
        renderBattleScreen();
      });
      targetsTabs.appendChild(tab);
    });
  }

  function renderMyBoard() {
    myBoardGrid.innerHTML = '';
    const grid = lastState.my_board;
    for (let y = 0; y < 10; y++) {
      for (let x = 0; x < 10; x++) {
        const cell = document.createElement('div');
        cell.className = 'bs-cell ' + grid[y][x];
        myBoardGrid.appendChild(cell);
      }
    }
  }

  function renderTargetBoard() {
    const opponents = lastState.opponents || {};
    const opp = selectedTarget ? opponents[selectedTarget] : null;
    targetBoardTitle.textContent = opp ? `Поле игрока ${selectedTarget}` : 'Нет доступных целей';
    targetBoardGrid.innerHTML = '';
    if (!opp) return;

    const canFire = !!lastState.is_my_turn && opp.alive;
    for (let y = 0; y < 10; y++) {
      for (let x = 0; x < 10; x++) {
        const cell = document.createElement('div');
        const val = opp.grid[y][x];
        cell.className = 'bs-cell ' + val;
        if (canFire && val === 'unknown') {
          cell.classList.add('targetable');
          cell.addEventListener('click', () => submit('fire', { target: selectedTarget, x, y }));
        }
        targetBoardGrid.appendChild(cell);
      }
    }

    battleHint.textContent = canFire
      ? 'Кликните по клетке, чтобы выстрелить.'
      : (opp.alive ? 'Дождитесь своего хода.' : 'Этот игрок уже выбыл из боя.');
  }

  function renderBattleLog() {
    battleLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- controls ----------

  joinBtn.addEventListener('click', () => submit('join', {}));
  startBtn.addEventListener('click', () => submit('start_placement', {}));
  rotateBtn.addEventListener('click', () => { orientation = !orientation; });
  randomizeBtn.addEventListener('click', () => submit('randomize_board', {}));
  readyBtn.addEventListener('click', () => submit('set_ready', {}));
})();

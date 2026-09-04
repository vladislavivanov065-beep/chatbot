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
  const myBoardGrid = document.getElementById('my-board-grid');
  const opponentBoardsEl = document.getElementById('opponent-boards');
  const battleHint = document.getElementById('battle-hint');
  const battleLog = document.getElementById('battle-log');

  let lastState = null;
  let heldShipSize = null;
  let orientation = true;   // true = horizontal
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

  // Maps "x,y" -> a CSS segment class (bow/stern/mid/solo, oriented) so ships
  // render as connected boat hulls instead of plain squares.
  function shipShapeMap(ships) {
    const map = {};
    (ships || []).forEach((s) => {
      const cells = s.cells;
      const n = cells.length;
      const horizontal = n > 1 ? cells[0][1] === cells[1][1] : true;
      cells.forEach(([x, y], i) => {
        let cls;
        if (n === 1) cls = 'seg-solo';
        else if (i === 0) cls = horizontal ? 'seg-h-start' : 'seg-v-start';
        else if (i === n - 1) cls = horizontal ? 'seg-h-end' : 'seg-v-end';
        else cls = horizontal ? 'seg-h-mid' : 'seg-v-mid';
        map[x + ',' + y] = cls;
      });
    });
    return map;
  }

  function shipSunkCellSet(ships) {
    const set = new Set();
    (ships || []).forEach((s) => {
      if (s.sunk) s.cells.forEach(([x, y]) => set.add(x + ',' + y));
    });
    return set;
  }

  // Cells surrounding a sunk ship (including diagonals) — since ships can
  // never touch, these are guaranteed empty water, so we dot-mark them.
  function sunkBorderCellSet(ships) {
    const shipCells = new Set();
    (ships || []).forEach((s) => {
      if (s.sunk) s.cells.forEach(([x, y]) => shipCells.add(x + ',' + y));
    });
    const border = new Set();
    (ships || []).forEach((s) => {
      if (!s.sunk) return;
      s.cells.forEach(([x, y]) => {
        for (let dx = -1; dx <= 1; dx++) {
          for (let dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            const nx = x + dx, ny = y + dy;
            const key = nx + ',' + ny;
            if (nx >= 0 && nx < 10 && ny >= 0 && ny < 10 && !shipCells.has(key)) border.add(key);
          }
        }
      });
    });
    return border;
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
    const shapeMap = shipShapeMap(lastState.my_ships);

    for (let y = 0; y < 10; y++) {
      ownCellEls[y] = [];
      for (let x = 0; x < 10; x++) {
        const cell = document.createElement('div');
        cell.className = 'bs-cell';
        const key = x + ',' + y;
        if (grid[y][x] === 'ship') {
          cell.classList.add('ship', 'own-placed');
          if (shapeMap[key]) cell.classList.add(shapeMap[key]);
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
    const opponents = s.opponents || {};
    const opponentCount = Object.keys(opponents).length;
    const allMode = s.fire_mode !== 'single';
    if (s.is_my_turn) {
      battleStatus.innerHTML = allMode && opponentCount > 1
        ? '<b>Ваш ход! Кликните по клетке — выстрел ударит по всем полям соперников сразу.</b>'
        : (opponentCount > 1
          ? '<b>Ваш ход! Кликните по клетке на поле нужного соперника.</b>'
          : '<b>Ваш ход! Выберите клетку.</b>');
    } else {
      battleStatus.innerHTML = `Ход игрока: <b>${s.turn_token}</b>`;
    }
    renderMyBoard();
    renderOpponentBoards();
    renderBattleLog();
  }

  function renderMyBoard() {
    myBoardGrid.innerHTML = '';
    const grid = lastState.my_board;
    const shapeMap = shipShapeMap(lastState.my_ships);
    const sunkCells = shipSunkCellSet(lastState.my_ships);
    const borderCells = sunkBorderCellSet(lastState.my_ships);
    for (let y = 0; y < 10; y++) {
      for (let x = 0; x < 10; x++) {
        const cell = document.createElement('div');
        const key = x + ',' + y;
        const val = grid[y][x];
        cell.className = 'bs-cell ' + val;
        if (shapeMap[key]) {
          cell.classList.add(shapeMap[key]);
          if (sunkCells.has(key)) cell.classList.add('seg-sunk');
        } else if (val === 'empty' && borderCells.has(key)) {
          cell.classList.add('border-dot');
        }
        myBoardGrid.appendChild(cell);
      }
    }
  }

  function renderOpponentBoards() {
    const opponents = lastState.opponents || {};
    const entries = Object.entries(opponents);
    opponentBoardsEl.innerHTML = '';

    const myTurn = !!lastState.is_my_turn;
    const anyAlive = entries.some(([, opp]) => opp.alive);

    entries.forEach(([t, opp]) => {
      const panel = document.createElement('div');
      panel.className = 'board-panel';

      const title = document.createElement('h3');
      title.style.marginTop = '0';
      title.textContent = `Поле игрока ${t}` + (opp.alive ? '' : ' 💀');
      panel.appendChild(title);

      const grid = document.createElement('div');
      grid.className = 'bs-grid';
      const canFire = myTurn && opp.alive;
      const shapeMap = shipShapeMap(opp.sunk_ships);
      const borderCells = sunkBorderCellSet(opp.sunk_ships);

      for (let y = 0; y < 10; y++) {
        for (let x = 0; x < 10; x++) {
          const cell = document.createElement('div');
          const key = x + ',' + y;
          const val = opp.grid[y][x];
          cell.className = 'bs-cell ' + val;
          if (val === 'sunk') {
            if (shapeMap[key]) cell.classList.add(shapeMap[key]);
          } else if (val === 'unknown' && borderCells.has(key)) {
            cell.classList.add('border-dot');
          }
          if (canFire && val === 'unknown') {
            cell.classList.add('targetable');
            cell.addEventListener('click', () => submit('fire', { x, y, target: t }));
          }
          grid.appendChild(cell);
        }
      }
      panel.appendChild(grid);
      opponentBoardsEl.appendChild(panel);
    });

    const allMode = lastState.fire_mode !== 'single';
    battleHint.textContent = myTurn
      ? (anyAlive
        ? (allMode
          ? 'Кликните по любой клетке на любом поле — выстрел ударит все живые поля соперников одновременно.'
          : 'Кликните по клетке на поле того соперника, по которому хотите выстрелить.')
        : '')
      : 'Дождитесь своего хода.';
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

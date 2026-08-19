(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/chess');

  const boardEl = document.getElementById('board');
  const statusEl = document.getElementById('status');
  const scoreEl = document.getElementById('score');
  const seatsEl = document.getElementById('seats-panel');
  const joinBtn = document.getElementById('join-btn');
  const restartBtn = document.getElementById('restart-btn');
  const spriteHolder = document.getElementById('piece-sprite-holder');
  const abilitiesEl = document.getElementById('abilities-panel');
  const abilityHintEl = document.getElementById('ability-hint');

  const ABILITY_ORDER = [
    'shield', 'attack_through', 'skip_turn', 'fog',
    'extra_turn', 'revival', 'teleport', 'freeze', 'explosion',
  ];

  const ABILITY_DEFS = {
    shield: { icon: '🛡', name: 'Щит королю', flow: 'instant' },
    attack_through: { icon: '⚔', name: 'Удар через фигуру', flow: 'piece-target', pieceFilter: (p) => ['R', 'B', 'Q'].includes(p.type) },
    skip_turn: { icon: '⏭', name: 'Пропуск хода', flow: 'seat' },
    fog: { icon: '🌫', name: 'Туман войны (2 круга)', flow: 'instant' },
    extra_turn: { icon: '⏩', name: 'Двойной ход', flow: 'instant' },
    revival: { icon: '♻️', name: 'Воскрешение пешки', flow: 'square', targets: squareTargetsRevival },
    teleport: { icon: '🌀', name: 'Телепорт', flow: 'piece-target', pieceFilter: () => true, freeTarget: true },
    freeze: { icon: '❄', name: 'Заморозка фигуры', flow: 'square', targets: squareTargetsFreeze },
    explosion: { icon: '💥', name: 'Взрыв', flow: 'square', targets: squareTargetsExplosion },
  };

  let lastState = null;
  let selected = null; // [r, c] - обычный ход
  let legalTargets = [];
  let spriteReady = false;

  let pendingAbility = null; // ключ способности
  let abilityStage = null; // 'need-piece' | 'need-target' | 'need-seat'
  let abilityFrom = null; // [r, c]
  let abilityTargets = []; // [[r,c], ...]

  fetch(spriteHolder ? '/static/chess/pieces.svg' : '')
    .then((r) => r.text())
    .then((svgText) => {
      spriteHolder.innerHTML = svgText;
      spriteReady = true;
      if (lastState) renderBoard();
    })
    .catch(() => {});

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/chess/';
  });

  socket.on('state', (state) => {
    lastState = state;
    selected = null;
    legalTargets = [];
    cancelAbility();
    render();
  });

  socket.on('join_error', (data) => flashStatus(data.message));
  socket.on('move_error', (data) => flashStatus(data.message));
  socket.on('ability_error', (data) => flashStatus(data.message));

  socket.on('legal_moves_result', (data) => {
    if (!selected || selected[0] !== data.pos[0] || selected[1] !== data.pos[1]) return;
    legalTargets = data.moves;
    renderBoard();
  });

  socket.on('attack_through_targets_result', (data) => {
    if (!abilityFrom || abilityFrom[0] !== data.pos[0] || abilityFrom[1] !== data.pos[1]) return;
    abilityTargets = data.moves;
    renderBoard();
  });

  joinBtn.addEventListener('click', () => {
    socket.emit('join', { token, lobby_id: lobbyId });
  });

  restartBtn.addEventListener('click', () => {
    if (!window.confirm('Начать партию заново для всех текущих игроков?')) return;
    socket.emit('restart', { token, lobby_id: lobbyId });
  });

  let flashTimer = null;
  function flashStatus(message) {
    if (flashTimer) clearTimeout(flashTimer);
    const prev = statusEl.textContent;
    statusEl.textContent = message;
    flashTimer = setTimeout(() => {
      statusEl.textContent = prev;
    }, 2500);
  }

  function pieceKey(r, c) {
    return r + ',' + c;
  }

  function pieceSymbolId(piece) {
    const set = (piece.seat == null) ? 'b' : (piece.seat % 2 === 1 ? 'w' : 'b');
    return set + piece.type.toLowerCase();
  }

  function hasPieceAt(s, r, c) {
    return s.pieces.some((p) => p.r === r && p.c === c);
  }

  function squareTargetsRevival(s) {
    return (s.my_home_cells || []).filter(([r, c]) => !hasPieceAt(s, r, c));
  }

  function squareTargetsFreeze(s) {
    return s.pieces.filter((p) => p.seat != null && p.seat !== s.my_seat).map((p) => [p.r, p.c]);
  }

  function squareTargetsExplosion(s) {
    return s.cells;
  }

  function render() {
    if (!lastState) return;
    renderStatus();
    renderScore();
    renderBadges();
    renderAbilities();
    renderBoard();
    renderSeats();
    joinBtn.disabled = lastState.my_seat != null;
    joinBtn.textContent = lastState.my_seat != null
      ? 'Вы играете (место ' + lastState.my_seat + ')'
      : 'Войти в игру';
    restartBtn.hidden = lastState.my_seat == null;
  }

  function renderScore() {
    const s = lastState;
    if (s.my_score == null) {
      scoreEl.hidden = true;
      return;
    }
    scoreEl.hidden = false;
    scoreEl.innerHTML = 'Ваши очки: <b>' + s.my_score + '</b>';
  }

  function renderBadges() {
    const s = lastState;
    let badges = document.getElementById('status-badges');
    if (!badges) {
      badges = document.createElement('div');
      badges.id = 'status-badges';
      badges.className = 'status-badges';
      scoreEl.insertAdjacentElement('afterend', badges);
    }
    badges.innerHTML = '';
    if (s.my_seat == null) return;
    if (s.my_shield) badges.appendChild(makeBadge('shield', '🛡 Щит активен'));
    if (s.my_piece_frozen_pos) badges.appendChild(makeBadge('frozen', '❄ Ваша фигура заморожена'));
    if (s.fog_active_for_me) badges.appendChild(makeBadge('fog', '🌫 Вы под туманом войны'));
    else if (s.fog_active) badges.appendChild(makeBadge('fog', '🌫 Туман войны действует'));
  }

  function makeBadge(cls, text) {
    const el = document.createElement('span');
    el.className = 'badge ' + cls;
    el.textContent = text;
    return el;
  }

  function renderStatus() {
    const s = lastState;
    if (s.finished) {
      statusEl.textContent = s.winner
        ? 'Игра окончена. Победил игрок #' + s.winner + '.'
        : 'Игра окончена.';
      return;
    }
    if (!s.started) {
      statusEl.textContent = 'Ждём второго игрока, чтобы начать партию (' + s.players_count + '/8)...';
      return;
    }
    const isYou = s.my_seat != null && s.my_seat === s.current_seat;
    const color = (s.seats[s.current_seat] || {}).color || '#fff';
    statusEl.innerHTML = 'Сейчас ходит: <b style="color:' + color + '">Игрок #' + s.current_seat + '</b>'
      + (isYou ? ' — это вы!' : '')
      + ' <span class="muted-inline">(' + s.players_count + '/8 в партии)</span>';
  }

  function renderAbilities() {
    const s = lastState;
    abilitiesEl.innerHTML = '';
    const myTurn = s.started && !s.finished && s.my_seat != null && s.my_seat === s.current_seat;

    ABILITY_ORDER.forEach((key) => {
      const def = ABILITY_DEFS[key];
      const cost = (s.ability_costs || {})[key];
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ability-btn' + (pendingAbility === key ? ' pending' : '');

      let disabled = s.my_seat == null || s.my_score < cost;
      if (key === 'shield' && s.my_shield) disabled = true;
      if (key === 'extra_turn' && s.my_extra_turn_pending) disabled = true;
      if (key === 'revival' && !s.my_revivable_pawns) disabled = true;
      if (def.flow !== 'instant' && key !== 'shield' && key !== 'extra_turn' && !myTurn) disabled = true;

      btn.disabled = disabled;
      btn.innerHTML = '<span class="icon">' + def.icon + '</span>'
        + '<span class="name">' + def.name + '</span>'
        + '<span class="cost">' + cost + '</span>';
      btn.addEventListener('click', () => onAbilityButtonClick(key));
      abilitiesEl.appendChild(btn);
    });

    if (pendingAbility) {
      abilityHintEl.hidden = false;
      abilityHintEl.textContent = hintFor(pendingAbility, abilityStage) + ' (нажмите способность ещё раз, чтобы отменить)';
    } else {
      abilityHintEl.hidden = true;
    }
  }

  function hintFor(key, stage) {
    if (key === 'skip_turn') return 'Выберите игрока в списке справа, который пропустит ход';
    if (key === 'attack_through') {
      return stage === 'need-piece' ? 'Выберите свою ладью, слона или ферзя' : 'Выберите фигуру соперника для удара через преграду';
    }
    if (key === 'teleport') {
      return stage === 'need-piece' ? 'Выберите свою фигуру' : 'Выберите свободную клетку для телепорта';
    }
    if (key === 'revival') return 'Выберите свободную клетку в своей стартовой зоне';
    if (key === 'freeze') return 'Выберите фигуру соперника';
    if (key === 'explosion') return 'Выберите клетку — центр взрыва';
    return '';
  }

  function onAbilityButtonClick(key) {
    if (pendingAbility === key) {
      cancelAbility();
      renderAbilities();
      return;
    }
    const s = lastState;
    const def = ABILITY_DEFS[key];
    cancelAbility();

    if (def.flow === 'instant') {
      socket.emit('use_ability', { token, lobby_id: lobbyId, ability: key, params: {} });
      return;
    }
    pendingAbility = key;
    selected = null;
    legalTargets = [];
    if (def.flow === 'seat') {
      abilityStage = 'need-seat';
    } else if (def.flow === 'square') {
      abilityStage = 'need-target';
      abilityTargets = def.targets(s);
    } else if (def.flow === 'piece-target') {
      abilityStage = 'need-piece';
    }
    render();
  }

  function cancelAbility() {
    pendingAbility = null;
    abilityStage = null;
    abilityFrom = null;
    abilityTargets = [];
  }

  function renderSeats() {
    const s = lastState;
    seatsEl.innerHTML = '';
    Object.keys(s.seats).sort((a, b) => a - b).forEach((sidStr) => {
      const sid = Number(sidStr);
      const info = s.seats[sid];
      if (info.status === 'NOT_CREATED') return;
      const row = document.createElement('div');
      row.className = 'seat-row';
      if (info.is_you) row.classList.add('you');
      if (sid === s.current_seat) row.classList.add('turn');
      if (info.status !== 'ACTIVE') row.classList.add('inactive');

      const isSkipTarget = pendingAbility === 'skip_turn' && info.status === 'ACTIVE';
      if (isSkipTarget) {
        row.classList.add('targetable');
        row.addEventListener('click', () => {
          socket.emit('use_ability', { token, lobby_id: lobbyId, ability: 'skip_turn', params: { target_seat: sid } });
          cancelAbility();
        });
      }

      const dot = document.createElement('span');
      dot.className = 'dot';
      dot.style.background = info.color;
      row.appendChild(dot);
      const label = document.createElement('span');
      label.className = 'label';
      label.textContent = 'Игрок #' + sid + (info.is_you ? ' — вы' : '');
      row.appendChild(label);
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = {
        ACTIVE: sid === s.current_seat ? 'ходит' : '',
        VACANT: 'свободно',
        NEUTRAL: 'выбыл',
      }[info.status] || '';
      row.appendChild(tag);
      seatsEl.appendChild(row);
    });
  }

  function renderBoard() {
    const s = lastState;
    boardEl.innerHTML = '';
    if (!s.cells.length) return;

    let minR = Infinity, maxR = -Infinity, minC = Infinity, maxC = -Infinity;
    s.cells.forEach(([r, c]) => {
      if (r < minR) minR = r;
      if (r > maxR) maxR = r;
      if (c < minC) minC = c;
      if (c > maxC) maxC = c;
    });

    boardEl.style.gridTemplateRows = 'repeat(' + (maxR - minR + 1) + ', var(--sq-size))';
    boardEl.style.gridTemplateColumns = 'repeat(' + (maxC - minC + 1) + ', var(--sq-size))';

    const pieceMap = {};
    s.pieces.forEach((p) => {
      pieceMap[pieceKey(p.r, p.c)] = p;
    });

    const targetKeys = new Set(legalTargets.map(([r, c]) => pieceKey(r, c)));
    const abilityTargetKeys = new Set(abilityTargets.map(([r, c]) => pieceKey(r, c)));
    const myTurn = s.started && !s.finished && s.my_seat != null && s.my_seat === s.current_seat;
    const frozenKey = s.my_piece_frozen_pos ? pieceKey(s.my_piece_frozen_pos[0], s.my_piece_frozen_pos[1]) : null;

    s.cells.forEach(([r, c]) => {
      const div = document.createElement('div');
      div.className = 'sq ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
      div.style.gridRow = (r - minR + 1);
      div.style.gridColumn = (c - minC + 1);
      div.dataset.r = r;
      div.dataset.c = c;

      const piece = pieceMap[pieceKey(r, c)];
      if (piece) {
        const wrap = document.createElement('div');
        wrap.className = 'piece-wrap';
        wrap.style.background = piece.seat != null
          ? hexToRgba(s.seats[piece.seat].color, 0.55)
          : 'rgba(140, 140, 140, 0.45)';
        if (spriteReady) {
          wrap.innerHTML = '<svg class="piece-svg" viewBox="0 0 40 40"><use href="#' + pieceSymbolId(piece) + '"></use></svg>';
        }
        div.appendChild(wrap);
      }

      const key = pieceKey(r, c);
      if (frozenKey === key) div.classList.add('selected');
      if (!pendingAbility && selected && selected[0] === r && selected[1] === c) {
        div.classList.add('selected');
      }
      if (pendingAbility && abilityFrom && abilityFrom[0] === r && abilityFrom[1] === c) {
        div.classList.add('selected');
      }
      if (!pendingAbility && targetKeys.has(key)) {
        div.classList.add('move-target');
        if (piece) div.classList.add('has-piece');
      }
      if (pendingAbility && abilityStage === 'need-target' && abilityTargetKeys.has(key)) {
        div.classList.add('move-target');
        if (piece) div.classList.add('has-piece');
      }

      const isOwnPiece = piece && myTurn && piece.seat === s.my_seat;
      const isAbilityPieceCandidate = pendingAbility && abilityStage === 'need-piece' && piece
        && piece.seat === s.my_seat && ABILITY_DEFS[pendingAbility].pieceFilter(piece);
      const isAbilityTarget = pendingAbility && abilityStage === 'need-target' && abilityTargetKeys.has(key);
      const isMoveTarget = !pendingAbility && targetKeys.has(key);

      const clickable = isOwnPiece || (!pendingAbility && myTurn) || isAbilityPieceCandidate || isAbilityTarget;
      if (clickable) {
        div.addEventListener('click', () => onSquareClick(r, c));
      }
      if (isOwnPiece || isMoveTarget || isAbilityPieceCandidate || isAbilityTarget) {
        div.classList.add('selectable');
      }

      boardEl.appendChild(div);
    });
  }

  function hexToRgba(hex, alpha) {
    const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    if (!m) return hex;
    const r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  function onSquareClick(r, c) {
    if (pendingAbility) {
      onAbilitySquareClick(r, c);
      return;
    }
    const s = lastState;
    if (!s || !s.started || s.finished) return;
    const myTurn = s.my_seat != null && s.my_seat === s.current_seat;
    const piece = s.pieces.find((p) => p.r === r && p.c === c);

    if (selected) {
      const isTarget = legalTargets.some(([tr, tc]) => tr === r && tc === c);
      if (isTarget) {
        socket.emit('move', { token, lobby_id: lobbyId, from: selected, to: [r, c] });
        selected = null;
        legalTargets = [];
        renderBoard();
        return;
      }
    }

    if (myTurn && piece && piece.seat === s.my_seat) {
      selected = [r, c];
      legalTargets = [];
      socket.emit('legal_moves', { token, lobby_id: lobbyId, pos: [r, c] });
      renderBoard();
    } else {
      selected = null;
      legalTargets = [];
      renderBoard();
    }
  }

  function onAbilitySquareClick(r, c) {
    const s = lastState;
    const key = pendingAbility;
    const def = ABILITY_DEFS[key];
    const piece = s.pieces.find((p) => p.r === r && p.c === c);

    if (abilityStage === 'need-piece') {
      if (!piece || piece.seat !== s.my_seat || !def.pieceFilter(piece)) return;
      abilityFrom = [r, c];
      abilityStage = 'need-target';
      abilityTargets = [];
      if (key === 'attack_through') {
        socket.emit('attack_through_targets', { token, lobby_id: lobbyId, pos: [r, c] });
      } else if (key === 'teleport') {
        abilityTargets = s.cells.filter(([cr, cc]) => !hasPieceAt(s, cr, cc));
      }
      render();
      return;
    }

    if (abilityStage === 'need-target') {
      const isTarget = abilityTargets.some(([tr, tc]) => tr === r && tc === c);
      if (!isTarget) return;
      let params;
      if (key === 'attack_through' || key === 'teleport') {
        params = { from: abilityFrom, to: [r, c] };
      } else if (key === 'revival') {
        params = { to: [r, c] };
      } else if (key === 'freeze') {
        params = { pos: [r, c] };
      } else if (key === 'explosion') {
        params = { center: [r, c] };
      }
      socket.emit('use_ability', { token, lobby_id: lobbyId, ability: key, params });
      cancelAbility();
    }
  }
})();

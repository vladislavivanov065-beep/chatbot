(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/uno');

  const COLOR_NAMES = { red: 'красный', yellow: 'жёлтый', green: 'зелёный', blue: 'синий' };
  const SYMBOL_MAP = { skip: '🚫', reverse: '🔄', draw2: '+2', wild: '★', wild4: '+4' };

  const waitingCard = document.getElementById('waiting-card');
  const waitingStatus = document.getElementById('waiting-status');
  const waitingPlayers = document.getElementById('waiting-players');
  const joinBtn = document.getElementById('join-btn');
  const startBtn = document.getElementById('start-btn');

  const finishedCard = document.getElementById('finished-card');
  const finishedBanner = document.getElementById('finished-banner');
  const finishedLog = document.getElementById('finished-log');

  const gameLayout = document.getElementById('game-layout');
  const tableStatus = document.getElementById('table-status');
  const opponentsList = document.getElementById('opponents-list');
  const drawPile = document.getElementById('draw-pile');
  const drawPileCount = document.getElementById('draw-pile-count');
  const discardPile = document.getElementById('discard-pile');
  const handCards = document.getElementById('hand-cards');
  const drawBtn = document.getElementById('draw-btn');
  const passBtn = document.getElementById('pass-btn');
  const unoBtn = document.getElementById('uno-btn');
  const handHint = document.getElementById('hand-hint');
  const eventLog = document.getElementById('event-log');

  const colorPickerOverlay = document.getElementById('color-picker-overlay');
  const colorCancelBtn = document.getElementById('color-cancel-btn');

  let lastState = null;
  let pendingWildCardId = null;

  function cardSymbol(card) {
    return SYMBOL_MAP[card.value] || card.value;
  }

  function makeCardEl(card, extraClass) {
    const isWild = card.value === 'wild' || card.value === 'wild4';
    const el = document.createElement('div');
    el.className = 'uno-card ' + (isWild ? 'wildcard' : card.color) + (extraClass ? ' ' + extraClass : '');
    el.innerHTML = `<span class="card-symbol">${cardSymbol(card)}</span>`;
    return el;
  }

  function isPlayableClientSide(card, top, color, hand) {
    if (card.value === 'wild4') {
      const hasMatch = hand.some((c) => c.id !== card.id && c.color === color);
      return !hasMatch;
    }
    if (card.value === 'wild') return true;
    if (!top) return true;
    return card.color === color || card.value === top.value;
  }

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/uno/';
  });

  socket.on('action_error', (data) => {
    const msg = (data && data.message) || 'Действие невозможно';
    window.__lastActionError = msg;
    handHint.textContent = msg;
    handHint.style.color = '#ff9d90';
    setTimeout(() => {
      handHint.textContent = '';
      handHint.style.color = '';
    }, 2500);
  });

  socket.on('state', (state) => {
    lastState = state;
    window.__lastStateForTest = state;
    render();
  });

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
    waitingStatus.innerHTML = `Игроков: <b>${seats.length} / ${lastState.max_players}</b>`;
    waitingPlayers.textContent = seats.length ? seats.join(', ') : 'Пока никого нет';

    const alreadyIn = lastState.my_seat !== null && lastState.my_seat !== undefined;
    joinBtn.hidden = alreadyIn;
    joinBtn.disabled = seats.length >= lastState.max_players;
    startBtn.hidden = !(window.IS_CREATOR && lastState.can_start);
  }

  function renderFinished() {
    const iWon = lastState.winner === token;
    finishedBanner.textContent = lastState.winner
      ? (iWon ? '🏆 Вы победили!' : `🏆 Победил игрок: ${lastState.winner}`)
      : 'Игра окончена.';
    finishedLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- active game ----------

  function renderGame() {
    const s = lastState;
    const dirArrow = s.direction === 1 ? '↻' : '↺';
    const colorLabel = s.current_color ? COLOR_NAMES[s.current_color] : '?';
    tableStatus.innerHTML =
      `Ход: <b>${s.current_player}${s.current_player === token ? ' (вы)' : ''}</b>` +
      ` · Цвет: <b>${colorLabel}</b> · Направление: ${dirArrow}`;

    renderOpponents();
    renderPiles();
    renderHand();
    renderLog();
    renderActionButtons();
  }

  function renderOpponents() {
    const s = lastState;
    opponentsList.innerHTML = '';
    (s.seats || []).filter((t) => t !== token).forEach((t) => {
      const isTurn = s.current_player === t;
      const pending = (s.pending_uno || []).includes(t);
      const chip = document.createElement('div');
      chip.className = 'opponent-chip' + (isTurn ? ' turn' : '') + (pending ? ' uno-warning' : '');
      const size = s.hand_sizes && s.hand_sizes[t] !== undefined ? s.hand_sizes[t] : '?';
      chip.textContent = `${t}: ${size} карт(ы)` + (pending ? ' — UNO!' : '');
      if (pending) {
        const catchBtn = document.createElement('button');
        catchBtn.className = 'btn btn-small btn-ghost';
        catchBtn.style.marginLeft = '8px';
        catchBtn.textContent = 'Поймать!';
        catchBtn.addEventListener('click', () => socket.emit('catch_uno', { token, lobby_id: lobbyId, target: t }));
        chip.appendChild(catchBtn);
      }
      opponentsList.appendChild(chip);
    });
  }

  function renderPiles() {
    const s = lastState;
    drawPileCount.textContent = `${s.draw_pile_size} карт`;
    discardPile.innerHTML = '';
    if (s.top_card) {
      discardPile.appendChild(makeCardEl(s.top_card));
    }
  }

  function renderHand() {
    const s = lastState;
    handCards.innerHTML = '';
    const hand = s.my_hand || [];
    hand.forEach((card) => {
      const playable = s.is_my_turn && isPlayableClientSide(card, s.top_card, s.current_color, hand);
      const el = makeCardEl(card, 'hand-card' + (playable ? '' : ' unplayable'));
      el.addEventListener('click', () => {
        if (!s.is_my_turn) return;
        const isWild = card.value === 'wild' || card.value === 'wild4';
        if (isWild) {
          pendingWildCardId = card.id;
          colorPickerOverlay.hidden = false;
        } else {
          socket.emit('play_card', { token, lobby_id: lobbyId, card_id: card.id });
        }
      });
      handCards.appendChild(el);
    });
  }

  function renderActionButtons() {
    const s = lastState;
    drawBtn.disabled = !s.is_my_turn;
    passBtn.hidden = !s.is_my_turn;
    unoBtn.hidden = !s.my_uno_pending;
  }

  function renderLog() {
    eventLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- controls ----------

  joinBtn.addEventListener('click', () => socket.emit('join', { token, lobby_id: lobbyId }));
  startBtn.addEventListener('click', () => socket.emit('start_game', { token, lobby_id: lobbyId }));

  drawPile.addEventListener('click', () => {
    if (lastState && lastState.is_my_turn) {
      socket.emit('draw_card', { token, lobby_id: lobbyId });
    }
  });

  drawBtn.addEventListener('click', () => socket.emit('draw_card', { token, lobby_id: lobbyId }));
  passBtn.addEventListener('click', () => socket.emit('pass_turn', { token, lobby_id: lobbyId }));
  unoBtn.addEventListener('click', () => socket.emit('call_uno', { token, lobby_id: lobbyId }));

  document.querySelectorAll('.color-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (pendingWildCardId) {
        socket.emit('play_card', { token, lobby_id: lobbyId, card_id: pendingWildCardId, color: btn.dataset.color });
      }
      pendingWildCardId = null;
      colorPickerOverlay.hidden = true;
    });
  });

  colorCancelBtn.addEventListener('click', () => {
    pendingWildCardId = null;
    colorPickerOverlay.hidden = true;
  });
})();

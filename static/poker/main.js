(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/poker');

  const SUIT_COLOR = { '♠': 'black', '♣': 'black', '♥': 'red', '♦': 'red' };
  const STAGE_NAMES = { preflop: 'префлоп', flop: 'флоп', turn: 'тёрн', river: 'ривер', showdown: 'вскрытие' };

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
  const communityCards = document.getElementById('community-cards');
  const seatsList = document.getElementById('seats-list');
  const myHoleCards = document.getElementById('my-hole-cards');
  const foldBtn = document.getElementById('fold-btn');
  const checkBtn = document.getElementById('check-btn');
  const callBtn = document.getElementById('call-btn');
  const allinBtn = document.getElementById('allin-btn');
  const raiseSlider = document.getElementById('raise-slider');
  const raiseAmount = document.getElementById('raise-amount');
  const raiseBtn = document.getElementById('raise-btn');
  const handHint = document.getElementById('hand-hint');
  const eventLog = document.getElementById('event-log');

  let lastState = null;

  function makeCardEl(card) {
    const el = document.createElement('div');
    el.className = 'poker-card ' + (SUIT_COLOR[card.suit] || 'black');
    el.innerHTML =
      `<div class="rank-top">${card.rank}${card.suit}</div>` +
      `<div class="suit-mid">${card.suit}</div>` +
      `<div class="rank-bottom">${card.rank}${card.suit}</div>`;
    return el;
  }

  function submit(action, amount) {
    socket.emit('poker_action', { token, lobby_id: lobbyId, action, amount });
  }

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/poker/';
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
    renderGameScreen();
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
      ? (iWon ? '🏆 Вы выиграли все фишки!' : `🏆 Победил игрок: ${lastState.winner}`)
      : 'Игра окончена.';
    finishedLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- active game ----------

  function renderGameScreen() {
    const s = lastState;
    tableStatus.innerHTML =
      `Банк: <b>${s.pot}</b> · Стадия: <b>${STAGE_NAMES[s.stage] || s.stage || '?'}</b>` +
      (s.current_player ? ` · Ход: <b>${s.current_player}${s.current_player === token ? ' (вы)' : ''}</b>` : '');

    renderCommunityCards();
    renderSeats();
    renderMyHoleCards();
    renderActionButtons();
    renderLog();

    if (!handHint.style.color) {
      handHint.textContent = s.is_my_turn ? 'Ваш ход!' : (s.current_player ? `Ходит: ${s.current_player}` : '');
    }
  }

  function renderCommunityCards() {
    communityCards.innerHTML = '';
    (lastState.community || []).forEach((c) => communityCards.appendChild(makeCardEl(c)));
  }

  function renderMyHoleCards() {
    myHoleCards.innerHTML = '';
    (lastState.my_hole_cards || []).forEach((c) => myHoleCards.appendChild(makeCardEl(c)));
  }

  function renderSeats() {
    const s = lastState;
    seatsList.innerHTML = '';
    (s.seats || []).forEach((t) => {
      const row = document.createElement('div');
      row.className = 'seat-row' +
        (t === token ? ' me' : '') +
        (s.current_player === t ? ' turn' : '') +
        ((s.folded || []).includes(t) ? ' folded' : '') +
        ((s.all_in || []).includes(t) ? ' all-in' : '');

      const nameSpan = document.createElement('span');
      nameSpan.className = 'seat-name';
      nameSpan.innerHTML = `${t}${t === token ? ' (вы)' : ''}` + (s.dealer === t ? ' <span class="dealer-chip">D</span>' : '');
      row.appendChild(nameSpan);

      const betSpan = document.createElement('span');
      betSpan.className = 'seat-bet';
      const bet = (s.player_bets && s.player_bets[t]) || 0;
      betSpan.textContent = bet ? `ставка: ${bet}` : '';
      row.appendChild(betSpan);

      const stackSpan = document.createElement('span');
      stackSpan.className = 'seat-stack';
      const stack = (s.stacks && s.stacks[t]) ?? 0;
      stackSpan.textContent = `${stack} 🪙`;
      row.appendChild(stackSpan);

      seatsList.appendChild(row);
    });
  }

  function renderActionButtons() {
    const s = lastState;
    const myTurn = !!s.is_my_turn;
    const toCall = s.to_call || 0;
    const myStack = s.my_stack || 0;

    foldBtn.disabled = !myTurn;
    checkBtn.disabled = !myTurn || toCall > 0;
    callBtn.disabled = !myTurn || toCall === 0;
    callBtn.textContent = toCall ? `Уравнять (${toCall})` : 'Уравнять';
    allinBtn.disabled = !myTurn || myStack <= 0;
    raiseBtn.disabled = !myTurn || myStack <= 0;

    const myBet = (s.player_bets && s.player_bets[token]) || 0;
    const minRaiseTo = (s.current_bet || 0) + (s.min_raise || 0);
    const maxRaiseTo = myBet + myStack;
    raiseSlider.min = Math.min(minRaiseTo, maxRaiseTo);
    raiseSlider.max = Math.max(minRaiseTo, maxRaiseTo);
    if (document.activeElement !== raiseSlider && document.activeElement !== raiseAmount) {
      raiseSlider.value = raiseSlider.min;
      raiseAmount.value = raiseSlider.min;
    }
  }

  function renderLog() {
    eventLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${l}</div>`).join('');
  }

  // ---------- controls ----------

  joinBtn.addEventListener('click', () => socket.emit('join', { token, lobby_id: lobbyId }));
  startBtn.addEventListener('click', () => socket.emit('start_game', { token, lobby_id: lobbyId }));

  foldBtn.addEventListener('click', () => submit('fold'));
  checkBtn.addEventListener('click', () => submit('check'));
  callBtn.addEventListener('click', () => submit('call'));
  allinBtn.addEventListener('click', () => {
    const s = lastState;
    const myBet = (s.player_bets && s.player_bets[token]) || 0;
    submit('raise', myBet + (s.my_stack || 0));
  });
  raiseBtn.addEventListener('click', () => submit('raise', parseInt(raiseAmount.value, 10)));

  raiseSlider.addEventListener('input', () => { raiseAmount.value = raiseSlider.value; });
  raiseAmount.addEventListener('input', () => { raiseSlider.value = raiseAmount.value; });
})();

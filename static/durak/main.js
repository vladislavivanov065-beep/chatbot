(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/durak');

  const waitingCard = document.getElementById('waiting-card');
  const waitingStatus = document.getElementById('waiting-status');
  const waitingPlayers = document.getElementById('waiting-players');
  const joinBtn = document.getElementById('join-btn');
  const startBtn = document.getElementById('start-btn');

  const finishedCard = document.getElementById('finished-card');
  const finishedBanner = document.getElementById('finished-banner');

  const gameCard = document.getElementById('game-card');
  const statusLine = document.getElementById('status-line');
  const tableArea = document.getElementById('table-area');
  const actionBar = document.getElementById('action-bar');
  const hintText = document.getElementById('hint-text');
  const handArea = document.getElementById('hand-area');

  const playersPanel = document.getElementById('players-panel');

  let lastState = null;
  let selectedCard = null;
  let transferMode = false;
  let hintTimer = null;

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/durak/';
  });

  socket.on('action_error', (data) => {
    window.__lastActionError = data;
    flashHint((data && data.message) || 'Действие невозможно', true);
  });

  socket.on('state', (state) => {
    lastState = state;
    window.__lastStateForTest = state;
    selectedCard = null;
    transferMode = false;
    render();
  });

  function flashHint(text, isError) {
    hintText.textContent = text;
    hintText.style.color = isError ? '#ffb4b0' : '';
    if (hintTimer) clearTimeout(hintTimer);
    hintTimer = setTimeout(() => {
      hintText.textContent = '';
      hintText.style.color = '';
    }, 3000);
  }

  function sameCard(a, b) {
    return a && b && a.rank === b.rank && a.suit === b.suit;
  }

  function cardEl(card, extraClass) {
    const el = document.createElement('div');
    el.className = 'card' + (extraClass ? ' ' + extraClass : '');
    if (!card) {
      el.classList.add('back');
      return el;
    }
    if (card.suit === '♥' || card.suit === '♦') el.classList.add('red');
    const rankEl = document.createElement('div');
    rankEl.textContent = card.rank;
    const suitEl = document.createElement('div');
    suitEl.className = 'suit';
    suitEl.textContent = card.suit;
    el.appendChild(rankEl);
    el.appendChild(suitEl);
    return el;
  }

  function render() {
    if (!lastState) return;
    renderPlayers();

    if (!lastState.started) {
      waitingCard.hidden = false;
      finishedCard.hidden = true;
      gameCard.hidden = true;
      renderWaiting();
      return;
    }

    waitingCard.hidden = true;

    if (lastState.finished) {
      finishedCard.hidden = false;
      gameCard.hidden = true;
      finishedBanner.textContent = lastState.fool
        ? (lastState.fool === token ? '🃏 Вы — дурак!' : `🃏 Дурак — ${lastState.fool}`)
        : '🤝 Ничья — колода закончилась одновременно у всех.';
      return;
    }

    finishedCard.hidden = true;
    gameCard.hidden = false;
    renderGame();
  }

  function renderWaiting() {
    const seats = lastState.seats || [];
    waitingStatus.innerHTML =
      `Вариант: <b>${lastState.variant === 'perevodnoy' ? 'Переводной' : 'Подкидной'}</b> · ` +
      `Игроков: <b>${seats.length} / ${lastState.max_players}</b>`;
    waitingPlayers.textContent = seats.length ? seats.join(', ') : 'Пока никого нет';

    const alreadyIn = lastState.my_seat !== null && lastState.my_seat !== undefined;
    joinBtn.hidden = alreadyIn;
    joinBtn.disabled = seats.length >= lastState.max_players;

    startBtn.hidden = !(window.IS_CREATOR && lastState.can_start);
  }

  function renderGame() {
    const s = lastState;
    const isAttacker = s.attacker === token;
    const isDefender = s.defender === token;

    statusLine.innerHTML =
      `Козырь: ${cardHtml(s.trump_card)} · ` +
      `В колоде: <b>${s.talon_count}</b> · В отбое: <b>${s.discard_count}</b><br>` +
      `Атакует: <b>${s.attacker}</b>${isAttacker ? ' (вы)' : ''} · ` +
      `Защищается: <b>${s.defender}</b>${isDefender ? ' (вы)' : ''}`;

    renderTable(isDefender);
    renderActionBar(isAttacker, isDefender);
    renderHand(isAttacker, isDefender);
  }

  function cardHtml(card) {
    if (!card) return '?';
    const red = card.suit === '♥' || card.suit === '♦';
    return `<span style="${red ? 'color:#ffb4b0' : ''}">${card.rank}${card.suit}</span>`;
  }

  function renderTable(isDefender) {
    tableArea.innerHTML = '';
    if (!lastState.table.length) {
      const empty = document.createElement('div');
      empty.className = 'table-empty';
      empty.textContent = 'Стол пуст — выберите карту, чтобы атаковать';
      tableArea.appendChild(empty);
      return;
    }

    const awaitingSlotPick = isDefender && selectedCard && !transferMode && openSlotCount() > 1;

    lastState.table.forEach((slot) => {
      const slotEl = document.createElement('div');
      slotEl.className = 'slot';
      slotEl.appendChild(cardEl(slot.attack, 'attack'));
      if (slot.defense) {
        slotEl.appendChild(cardEl(slot.defense, 'defense'));
      } else {
        slotEl.classList.add('open');
        if (awaitingSlotPick) {
          slotEl.classList.add('targetable');
          slotEl.addEventListener('click', () => {
            socket.emit('defend', {
              token,
              lobby_id: lobbyId,
              attack_card: slot.attack,
              defense_card: selectedCard,
            });
            selectedCard = null;
          });
        } else if (isDefender && selectedCard && !transferMode) {
          // single open slot - clicking the hand card already auto-defended, nothing to do here
        }
      }
      tableArea.appendChild(slotEl);
    });
  }

  function openSlotCount() {
    return lastState.table.filter((s) => !s.defense).length;
  }

  function renderActionBar(isAttacker, isDefender) {
    actionBar.innerHTML = '';
    const s = lastState;

    if (isDefender && s.table.length) {
      const takeBtn = document.createElement('button');
      takeBtn.className = 'btn btn-danger';
      takeBtn.textContent = 'Взять';
      takeBtn.onclick = () => socket.emit('take', { token, lobby_id: lobbyId });
      actionBar.appendChild(takeBtn);
    }

    if (isDefender && s.can_transfer) {
      const transferBtn = document.createElement('button');
      transferBtn.className = 'btn btn-ghost';
      transferBtn.textContent = transferMode ? 'Отменить перевод' : 'Перевести';
      transferBtn.onclick = () => {
        transferMode = !transferMode;
        selectedCard = null;
        render();
      };
      actionBar.appendChild(transferBtn);
    }

    if (isAttacker && s.table.length && !s.has_open_slots) {
      const doneBtn = document.createElement('button');
      doneBtn.className = 'btn';
      doneBtn.textContent = 'Бито';
      doneBtn.onclick = () => socket.emit('confirm_done', { token, lobby_id: lobbyId });
      actionBar.appendChild(doneBtn);
    }

    let hint = '';
    if (transferMode) hint = 'Выберите карту того же ранга, чтобы перевести ход';
    else if (isDefender && s.has_open_slots) hint = 'Выберите карту, чтобы отбиться, или нажмите «Взять»';
    else if (isAttacker && !s.table.length) hint = 'Ваш ход — выберите карту для атаки';
    else if (!s.table.length) hint = 'Ждём хода атакующего…';
    else hint = 'Можно подкинуть карту того же ранга, что на столе';
    if (!hintTimer) hintText.textContent = hint;
    else if (!hintText.textContent) hintText.textContent = hint;
  }

  function renderHand(isAttacker, isDefender) {
    handArea.innerHTML = '';
    const s = lastState;
    (s.my_hand || []).forEach((card) => {
      const el = cardEl(card, 'hand-card');
      if (sameCard(card, selectedCard)) el.classList.add('selected');
      el.addEventListener('click', () => onHandCardClick(card, isAttacker, isDefender));
      handArea.appendChild(el);
    });
  }

  function onHandCardClick(card, isAttacker, isDefender) {
    if (sameCard(card, selectedCard)) {
      selectedCard = null;
      render();
      return;
    }
    selectedCard = card;

    if (isDefender && transferMode) {
      socket.emit('transfer', { token, lobby_id: lobbyId, card });
      selectedCard = null;
      return;
    }

    if (isDefender && lastState.table.length) {
      const open = lastState.table.filter((s) => !s.defense);
      if (open.length === 1) {
        socket.emit('defend', {
          token,
          lobby_id: lobbyId,
          attack_card: open[0].attack,
          defense_card: card,
        });
        selectedCard = null;
        return;
      }
      // multiple open slots: wait for the player to click which one to cover
      render();
      return;
    }

    // attacker opening/throwing, or a podkidnoy bystander throwing in
    socket.emit('play_card', { token, lobby_id: lobbyId, card });
    selectedCard = null;
  }

  function renderPlayers() {
    playersPanel.innerHTML = '';
    const s = lastState;
    const list = s.started ? (s.players || []) : (s.seats || []).map((t) => ({ token: t, hand_count: null, out: false }));

    list.forEach((p) => {
      const row = document.createElement('div');
      row.className = 'player-row';
      if (s.started) {
        if (p.token === s.attacker) row.classList.add('attacker');
        if (p.token === s.defender) row.classList.add('defender');
        if (p.out) row.classList.add('out');
      }
      const name = document.createElement('span');
      name.textContent = p.token + (p.token === token ? ' (вы)' : '');
      const info = document.createElement('span');
      if (p.hand_count !== null) {
        info.textContent = p.out ? 'вышел' : `${p.hand_count} карт`;
      }
      row.appendChild(name);
      row.appendChild(info);
      playersPanel.appendChild(row);
    });
  }

  joinBtn.addEventListener('click', () => {
    socket.emit('join', { token, lobby_id: lobbyId });
  });

  startBtn.addEventListener('click', () => {
    socket.emit('start_game', { token, lobby_id: lobbyId });
  });
})();

(function () {
  const token = window.PLAYER_TOKEN;
  const lobbyId = window.LOBBY_ID;
  const socket = io('/mafia');

  const NIGHT_ROLES = new Set(['mafia', 'doctor', 'sheriff', 'maniac', 'bodyguard', 'lookout']);
  const SELF_TARGET_ALLOWED = new Set(['doctor', 'bodyguard']);
  const OPTIONAL_ROLES = ['sheriff', 'maniac', 'bodyguard', 'lookout', 'mayor'];

  const ROLE_INFO = {
    mafia: { emoji: '🔫', name: 'Мафия', desc: 'Ночью вместе с другими мафиози выбираете, кого убить.' },
    doctor: { emoji: '🩺', name: 'Врач', desc: 'Каждую ночь лечите одного игрока (можно себя), спасая от убийства.' },
    sheriff: { emoji: '🔎', name: 'Шериф', desc: 'Каждую ночь проверяете одного игрока — узнаёте, мафия он или нет.' },
    maniac: { emoji: '🔪', name: 'Маньяк', desc: 'Независимый убийца. Каждую ночь выбираете жертву. Побеждаете в одиночку, если остаётесь последним.' },
    bodyguard: { emoji: '🛡️', name: 'Телохранитель', desc: 'Каждую ночь охраняете одного игрока (можно себя) — если его атакуют, погибаете вместо него.' },
    lookout: { emoji: '👀', name: 'Наблюдатель', desc: 'Каждую ночь следите за одним игроком и узнаёте, кто его посещал.' },
    mayor: { emoji: '🎖️', name: 'Мэр', desc: 'Мирный житель, чей голос на дневном голосовании считается за два.' },
    civilian: { emoji: '👤', name: 'Мирный житель', desc: 'Особых способностей нет — только логика и голосование.' },
  };

  const DEATH_LABELS = {
    killed: 'убит(а) ночью',
    lynched: 'линчёван(а)',
    bodyguard_sacrifice: 'погиб(ла), защищая другого',
    disconnected: 'покинул(а) игру',
  };

  const waitingCard = document.getElementById('waiting-card');
  const waitingStatus = document.getElementById('waiting-status');
  const waitingRoleSummary = document.getElementById('waiting-role-summary');
  const waitingPlayers = document.getElementById('waiting-players');
  const joinBtn = document.getElementById('join-btn');
  const startBtn = document.getElementById('start-btn');

  const finishedCard = document.getElementById('finished-card');
  const finishedBanner = document.getElementById('finished-banner');
  const finishedRoles = document.getElementById('finished-roles');
  const finishedLog = document.getElementById('finished-log');

  const gameLayout = document.getElementById('game-layout');
  const phaseStatus = document.getElementById('phase-status');
  const myRoleCard = document.getElementById('my-role-card');
  const playersListEl = document.getElementById('players-list');
  const actionHint = document.getElementById('action-hint');
  const skipBtn = document.getElementById('skip-btn');

  const roleInfoPanel = document.getElementById('role-info-panel');
  const roleInfoTitle = document.getElementById('role-info-title');
  const roleInfoLog = document.getElementById('role-info-log');

  const chatTitle = document.getElementById('chat-title');
  const chatMessages = document.getElementById('chat-messages');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');

  const eventLog = document.getElementById('event-log');

  let lastState = null;

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  socket.on('connect', () => {
    socket.emit('register', { token, lobby_id: lobbyId });
  });

  socket.on('lobby_closed', (data) => {
    alert((data && data.message) || 'Лобби закрыто.');
    window.location.href = '/mafia/';
  });

  socket.on('action_error', (data) => {
    const msg = (data && data.message) || 'Действие невозможно';
    window.__lastActionError = msg;
    actionHint.textContent = msg;
    actionHint.style.color = '#ff9d90';
    setTimeout(() => {
      actionHint.textContent = '';
      actionHint.style.color = '';
    }, 3000);
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

    const cfg = lastState.role_config || {};
    let chips = `<span class="role-chip mandatory">🔫 Мафия ×${cfg.mafia_count}</span>`;
    chips += `<span class="role-chip mandatory">🩺 Врач</span>`;
    OPTIONAL_ROLES.forEach((r) => {
      if (cfg[r]) chips += `<span class="role-chip">${ROLE_INFO[r].emoji} ${ROLE_INFO[r].name}</span>`;
    });
    waitingRoleSummary.innerHTML = chips;

    const alreadyIn = lastState.my_seat !== null && lastState.my_seat !== undefined;
    joinBtn.hidden = alreadyIn;
    joinBtn.disabled = seats.length >= lastState.max_players;
    startBtn.hidden = !(window.IS_CREATOR && lastState.can_start);
  }

  function renderFinished() {
    const s = lastState;
    const labels = { mafia: '🔫 Победила мафия!', town: '🏘️ Победили мирные жители!', maniac: '🔪 Победил маньяк!' };
    finishedBanner.textContent = labels[s.winner] || 'Игра окончена.';
    finishedRoles.innerHTML = (s.players || [])
      .map((p) => `<span class="role-chip${p.alive ? '' : ' mandatory'}">${ROLE_INFO[p.role] ? ROLE_INFO[p.role].emoji : ''} ${p.token}: ${p.role_name || '?'}</span>`)
      .join('');
    finishedLog.innerHTML = (s.log || []).slice().reverse().map((l) => `<div>${escapeHtml(l)}</div>`).join('');
  }

  // ---------- active game ----------

  function renderGame() {
    const s = lastState;
    const phaseLabel = s.phase === 'night' ? `🌙 Ночь ${s.night_number}` : `☀️ День ${s.day_number}`;
    phaseStatus.innerHTML = `<b>${phaseLabel}</b> · ${s.my_alive ? 'вы живы' : 'вы выбыли 💀'}`;

    const info = ROLE_INFO[s.my_role] || {};
    myRoleCard.innerHTML =
      `<span class="role-emoji-big">${info.emoji || ''}</span>` +
      `<div><div class="role-name-big">${s.my_role_name}</div><div class="role-desc-small">${info.desc || ''}</div>` +
      (s.mafia_teammates && s.mafia_teammates.length > 1
        ? `<div class="mafia-teammates">Ваши сообщники: ${s.mafia_teammates.filter((t) => t !== token).join(', ')}</div>`
        : '') +
      `</div>`;

    renderPlayers();
    renderRoleInfo();
    renderChat();
    renderLog();
    renderSkipButton();
    renderActionHint();
  }

  function canActNight() {
    const s = lastState;
    return s.phase === 'night' && s.my_alive && NIGHT_ROLES.has(s.my_role);
  }

  function canVoteNow() {
    const s = lastState;
    return s.phase === 'day' && s.my_alive;
  }

  function renderPlayers() {
    const s = lastState;
    playersListEl.innerHTML = '';
    const nightActing = canActNight();
    const voting = canVoteNow();
    const myVoteTarget = s.my_vote;
    const myNightTarget = s.my_night_target;

    (s.players || []).forEach((p) => {
      const row = document.createElement('div');
      row.className = 'player-row' + (!p.alive ? ' dead' : '') + (p.token === token ? ' me' : '');

      const isMyCurrentTarget = (nightActing && myNightTarget === p.token) || (voting && myVoteTarget === p.token);
      if (isMyCurrentTarget) row.classList.add('my-target');

      const name = document.createElement('span');
      name.className = 'player-name';
      name.textContent = p.token + (p.token === token ? ' (вы)' : '');
      row.appendChild(name);

      const meta = document.createElement('span');
      meta.className = 'player-meta';
      let metaText = p.role_name ? p.role_name : '';
      if (!p.alive) metaText += ` 💀 ${DEATH_LABELS[p.death_reason] || ''}`;
      meta.textContent = metaText;
      row.appendChild(meta);

      if (s.phase === 'day' && s.vote_tally && s.vote_tally[p.token]) {
        const badge = document.createElement('span');
        badge.className = 'vote-badge';
        badge.textContent = `🗳️ ${s.vote_tally[p.token]}`;
        row.appendChild(badge);
      }

      if (p.alive) {
        const isSelf = p.token === token;
        if (nightActing && (!isSelf || SELF_TARGET_ALLOWED.has(s.my_role))) {
          row.classList.add('clickable');
          row.addEventListener('click', () => submit('night_action', { target: p.token }));
        } else if (voting && !isSelf) {
          row.classList.add('clickable');
          row.addEventListener('click', () => submit('vote', { target: p.token }));
        }
      }

      playersListEl.appendChild(row);
    });
  }

  function renderSkipButton() {
    const s = lastState;
    if (canActNight()) {
      skipBtn.hidden = false;
      skipBtn.textContent = 'Пропустить ход';
      skipBtn.onclick = () => submit('night_action', { target: null });
    } else if (canVoteNow()) {
      skipBtn.hidden = false;
      skipBtn.textContent = 'Воздержаться';
      skipBtn.onclick = () => submit('vote', { target: null });
    } else {
      skipBtn.hidden = true;
    }
  }

  function renderActionHint() {
    const s = lastState;
    if (!s.my_alive) {
      actionHint.textContent = 'Вы выбыли из игры и можете только наблюдать.';
      return;
    }
    if (s.phase === 'night') {
      if (!NIGHT_ROLES.has(s.my_role)) {
        actionHint.textContent = `Дождитесь утра — ждём: ${(s.night_waiting_on || []).join(', ') || 'всех'}`;
      } else if (s.night_submitted) {
        actionHint.textContent = `Действие выбрано. Ждём: ${(s.night_waiting_on || []).join(', ') || 'остальных'}`;
      } else {
        actionHint.textContent = 'Кликните по игроку в списке, чтобы выбрать цель.';
      }
    } else {
      const pending = s.day_voting_pending || [];
      actionHint.textContent = pending.length
        ? `Кликните по игроку, чтобы проголосовать. Ждём: ${pending.join(', ')}`
        : 'Голосование завершается…';
    }
  }

  function renderRoleInfo() {
    const s = lastState;
    if (s.my_role === 'sheriff' && s.sheriff_investigations) {
      roleInfoPanel.hidden = false;
      roleInfoTitle.textContent = '🔎 Результаты проверок';
      roleInfoLog.innerHTML = s.sheriff_investigations
        .slice().reverse()
        .map((r) => `<div>Ночь ${r.night}: <b>${r.target}</b> — ${r.is_mafia ? '🔴 мафия' : '🟢 не мафия'}</div>`)
        .join('') || '<div>Пока нет результатов.</div>';
    } else if (s.my_role === 'lookout' && s.lookout_watches) {
      roleInfoPanel.hidden = false;
      roleInfoTitle.textContent = '👀 Результаты наблюдения';
      roleInfoLog.innerHTML = s.lookout_watches
        .slice().reverse()
        .map((r) => `<div>Ночь ${r.night}: <b>${r.target}</b> посетили: ${r.visitors.length ? r.visitors.join(', ') : 'никто'}</div>`)
        .join('') || '<div>Пока нет результатов.</div>';
    } else {
      roleInfoPanel.hidden = true;
    }
  }

  function renderChat() {
    const s = lastState;
    let title, messages, canPost;
    if (s.phase === 'night') {
      if (s.my_role === 'mafia') {
        title = `🤫 Чат мафии (Ночь ${s.night_number})`;
        messages = s.mafia_chat || [];
        canPost = s.my_alive;
      } else {
        title = '🤫 Ночной чат мафии недоступен вашей роли';
        messages = [];
        canPost = false;
      }
    } else {
      title = `💬 Общий чат (День ${s.day_number})`;
      messages = s.day_chat || [];
      canPost = s.my_alive;
    }
    chatTitle.textContent = title;
    chatMessages.innerHTML = messages.map((m) => `<div><b>${escapeHtml(m.token)}:</b> ${escapeHtml(m.text)}</div>`).join('');
    chatMessages.scrollTop = chatMessages.scrollHeight;
    chatInput.disabled = !canPost;
    chatInput.placeholder = canPost ? 'Сообщение...' : 'Чат недоступен';
  }

  function renderLog() {
    eventLog.innerHTML = (lastState.log || []).slice().reverse().map((l) => `<div>${escapeHtml(l)}</div>`).join('');
  }

  // ---------- controls ----------

  joinBtn.addEventListener('click', () => submit('join', {}));
  startBtn.addEventListener('click', () => submit('start_game', {}));

  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    submit('chat', { text });
    chatInput.value = '';
  });
})();

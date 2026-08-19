(() => {
  let isRollingAnimation = false;
  const diceFaces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];
  let onlineState = null;

  async function loadRoom() {
    const response = await fetch(`/dice/api/room/${ROOM_CODE}`);
    onlineState = await response.json();

    if (onlineState.error) {
      document.body.innerHTML = `<h1>${onlineState.error}</h1>`;
      return;
    }

    renderOnlineRoom();
  }

  function renderOnlineRoom() {
    const info = document.getElementById("roomInfo");
    if (!info || !onlineState) return;

    const playersText = onlineState.players
      .map((p) => `Игрок ${p.player_index + 1}: ${p.login}`)
      .join("<br>");

    if (onlineState.status === "waiting") {
      info.innerHTML = `
        <h2>Ожидание игроков</h2>
        <p>Код комнаты:</p>
        <div class="room-code">${ROOM_CODE}</div>
        <p>${onlineState.players.length} / ${onlineState.max_players}</p>
        <p>${playersText}</p>
      `;
    } else if (onlineState.status === "playing") {
      const current = onlineState.players[onlineState.current_player];
      info.innerHTML = `
        <h2>Игра началась</h2>
        <p>${playersText}</p>
        <h3>Сейчас ходит: ${current.login}</h3>
      `;
    } else if (onlineState.status === "finished") {
      info.innerHTML = `
        <h2>Игра завершена</h2>
        <p>${playersText}</p>
      `;
    }

    if (onlineState.dice) {
      document.getElementById("die1").innerText = diceFaces[onlineState.dice[0] - 1];
      document.getElementById("die2").innerText = diceFaces[onlineState.dice[1] - 1];
    } else {
      document.getElementById("die1").innerText = "?";
      document.getElementById("die2").innerText = "?";
    }

    drawOnlineBoard();

    const myPlayer = onlineState.players.find((p) => p.login === CURRENT_LOGIN);
    const rollBtn = document.getElementById("rollBtn");
    if (!rollBtn) return;

    if (!myPlayer || onlineState.status !== "playing") {
      rollBtn.disabled = true;
      return;
    }

    rollBtn.disabled = myPlayer.player_index !== onlineState.current_player || onlineState.can_move;

    if (onlineState.rolling && !isRollingAnimation) {
      animateDiceOnly();
    }
  }

  function animateDiceOnly() {
    const d1 = document.getElementById("die1");
    const d2 = document.getElementById("die2");
    if (!d1 || !d2) return;

    isRollingAnimation = true;
    d1.classList.add("rolling");
    d2.classList.add("rolling");

    let ticks = 0;
    const animation = setInterval(() => {
      const a = Math.floor(Math.random() * 6) + 1;
      const b = Math.floor(Math.random() * 6) + 1;
      d1.innerText = diceFaces[a - 1];
      d2.innerText = diceFaces[b - 1];
      ticks++;
      if (ticks > 12) {
        clearInterval(animation);
        d1.classList.remove("rolling");
        d2.classList.remove("rolling");
        isRollingAnimation = false;
        loadRoom();
      }
    }, 80);
  }

  function drawOnlineBoard() {
    const boardDiv = document.getElementById("board");
    if (!boardDiv || !onlineState) return;

    boardDiv.innerHTML = "";

    for (let r = 0; r <= 6; r++) {
      for (let c = 0; c <= 6; c++) {
        const cell = document.createElement("div");

        if (r === 0 && c === 0) {
          cell.className = "corner";
        } else if (r === 0) {
          cell.className = "header";
          cell.innerText = c;
        } else if (c === 0) {
          cell.className = "header";
          cell.innerText = r;
        } else {
          const key = `${r}${c}`;
          cell.className = "cell";
          cell.dataset.key = key;
          cell.innerText = key;

          if (onlineState.board[key] !== undefined) {
            const token = document.createElement("div");
            token.className = `token player${onlineState.board[key]}`;
            token.innerText = onlineState.board[key] + 1;
            cell.innerText = "";
            cell.appendChild(token);
          }

          cell.onclick = () => makeOnlineMove(key);
        }

        boardDiv.appendChild(cell);
      }
    }

    highlightOnlineCells();
  }

  function highlightOnlineCells() {
    if (!onlineState || !onlineState.dice || !onlineState.can_move) return;

    const myPlayer = onlineState.players.find(
      (p) => String(p.login).trim() === String(CURRENT_LOGIN).trim()
    );
    if (!myPlayer) return;
    if (Number(myPlayer.player_index) !== Number(onlineState.current_player)) return;

    const [x, y] = onlineState.dice;
    const keys = x === y ? [`${x}${y}`] : [`${x}${y}`, `${y}${x}`];

    keys.forEach((key) => {
      const cell = document.querySelector(`[data-key="${key}"]`);
      if (!cell) return;
      cell.classList.add(onlineState.board[key] === undefined ? "highlight-free" : "highlight-busy");
    });
  }

  async function rollDiceOnline() {
    const d1 = document.getElementById("die1");
    const d2 = document.getElementById("die2");
    const rollBtn = document.getElementById("rollBtn");
    if (!d1 || !d2 || !rollBtn) return;

    rollBtn.disabled = true;
    d1.classList.add("rolling");
    d2.classList.add("rolling");

    let ticks = 0;
    const animation = setInterval(() => {
      const a = Math.floor(Math.random() * 6) + 1;
      const b = Math.floor(Math.random() * 6) + 1;
      d1.innerText = diceFaces[a - 1];
      d2.innerText = diceFaces[b - 1];
      ticks++;
      if (ticks > 12) {
        clearInterval(animation);
        d1.classList.remove("rolling");
        d2.classList.remove("rolling");
        sendRollRequest();
      }
    }, 80);
  }

  async function sendRollRequest() {
    const response = await fetch(`/dice/api/room/${ROOM_CODE}/roll`, { method: "POST" });
    const data = await response.json();

    if (data.error) {
      alert(data.error);
      await loadRoom();
      return;
    }

    if (data.skipped) {
      alert("Ход пропущен: выпали поля с вашими фишками");
    }

    await loadRoom();
  }

  async function makeOnlineMove(key) {
    if (!onlineState || onlineState.status !== "playing") return;

    const myPlayer = onlineState.players.find((p) => p.login === CURRENT_LOGIN);
    if (!myPlayer || myPlayer.player_index !== onlineState.current_player) return;

    const response = await fetch(`/dice/api/room/${ROOM_CODE}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });

    const data = await response.json();

    if (data.error) {
      alert(data.error);
      return;
    }

    if (data.winner !== undefined) {
      alert(`Игрок ${data.winner + 1} победил!`);
    }

    await loadRoom();
  }

  window.rollDiceOnline = rollDiceOnline;
  setInterval(loadRoom, 1500);
  loadRoom();
})();

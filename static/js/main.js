(() => {
  const socket = io();

  const screens = {
    name: document.getElementById("screen-name"),
    waiting: document.getElementById("screen-waiting"),
    game: document.getElementById("screen-game"),
    result: document.getElementById("screen-result"),
  };

  function showScreen(key) {
    Object.values(screens).forEach((el) => el.classList.remove("active"));
    screens[key].classList.add("active");
  }

  // --- name / matchmaking ---

  const nameInput = document.getElementById("name-input");
  const playBtn = document.getElementById("play-btn");

  function joinGame() {
    const name = nameInput.value.trim();
    socket.emit("join_game", { name });
    showScreen("waiting");
  }

  playBtn.addEventListener("click", joinGame);
  nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") joinGame();
  });

  socket.on("waiting", () => showScreen("waiting"));

  socket.on("opponent_left", () => {
    alert("Соперник отключился. Ищем нового…");
    showScreen("name");
  });

  // --- drawing canvas ---

  const canvas = document.getElementById("left-canvas");
  const ctx = canvas.getContext("2d");
  const opponentOverlay = document.getElementById("opponent-overlay");
  const leftTag = document.getElementById("left-tag");
  const rightTag = document.getElementById("right-tag");
  const referenceImg = document.getElementById("reference-img");
  const roundLabel = document.getElementById("round-label");
  const timerEl = document.getElementById("timer");

  let drawing = false;
  let currentColor = "#111111";
  let currentSize = 6;
  let eraserOn = false;
  let submitted = false;
  let timerInterval = null;
  let roundEndTime = 0;

  function resetCanvas() {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  resetCanvas();

  function pointerPos(e) {
    const rect = canvas.getBoundingClientRect();
    const point = e.touches ? e.touches[0] : e;
    return {
      x: ((point.clientX - rect.left) / rect.width) * canvas.width,
      y: ((point.clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function startDraw(e) {
    if (submitted) return;
    drawing = true;
    const { x, y } = pointerPos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    e.preventDefault();
  }

  function moveDraw(e) {
    if (!drawing || submitted) return;
    const { x, y } = pointerPos(e);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = currentSize;
    ctx.strokeStyle = eraserOn ? "#ffffff" : currentColor;
    ctx.lineTo(x, y);
    ctx.stroke();
    e.preventDefault();
  }

  function endDraw() {
    drawing = false;
  }

  canvas.addEventListener("mousedown", startDraw);
  canvas.addEventListener("mousemove", moveDraw);
  window.addEventListener("mouseup", endDraw);
  canvas.addEventListener("touchstart", startDraw, { passive: false });
  canvas.addEventListener("touchmove", moveDraw, { passive: false });
  canvas.addEventListener("touchend", endDraw);

  document.querySelectorAll(".color-swatch").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".color-swatch").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentColor = btn.dataset.color;
      eraserOn = false;
      document.getElementById("eraser-btn").classList.remove("active");
    });
  });

  document.getElementById("brush-size").addEventListener("input", (e) => {
    currentSize = Number(e.target.value);
  });

  document.getElementById("eraser-btn").addEventListener("click", (e) => {
    eraserOn = !eraserOn;
    e.target.classList.toggle("active", eraserOn);
  });

  document.getElementById("clear-btn").addEventListener("click", () => {
    if (submitted) return;
    resetCanvas();
  });

  document.getElementById("submit-btn").addEventListener("click", () => submitDrawing());

  function submitDrawing() {
    if (submitted) return;
    submitted = true;
    document.getElementById("submit-btn").disabled = true;
    socket.emit("submit", { image: canvas.toDataURL("image/png") });
  }

  // --- round lifecycle ---

  socket.on("start_round", (data) => {
    submitted = false;
    document.getElementById("submit-btn").disabled = false;
    resetCanvas();
    referenceImg.src = data.reference_url;
    roundLabel.textContent = `Раунд ${data.round} / ${data.total_rounds}`;
    leftTag.textContent = "Вы";
    rightTag.textContent = data.opponent_name;
    opponentOverlay.textContent = "Соперник рисует…";
    opponentOverlay.classList.remove("hidden");
    roundEndTime = data.end_time * 1000;

    showScreen("game");

    clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      const remaining = Math.max(0, Math.round((roundEndTime - Date.now()) / 1000));
      timerEl.textContent = remaining;
      if (remaining <= 0) {
        clearInterval(timerInterval);
        submitDrawing();
      }
    }, 250);
  });

  socket.on("opponent_submitted", () => {
    opponentOverlay.textContent = "Соперник готов ✔";
  });

  socket.on("round_result", (data) => {
    clearInterval(timerInterval);
    opponentOverlay.classList.remove("hidden");

    document.getElementById("result-title").textContent =
      data.round < data.total_rounds || !data.match_over
        ? `Раунд ${data.round} / ${data.total_rounds}`
        : "Матч завершён!";

    document.getElementById("result-your-img").src = data.your_image || "";
    document.getElementById("result-opponent-img").src = data.opponent_image || "";
    document.getElementById("result-reference-img").src = data.reference_url;
    document.getElementById("result-your-score").textContent = `${data.your_score}%`;
    document.getElementById("result-opponent-score").textContent = `${data.opponent_score}%`;
    document.getElementById("result-opponent-name").textContent = rightTag.textContent;

    const winnerEl = document.getElementById("result-winner");
    if (data.round_winner === "you") winnerEl.textContent = "🏆 Вы победили в этом раунде!";
    else if (data.round_winner === "opponent") winnerEl.textContent = "Соперник выиграл раунд.";
    else winnerEl.textContent = "Ничья в этом раунде.";

    document.getElementById("total-scores").textContent =
      `Общий счёт — Вы: ${data.total_scores.you}, Соперник: ${data.total_scores.opponent}`;

    const nextBtn = document.getElementById("next-btn");
    const rematchBtn = document.getElementById("rematch-btn");
    const rematchStatus = document.getElementById("rematch-status");
    rematchStatus.textContent = "";

    if (data.match_over) {
      nextBtn.classList.add("hidden");
      rematchBtn.classList.remove("hidden");
      if (data.match_winner === "you") winnerEl.textContent = "🎉 Вы выиграли матч!";
      else if (data.match_winner === "opponent") winnerEl.textContent = "Соперник выиграл матч.";
      else winnerEl.textContent = "Матч завершился вничью.";
    } else {
      nextBtn.classList.remove("hidden");
      rematchBtn.classList.add("hidden");
    }

    showScreen("result");
  });

  document.getElementById("next-btn").addEventListener("click", () => {
    showScreen("waiting");
    document.querySelector("#screen-waiting p").textContent = "Ждём начала следующего раунда…";
  });

  document.getElementById("rematch-btn").addEventListener("click", (e) => {
    socket.emit("play_again");
    e.target.disabled = true;
    document.getElementById("rematch-status").textContent = "Ждём решения соперника…";
  });

  socket.on("opponent_wants_rematch", () => {
    document.getElementById("rematch-status").textContent = "Соперник хочет сыграть ещё раз!";
  });
})();

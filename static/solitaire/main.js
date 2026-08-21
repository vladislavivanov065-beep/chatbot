(function () {
  const SUITS = ['S', 'C', 'H', 'D'];
  const SUIT_SYMBOL = { S: '♠', C: '♣', H: '♥', D: '♦' };
  const SUIT_COLOR = { S: 'black', C: 'black', H: 'red', D: 'red' };
  const RANK_LABEL = { 1: 'A', 11: 'J', 12: 'Q', 13: 'K' };

  const newGameBtn = document.getElementById('new-game-btn');
  const hintText = document.getElementById('hint-text');
  const stockPile = document.getElementById('stock-pile');
  const wastePile = document.getElementById('waste-pile');
  const foundationEls = Array.from(document.querySelectorAll('.foundation-pile'));
  const tableauEl = document.getElementById('tableau');
  const winBanner = document.getElementById('win-banner');

  let state = null;
  let selected = null;   // {source: 'waste'|'tableau', colIndex, cardIndex}
  let hintTimer = null;

  function rankLabel(rank) {
    return RANK_LABEL[rank] || String(rank);
  }

  function newDeck() {
    const deck = [];
    let id = 0;
    SUITS.forEach((suit) => {
      for (let rank = 1; rank <= 13; rank++) {
        deck.push({ id: id++, suit, rank, faceUp: false });
      }
    });
    for (let i = deck.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [deck[i], deck[j]] = [deck[j], deck[i]];
    }
    return deck;
  }

  function newGame() {
    const deck = newDeck();
    const tableau = [];
    for (let col = 0; col < 7; col++) {
      const cards = deck.splice(0, col + 1);
      cards[cards.length - 1].faceUp = true;
      tableau.push(cards);
    }
    state = {
      tableau,
      foundations: { S: [], C: [], H: [], D: [] },
      stock: deck,
      waste: [],
      won: false,
    };
    selected = null;
    winBanner.hidden = true;
    render();
  }

  function flashHint(text) {
    hintText.textContent = text;
    if (hintTimer) clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { hintText.textContent = ''; }, 2200);
  }

  // ---------- move logic ----------

  function canPlaceOnTableau(destColIndex, movingCards) {
    const destCol = state.tableau[destColIndex];
    const head = movingCards[0];
    if (!destCol.length) return head.rank === 13;
    const top = destCol[destCol.length - 1];
    return head.rank === top.rank - 1 && SUIT_COLOR[head.suit] !== SUIT_COLOR[top.suit];
  }

  function canPlaceOnFoundation(suit, card) {
    if (card.suit !== suit) return false;
    const pile = state.foundations[suit];
    if (!pile.length) return card.rank === 1;
    return card.rank === pile[pile.length - 1].rank + 1;
  }

  function movingCardsFor(sel) {
    if (sel.source === 'waste') {
      return state.waste.length ? [state.waste[state.waste.length - 1]] : [];
    }
    return state.tableau[sel.colIndex].slice(sel.cardIndex);
  }

  function removeSource(sel) {
    if (sel.source === 'waste') {
      state.waste.pop();
    } else {
      const col = state.tableau[sel.colIndex];
      col.length = sel.cardIndex;
      if (col.length && !col[col.length - 1].faceUp) col[col.length - 1].faceUp = true;
    }
  }

  function tryMoveToTableau(sel, destColIndex) {
    if (sel.source === 'tableau' && sel.colIndex === destColIndex) {
      selected = null;
      render();
      return;
    }
    const cards = movingCardsFor(sel);
    if (!cards.length) return;
    if (!canPlaceOnTableau(destColIndex, cards)) {
      flashHint('Недопустимый ход');
      return;
    }
    state.tableau[destColIndex].push(...cards);
    removeSource(sel);
    selected = null;
    afterMove();
  }

  function tryMoveToFoundation(sel, suit) {
    const cards = movingCardsFor(sel);
    if (cards.length !== 1) {
      flashHint('На дом переносится только одна карта');
      return;
    }
    if (!canPlaceOnFoundation(suit, cards[0])) {
      flashHint('Недопустимый ход');
      return;
    }
    state.foundations[suit].push(cards[0]);
    removeSource(sel);
    selected = null;
    afterMove();
  }

  function autoToFoundation(source, colIndex, cardIndex) {
    let card, suit;
    if (source === 'waste') {
      if (!state.waste.length) return false;
      card = state.waste[state.waste.length - 1];
    } else {
      const col = state.tableau[colIndex];
      if (cardIndex !== col.length - 1) return false;
      card = col[col.length - 1];
    }
    suit = card.suit;
    if (!canPlaceOnFoundation(suit, card)) return false;
    state.foundations[suit].push(card);
    removeSource({ source, colIndex, cardIndex });
    selected = null;
    afterMove();
    return true;
  }

  function afterMove() {
    checkWin();
    render();
  }

  function checkWin() {
    const total = SUITS.reduce((sum, s) => sum + state.foundations[s].length, 0);
    if (total === 52) {
      state.won = true;
      winBanner.hidden = false;
    }
  }

  function drawStock() {
    if (state.stock.length) {
      const card = state.stock.pop();
      card.faceUp = true;
      state.waste.push(card);
    } else if (state.waste.length) {
      state.stock = state.waste.reverse().map((c) => { c.faceUp = false; return c; });
      state.waste = [];
    } else {
      flashHint('Колода пуста');
    }
    render();
  }

  // ---------- rendering ----------

  function makeCardEl(card, extraClasses) {
    const el = document.createElement('div');
    el.className = 'card ' + (card.faceUp ? SUIT_COLOR[card.suit] : 'face-down') + (extraClasses ? ' ' + extraClasses : '');
    if (card.faceUp) {
      el.innerHTML =
        `<div class="rank-top">${rankLabel(card.rank)}${SUIT_SYMBOL[card.suit]}</div>` +
        `<div class="suit-mid">${SUIT_SYMBOL[card.suit]}</div>` +
        `<div class="rank-bottom">${rankLabel(card.rank)}${SUIT_SYMBOL[card.suit]}</div>`;
    }
    return el;
  }

  function render() {
    window.__lastStateForTest = state;

    // stock
    stockPile.innerHTML = '';
    if (state.stock.length) {
      const el = makeCardEl({ faceUp: false });
      el.addEventListener('click', drawStock);
      stockPile.appendChild(el);
    } else {
      const slot = document.createElement('div');
      slot.className = 'card-slot empty';
      slot.title = state.waste.length ? 'Пересобрать колоду' : 'Пусто';
      slot.addEventListener('click', drawStock);
      stockPile.appendChild(slot);
    }

    // waste
    wastePile.innerHTML = '';
    if (state.waste.length) {
      const top = state.waste[state.waste.length - 1];
      const isSelected = selected && selected.source === 'waste';
      const el = makeCardEl(top, isSelected ? 'selected' : '');
      el.addEventListener('click', () => onCardClick('waste', null, state.waste.length - 1));
      el.addEventListener('dblclick', () => autoToFoundation('waste', null, state.waste.length - 1));
      wastePile.appendChild(el);
    }

    // foundations
    foundationEls.forEach((pileEl) => {
      const suit = pileEl.dataset.suit;
      pileEl.innerHTML = '';
      const pile = state.foundations[suit];
      if (pile.length) {
        const top = pile[pile.length - 1];
        const el = makeCardEl(top);
        el.addEventListener('click', () => onDestClick({ type: 'foundation', suit }));
        pileEl.appendChild(el);
      } else {
        const hint = document.createElement('div');
        hint.className = 'foundation-suit-hint';
        hint.textContent = SUIT_SYMBOL[suit];
        hint.style.pointerEvents = 'auto';
        hint.style.cursor = 'pointer';
        hint.addEventListener('click', () => onDestClick({ type: 'foundation', suit }));
        pileEl.appendChild(hint);
      }
    });

    // tableau
    tableauEl.innerHTML = '';
    state.tableau.forEach((col, colIndex) => {
      const colEl = document.createElement('div');
      colEl.className = 'tableau-col';
      if (!col.length) {
        const slot = document.createElement('div');
        slot.className = 'card-slot empty';
        slot.addEventListener('click', () => onDestClick({ type: 'tableau', colIndex }));
        colEl.appendChild(slot);
      } else {
        col.forEach((card, cardIndex) => {
          const isSelected = selected && selected.source === 'tableau' &&
            selected.colIndex === colIndex && cardIndex >= selected.cardIndex;
          const el = makeCardEl(card, isSelected ? 'selected' : '');
          el.style.top = (cardIndex * 24) + 'px';
          el.style.zIndex = String(cardIndex);
          if (card.faceUp) {
            el.addEventListener('click', () => onCardClick('tableau', colIndex, cardIndex));
            el.addEventListener('dblclick', () => autoToFoundation('tableau', colIndex, cardIndex));
          } else {
            el.addEventListener('click', () => onDestClick({ type: 'tableau', colIndex }));
          }
          colEl.appendChild(el);
        });
        colEl.style.height = (24 * (col.length - 1) + 92) + 'px';
      }
      tableauEl.appendChild(colEl);
    });
  }

  function onCardClick(source, colIndex, cardIndex) {
    if (selected) {
      if (source === 'tableau') {
        onDestClick({ type: 'tableau', colIndex });
        return;
      }
      // clicked the waste card again while something is selected: treat as reselect
    }
    selected = { source, colIndex, cardIndex };
    render();
  }

  function onDestClick(dest) {
    if (!selected) return;
    if (dest.type === 'tableau') {
      tryMoveToTableau(selected, dest.colIndex);
    } else if (dest.type === 'foundation') {
      tryMoveToFoundation(selected, dest.suit);
    }
  }

  newGameBtn.addEventListener('click', newGame);

  newGame();
})();

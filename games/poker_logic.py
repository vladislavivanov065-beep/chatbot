"""Pure game engine for Texas Hold'em poker (2-8 players, chips only — no real money).

No Flask/socket dependencies here — keyed by opaque player tokens
(account usernames), same convention as the other card games on this
site. See games/poker.py for the network layer.

House rules / MVP simplifications: fixed blinds (no escalating levels),
no antes, standard side-pot splitting for all-ins, ties split a pot
evenly with any odd remainder chip going to the earliest player left
of the dealer among the winners. A "session" plays hands back to back
automatically (dealer button rotating each time) until only one
player still has chips.
"""
import itertools
import random
import uuid
from collections import Counter

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠", "♣", "♥", "♦"]
RANK_VALUES = {r: i + 2 for i, r in enumerate(RANKS)}

MIN_PLAYERS = 2
MAX_PLAYERS = 8
STARTING_STACK = 1000
SMALL_BLIND = 10
BIG_BLIND = 20

HAND_CATEGORY_NAMES = {
    8: "Стрит-флеш", 7: "Каре", 6: "Фулл-хаус", 5: "Флеш", 4: "Стрит",
    3: "Сет", 2: "Две пары", 1: "Пара", 0: "Старшая карта",
}


def _new_id():
    return uuid.uuid4().hex[:10]


def _build_deck():
    return [{"id": _new_id(), "rank": r, "suit": s} for r in RANKS for s in SUITS]


# ---------- hand evaluation ----------

def _rank5(cards):
    """Score a single 5-card hand. Higher tuple = better hand."""
    values = sorted((RANK_VALUES[c["rank"]] for c in cards), reverse=True)
    suits = [c["suit"] for c in cards]
    is_flush = len(set(suits)) == 1

    unique_values = sorted(set(values), reverse=True)
    is_straight = False
    straight_high = None
    if len(unique_values) == 5 and unique_values[0] - unique_values[4] == 4:
        is_straight = True
        straight_high = unique_values[0]
    elif set(unique_values) == {14, 5, 4, 3, 2}:
        is_straight = True
        straight_high = 5

    counts = Counter(values)
    by_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    counts_sorted = [c for _, c in by_count]
    ranks_by_count = [r for r, _ in by_count]

    if is_straight and is_flush:
        return (8, straight_high)
    if counts_sorted[0] == 4:
        return (7, ranks_by_count[0], ranks_by_count[1])
    if counts_sorted[0] == 3 and counts_sorted[1] == 2:
        return (6, ranks_by_count[0], ranks_by_count[1])
    if is_flush:
        return (5,) + tuple(values)
    if is_straight:
        return (4, straight_high)
    if counts_sorted[0] == 3:
        return (3, ranks_by_count[0]) + tuple(ranks_by_count[1:])
    if counts_sorted[0] == 2 and counts_sorted[1] == 2:
        return (2, ranks_by_count[0], ranks_by_count[1], ranks_by_count[2])
    if counts_sorted[0] == 2:
        return (1, ranks_by_count[0]) + tuple(ranks_by_count[1:])
    return (0,) + tuple(values)


def best_hand(cards):
    """Best 5-card hand (score, cards) out of 5-7 given cards."""
    best_score = None
    best_combo = None
    for combo in itertools.combinations(cards, 5):
        score = _rank5(list(combo))
        if best_score is None or score > best_score:
            best_score = score
            best_combo = combo
    return best_score, list(best_combo)


def hand_category_name(score):
    return HAND_CATEGORY_NAMES.get(score[0], "?")


# ---------- game engine ----------

class PokerGame:
    def __init__(self, max_players=8):
        self.max_players = max(MIN_PLAYERS, min(max_players, MAX_PLAYERS))

        self.seat_order = []
        self.started = False
        self.finished = False
        self.winner = None

        self.rng = random.Random()
        self.stacks = {}
        self.dealer_idx = -1

        self.phase = "waiting"   # waiting | hand | between_hands
        self.stage = None        # preflop | flop | turn | river | showdown
        self.deck = []
        self.community = []
        self.hole_cards = {}
        self.folded = set()
        self.all_in = set()
        self.player_bets = {}       # this betting round
        self.total_committed = {}   # this whole hand
        self.current_bet = 0
        self.min_raise = BIG_BLIND
        self.acted_this_round = set()
        self.active_order = []      # tokens still dealt in, in acting order
        self.turn_idx = 0
        self.last_hand_summary = []

        self.log = []

    # ---------- lobby ----------

    def add_player(self, token):
        if self.started or token in self.seat_order:
            return None
        if len(self.seat_order) >= self.max_players:
            return None
        self.seat_order.append(token)
        self.stacks[token] = STARTING_STACK
        return len(self.seat_order) - 1

    def can_start(self):
        return not self.started and len(self.seat_order) >= MIN_PLAYERS

    def start(self):
        if not self.can_start():
            return False
        self.started = True
        self._log("Игра началась.")
        self._start_hand()
        return True

    def _log(self, text):
        self.log.append(text)
        self.log = self.log[-60:]

    # ---------- hand setup ----------

    def _players_with_chips(self):
        return [t for t in self.seat_order if self.stacks.get(t, 0) > 0]

    def _start_hand(self):
        contenders = self._players_with_chips()
        if len(contenders) < 2:
            self.finished = True
            self.winner = contenders[0] if contenders else None
            self.phase = "between_hands"
            self.total_committed = {}
            self.player_bets = {}
            if self.winner:
                self._log(f"{self.winner} выигрывает всю игру!")
            return

        self.dealer_idx = (self.dealer_idx + 1) % len(self.seat_order)
        while self.seat_order[self.dealer_idx] not in contenders:
            self.dealer_idx = (self.dealer_idx + 1) % len(self.seat_order)

        order = []
        i = self.dealer_idx
        for _ in range(len(self.seat_order)):
            t = self.seat_order[i]
            if t in contenders:
                order.append(t)
            i = (i + 1) % len(self.seat_order)
        self.active_order = order

        self.deck = _build_deck()
        self.rng.shuffle(self.deck)
        self.community = []
        self.hole_cards = {t: [self.deck.pop(), self.deck.pop()] for t in order}
        self.folded = set()
        self.all_in = set()
        self.total_committed = {t: 0 for t in order}
        self.last_hand_summary = []

        sb_idx = 1 % len(order) if len(order) > 2 else 0
        bb_idx = 2 % len(order) if len(order) > 2 else 1
        sb_token = order[sb_idx]
        bb_token = order[bb_idx]
        self._post_blind(sb_token, SMALL_BLIND)
        self._post_blind(bb_token, BIG_BLIND)

        self.current_bet = BIG_BLIND
        self.min_raise = BIG_BLIND
        self.phase = "hand"
        self.stage = "preflop"
        self.player_bets = {t: (SMALL_BLIND if t == sb_token else BIG_BLIND if t == bb_token else 0) for t in order}
        self.acted_this_round = set()
        self.turn_idx = (bb_idx + 1) % len(order) if len(order) > 2 else 0
        self._log(f"Новая раздача. Дилер: {order[0]}, малый блайнд: {sb_token}, большой блайнд: {bb_token}.")
        self._skip_to_actionable()

    def _post_blind(self, token, amount):
        amount = min(amount, self.stacks[token])
        self.stacks[token] -= amount
        self.total_committed[token] += amount
        if self.stacks[token] == 0:
            self.all_in.add(token)

    # ---------- betting ----------

    def _live_players(self):
        return [t for t in self.active_order if t not in self.folded]

    def _can_act(self, token):
        return token not in self.folded and token not in self.all_in

    def _skip_to_actionable(self):
        n = len(self.active_order)
        if n == 0:
            return
        for _ in range(n):
            t = self.active_order[self.turn_idx]
            if self._can_act(t):
                return
            self.turn_idx = (self.turn_idx + 1) % n
        # nobody can act (all folded/all-in) -> resolve round

    def current_player(self):
        if self.phase != "hand" or not self.active_order:
            return None
        if self._round_needs_no_more_action():
            return None
        return self.active_order[self.turn_idx]

    def _round_needs_no_more_action(self):
        live = self._live_players()
        if len(live) <= 1:
            return True
        actionable = [t for t in live if self._can_act(t)]
        if not actionable:
            return True
        for t in actionable:
            if t not in self.acted_this_round or self.player_bets.get(t, 0) != self.current_bet:
                return False
        return True

    def act(self, token, action, amount=None):
        if self.phase != "hand" or self.finished:
            return False, "Сейчас не идёт раздача"
        if self.current_player() != token:
            return False, "Сейчас не ваш ход"

        if action == "fold":
            self.folded.add(token)
            self.acted_this_round.add(token)
            self._log(f"{token} сбрасывает карты.")
        elif action == "check":
            if self.player_bets.get(token, 0) != self.current_bet:
                return False, "Нельзя чекнуть — есть ставка для колла"
            self.acted_this_round.add(token)
            self._log(f"{token} чекает.")
        elif action == "call":
            to_call = self.current_bet - self.player_bets.get(token, 0)
            pay = min(to_call, self.stacks[token])
            self.stacks[token] -= pay
            self.player_bets[token] = self.player_bets.get(token, 0) + pay
            self.total_committed[token] += pay
            if self.stacks[token] == 0:
                self.all_in.add(token)
            self.acted_this_round.add(token)
            self._log(f"{token} уравнивает" + (f" на {pay}" if pay else "") + ".")
        elif action == "raise":
            if amount is None:
                return False, "Не указана сумма"
            current_player_bet = self.player_bets.get(token, 0)
            stack = self.stacks[token]
            max_total = current_player_bet + stack
            amount = min(amount, max_total)
            if amount <= self.current_bet and amount < max_total:
                return False, "Сумма меньше текущей ставки"
            raise_size = amount - self.current_bet
            is_all_in = amount == max_total
            if raise_size < self.min_raise and not is_all_in:
                return False, f"Минимальное повышение — до {self.current_bet + self.min_raise}"
            pay = amount - current_player_bet
            self.stacks[token] -= pay
            self.player_bets[token] = amount
            self.total_committed[token] += pay
            if raise_size > 0:
                self.min_raise = raise_size
            self.current_bet = amount
            if self.stacks[token] == 0:
                self.all_in.add(token)
            self.acted_this_round = {token}
            self._log(f"{token} повышает до {amount}" + (" (ва-банк)" if is_all_in else "") + ".")
        else:
            return False, "Неизвестное действие"

        self._advance_after_action()
        return True, None

    def _advance_after_action(self):
        live = self._live_players()
        if len(live) <= 1:
            self._finish_hand_by_fold(live[0] if live else None)
            return
        n = len(self.active_order)
        self.turn_idx = (self.turn_idx + 1) % n
        self._skip_to_actionable()
        if self._round_needs_no_more_action():
            self._advance_stage()

    def _advance_stage(self):
        live = self._live_players()
        if len(live) <= 1:
            self._finish_hand_by_fold(live[0] if live else None)
            return

        actionable = [t for t in live if self._can_act(t)]
        if self.stage == "river" or len(actionable) <= 1:
            if self.stage != "river":
                while self.stage != "river":
                    self._deal_next_stage()
            self._showdown()
            return

        self._deal_next_stage()
        self.player_bets = {t: 0 for t in self.active_order}
        self.current_bet = 0
        self.min_raise = BIG_BLIND
        self.acted_this_round = set()
        n = len(self.active_order)
        self.turn_idx = 0
        for offset in range(n):
            idx = offset % n
            if self._can_act(self.active_order[idx]):
                self.turn_idx = idx
                break
        self._skip_to_actionable()
        if self._round_needs_no_more_action():
            self._advance_stage()

    def _deal_next_stage(self):
        if self.stage == "preflop":
            self.deck.pop()
            self.community.extend([self.deck.pop() for _ in range(3)])
            self.stage = "flop"
        elif self.stage == "flop":
            self.deck.pop()
            self.community.append(self.deck.pop())
            self.stage = "turn"
        elif self.stage == "turn":
            self.deck.pop()
            self.community.append(self.deck.pop())
            self.stage = "river"
        self._log(f"{self.stage.capitalize()}: {' '.join(self._card_label(c) for c in self.community)}")

    def _card_label(self, card):
        return f"{card['rank']}{card['suit']}"

    # ---------- showdown / pot distribution ----------

    def _compute_side_pots(self):
        remaining = dict(self.total_committed)
        pots = []
        while any(v > 0 for v in remaining.values()):
            min_amt = min(v for v in remaining.values() if v > 0)
            layer_players = [t for t, v in remaining.items() if v > 0]
            amount = min_amt * len(layer_players)
            eligible = [t for t in layer_players if t not in self.folded]
            pots.append({"amount": amount, "eligible": eligible})
            for t in layer_players:
                remaining[t] -= min_amt
        return pots

    def _refund_uncalled_bet(self):
        """If the largest total bet(s) in the hand were never matched by
        anyone still live (they folded instead of calling), the uncalled
        excess goes back to whoever put it in — the standard poker
        "uncalled bet" rule. Without this, that excess becomes one or more
        orphaned pot layers with no eligible winner and would otherwise
        just vanish. Every folded player's contribution above the live
        max is refunded, not just the single largest one, since several
        folded players can each have over-contributed at different levels."""
        live = self._live_players()
        if not live or not self.total_committed:
            return
        live_max = max(self.total_committed.get(t, 0) for t in live)
        for t, committed in list(self.total_committed.items()):
            if committed > live_max:
                refund = committed - live_max
                self.stacks[t] += refund
                self.total_committed[t] -= refund
                self._log(f"{t} получает назад неуравненную часть ставки ({refund}).")

    def _finish_hand_by_fold(self, winner):
        if winner:
            pot = sum(self.total_committed.values())
            self.stacks[winner] += pot
            self._log(f"Все остальные сбросили карты. {winner} забирает банк ({pot}).")
            self.last_hand_summary = [{"token": winner, "amount": pot, "hand": None}]
        self._end_hand()

    def _showdown(self):
        self.stage = "showdown"
        self._refund_uncalled_bet()
        pots = self._compute_side_pots()
        results = {}
        summary = []
        for pot in pots:
            eligible = pot["eligible"]
            if not eligible:
                continue
            if len(eligible) == 1:
                winners = eligible
            else:
                scored = [(t, best_hand(self.hole_cards[t] + self.community)[0]) for t in eligible]
                best_score = max(s for _, s in scored)
                winners = [t for t, s in scored if s == best_score]
            share = pot["amount"] // len(winners)
            remainder = pot["amount"] - share * len(winners)
            for i, w in enumerate(winners):
                amount = share + (remainder if i == 0 else 0)
                self.stacks[w] += amount
                results[w] = results.get(w, 0) + amount

        for t, amount in results.items():
            score, _ = best_hand(self.hole_cards[t] + self.community)
            summary.append({
                "token": t,
                "amount": amount,
                "hand": hand_category_name(score),
                "cards": self.hole_cards[t],
            })
        self.last_hand_summary = summary
        for t in self._live_players():
            label = hand_category_name(best_hand(self.hole_cards[t] + self.community)[0])
            self._log(f"{t} показывает: {' '.join(self._card_label(c) for c in self.hole_cards[t])} ({label}).")
        for t, amount in results.items():
            self._log(f"{t} забирает {amount} из банка.")
        self._end_hand()

    def _end_hand(self):
        self.phase = "between_hands"
        busted = [t for t in self.seat_order if self.stacks.get(t, 0) == 0]
        for t in busted:
            if t in self.active_order:
                self._log(f"{t} выбывает без фишек.")
        if len(self._players_with_chips()) < 2:
            self.finished = True
            winner = self._players_with_chips()
            self.winner = winner[0] if winner else None
            self.total_committed = {}
            self.player_bets = {}
            if self.winner:
                self._log(f"{self.winner} выигрывает всю игру!")
            return
        self._start_hand()

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if not self.started:
            if token in self.seat_order:
                self.seat_order.remove(token)
            return
        if token not in self.seat_order:
            return
        self.stacks[token] = 0
        if self.phase == "hand" and token in self.active_order and token not in self.folded:
            # Check whose turn it was BEFORE folding them: folding can itself
            # close the betting round, which makes current_player() return
            # None — comparing against the post-fold current_player() would
            # then never match, leaving turn_idx stuck pointing at a folded
            # player and the game unable to progress.
            was_their_turn = self.active_order[self.turn_idx] == token
            self.folded.add(token)
            live = self._live_players()
            if len(live) <= 1:
                self._finish_hand_by_fold(live[0] if live else None)
            elif was_their_turn:
                self._advance_after_action()
            elif self._round_needs_no_more_action():
                self._advance_stage()
        self._log(f"{token} покинул(а) игру.")
        if len(self._players_with_chips()) < 2 and self.phase != "hand":
            self.finished = True
            winner = self._players_with_chips()
            self.winner = winner[0] if winner else None

    # ---------- serialization ----------

    def state_for(self, token):
        base = {
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "max_players": self.max_players,
        }
        if not self.started:
            base["seats"] = list(self.seat_order)
            base["can_start"] = self.can_start()
            base["my_seat"] = self.seat_order.index(token) if token in self.seat_order else None
            return base

        base.update({
            "phase": self.phase,
            "stage": self.stage,
            "community": self.community,
            "stacks": dict(self.stacks),
            "seats": list(self.seat_order),
            "dealer": self.seat_order[self.dealer_idx] if self.dealer_idx >= 0 else None,
            "active_order": list(self.active_order),
            "folded": list(self.folded),
            "all_in": list(self.all_in),
            "player_bets": dict(self.player_bets),
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "current_player": self.current_player(),
            "is_my_turn": self.current_player() == token,
            "pot": sum(self.total_committed.values()) if self.phase == "hand" else sum(
                s["amount"] for s in self.last_hand_summary
            ),
            "my_hole_cards": self.hole_cards.get(token, []),
            "last_hand_summary": self.last_hand_summary,
            "log": self.log[-30:],
        })
        if self.phase == "hand":
            my_bet = self.player_bets.get(token, 0)
            to_call = max(0, self.current_bet - my_bet)
            base["to_call"] = to_call
            base["my_stack"] = self.stacks.get(token, 0)
        return base

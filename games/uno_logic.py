"""Pure game engine for Uno (2-6 players).

No Flask/socket dependencies here — keyed by opaque player tokens
(account usernames), same convention as the other card game on this
site, Дурак. Unlike Дурак's "everyone submits, then resolve" turn
model, Uno is strictly sequential (one player acts, then the next),
so this mirrors Chess's alternating-turn pattern instead.

House rules used below: drawing is always allowed even if you hold a
playable card (not forced-play); a drawn card may be played
immediately that same turn if it's legal, otherwise the turn passes;
Wild Draw Four may only be played when you hold no card matching the
current color (the standard tournament restriction); the UNO-call
catch window stays open until the caller calls it, gets caught, or
their hand size changes — there's no strict "before the next player's
turn" cutoff.
"""
import random
import uuid

COLORS = ["red", "yellow", "green", "blue"]
ACTIONS = ["skip", "reverse", "draw2"]
MIN_PLAYERS = 2
MAX_PLAYERS = 6
START_HAND_SIZE = 7


def _new_id():
    return uuid.uuid4().hex[:10]


def _build_deck():
    deck = []
    for color in COLORS:
        deck.append({"id": _new_id(), "color": color, "value": "0"})
        for n in range(1, 10):
            deck.append({"id": _new_id(), "color": color, "value": str(n)})
            deck.append({"id": _new_id(), "color": color, "value": str(n)})
        for action in ACTIONS:
            deck.append({"id": _new_id(), "color": color, "value": action})
            deck.append({"id": _new_id(), "color": color, "value": action})
    for _ in range(4):
        deck.append({"id": _new_id(), "color": None, "value": "wild"})
        deck.append({"id": _new_id(), "color": None, "value": "wild4"})
    return deck


def _is_wild(card):
    return card["value"] in ("wild", "wild4")


class UnoGame:
    def __init__(self, max_players=6):
        self.max_players = max(MIN_PLAYERS, min(max_players, MAX_PLAYERS))

        self.seat_order = []
        self.started = False
        self.finished = False
        self.winner = None

        self.rng = random.Random()
        self.hands = {}
        self.draw_pile = []
        self.discard_pile = []
        self.direction = 1
        self.current_idx = 0
        self.current_color = None
        self.pending_uno = set()
        self.log = []

    # ---------- lobby ----------

    def add_player(self, token):
        if self.started or token in self.seat_order:
            return None
        if len(self.seat_order) >= self.max_players:
            return None
        self.seat_order.append(token)
        return len(self.seat_order) - 1

    def can_start(self):
        return not self.started and len(self.seat_order) >= MIN_PLAYERS

    def start(self):
        if not self.can_start():
            return False

        deck = _build_deck()
        self.rng.shuffle(deck)
        self.hands = {t: [] for t in self.seat_order}
        for _ in range(START_HAND_SIZE):
            for t in self.seat_order:
                self.hands[t].append(deck.pop())

        # first discard can't be a wild4 (standard rule); reshuffle if it is
        first = deck.pop()
        while first["value"] == "wild4":
            deck.insert(0, first)
            self.rng.shuffle(deck)
            first = deck.pop()
        self.discard_pile = [first]
        self.current_color = first["color"] if first["color"] else self.rng.choice(COLORS)
        self.draw_pile = deck

        self.direction = 1
        self.current_idx = 0
        self.started = True
        self._log(f"Игра началась. Первая карта: {self._card_label(first)}.")

        if first["value"] == "skip":
            self._advance(2)
        elif first["value"] == "reverse":
            if len(self.seat_order) > 2:
                self.direction *= -1
            self._advance(1)
        elif first["value"] == "draw2":
            victim = self._player_at(1)
            self._draw_cards(victim, 2)
            self._log(f"{victim} берёт 2 карты (стартовая карта +2).")
            self._advance(2)
        return True

    # ---------- helpers ----------

    def _log(self, text):
        self.log.append(text)
        self.log = self.log[-50:]

    def _card_label(self, card):
        if card["value"] == "wild":
            return "Дикая"
        if card["value"] == "wild4":
            return "Дикая +4"
        return f"{card['color']} {card['value']}"

    def current_player(self):
        if not self.seat_order:
            return None
        return self.seat_order[self.current_idx]

    def _player_at(self, steps):
        return self.seat_order[(self.current_idx + steps * self.direction) % len(self.seat_order)]

    def _advance(self, steps):
        self.current_idx = (self.current_idx + steps * self.direction) % len(self.seat_order)

    def _reshuffle_if_needed(self):
        if self.draw_pile:
            return
        if len(self.discard_pile) <= 1:
            return
        top = self.discard_pile[-1]
        rest = self.discard_pile[:-1]
        for c in rest:
            c["color"] = c["color"] if c["value"] not in ("wild", "wild4") else None
        self.rng.shuffle(rest)
        self.draw_pile = rest
        self.discard_pile = [top]
        self._log("Колода закончилась — перемешана из отбоя.")

    def _draw_cards(self, token, count):
        drawn = []
        for _ in range(count):
            self._reshuffle_if_needed()
            if not self.draw_pile:
                break
            card = self.draw_pile.pop()
            self.hands[token].append(card)
            drawn.append(card)
        if len(self.hands[token]) != 1:
            self.pending_uno.discard(token)
        return drawn

    # ---------- actions ----------

    def submit_play(self, token, card_id, chosen_color=None):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if self.current_player() != token:
            return False, "Сейчас не ваш ход"
        hand = self.hands.get(token)
        if hand is None:
            return False, "Вы не в игре"
        card = next((c for c in hand if c["id"] == card_id), None)
        if not card:
            return False, "Нет такой карты"

        top = self.discard_pile[-1]
        if card["value"] == "wild4":
            has_matching_color = any(c["color"] == self.current_color for c in hand if c["id"] != card_id)
            if has_matching_color:
                return False, "Нельзя сыграть +4, пока есть карта текущего цвета"
        elif not _is_wild(card):
            if card["color"] != self.current_color and card["value"] != top["value"]:
                return False, "Эта карта не подходит по цвету или значению"

        if _is_wild(card):
            if chosen_color not in COLORS:
                return False, "Выберите цвет для дикой карты"

        hand.remove(card)
        self.discard_pile.append(card)
        self.current_color = chosen_color if _is_wild(card) else card["color"]
        self._log(f"{token} играет: {self._card_label(card)}" + (f", выбирает {chosen_color}" if _is_wild(card) else "") + ".")

        if not hand:
            self.finished = True
            self.winner = token
            self._log(f"{token} избавился(лась) от всех карт и побеждает!")
            return True, None

        if len(hand) == 1:
            self.pending_uno.add(token)
        else:
            self.pending_uno.discard(token)

        self._apply_effect(card)
        return True, None

    def _apply_effect(self, card):
        if card["value"] == "skip":
            skipped = self._player_at(1)
            self._advance(2)
            self._log(f"{skipped} пропускает ход.")
        elif card["value"] == "reverse":
            if len(self.seat_order) > 2:
                self.direction *= -1
                self._advance(1)
            else:
                self._advance(2)
        elif card["value"] == "draw2":
            victim = self._player_at(1)
            self._draw_cards(victim, 2)
            self._log(f"{victim} берёт 2 карты и пропускает ход.")
            self._advance(2)
        elif card["value"] == "wild4":
            victim = self._player_at(1)
            self._draw_cards(victim, 4)
            self._log(f"{victim} берёт 4 карты и пропускает ход.")
            self._advance(2)
        else:
            self._advance(1)

    def submit_draw(self, token):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if self.current_player() != token:
            return False, "Сейчас не ваш ход"
        drawn = self._draw_cards(token, 1)
        if not drawn:
            return False, "Колода пуста"
        card = drawn[0]
        top = self.discard_pile[-1]
        playable = card["color"] == self.current_color or card["value"] == top["value"] or _is_wild(card)
        if card["value"] == "wild4" and playable:
            has_matching_color = any(c["color"] == self.current_color for c in self.hands[token] if c["id"] != card["id"])
            playable = not has_matching_color
        self._log(f"{token} берёт карту из колоды.")
        if not playable:
            self._advance(1)
        return True, None

    def submit_pass(self, token):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if self.current_player() != token:
            return False, "Сейчас не ваш ход"
        self._advance(1)
        self._log(f"{token} пропускает ход.")
        return True, None

    def call_uno(self, token):
        if token not in self.pending_uno:
            return False, "Нечего объявлять"
        self.pending_uno.discard(token)
        self._log(f"{token} кричит UNO!")
        return True, None

    def catch_uno(self, token, target):
        if target not in self.hands or len(self.hands[target]) != 1 or target not in self.pending_uno:
            return False, "Нечего ловить"
        self._draw_cards(target, 2)
        self.pending_uno.discard(target)
        self._log(f"{token} ловит {target} без UNO! {target} берёт 2 карты.")
        return True, None

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if not self.started:
            if token in self.seat_order:
                self.seat_order.remove(token)
            return
        if self.finished or token not in self.seat_order:
            return

        current_token = self.current_player()
        if current_token == token and len(self.seat_order) > 1:
            next_token = self._player_at(1)
        else:
            next_token = current_token

        for card in self.hands.pop(token, []):
            card["color"] = card["color"] if card["value"] not in ("wild", "wild4") else None
            self.draw_pile.insert(0, card)
        self.pending_uno.discard(token)
        self.seat_order.remove(token)
        self._log(f"{token} покинул(а) игру, карты возвращены в колоду.")

        if len(self.seat_order) == 1:
            self.finished = True
            self.winner = self.seat_order[0]
            self._log(f"{self.winner} побеждает — остальные игроки выбыли!")
            return
        if not self.seat_order:
            self.finished = True
            return

        if next_token in self.seat_order:
            self.current_idx = self.seat_order.index(next_token)
        else:
            self.current_idx %= len(self.seat_order)

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

        my_hand = self.hands.get(token, [])
        top = self.discard_pile[-1] if self.discard_pile else None

        base.update({
            "seats": list(self.seat_order),
            "my_hand": my_hand,
            "hand_sizes": {t: len(h) for t, h in self.hands.items()},
            "top_card": top,
            "current_color": self.current_color,
            "direction": self.direction,
            "current_player": self.current_player(),
            "is_my_turn": self.current_player() == token,
            "draw_pile_size": len(self.draw_pile),
            "pending_uno": list(self.pending_uno),
            "my_uno_pending": token in self.pending_uno,
            "log": self.log[-30:],
        })
        return base

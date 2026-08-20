"""Pure game engine for Durak (Дурак), podkidnoy and perevodnoy variants.

No Flask/socket dependencies here — this module only knows about cards,
hands, and turn order, keyed by opaque player tokens (account usernames).
See the in-app rules summary in games/durak.py for the house-rule choices
made below (single-attacker "бито" confirmation, immediate "take", etc).
"""
import random

RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠", "♣", "♥", "♦"]
HAND_SIZE = 6
MAX_TABLE_CARDS = 6
MAX_PLAYERS = 5   # 36-card deck: 6 players * 6 cards would leave no talon card for the trump


def _rank_index(rank):
    return RANKS.index(rank)


class DurakGame:
    def __init__(self, variant="podkidnoy", max_players=4, allow_cheating=False):
        self.variant = variant  # "podkidnoy" | "perevodnoy"
        self.max_players = max(2, min(max_players, MAX_PLAYERS))
        self.allow_cheating = allow_cheating
        self.cheated_out = set()  # tokens who used up their one cheat attempt

        self.seat_order = []   # tokens, fixed turn order once started
        self.hands = {}        # token -> list[(rank, suit)]
        self.talon = []        # face-down draw pile; talon[0] is the trump card, drawn last
        self.trump_suit = None
        self.trump_card = None

        self.table = []        # list of {"attack": card, "defense": card|None}
        self.discard_count = 0
        self.attacker_idx = None
        self.defender_idx = None
        self._bout_defender_start_size = None

        self.started = False
        self.finished = False
        self.fool = None
        self.out_of_game = set()

    # ---------- joining ----------

    def add_player(self, token):
        if self.started or token in self.seat_order:
            return None
        if len(self.seat_order) >= self.max_players:
            return None
        self.seat_order.append(token)
        return len(self.seat_order) - 1

    def can_start(self):
        return not self.started and len(self.seat_order) >= 2

    def start(self):
        if not self.can_start():
            return False

        deck = [(r, s) for s in SUITS for r in RANKS]
        random.shuffle(deck)

        self.hands = {t: [] for t in self.seat_order}
        for _ in range(HAND_SIZE):
            for t in self.seat_order:
                self.hands[t].append(deck.pop())

        self.trump_card = deck[0]
        self.trump_suit = self.trump_card[1]
        self.talon = deck

        best = None
        for t in self.seat_order:
            for card in self.hands[t]:
                if card[1] == self.trump_suit:
                    ri = _rank_index(card[0])
                    if best is None or ri < best[0]:
                        best = (ri, t)
        first_attacker = best[1] if best else self.seat_order[0]

        self.started = True
        self._start_bout(self.seat_order.index(first_attacker))
        return True

    # ---------- turn helpers ----------

    def current_attacker(self):
        return self.seat_order[self.attacker_idx] if self.attacker_idx is not None else None

    def current_defender(self):
        return self.seat_order[self.defender_idx] if self.defender_idx is not None else None

    def _next_active_index(self, idx):
        n = len(self.seat_order)
        if n == 0:
            return None
        for step in range(1, n + 1):
            candidate = (idx + step) % n
            if self.seat_order[candidate] not in self.out_of_game:
                return candidate
        return None

    def _start_bout(self, attacker_idx):
        self.attacker_idx = attacker_idx
        self.defender_idx = self._next_active_index(attacker_idx)
        self.table = []
        self._bout_defender_start_size = (
            len(self.hands[self.current_defender()]) if self.defender_idx is not None else 0
        )

    def _open_slots(self):
        return [slot for slot in self.table if slot["defense"] is None]

    def _table_ranks(self):
        ranks = set()
        for slot in self.table:
            ranks.add(slot["attack"][0])
            if slot["defense"]:
                ranks.add(slot["defense"][0])
        return ranks

    def _beats(self, attack_card, defense_card):
        ar, asuit = attack_card
        dr, dsuit = defense_card
        if dsuit == asuit:
            return _rank_index(dr) > _rank_index(ar)
        return dsuit == self.trump_suit and asuit != self.trump_suit

    def attack_cap(self):
        if self._bout_defender_start_size is None:
            return 0
        return min(MAX_TABLE_CARDS, self._bout_defender_start_size)

    # ---------- actions ----------

    def open_attack(self, token, card):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if token != self.current_attacker():
            return False, "Не ваш ход атаковать"
        if self.table:
            return False, "Раунд уже начат — используйте подкидывание"
        if card not in self.hands.get(token, []):
            return False, "Нет такой карты"
        self.hands[token].remove(card)
        self.table.append({"attack": card, "defense": None, "thrower": token, "illegal": False})
        return True, None

    def can_throw(self, token, card, as_cheat=False):
        if not self.started or self.finished or not self.table:
            return False
        if token not in self.seat_order or token == self.current_defender():
            return False
        if token in self.out_of_game:
            return False
        if card not in self.hands.get(token, []):
            return False
        if len(self.table) >= self.attack_cap():
            return False
        if card[0] not in self._table_ranks():
            return as_cheat and self.allow_cheating and token not in self.cheated_out
        return True

    def throw_in(self, token, card, as_cheat=False):
        if not self.can_throw(token, card, as_cheat=as_cheat):
            return False, "Нельзя подкинуть эту карту"
        illegal = card[0] not in self._table_ranks()
        self.hands[token].remove(card)
        self.table.append({"attack": card, "defense": None, "thrower": token, "illegal": illegal})
        return True, None

    def catch_cheat(self, catcher_token, card):
        """Challenge an open, still-undefended table card as an illegal throw-in.

        Returns (True, cheater_token) if the challenge was correct — the card
        goes back to the cheater's hand and they lose their ability to cheat
        again this game. Returns (False, error_message) otherwise, including
        when the challenged card turns out to have been legitimate.
        """
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if not self.allow_cheating:
            return False, "В этой игре мухлёж выключен"
        if catcher_token not in self.seat_order or catcher_token in self.out_of_game:
            return False, "Вы не участвуете в игре"
        slot = next(
            (s for s in self.table if tuple(s["attack"]) == tuple(card) and s["defense"] is None),
            None,
        )
        if not slot:
            return False, "Такой небитой карты на столе нет"
        thrower = slot.get("thrower")
        if catcher_token == thrower:
            return False, "Нельзя поймать свою же карту"
        if not slot.get("illegal"):
            return False, "Эта карта честная"
        self.table.remove(slot)
        self.hands[thrower].append(slot["attack"])
        self.cheated_out.add(thrower)
        return True, thrower

    def defend(self, token, attack_card, defense_card):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if token != self.current_defender():
            return False, "Не ваш ход защищаться"
        if defense_card not in self.hands.get(token, []):
            return False, "Нет такой карты"
        slot = next(
            (s for s in self.table if tuple(s["attack"]) == tuple(attack_card) and s["defense"] is None),
            None,
        )
        if not slot:
            return False, "Такой небитой карты на столе нет"
        if not self._beats(slot["attack"], defense_card):
            return False, "Эта карта не бьёт"
        self.hands[token].remove(defense_card)
        slot["defense"] = defense_card
        return True, None

    def can_transfer(self, token):
        if self.variant != "perevodnoy" or not self.started or self.finished:
            return False
        if token != self.current_defender() or not self.table:
            return False
        if len(self.seat_order) < 3:
            return False
        if any(s["defense"] is not None for s in self.table):
            return False
        ranks = self._table_ranks()
        if len(ranks) != 1:
            return False
        rank = next(iter(ranks))
        if not any(c[0] == rank for c in self.hands.get(token, [])):
            return False
        next_idx = self._next_active_index(self.defender_idx)
        if next_idx is None or next_idx == self.attacker_idx:
            return False
        next_defender = self.seat_order[next_idx]
        return len(self.table) + 1 <= min(MAX_TABLE_CARDS, len(self.hands[next_defender]))

    def transfer(self, token, card):
        if not self.can_transfer(token):
            return False, "Перевод сейчас невозможен"
        rank = next(iter(self._table_ranks()))
        if card[0] != rank or card not in self.hands.get(token, []):
            return False, "Нужна карта того же ранга"
        self.hands[token].remove(card)
        self.table.append({"attack": card, "defense": None, "thrower": token, "illegal": False})
        self.defender_idx = self._next_active_index(self.defender_idx)
        return True, None

    def take(self, token):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if token != self.current_defender():
            return False, "Не ваш ход"
        if not self.table:
            return False, "Стол пуст"
        cards = []
        for slot in self.table:
            cards.append(slot["attack"])
            if slot["defense"]:
                cards.append(slot["defense"])
        self.hands[token].extend(cards)
        self._resolve_bout(defender_took=True)
        return True, None

    def confirm_done(self, token):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        if token != self.current_attacker():
            return False, "Только атакующий может завершить розыгрыш"
        if not self.table:
            return False, "Стол пуст"
        if self._open_slots():
            return False, "Есть небитые карты"
        self.discard_count += 2 * len(self.table)
        self._resolve_bout(defender_took=False)
        return True, None

    # ---------- bout resolution ----------

    def _resolve_bout(self, defender_took):
        old_attacker_idx = self.attacker_idx
        old_defender_idx = self.defender_idx
        self.table = []
        self._bout_defender_start_size = None

        order = []
        idx = old_attacker_idx
        for _ in range(len(self.seat_order)):
            order.append(idx)
            idx = (idx + 1) % len(self.seat_order)
        if old_defender_idx in order:
            order.remove(old_defender_idx)
            order.append(old_defender_idx)

        for i in order:
            token = self.seat_order[i]
            if token in self.out_of_game:
                continue
            hand = self.hands[token]
            while len(hand) < HAND_SIZE and self.talon:
                hand.append(self.talon.pop())

        for t in list(self.seat_order):
            if t not in self.out_of_game and not self.hands[t] and not self.talon:
                self.out_of_game.add(t)

        active = [t for t in self.seat_order if t not in self.out_of_game]
        if not self.talon and len(active) <= 1:
            self.finished = True
            self.fool = active[0] if active else None
            return

        if defender_took:
            new_attacker_idx = self._next_active_index(old_defender_idx)
        elif self.seat_order[old_defender_idx] in self.out_of_game:
            new_attacker_idx = self._next_active_index(old_defender_idx)
        else:
            new_attacker_idx = old_defender_idx

        self._start_bout(new_attacker_idx)

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if token not in self.seat_order:
            return
        if not self.started:
            self.seat_order.remove(token)
            return

        idx = self.seat_order.index(token)
        was_attacker = idx == self.attacker_idx
        was_defender = idx == self.defender_idx

        self.hands.pop(token, None)
        self.out_of_game.discard(token)
        self.seat_order.pop(idx)
        if self.attacker_idx is not None and self.attacker_idx > idx:
            self.attacker_idx -= 1
        if self.defender_idx is not None and self.defender_idx > idx:
            self.defender_idx -= 1

        active = [t for t in self.seat_order if t not in self.out_of_game]
        if len(active) <= 1:
            self.finished = True
            self.fool = None
            return

        if was_attacker or was_defender:
            self.table = []
            self._bout_defender_start_size = None
            anchor = self.attacker_idx if was_attacker else self.defender_idx
            anchor = max(0, min(anchor, len(self.seat_order) - 1))
            start_idx = anchor if self.seat_order[anchor] not in self.out_of_game else self._next_active_index(anchor)
            self._start_bout(start_idx)
        else:
            self.defender_idx = self._next_active_index(self.attacker_idx)

    # ---------- serialization ----------

    def state_for(self, token):
        if not self.started:
            return {
                "started": False,
                "finished": False,
                "variant": self.variant,
                "max_players": self.max_players,
                "allow_cheating": self.allow_cheating,
                "seats": list(self.seat_order),
                "can_start": self.can_start(),
                "my_seat": self.seat_order.index(token) if token in self.seat_order else None,
            }

        def card_dict(card):
            return {"rank": card[0], "suit": card[1]} if card else None

        table = [
            {"attack": card_dict(s["attack"]), "defense": card_dict(s["defense"])}
            for s in self.table
        ]

        return {
            "started": True,
            "finished": self.finished,
            "fool": self.fool,
            "variant": self.variant,
            "trump_suit": self.trump_suit,
            "trump_card": card_dict(self.trump_card),
            "talon_count": len(self.talon),
            "discard_count": self.discard_count,
            "my_hand": [card_dict(c) for c in self.hands.get(token, [])],
            "my_seat": self.seat_order.index(token) if token in self.seat_order else None,
            "attacker": self.current_attacker(),
            "defender": self.current_defender(),
            "can_transfer": self.can_transfer(token),
            "has_open_slots": bool(self._open_slots()),
            "attack_cap": self.attack_cap(),
            "allow_cheating": self.allow_cheating,
            "my_cheated_out": token in self.cheated_out,
            "table": table,
            "players": [
                {
                    "token": t,
                    "hand_count": len(self.hands.get(t, [])),
                    "out": t in self.out_of_game,
                    "marked_cheater": t in self.cheated_out,
                }
                for t in self.seat_order
            ],
        }

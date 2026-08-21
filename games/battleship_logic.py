"""Pure game engine for multiplayer (2-4) Battleship ("Морской бой").

No Flask/socket dependencies here. Classic Russian ruleset: 10x10 board,
the standard 1x4-deck / 2x3-deck / 3x2-deck / 4x1-deck ship set, ships
may not touch each other (even diagonally). Turn order is round-robin —
on your turn you fire one shot at any single cell on any other living
player's board, then the turn passes to the next living player
regardless of hit or miss (a "everyone can be targeted" free-for-all,
rather than fixed 1-on-1 pairs).
"""
import random
import uuid

BOARD_SIZE = 10
SHIP_SIZES = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
MIN_PLAYERS = 2
MAX_PLAYERS = 4


def _new_id():
    return uuid.uuid4().hex[:10]


def _cells_for(x, y, size, horizontal):
    if horizontal:
        return [(x + i, y) for i in range(size)]
    return [(x, y + i) for i in range(size)]


def _in_bounds(x, y):
    return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE


class BattleshipGame:
    def __init__(self, max_players=4):
        self.max_players = max(MIN_PLAYERS, min(max_players, MAX_PLAYERS))

        self.seat_order = []
        self.phase = "waiting"   # waiting | placing | playing | finished
        self.finished = False
        self.winner = None

        self.rng = random.Random()
        self.players = {}   # token -> player dict, populated once placement starts
        self.turn_order = []
        self.current_idx = 0
        self.log = []

    # ---------- lobby ----------

    def add_player(self, token):
        if self.phase != "waiting" or token in self.seat_order:
            return None
        if len(self.seat_order) >= self.max_players:
            return None
        self.seat_order.append(token)
        return len(self.seat_order) - 1

    def can_start_placement(self):
        return self.phase == "waiting" and len(self.seat_order) >= MIN_PLAYERS

    def start_placement(self):
        if not self.can_start_placement():
            return False
        self.phase = "placing"
        for token in self.seat_order:
            self.players[token] = {
                "token": token,
                "ships": [],            # list of {id, size, cells, hits, sunk}
                "board_ship_at": {},    # (x, y) -> ship_id
                "shots_at_me": {},      # (x, y) -> "hit" | "miss"
                "ready": False,
                "alive": True,
            }
        self._log("Расстановка кораблей началась.")
        return True

    # ---------- placement ----------

    def _remaining_sizes(self, player):
        placed = sorted(s["size"] for s in player["ships"])
        remaining = sorted(SHIP_SIZES)
        for size in placed:
            remaining.remove(size)
        return remaining

    def _fits(self, player, cells):
        for (x, y) in cells:
            if not _in_bounds(x, y):
                return False
            if (x, y) in player["board_ship_at"]:
                return False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if (x + dx, y + dy) in player["board_ship_at"]:
                        return False
        return True

    def place_ship(self, token, x, y, size, horizontal):
        if self.phase != "placing":
            return False, "Сейчас не время расстановки"
        player = self.players.get(token)
        if not player or player["ready"]:
            return False, "Недоступно"
        if size not in self._remaining_sizes(player):
            return False, "Такого корабля больше нет"
        cells = _cells_for(x, y, size, horizontal)
        if not self._fits(player, cells):
            return False, "Нельзя разместить здесь (выход за поле или касание другого корабля)"
        ship = {"id": _new_id(), "size": size, "cells": cells, "hits": set(), "sunk": False}
        player["ships"].append(ship)
        for c in cells:
            player["board_ship_at"][c] = ship["id"]
        return True, None

    def remove_ship(self, token, ship_id):
        player = self.players.get(token)
        if not player or player["ready"]:
            return False, "Недоступно"
        ship = next((s for s in player["ships"] if s["id"] == ship_id), None)
        if not ship:
            return False, "Нет такого корабля"
        player["ships"].remove(ship)
        for c in ship["cells"]:
            player["board_ship_at"].pop(c, None)
        return True, None

    def randomize_board(self, token):
        player = self.players.get(token)
        if not player or player["ready"]:
            return False, "Недоступно"
        for _ in range(200):
            ships = []
            board_ship_at = {}
            ok = True
            for size in sorted(SHIP_SIZES, reverse=True):
                placed = False
                for _attempt in range(300):
                    horizontal = self.rng.random() < 0.5
                    x = self.rng.randint(0, BOARD_SIZE - 1)
                    y = self.rng.randint(0, BOARD_SIZE - 1)
                    cells = _cells_for(x, y, size, horizontal)
                    probe = {"board_ship_at": board_ship_at}
                    if self._fits(probe, cells):
                        ship = {"id": _new_id(), "size": size, "cells": cells, "hits": set(), "sunk": False}
                        ships.append(ship)
                        for c in cells:
                            board_ship_at[c] = ship["id"]
                        placed = True
                        break
                if not placed:
                    ok = False
                    break
            if ok:
                player["ships"] = ships
                player["board_ship_at"] = board_ship_at
                return True, None
        return False, "Не удалось расставить, попробуйте ещё раз"

    def set_ready(self, token):
        player = self.players.get(token)
        if not player:
            return False, "Недоступно"
        if len(player["ships"]) != len(SHIP_SIZES):
            return False, "Расставьте все корабли"
        player["ready"] = True
        self._log(f"{token} готов к бою.")
        if all(self.players[t]["ready"] for t in self.seat_order):
            self._start_playing()
        return True, None

    def _start_playing(self):
        self.phase = "playing"
        self.turn_order = list(self.seat_order)
        self.rng.shuffle(self.turn_order)
        self.current_idx = 0
        self._log(f"Бой начинается! Первым стреляет {self.turn_order[0]}.")

    # ---------- battle ----------

    def alive_tokens(self):
        return [t for t in self.turn_order if self.players[t]["alive"]]

    def fire(self, token, target_token, x, y):
        if self.phase != "playing" or self.finished:
            return False, "Бой ещё не идёт"
        if not self.turn_order or self.turn_order[self.current_idx] != token:
            return False, "Сейчас не ваш ход"
        if target_token == token:
            return False, "Нельзя стрелять по своему полю"
        target = self.players.get(target_token)
        if not target or not target["alive"]:
            return False, "Недоступная цель"
        if not _in_bounds(x, y):
            return False, "Клетка вне поля"
        if (x, y) in target["shots_at_me"]:
            return False, "Сюда уже стреляли"

        ship_id = target["board_ship_at"].get((x, y))
        if ship_id:
            target["shots_at_me"][(x, y)] = "hit"
            ship = next(s for s in target["ships"] if s["id"] == ship_id)
            ship["hits"].add((x, y))
            if len(ship["hits"]) >= ship["size"]:
                ship["sunk"] = True
                self._log(f"{token} потопил корабль игрока {target_token} ({ship['size']} палуб(а)).")
                if all(s["sunk"] for s in target["ships"]):
                    target["alive"] = False
                    self._log(f"{target_token} выбывает из боя!")
            else:
                self._log(f"{token} попал по полю {target_token}.")
        else:
            target["shots_at_me"][(x, y)] = "miss"
            self._log(f"{token} промахнулся по полю {target_token}.")

        alive = self.alive_tokens()
        if len(alive) <= 1:
            self.finished = True
            self.phase = "finished"
            self.winner = alive[0] if alive else None
            if self.winner:
                self._log(f"{self.winner} побеждает в морском бою!")
        else:
            self._advance_turn()

        return True, None

    def _advance_turn(self):
        if not self.turn_order:
            return
        for _ in range(len(self.turn_order)):
            self.current_idx = (self.current_idx + 1) % len(self.turn_order)
            if self.players[self.turn_order[self.current_idx]]["alive"]:
                return

    def _log(self, text):
        self.log.append(text)
        self.log = self.log[-30:]

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if self.phase == "waiting":
            if token in self.seat_order:
                self.seat_order.remove(token)
            return
        player = self.players.get(token)
        if not player:
            return
        if self.phase == "placing":
            player["ready"] = True
            player["alive"] = False
            if all(self.players[t]["ready"] for t in self.seat_order):
                remaining = [t for t in self.seat_order if self.players[t]["alive"]]
                if len(remaining) <= 1:
                    self.finished = True
                    self.phase = "finished"
                    self.winner = remaining[0] if remaining else None
                else:
                    self._start_playing()
            return
        if self.phase == "playing" and player["alive"]:
            player["alive"] = False
            self._log(f"{token} покинул бой и выбывает.")
            alive = self.alive_tokens()
            if len(alive) <= 1:
                self.finished = True
                self.phase = "finished"
                self.winner = alive[0] if alive else None
                if self.winner:
                    self._log(f"{self.winner} побеждает в морском бою!")
            elif self.turn_order[self.current_idx] == token:
                self._advance_turn()

    # ---------- serialization ----------

    def _own_grid(self, player):
        grid = [["empty" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        for (x, y), ship_id in player["board_ship_at"].items():
            grid[y][x] = "ship"
        for (x, y), result in player["shots_at_me"].items():
            grid[y][x] = "hit" if result == "hit" else "miss"
        return grid

    def _fog_grid(self, viewer_shots_placeholder, target_player):
        """Grid as seen by an opponent: only shot results, plus full outline
        of any ship that's been fully sunk."""
        grid = [["unknown" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        for (x, y), result in target_player["shots_at_me"].items():
            grid[y][x] = "hit" if result == "hit" else "miss"
        for ship in target_player["ships"]:
            if ship["sunk"]:
                for (x, y) in ship["cells"]:
                    grid[y][x] = "sunk"
        return grid

    def state_for(self, token):
        base = {
            "phase": self.phase,
            "finished": self.finished,
            "winner": self.winner,
            "max_players": self.max_players,
            "seats": list(self.seat_order),
            "log": self.log[-10:],
        }

        if self.phase == "waiting":
            base["can_start"] = self.can_start_placement()
            base["my_seat"] = self.seat_order.index(token) if token in self.seat_order else None
            return base

        player = self.players.get(token)
        if not player:
            return base

        if self.phase == "placing":
            base["my_ships"] = [
                {"id": s["id"], "size": s["size"], "cells": s["cells"]} for s in player["ships"]
            ]
            base["remaining_sizes"] = self._remaining_sizes(player)
            base["ready"] = player["ready"]
            base["others_ready"] = {t: self.players[t]["ready"] for t in self.seat_order if t != token}
            return base

        # playing / finished
        base["my_board"] = self._own_grid(player)
        base["my_alive"] = player["alive"]
        base["opponents"] = {}
        for t in self.seat_order:
            if t == token:
                continue
            opp = self.players[t]
            base["opponents"][t] = {"alive": opp["alive"], "grid": self._fog_grid(player, opp)}
        base["turn_token"] = self.turn_order[self.current_idx] if self.turn_order and not self.finished else None
        base["is_my_turn"] = base["turn_token"] == token
        base["targets"] = [t for t in self.seat_order if t != token and self.players[t]["alive"]]
        return base

"""Pure game engine for a co-op, turn-based, top-down dungeon crawler.

No Flask/socket dependencies here. A run is generated fresh each game:
procedural rooms-and-corridors map, enemies that get stronger the
further a room is from the spawn room, a shop, random loot drops, and
a boss at the far end. See games/dungeon.py for the network layer and
the in-app rules summary for the MVP simplifications made below
(cardinal-only movement, no ranged/line-of-sight, shared team gold,
real-time revival window).
"""
import random
import time
import uuid

WIDTH, HEIGHT = 19, 19
ROOM_COUNT = 7
MIN_ROOM, MAX_ROOM = 3, 5
MAX_PARTY = 4
AGGRO_RANGE = 6   # enemies only notice/chase a player within this many tiles
REVIVE_WINDOW_SECONDS = 60
INVENTORY_CAP = 8

BASE_HP = 30
BASE_ATTACK = 7
BASE_DEFENSE = 3
DEPTH_SCALE = 0.9

THEMES = {
    "forest": {"name": "Лес", "floor": "#3b5d3a", "wall": "#20301f"},
    "cave": {"name": "Пещера", "floor": "#4a4a52", "wall": "#26262c"},
    "ruins": {"name": "Руины", "floor": "#6b5b3e", "wall": "#3a3020"},
}

ENEMY_TYPES = {
    "zombie": {"name": "Зомби", "emoji": "🧟", "hp": 18, "attack": 4, "defense": 1},
    "spider": {"name": "Паук", "emoji": "🕷️", "hp": 10, "attack": 6, "defense": 0},
    "skeleton": {"name": "Скелет", "emoji": "💀", "hp": 14, "attack": 5, "defense": 3},
}
BOSS_TYPES = {
    "guardian": {"name": "Страж подземелья", "emoji": "🗿", "hp": 90, "attack": 10, "defense": 5},
    "golem": {"name": "Огненный голем", "emoji": "🔥", "hp": 110, "attack": 12, "defense": 3},
}

SLOTS = ["helmet", "armor", "weapon", "shield"]
SLOT_NAMES = {"helmet": "Шлем", "armor": "Доспехи", "weapon": "Оружие", "shield": "Щит"}
SLOT_EMOJI = {"helmet": "🪖", "armor": "🛡", "weapon": "⚔️", "shield": "🔰"}
TIERS = [("common", "Обычный", 1.0, 65), ("rare", "Редкий", 1.6, 27), ("epic", "Эпический", 2.4, 8)]

DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


def _new_id():
    return uuid.uuid4().hex[:10]


def _roll_item(slot, depth, rng):
    tier_key, tier_name, tier_mult, _ = rng.choices(TIERS, weights=[t[3] for t in TIERS])[0]
    power = tier_mult * (1 + depth * 1.1)
    item = {"id": _new_id(), "slot": slot, "tier": tier_key, "attack": 0, "defense": 0, "hp": 0}
    if slot == "weapon":
        item["attack"] = max(1, round(3 * power))
    elif slot == "shield":
        item["defense"] = max(1, round(2 * power))
        item["hp"] = round(2 * power)
    elif slot == "armor":
        item["defense"] = max(1, round(3 * power))
        item["hp"] = round(4 * power)
    elif slot == "helmet":
        item["defense"] = max(0, round(1 * power))
        item["hp"] = round(3 * power)
    item["name"] = f"{SLOT_NAMES[slot]} ({tier_name})"
    item["price"] = round(8 * power) + 6
    return item


def _room_center(room):
    x, y, w, h = room
    return x + w // 2, y + h // 2


def _generate_map(rng):
    grid = [["#"] * WIDTH for _ in range(HEIGHT)]
    rooms = []
    attempts = 0
    while len(rooms) < ROOM_COUNT and attempts < 300:
        attempts += 1
        w = rng.randint(MIN_ROOM, MAX_ROOM)
        h = rng.randint(MIN_ROOM, MAX_ROOM)
        x = rng.randint(1, WIDTH - w - 2)
        y = rng.randint(1, HEIGHT - h - 2)
        rooms.append((x, y, w, h))

    for (x, y, w, h) in rooms:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                grid[yy][xx] = "."

    for i in range(1, len(rooms)):
        x1, y1 = _room_center(rooms[i - 1])
        x2, y2 = _room_center(rooms[i])
        if rng.random() < 0.5:
            for x in range(min(x1, x2), max(x1, x2) + 1):
                grid[y1][x] = "."
            for y in range(min(y1, y2), max(y1, y2) + 1):
                grid[y][x2] = "."
        else:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                grid[y][x1] = "."
            for x in range(min(x1, x2), max(x1, x2) + 1):
                grid[y2][x] = "."

    return grid, rooms


class DungeonGame:
    def __init__(self, theme="forest", max_players=4):
        self.theme = theme if theme in THEMES else "forest"
        self.max_players = max(1, min(max_players, MAX_PARTY))

        self.seat_order = []
        self.started = False
        self.finished = False
        self.victory = None

        self.rng = random.Random()
        self.grid = None
        self.rooms = []
        self.players = {}   # token -> player dict
        self.enemies = []   # list of enemy dicts
        self.floor_items = {}   # (x, y) -> item dict
        self.shop_tile = None
        self.shop_stock = []
        self.gold = 0

        self.round = 0
        self.pending_actions = {}   # token -> action dict
        self.log = []               # recent event strings, newest last

    # ---------- lobby ----------

    def add_player(self, token):
        if self.started or token in self.seat_order:
            return None
        if len(self.seat_order) >= self.max_players:
            return None
        self.seat_order.append(token)
        return len(self.seat_order) - 1

    def can_start(self):
        return not self.started and len(self.seat_order) >= 1

    def start(self):
        if not self.can_start():
            return False

        self.grid, self.rooms = _generate_map(self.rng)
        spawn = self.rooms[0]
        sx, sy = _room_center(spawn)

        self.players = {}
        for token in self.seat_order:
            self.players[token] = {
                "token": token,
                "x": sx,
                "y": sy,
                "hp": BASE_HP,
                "max_hp": BASE_HP,
                "status": "alive",   # alive | downed | dead
                "downed_at": None,
                "equipment": {slot: None for slot in SLOTS},
                "inventory": [],
            }

        for idx, room in enumerate(self.rooms[1:], start=1):
            depth = idx / (len(self.rooms) - 1)
            is_boss_room = idx == len(self.rooms) - 1
            if is_boss_room:
                boss_key = self.rng.choice(list(BOSS_TYPES))
                bx, by = _room_center(room)
                self._spawn_enemy(boss_key, BOSS_TYPES[boss_key], bx, by, depth, is_boss=True)
                continue

            enemy_count = self.rng.randint(1, 3)
            cells = self._room_floor_cells(room)
            self.rng.shuffle(cells)
            for (ex, ey) in cells[:enemy_count]:
                type_key = self.rng.choice(list(ENEMY_TYPES))
                self._spawn_enemy(type_key, ENEMY_TYPES[type_key], ex, ey, depth, is_boss=False)

        shop_room_idx = self.rng.randint(1, len(self.rooms) - 2) if len(self.rooms) > 2 else None
        if shop_room_idx is not None:
            cells = self._room_floor_cells(self.rooms[shop_room_idx])
            cells = [c for c in cells if not self._enemy_at(*c)]
            if cells:
                self.shop_tile = self.rng.choice(cells)
                shop_depth = shop_room_idx / (len(self.rooms) - 1)
                self.shop_stock = [
                    _roll_item(self.rng.choice(SLOTS), shop_depth, self.rng) for _ in range(3)
                ]

        self.gold = 0
        self.started = True
        self.round = 1
        self._log(f"Отряд входит в подземелье ({THEMES[self.theme]['name']}).")
        return True

    def _room_floor_cells(self, room):
        x, y, w, h = room
        return [(xx, yy) for yy in range(y, y + h) for xx in range(x, x + w)]

    def _spawn_enemy(self, type_key, base, x, y, depth, is_boss):
        mult = 1.0 if is_boss else (1 + depth * DEPTH_SCALE)
        hp = round(base["hp"] * mult)
        self.enemies.append(
            {
                "id": _new_id(),
                "type": type_key,
                "name": base["name"],
                "emoji": base["emoji"],
                "x": x,
                "y": y,
                "hp": hp,
                "max_hp": hp,
                "attack": round(base["attack"] * mult),
                "defense": round(base["defense"] * mult),
                "is_boss": is_boss,
                "depth": depth,
            }
        )

    def _log(self, text):
        self.log.append(text)
        self.log = self.log[-30:]

    # ---------- helpers ----------

    def _in_bounds(self, x, y):
        return 0 <= x < WIDTH and 0 <= y < HEIGHT

    def _is_floor(self, x, y):
        return self._in_bounds(x, y) and self.grid[y][x] == "."

    def _enemy_at(self, x, y):
        return next((e for e in self.enemies if e["x"] == x and e["y"] == y and e["hp"] > 0), None)

    def _player_stats(self, player):
        attack = BASE_ATTACK
        defense = BASE_DEFENSE
        max_hp = BASE_HP
        for item in player["equipment"].values():
            if item:
                attack += item["attack"]
                defense += item["defense"]
                max_hp += item["hp"]
        return attack, defense, max_hp

    def _refresh_max_hp(self, player):
        _, _, max_hp = self._player_stats(player)
        if max_hp != player["max_hp"]:
            player["hp"] = min(player["hp"], max_hp) if player["hp"] > 0 else player["hp"]
            player["max_hp"] = max_hp

    def _adjacent(self, ax, ay, bx, by):
        return abs(ax - bx) + abs(ay - by) == 1

    # ---------- turn actions (queued, resolved together) ----------

    def submit_action(self, token, action):
        if not self.started or self.finished:
            return False, "Игра не идёт"
        player = self.players.get(token)
        if not player:
            return False, "Вы не в отряде"
        if player["status"] != "alive":
            return False, "Вы не можете действовать сейчас"
        if token in self.pending_actions:
            return False, "Действие уже выбрано на этот ход"
        if action.get("type") not in ("move", "attack", "revive"):
            return False, "Неизвестное действие"
        self.pending_actions[token] = action

        living = [t for t, p in self.players.items() if p["status"] == "alive"]
        if all(t in self.pending_actions for t in living):
            self._resolve_round()
        return True, None

    def _resolve_round(self):
        for token in self.seat_order:
            action = self.pending_actions.get(token)
            player = self.players.get(token)
            if not action or not player or player["status"] != "alive":
                continue
            self._apply_player_action(player, action)
            if self.finished:
                self.pending_actions = {}
                return

        self._enemy_turn()
        self._regen_out_of_combat()
        self.pending_actions = {}
        self.round += 1
        self._check_end_conditions()

    def _regen_out_of_combat(self):
        """Small passive heal for anyone with no enemy nearby, so retreating
        from a bad fight is a real option instead of every wound being
        permanent for the rest of the run."""
        for player in self.players.values():
            if player["status"] != "alive":
                continue
            near_enemy = any(
                abs(e["x"] - player["x"]) + abs(e["y"] - player["y"]) <= 2 for e in self.enemies
            )
            if not near_enemy and player["hp"] < player["max_hp"]:
                player["hp"] = min(player["max_hp"], player["hp"] + 2)

    def _apply_player_action(self, player, action):
        kind = action.get("type")
        attack, _, _ = self._player_stats(player)

        if kind == "move":
            dx, dy = action.get("dx", 0), action.get("dy", 0)
            if (dx, dy) not in DIRS:
                return
            nx, ny = player["x"] + dx, player["y"] + dy
            if not self._is_floor(nx, ny) or self._enemy_at(nx, ny):
                return
            player["x"], player["y"] = nx, ny
            item = self.floor_items.pop((nx, ny), None)
            if item:
                if len(player["inventory"]) < INVENTORY_CAP:
                    player["inventory"].append(item)
                    self._log(f"{player['token']} подобрал: {item['name']}.")
                else:
                    self.floor_items[(nx, ny)] = item

        elif kind == "attack":
            target = action.get("target") or []
            if len(target) != 2:
                return
            tx, ty = target
            if not self._adjacent(player["x"], player["y"], tx, ty):
                return
            enemy = self._enemy_at(tx, ty)
            if not enemy:
                return
            dmg = max(1, attack - enemy["defense"])
            enemy["hp"] -= dmg
            self._log(f"{player['token']} бьёт {enemy['name']} на {dmg}.")
            if enemy["hp"] <= 0:
                self._kill_enemy(enemy)
            # no immediate counter-attack here: a surviving enemy still gets
            # its one action this round, during the enemy phase below —
            # giving it a separate counter here as well would let it hit twice

        elif kind == "revive":
            target_token = action.get("target")
            ally = self.players.get(target_token)
            if not ally or ally["status"] != "downed":
                return
            if not self._adjacent(player["x"], player["y"], ally["x"], ally["y"]):
                return
            _, _, ally_max_hp = self._player_stats(ally)
            ally["hp"] = max(1, ally_max_hp // 2)
            ally["status"] = "alive"
            ally["downed_at"] = None
            self._log(f"{player['token']} воскресил {target_token}!")

    def _kill_enemy(self, enemy):
        self.enemies.remove(enemy)
        self._log(f"{enemy['name']} повержен!")
        gold_reward = 5 + round(enemy.get("depth", 0) * 15) + (40 if enemy["is_boss"] else 0)
        self.gold += gold_reward
        drop_chance = 1.0 if enemy["is_boss"] else 0.5
        if self.rng.random() < drop_chance and (enemy["x"], enemy["y"]) not in self.floor_items:
            slot = self.rng.choice(SLOTS)
            item = _roll_item(slot, enemy.get("depth", 0), self.rng)
            self.floor_items[(enemy["x"], enemy["y"])] = item
        if enemy["is_boss"]:
            self.finished = True
            self.victory = True
            self._log("Босс повержен! Отряд побеждает.")

    def _check_player_downed(self, player):
        if player["hp"] <= 0 and player["status"] == "alive":
            player["hp"] = 0
            player["status"] = "downed"
            player["downed_at"] = time.time()
            self._log(f"{player['token']} повержен и нуждается в спасении!")

    def _enemy_turn(self):
        living_players = [p for p in self.players.values() if p["status"] == "alive"]
        if not living_players:
            return
        for enemy in list(self.enemies):
            if enemy["hp"] <= 0:
                continue
            target = min(
                living_players,
                key=lambda p: abs(p["x"] - enemy["x"]) + abs(p["y"] - enemy["y"]),
            )
            dist_to_target = abs(target["x"] - enemy["x"]) + abs(target["y"] - enemy["y"])
            if dist_to_target > AGGRO_RANGE:
                continue  # too far away to have noticed anyone yet

            if self._adjacent(enemy["x"], enemy["y"], target["x"], target["y"]):
                _, defense, _ = self._player_stats(target)
                dmg = max(1, enemy["attack"] - defense)
                target["hp"] -= dmg
                self._log(f"{enemy['name']} атакует {target['token']} на {dmg}.")
                self._check_player_downed(target)
                continue

            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            step_options = []
            if dx != 0:
                step_options.append((1 if dx > 0 else -1, 0))
            if dy != 0:
                step_options.append((0, 1 if dy > 0 else -1))
            self.rng.shuffle(step_options)
            for (sdx, sdy) in step_options:
                nx, ny = enemy["x"] + sdx, enemy["y"] + sdy
                if self._is_floor(nx, ny) and not self._enemy_at(nx, ny) and not any(
                    p["x"] == nx and p["y"] == ny for p in self.players.values()
                ):
                    enemy["x"], enemy["y"] = nx, ny
                    break

    def _check_end_conditions(self):
        now = time.time()
        for player in self.players.values():
            if player["status"] == "downed" and now - player["downed_at"] > REVIVE_WINDOW_SECONDS:
                player["status"] = "dead"
                self._log(f"{player['token']} не был спасён вовремя и выбывает.")

        if all(p["status"] == "dead" for p in self.players.values()):
            self.finished = True
            self.victory = False
            self._log("Весь отряд пал. Подземелье побеждает.")

    def check_revival_timeouts(self):
        """Called periodically (real-time) so an unattended down-timer still expires."""
        if not self.started or self.finished:
            return False
        before = [p["status"] for p in self.players.values()]
        self._check_end_conditions()
        after = [p["status"] for p in self.players.values()]
        return before != after or self.finished

    # ---------- non-turn actions (instant) ----------

    def equip_item(self, token, item_id):
        player = self.players.get(token)
        if not player or player["status"] == "dead":
            return False, "Недоступно"
        item = next((i for i in player["inventory"] if i["id"] == item_id), None)
        if not item:
            return False, "Нет такого предмета"
        player["inventory"].remove(item)
        old = player["equipment"][item["slot"]]
        player["equipment"][item["slot"]] = item
        if old:
            player["inventory"].append(old)
        self._refresh_max_hp(player)
        return True, None

    def sell_item(self, token, item_id):
        player = self.players.get(token)
        if not player or player["status"] == "dead":
            return False, "Недоступно"
        item = next((i for i in player["inventory"] if i["id"] == item_id), None)
        if not item:
            return False, "Нет такого предмета"
        player["inventory"].remove(item)
        self.gold += max(1, item["price"] // 2)
        return True, None

    def buy_item(self, token, item_id):
        player = self.players.get(token)
        if not player or player["status"] != "alive":
            return False, "Недоступно"
        if not self.shop_tile or (player["x"], player["y"]) != tuple(self.shop_tile):
            return False, "Вы не в магазине"
        item = next((i for i in self.shop_stock if i["id"] == item_id), None)
        if not item:
            return False, "Такого товара нет"
        if self.gold < item["price"]:
            return False, "Недостаточно золота"
        if len(player["inventory"]) >= INVENTORY_CAP:
            return False, "Инвентарь полон"
        self.gold -= item["price"]
        self.shop_stock.remove(item)
        player["inventory"].append(item)
        return True, None

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if token not in self.seat_order:
            return
        if not self.started:
            self.seat_order.remove(token)
            return
        player = self.players.get(token)
        if player:
            player["status"] = "dead"
        self.pending_actions.pop(token, None)
        living = [t for t, p in self.players.items() if p["status"] == "alive"]
        if living:
            if all(t in self.pending_actions for t in living):
                self._resolve_round()
        if all(p["status"] == "dead" for p in self.players.values()):
            self.finished = True
            self.victory = False

    # ---------- serialization ----------

    def state_for(self, token):
        if not self.started:
            return {
                "started": False,
                "finished": False,
                "theme": self.theme,
                "theme_name": THEMES[self.theme]["name"],
                "max_players": self.max_players,
                "seats": list(self.seat_order),
                "can_start": self.can_start(),
                "my_seat": self.seat_order.index(token) if token in self.seat_order else None,
            }

        rows = ["".join(row) for row in self.grid]
        now = time.time()

        def player_dict(p):
            attack, defense, max_hp = self._player_stats(p)
            downed_remaining = None
            if p["status"] == "downed":
                downed_remaining = max(0, round(REVIVE_WINDOW_SECONDS - (now - p["downed_at"])))
            return {
                "token": p["token"],
                "x": p["x"],
                "y": p["y"],
                "hp": max(0, p["hp"]),
                "max_hp": max_hp,
                "attack": attack,
                "defense": defense,
                "status": p["status"],
                "downed_remaining": downed_remaining,
                "equipment": p["equipment"],
                "inventory": p["inventory"],
            }

        return {
            "started": True,
            "finished": self.finished,
            "victory": self.victory,
            "theme": self.theme,
            "theme_name": THEMES[self.theme]["name"],
            "width": WIDTH,
            "height": HEIGHT,
            "grid": rows,
            "round": self.round,
            "gold": self.gold,
            "shop_tile": list(self.shop_tile) if self.shop_tile else None,
            "shop_stock": self.shop_stock,
            "players": [player_dict(p) for p in self.players.values()],
            "enemies": [
                {
                    "id": e["id"],
                    "name": e["name"],
                    "emoji": e["emoji"],
                    "x": e["x"],
                    "y": e["y"],
                    "hp": e["hp"],
                    "max_hp": e["max_hp"],
                    "is_boss": e["is_boss"],
                }
                for e in self.enemies
            ],
            "floor_items": [
                {"x": x, "y": y, "item": item} for (x, y), item in self.floor_items.items()
            ],
            "log": self.log[-8:],
            "my_status": self.players.get(token, {}).get("status"),
            "pending_submitted": list(self.pending_actions.keys()),
            "waiting_on": [
                t for t, p in self.players.items() if p["status"] == "alive" and t not in self.pending_actions
            ],
        }

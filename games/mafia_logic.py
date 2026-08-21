"""Pure game engine for multiplayer Mafia / social deduction ("Мафия").

No Flask/socket dependencies here. Roles are chosen by the lobby
creator when the lobby is made (mirroring how Durak's variant is
picked at creation time): Мафия (count configurable) and Врач are
always in play, plus up to five optional roles. A run alternates
night phases (private role actions + a mafia-only chat) and day
phases (public chat + a public vote to lynch one player), resolving
each phase the moment every player who needs to act has acted —
the same "wait for everyone, then resolve" pattern used by the other
turn-based games on this site.
"""
import random

MIN_PLAYERS = 4
MAX_PLAYERS = 10

OPTIONAL_ROLES = ["sheriff", "maniac", "bodyguard", "lookout", "mayor"]
NIGHT_ROLES = {"mafia", "doctor", "sheriff", "maniac", "bodyguard", "lookout"}
SELF_TARGET_ALLOWED = {"doctor", "bodyguard"}

ROLE_NAMES = {
    "mafia": "Мафия",
    "doctor": "Врач",
    "sheriff": "Шериф",
    "maniac": "Маньяк",
    "bodyguard": "Телохранитель",
    "lookout": "Наблюдатель",
    "mayor": "Мэр",
    "civilian": "Мирный житель",
}

CHAT_MAX_LEN = 300


class MafiaGame:
    def __init__(self, max_players=8, mafia_count=1, sheriff=True, maniac=False,
                 bodyguard=False, lookout=False, mayor=False):
        self.max_players = max(MIN_PLAYERS, min(max_players, MAX_PLAYERS))
        self.role_config = {
            "mafia_count": max(1, int(mafia_count)),
            "sheriff": bool(sheriff),
            "maniac": bool(maniac),
            "bodyguard": bool(bodyguard),
            "lookout": bool(lookout),
            "mayor": bool(mayor),
        }

        self.seat_order = []
        self.started = False
        self.finished = False
        self.winner = None   # "mafia" | "town" | "maniac" | None

        self.rng = random.Random()
        self.players = {}   # token -> {token, role, alive, death_reason, death_at}
        self.phase = None   # "night" | "day"
        self.night_number = 0
        self.day_number = 0

        self.night_actions = {}   # token -> {"target": token|None}
        self.day_votes = {}       # token -> target token|None

        self.day_chat = []
        self.mafia_chat = []
        self.sheriff_investigations = []   # [{night, target, is_mafia}]
        self.lookout_watches = []          # [{night, target, visitors}]
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
        if self.started or len(self.seat_order) < MIN_PLAYERS:
            return False
        n = len(self.seat_order)
        total_special = self.role_config["mafia_count"] + 1 + sum(
            1 for k in OPTIONAL_ROLES if self.role_config[k]
        )
        if total_special > n:
            return False
        if self.role_config["mafia_count"] * 2 >= n:
            return False
        return True

    def start(self):
        if not self.can_start():
            return False, "Недостаточно игроков или мафии слишком много для такого состава"

        roles = ["mafia"] * self.role_config["mafia_count"] + ["doctor"]
        for key in OPTIONAL_ROLES:
            if self.role_config[key]:
                roles.append(key)
        while len(roles) < len(self.seat_order):
            roles.append("civilian")
        self.rng.shuffle(roles)

        self.players = {
            token: {"token": token, "role": role, "alive": True, "death_reason": None, "death_at": None}
            for token, role in zip(self.seat_order, roles)
        }

        self.started = True
        self.phase = "night"
        self.night_number = 1
        self._log("Роли розданы. Город засыпает — наступает первая ночь.")
        return True, None

    # ---------- helpers ----------

    def living_tokens(self):
        return [t for t in self.seat_order if self.players[t]["alive"]]

    def alive_by_role(self, role):
        return [t for t in self.living_tokens() if self.players[t]["role"] == role]

    def _single_alive_role(self, role):
        matches = self.alive_by_role(role)
        return matches[0] if matches else None

    def _pick_top(self, tally):
        if not tally:
            return None
        top = max(tally.values())
        candidates = [k for k, v in tally.items() if v == top]
        return self.rng.choice(candidates)

    def _role_name(self, role):
        return ROLE_NAMES.get(role, role)

    def _log(self, text):
        self.log.append(text)
        self.log = self.log[-50:]

    # ---------- night actions ----------

    def _actors_tonight(self):
        return [t for t in self.living_tokens() if self.players[t]["role"] in NIGHT_ROLES]

    def _all_night_actions_submitted(self):
        return all(t in self.night_actions for t in self._actors_tonight())

    def submit_night_action(self, token, action):
        if not self.started or self.finished or self.phase != "night":
            return False, "Сейчас не ночь"
        player = self.players.get(token)
        if not player or not player["alive"]:
            return False, "Недоступно"
        role = player["role"]
        if role not in NIGHT_ROLES:
            return False, "У вашей роли нет ночного действия"
        target = action.get("target")
        if target is not None:
            if target not in self.players or not self.players[target]["alive"]:
                return False, "Недопустимая цель"
            if target == token and role not in SELF_TARGET_ALLOWED:
                return False, "Нельзя выбрать себя"
        self.night_actions[token] = {"target": target}
        if self._all_night_actions_submitted():
            self._resolve_night()
        return True, None

    def _resolve_night(self):
        mafia_votes = {}
        for t in self.alive_by_role("mafia"):
            tgt = self.night_actions.get(t, {}).get("target")
            if tgt:
                mafia_votes[tgt] = mafia_votes.get(tgt, 0) + 1
        mafia_target = self._pick_top(mafia_votes)

        doctor_tok = self._single_alive_role("doctor")
        doctor_target = self.night_actions.get(doctor_tok, {}).get("target") if doctor_tok else None

        bodyguard_tok = self._single_alive_role("bodyguard")
        bodyguard_target = self.night_actions.get(bodyguard_tok, {}).get("target") if bodyguard_tok else None

        maniac_tok = self._single_alive_role("maniac")
        maniac_target = self.night_actions.get(maniac_tok, {}).get("target") if maniac_tok else None

        sheriff_tok = self._single_alive_role("sheriff")
        if sheriff_tok:
            tgt = self.night_actions.get(sheriff_tok, {}).get("target")
            if tgt:
                self.sheriff_investigations.append(
                    {"night": self.night_number, "target": tgt, "is_mafia": self.players[tgt]["role"] == "mafia"}
                )

        lookout_tok = self._single_alive_role("lookout")
        if lookout_tok:
            tgt = self.night_actions.get(lookout_tok, {}).get("target")
            if tgt:
                visitors = [t for t, a in self.night_actions.items() if a.get("target") == tgt and t != lookout_tok]
                self.lookout_watches.append({"night": self.night_number, "target": tgt, "visitors": visitors})

        raw_targets = {t for t in (mafia_target, maniac_target) if t}
        died = []
        for tgt in raw_targets:
            if tgt == doctor_target:
                self._log(f"{tgt} подвергся(лась) нападению этой ночью, но выжил(а) благодаря врачу.")
                continue
            if bodyguard_tok and bodyguard_target == tgt and self.players[bodyguard_tok]["alive"]:
                self.players[bodyguard_tok]["alive"] = False
                self.players[bodyguard_tok]["death_reason"] = "bodyguard_sacrifice"
                self.players[bodyguard_tok]["death_at"] = self.night_number
                died.append(bodyguard_tok)
                self._log(f"Телохранитель {bodyguard_tok} погиб(ла), заслонив собой {tgt}. {tgt} выжил(а).")
                continue
            self.players[tgt]["alive"] = False
            self.players[tgt]["death_reason"] = "killed"
            self.players[tgt]["death_at"] = self.night_number
            died.append(tgt)
            self._log(f"{tgt} был(а) убит(а) этой ночью. Роль: {self._role_name(self.players[tgt]['role'])}.")

        if not died:
            self._log("Этой ночью никто не погиб.")

        self.night_actions = {}
        self.day_votes = {}
        if not self._check_win():
            self.phase = "day"
            self.day_number = self.night_number

    # ---------- day voting ----------

    def submit_vote(self, token, target):
        if not self.started or self.finished or self.phase != "day":
            return False, "Сейчас не день"
        player = self.players.get(token)
        if not player or not player["alive"]:
            return False, "Недоступно"
        if target is not None and (target not in self.players or not self.players[target]["alive"]):
            return False, "Недопустимая цель"
        self.day_votes[token] = target
        if all(t in self.day_votes for t in self.living_tokens()):
            self._resolve_day()
        return True, None

    def _resolve_day(self):
        tally = {}
        for voter, target in self.day_votes.items():
            if not target:
                continue
            weight = 2 if self.players[voter]["role"] == "mayor" else 1
            tally[target] = tally.get(target, 0) + weight

        lynched = None
        if tally:
            top = max(tally.values())
            leaders = [k for k, v in tally.items() if v == top]
            if len(leaders) == 1:
                lynched = leaders[0]

        if lynched:
            self.players[lynched]["alive"] = False
            self.players[lynched]["death_reason"] = "lynched"
            self.players[lynched]["death_at"] = self.day_number
            self._log(f"{lynched} был(а) линчёван(а) горожанами. Роль: {self._role_name(self.players[lynched]['role'])}.")
        else:
            self._log("Голосование не выявило большинства — никто не был линчёван.")

        self.day_votes = {}
        if not self._check_win():
            self.phase = "night"
            self.night_number += 1
            self.night_actions = {}

    # ---------- win conditions ----------

    def _check_win(self):
        alive = self.living_tokens()
        total_alive = len(alive)
        mafia_alive = len(self.alive_by_role("mafia"))
        maniac_alive = len(self.alive_by_role("maniac"))

        if total_alive == 0:
            self.finished = True
            self.winner = None
        elif maniac_alive and maniac_alive == total_alive:
            self.finished = True
            self.winner = "maniac"
        elif mafia_alive == 0 and maniac_alive == 0:
            self.finished = True
            self.winner = "town"
        elif mafia_alive > 0 and mafia_alive * 2 >= total_alive:
            self.finished = True
            self.winner = "mafia"

        if self.finished:
            self._log(self._win_message())
        return self.finished

    def _win_message(self):
        if self.winner == "mafia":
            return "Мафия захватила город. Мафия побеждает!"
        if self.winner == "town":
            return "Вся мафия обезврежена. Мирные жители побеждают!"
        if self.winner == "maniac":
            return "Маньяк остался единственным выжившим и побеждает в одиночку!"
        return "Игра окончена — выживших не осталось."

    # ---------- chat ----------

    def submit_chat(self, token, text):
        text = (text or "").strip()
        if not text:
            return False, "Пустое сообщение"
        text = text[:CHAT_MAX_LEN]
        player = self.players.get(token)
        if not player or not player["alive"]:
            return False, "Только живые игроки могут писать в чат"
        if self.phase == "day":
            self.day_chat.append({"token": token, "text": text, "day": self.day_number})
            return True, None
        if self.phase == "night":
            if player["role"] != "mafia":
                return False, "Ночной чат доступен только мафии"
            self.mafia_chat.append({"token": token, "text": text, "night": self.night_number})
            return True, None
        return False, "Недоступно"

    # ---------- disconnect handling ----------

    def remove_player(self, token):
        if not self.started:
            if token in self.seat_order:
                self.seat_order.remove(token)
            return
        player = self.players.get(token)
        if not player or not player["alive"]:
            return
        player["alive"] = False
        player["death_reason"] = "disconnected"
        player["death_at"] = self.night_number if self.phase == "night" else self.day_number
        self._log(f"{token} покинул(а) игру и выбывает.")
        if self._check_win():
            return
        if self.phase == "night" and self._all_night_actions_submitted():
            self._resolve_night()
        elif self.phase == "day" and all(t in self.day_votes for t in self.living_tokens()):
            self._resolve_day()

    # ---------- serialization ----------

    def state_for(self, token):
        base = {
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "max_players": self.max_players,
            "role_config": dict(self.role_config),
        }

        if not self.started:
            base["seats"] = list(self.seat_order)
            base["can_start"] = self.can_start()
            base["my_seat"] = self.seat_order.index(token) if token in self.seat_order else None
            return base

        player = self.players.get(token)
        if not player:
            return base

        my_role = player["role"]
        is_mafia_viewer = my_role == "mafia"

        def visible_role(p):
            if not p["alive"] or self.finished or p["token"] == token:
                return p["role"]
            if is_mafia_viewer and p["role"] == "mafia":
                return p["role"]
            return None

        players_out = [
            {
                "token": p["token"],
                "alive": p["alive"],
                "role": visible_role(p),
                "role_name": ROLE_NAMES.get(visible_role(p)) if visible_role(p) else None,
                "death_reason": p["death_reason"],
            }
            for p in self.players.values()
        ]

        base.update({
            "phase": self.phase,
            "night_number": self.night_number,
            "day_number": self.day_number,
            "my_role": my_role,
            "my_role_name": self._role_name(my_role),
            "my_alive": player["alive"],
            "players": players_out,
            "log": self.log[-30:],
            "day_chat": self.day_chat[-100:],
        })

        if self.phase == "night":
            base["night_waiting_on"] = [t for t in self._actors_tonight() if t not in self.night_actions]
            base["night_submitted"] = token in self.night_actions
            base["my_night_target"] = self.night_actions.get(token, {}).get("target")

        if is_mafia_viewer:
            base["mafia_chat"] = self.mafia_chat[-100:]
            base["mafia_teammates"] = [p["token"] for p in self.players.values() if p["role"] == "mafia"]

        if my_role == "sheriff":
            base["sheriff_investigations"] = self.sheriff_investigations

        if my_role == "lookout":
            base["lookout_watches"] = self.lookout_watches

        if self.phase == "day":
            tally = {}
            for voter, target in self.day_votes.items():
                if target:
                    weight = 2 if self.players[voter]["role"] == "mayor" else 1
                    tally[target] = tally.get(target, 0) + weight
            base["day_votes"] = [{"voter": v, "target": t} for v, t in self.day_votes.items()]
            base["vote_tally"] = tally
            base["day_voting_pending"] = [t for t in self.living_tokens() if t not in self.day_votes]
            base["my_vote"] = self.day_votes.get(token)

        return base

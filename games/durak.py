"""Durak (card game) lobbies: podkidnoy and perevodnoy variants, 2-5 players.

Mirrors the chess lobby pattern (games/chess.py): any number of parallel
lobbies, each with its own DurakGame instance and its own token/sid
bookkeeping. The player who created a lobby closes it for everyone in it
by leaving (after the usual reconnect grace period).
"""
import time
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for

from auth import login_required
from extensions import socketio
from games.durak_logic import DurakGame, MAX_PLAYERS

durak_bp = Blueprint("durak", __name__, url_prefix="/durak")

NAMESPACE = "/durak"
GRACE_SECONDS = 30

lobbies = {}       # lobby_id -> lobby state
sid_to_lobby = {}  # sid -> lobby_id, for the disconnect handler


def new_lobby_id():
    return uuid.uuid4().hex[:8]


def new_lobby(creator, variant, max_players, allow_cheating):
    return {
        "game": DurakGame(variant=variant, max_players=max_players, allow_cheating=allow_cheating),
        "creator": creator,
        "created_at": time.time(),
        "token_to_sid": {},
        "sid_to_token": {},
        "removal_generation": {},
    }


def broadcast_state(lobby_id):
    lobby = lobbies.get(lobby_id)
    if not lobby:
        return
    for tok, sid in list(lobby["token_to_sid"].items()):
        socketio.emit("state", lobby["game"].state_for(tok), to=sid, namespace=NAMESPACE)


def _card_tuple(data):
    if not data or "rank" not in data or "suit" not in data:
        return None
    return (data["rank"], data["suit"])


@durak_bp.route("/")
@login_required
def index():
    rows = []
    for lobby_id, lobby in lobbies.items():
        game = lobby["game"]
        rows.append(
            {
                "lobby_id": lobby_id,
                "creator": lobby["creator"],
                "variant": game.variant,
                "players": len(game.seat_order),
                "max_players": game.max_players,
                "allow_cheating": game.allow_cheating,
                "status": "finished" if game.finished else ("playing" if game.started else "waiting"),
            }
        )
    rows.sort(key=lambda r: lobbies[r["lobby_id"]]["created_at"], reverse=True)
    return render_template("durak/lobbies.html", lobbies=rows, max_players_choice=range(2, MAX_PLAYERS + 1))


@durak_bp.route("/create", methods=["POST"])
@login_required
def create():
    variant = request.form.get("variant") if request.form.get("variant") in ("podkidnoy", "perevodnoy") else "podkidnoy"
    try:
        max_players = int(request.form.get("max_players", 4))
    except ValueError:
        max_players = 4
    allow_cheating = request.form.get("allow_cheating") == "on"
    lobby_id = new_lobby_id()
    lobbies[lobby_id] = new_lobby(session["user"], variant, max_players, allow_cheating)
    return redirect(url_for("durak.lobby", lobby_id=lobby_id))


@durak_bp.route("/lobby/<lobby_id>")
@login_required
def lobby(lobby_id):
    lob = lobbies.get(lobby_id)
    if not lob:
        return redirect(url_for("durak.index"))
    return render_template(
        "durak/index.html",
        token=session["user"],
        lobby_id=lobby_id,
        is_creator=(lob["creator"] == session["user"]),
    )


@socketio.on("register", namespace=NAMESPACE)
def on_register(data):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    sid = request.sid
    lobby["token_to_sid"][token] = sid
    lobby["sid_to_token"][sid] = token
    lobby["removal_generation"][token] = lobby["removal_generation"].get(token, 0) + 1
    sid_to_lobby[sid] = lobby_id
    socketio.emit("state", lobby["game"].state_for(token), to=sid, namespace=NAMESPACE)


@socketio.on("join", namespace=NAMESPACE)
def on_join(data):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    seat = lobby["game"].add_player(token)
    if seat is None:
        socketio.emit(
            "action_error",
            {"message": "Нельзя присоединиться (игра уже началась или мест нет)"},
            to=request.sid,
            namespace=NAMESPACE,
        )
        return
    broadcast_state(lobby_id)


@socketio.on("start_game", namespace=NAMESPACE)
def on_start_game(data):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    if lobby["creator"] != token:
        socketio.emit(
            "action_error", {"message": "Начать игру может только создатель лобби"}, to=request.sid, namespace=NAMESPACE
        )
        return
    if not lobby["game"].start():
        socketio.emit("action_error", {"message": "Недостаточно игроков"}, to=request.sid, namespace=NAMESPACE)
        return
    broadcast_state(lobby_id)


def _dispatch(data, action):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    ok, error = action(lobby["game"], token, data or {})
    if not ok:
        socketio.emit("action_error", {"message": error or "Действие невозможно"}, to=request.sid, namespace=NAMESPACE)
        return
    broadcast_state(lobby_id)


@socketio.on("play_card", namespace=NAMESPACE)
def on_play_card(data):
    def action(game, token, payload):
        card = _card_tuple(payload.get("card"))
        if not card:
            return False, "Нет карты"
        if not game.table:
            return game.open_attack(token, card)
        return game.throw_in(token, card, as_cheat=bool(payload.get("cheat")))

    _dispatch(data, action)


@socketio.on("catch_cheat", namespace=NAMESPACE)
def on_catch_cheat(data):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    card = _card_tuple((data or {}).get("card"))
    if not card:
        return
    ok, result = lobby["game"].catch_cheat(token, card)
    if not ok:
        socketio.emit("action_error", {"message": result or "Действие невозможно"}, to=request.sid, namespace=NAMESPACE)
        return
    cheater = result
    for sid in list(lobby["token_to_sid"].values()):
        socketio.emit(
            "cheat_caught",
            {"catcher": token, "cheater": cheater, "card": {"rank": card[0], "suit": card[1]}},
            to=sid,
            namespace=NAMESPACE,
        )
    broadcast_state(lobby_id)


@socketio.on("defend", namespace=NAMESPACE)
def on_defend(data):
    def action(game, token, payload):
        attack_card = _card_tuple(payload.get("attack_card"))
        defense_card = _card_tuple(payload.get("defense_card"))
        if not attack_card or not defense_card:
            return False, "Нет карты"
        return game.defend(token, attack_card, defense_card)

    _dispatch(data, action)


@socketio.on("transfer", namespace=NAMESPACE)
def on_transfer(data):
    def action(game, token, payload):
        card = _card_tuple(payload.get("card"))
        if not card:
            return False, "Нет карты"
        return game.transfer(token, card)

    _dispatch(data, action)


@socketio.on("take", namespace=NAMESPACE)
def on_take(data):
    _dispatch(data, lambda game, token, payload: game.take(token))


@socketio.on("confirm_done", namespace=NAMESPACE)
def on_confirm_done(data):
    _dispatch(data, lambda game, token, payload: game.confirm_done(token))


@socketio.on("disconnect", namespace=NAMESPACE)
def on_disconnect():
    sid = request.sid
    lobby_id = sid_to_lobby.pop(sid, None)
    lobby = lobbies.get(lobby_id) if lobby_id else None
    if not lobby:
        return
    token = lobby["sid_to_token"].pop(sid, None)
    if not token:
        return
    if lobby["token_to_sid"].get(token) == sid:
        del lobby["token_to_sid"][token]
    generation = lobby["removal_generation"].get(token, 0)

    def delayed_removal():
        socketio.sleep(GRACE_SECONDS)
        current_lobby = lobbies.get(lobby_id)
        if not current_lobby or current_lobby is not lobby:
            return
        if lobby["removal_generation"].get(token) != generation or token in lobby["token_to_sid"]:
            return

        if token == lobby["creator"]:
            for remaining_sid in list(lobby["token_to_sid"].values()):
                socketio.emit(
                    "lobby_closed",
                    {"message": "Создатель покинул партию. Лобби закрыто."},
                    to=remaining_sid,
                    namespace=NAMESPACE,
                )
            lobbies.pop(lobby_id, None)
            return

        lobby["game"].remove_player(token)
        broadcast_state(lobby_id)

    socketio.start_background_task(delayed_removal)

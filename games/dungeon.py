"""Co-op turn-based dungeon crawler lobbies, 1-4 players.

Mirrors the chess/durak lobby pattern: any number of parallel lobbies,
each with its own DungeonGame instance and its own token/sid
bookkeeping. The player who created a lobby closes it for everyone in
it by leaving (after the usual reconnect grace period).
"""
import time
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for

from auth import login_required
from extensions import socketio
from games.dungeon_logic import DungeonGame, MAX_PARTY, THEMES

dungeon_bp = Blueprint("dungeon", __name__, url_prefix="/dungeon")

NAMESPACE = "/dungeon"
GRACE_SECONDS = 30
REVIVE_POLL_SECONDS = 4

lobbies = {}
sid_to_lobby = {}


def new_lobby_id():
    return uuid.uuid4().hex[:8]


def new_lobby(creator, theme, max_players):
    return {
        "game": DungeonGame(theme=theme, max_players=max_players),
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


def _revive_watchdog(lobby_id, lobby):
    game = lobby["game"]
    while lobbies.get(lobby_id) is lobby and not game.finished:
        socketio.sleep(REVIVE_POLL_SECONDS)
        current = lobbies.get(lobby_id)
        if current is not lobby:
            return
        if game.started and game.check_revival_timeouts():
            broadcast_state(lobby_id)


@dungeon_bp.route("/")
@login_required
def index():
    rows = []
    for lobby_id, lobby in lobbies.items():
        game = lobby["game"]
        rows.append(
            {
                "lobby_id": lobby_id,
                "creator": lobby["creator"],
                "theme_name": THEMES[game.theme]["name"],
                "players": len(game.seat_order),
                "max_players": game.max_players,
                "status": "finished" if game.finished else ("playing" if game.started else "waiting"),
            }
        )
    rows.sort(key=lambda r: lobbies[r["lobby_id"]]["created_at"], reverse=True)
    return render_template("dungeon/lobbies.html", lobbies=rows, themes=THEMES)


@dungeon_bp.route("/create", methods=["POST"])
@login_required
def create():
    theme = request.form.get("theme") if request.form.get("theme") in THEMES else "forest"
    try:
        max_players = int(request.form.get("max_players", 4))
    except ValueError:
        max_players = 4
    lobby_id = new_lobby_id()
    lobbies[lobby_id] = new_lobby(session["user"], theme, max(1, min(max_players, MAX_PARTY)))
    return redirect(url_for("dungeon.lobby", lobby_id=lobby_id))


@dungeon_bp.route("/lobby/<lobby_id>")
@login_required
def lobby(lobby_id):
    lob = lobbies.get(lobby_id)
    if not lob:
        return redirect(url_for("dungeon.index"))
    return render_template(
        "dungeon/index.html",
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
    cls = (data or {}).get("cls") or "knight"
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    seat = lobby["game"].add_player(token, cls)
    if seat is None:
        socketio.emit(
            "action_error",
            {"message": "Нельзя присоединиться (отряд уже в подземелье или мест нет)"},
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
            "action_error", {"message": "Начать может только создатель лобби"}, to=request.sid, namespace=NAMESPACE
        )
        return
    if not lobby["game"].start():
        socketio.emit("action_error", {"message": "Недостаточно игроков"}, to=request.sid, namespace=NAMESPACE)
        return
    socketio.start_background_task(_revive_watchdog, lobby_id, lobby)
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


@socketio.on("submit_action", namespace=NAMESPACE)
def on_submit_action(data):
    def action(game, token, payload):
        turn_action = payload.get("action") or {}
        return game.submit_action(token, turn_action)

    _dispatch(data, action)


@socketio.on("equip_item", namespace=NAMESPACE)
def on_equip_item(data):
    def action(game, token, payload):
        return game.equip_item(token, payload.get("item_id"))

    _dispatch(data, action)


@socketio.on("sell_item", namespace=NAMESPACE)
def on_sell_item(data):
    def action(game, token, payload):
        return game.sell_item(token, payload.get("item_id"))

    _dispatch(data, action)


@socketio.on("buy_item", namespace=NAMESPACE)
def on_buy_item(data):
    def action(game, token, payload):
        return game.buy_item(token, payload.get("item_id"))

    _dispatch(data, action)


@socketio.on("give_item", namespace=NAMESPACE)
def on_give_item(data):
    def action(game, token, payload):
        return game.give_item(token, payload.get("item_id"), payload.get("to"))

    _dispatch(data, action)


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
                    {"message": "Создатель покинул отряд. Лобби закрыто."},
                    to=remaining_sid,
                    namespace=NAMESPACE,
                )
            lobbies.pop(lobby_id, None)
            return

        lobby["game"].remove_player(token)
        broadcast_state(lobby_id)

    socketio.start_background_task(delayed_removal)

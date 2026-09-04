"""Multiplayer (2-8) Texas Hold'em lobbies (chips only — no real money).

Mirrors the chess/durak/dungeon/battleship/mafia/uno lobby pattern: any
number of parallel lobbies, each with its own PokerGame instance and its
own token/sid bookkeeping. The player who created a lobby closes it for
everyone in it by leaving (after the usual reconnect grace period).
"""
import time
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for

from auth import login_required
from extensions import socketio
from games.poker_logic import MAX_PLAYERS, MIN_PLAYERS, PokerGame

poker_bp = Blueprint("poker", __name__, url_prefix="/poker")

NAMESPACE = "/poker"
GRACE_SECONDS = 30

lobbies = {}
sid_to_lobby = {}


def new_lobby_id():
    return uuid.uuid4().hex[:8]


def new_lobby(creator, max_players):
    return {
        "game": PokerGame(max_players=max_players),
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


@poker_bp.route("/")
@login_required
def index():
    rows = []
    for lobby_id, lobby in lobbies.items():
        game = lobby["game"]
        rows.append(
            {
                "lobby_id": lobby_id,
                "creator": lobby["creator"],
                "players": len(game.seat_order),
                "max_players": game.max_players,
                "status": "finished" if game.finished else ("playing" if game.started else "waiting"),
            }
        )
    rows.sort(key=lambda r: lobbies[r["lobby_id"]]["created_at"], reverse=True)
    return render_template("poker/lobbies.html", lobbies=rows, min_players=MIN_PLAYERS, max_players_cap=MAX_PLAYERS)


@poker_bp.route("/create", methods=["POST"])
@login_required
def create():
    try:
        max_players = int(request.form.get("max_players", 6))
    except ValueError:
        max_players = 6
    lobby_id = new_lobby_id()
    lobbies[lobby_id] = new_lobby(session["user"], max(MIN_PLAYERS, min(max_players, MAX_PLAYERS)))
    return redirect(url_for("poker.lobby", lobby_id=lobby_id))


@poker_bp.route("/lobby/<lobby_id>")
@login_required
def lobby(lobby_id):
    lob = lobbies.get(lobby_id)
    if not lob:
        return redirect(url_for("poker.index"))
    return render_template(
        "poker/index.html",
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
            "action_error", {"message": "Начать может только создатель лобби"}, to=request.sid, namespace=NAMESPACE
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


@socketio.on("poker_action", namespace=NAMESPACE)
def on_poker_action(data):
    def action(game, token, payload):
        return game.act(token, payload.get("action"), payload.get("amount"))

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
                    {"message": "Создатель покинул лобби. Игра закрыта."},
                    to=remaining_sid,
                    namespace=NAMESPACE,
                )
            lobbies.pop(lobby_id, None)
            return

        lobby["game"].remove_player(token)
        broadcast_state(lobby_id)

    socketio.start_background_task(delayed_removal)

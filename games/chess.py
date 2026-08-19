"""Chess for 2-8 players: any number of parallel lobbies, each its own match,
seated by account username. The player who created a lobby closes it for
everyone in it by leaving."""
import time
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for

from auth import login_required
from extensions import socketio
from games.chess_logic import Game

chess_bp = Blueprint("chess", __name__, url_prefix="/chess")

NAMESPACE = "/chess"
GRACE_SECONDS = 30

lobbies = {}       # lobby_id -> lobby state (see new_lobby())
sid_to_lobby = {}  # sid -> lobby_id, for the disconnect handler


def new_lobby_id():
    return uuid.uuid4().hex[:8]


def new_lobby(creator):
    return {
        "game": Game(),
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


@chess_bp.route("/")
@login_required
def index():
    rows = []
    for lobby_id, lobby in lobbies.items():
        game = lobby["game"]
        rows.append(
            {
                "lobby_id": lobby_id,
                "creator": lobby["creator"],
                "players": game.occupied_seats_count(),
                "status": "finished" if game.finished else ("playing" if game.started else "waiting"),
            }
        )
    rows.sort(key=lambda r: lobbies[r["lobby_id"]]["created_at"], reverse=True)
    return render_template("chess/lobbies.html", lobbies=rows)


@chess_bp.route("/create", methods=["POST"])
@login_required
def create():
    lobby_id = new_lobby_id()
    lobbies[lobby_id] = new_lobby(session["user"])
    return redirect(url_for("chess.lobby", lobby_id=lobby_id))


@chess_bp.route("/lobby/<lobby_id>")
@login_required
def lobby(lobby_id):
    if lobby_id not in lobbies:
        return redirect(url_for("chess.index"))
    return render_template("chess/index.html", token=session["user"], lobby_id=lobby_id)


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
            "join_error",
            {"message": "Игра уже заполнена (максимум 8 игроков)"},
            to=request.sid,
            namespace=NAMESPACE,
        )
        return
    broadcast_state(lobby_id)


@socketio.on("legal_moves", namespace=NAMESPACE)
def on_legal_moves(data):
    token = (data or {}).get("token")
    pos = (data or {}).get("pos")
    lobby = lobbies.get((data or {}).get("lobby_id"))
    if not token or not pos or not lobby:
        return
    game = lobby["game"]
    piece = game.board.get(tuple(pos))
    if not piece or piece["seat"] != game.players.get(token):
        socketio.emit("legal_moves_result", {"pos": pos, "moves": []}, to=request.sid, namespace=NAMESPACE)
        return
    moves = game.legal_moves(tuple(pos))
    socketio.emit("legal_moves_result", {"pos": pos, "moves": moves}, to=request.sid, namespace=NAMESPACE)


@socketio.on("move", namespace=NAMESPACE)
def on_move(data):
    token = (data or {}).get("token")
    frm = (data or {}).get("from")
    to = (data or {}).get("to")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not frm or not to or not lobby:
        return
    ok, error = lobby["game"].make_move(token, frm, to)
    if not ok:
        socketio.emit("move_error", {"message": error}, to=request.sid, namespace=NAMESPACE)
        return
    broadcast_state(lobby_id)


@socketio.on("attack_through_targets", namespace=NAMESPACE)
def on_attack_through_targets(data):
    token = (data or {}).get("token")
    pos = (data or {}).get("pos")
    lobby = lobbies.get((data or {}).get("lobby_id"))
    if not token or not pos or not lobby:
        return
    game = lobby["game"]
    piece = game.board.get(tuple(pos))
    if not piece or piece["seat"] != game.players.get(token):
        socketio.emit("attack_through_targets_result", {"pos": pos, "moves": []}, to=request.sid, namespace=NAMESPACE)
        return
    moves = game.attack_through_targets(tuple(pos))
    socketio.emit("attack_through_targets_result", {"pos": pos, "moves": moves}, to=request.sid, namespace=NAMESPACE)


@socketio.on("use_ability", namespace=NAMESPACE)
def on_use_ability(data):
    token = (data or {}).get("token")
    ability = (data or {}).get("ability")
    params = (data or {}).get("params")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not ability or not lobby:
        return
    ok, error = lobby["game"].use_ability(token, ability, params)
    if not ok:
        socketio.emit("ability_error", {"message": error}, to=request.sid, namespace=NAMESPACE)
        return
    broadcast_state(lobby_id)


@socketio.on("restart", namespace=NAMESPACE)
def on_restart(data):
    token = (data or {}).get("token")
    lobby_id = (data or {}).get("lobby_id")
    lobby = lobbies.get(lobby_id)
    if not token or not lobby:
        return
    if lobby["game"].players.get(token) is None:
        socketio.emit(
            "move_error",
            {"message": "Рестарт может начать только участник партии"},
            to=request.sid,
            namespace=NAMESPACE,
        )
        return
    lobby["game"].restart()
    broadcast_state(lobby_id)


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
            # the creator leaving closes the lobby for everyone still in it
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

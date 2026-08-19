"""Chess for 2-8 players: one shared match per server, seated by account username."""
from flask import Blueprint, render_template, session, request

from auth import login_required
from extensions import socketio
from games.chess_logic import Game

chess_bp = Blueprint("chess", __name__, url_prefix="/chess")

NAMESPACE = "/chess"
GRACE_SECONDS = 30

game = Game()
token_to_sid = {}
sid_to_token = {}
removal_generation = {}


def new_state_broadcast():
    for tok, sid in list(token_to_sid.items()):
        socketio.emit("state", game.state_for(tok), to=sid, namespace=NAMESPACE)


@chess_bp.route("/")
@login_required
def index():
    return render_template("chess/index.html", token=session["user"])


@socketio.on("register", namespace=NAMESPACE)
def on_register(data):
    token = (data or {}).get("token")
    if not token:
        return
    sid = request.sid
    token_to_sid[token] = sid
    sid_to_token[sid] = token
    removal_generation[token] = removal_generation.get(token, 0) + 1
    socketio.emit("state", game.state_for(token), to=sid, namespace=NAMESPACE)


@socketio.on("join", namespace=NAMESPACE)
def on_join(data):
    token = (data or {}).get("token")
    if not token:
        return
    global game
    if game.finished:
        game = Game()
    seat = game.add_player(token)
    if seat is None:
        socketio.emit(
            "join_error",
            {"message": "Игра уже заполнена (максимум 8 игроков)"},
            to=request.sid,
            namespace=NAMESPACE,
        )
        return
    new_state_broadcast()


@socketio.on("legal_moves", namespace=NAMESPACE)
def on_legal_moves(data):
    token = (data or {}).get("token")
    pos = (data or {}).get("pos")
    if not token or not pos:
        return
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
    if not token or not frm or not to:
        return
    ok, error = game.make_move(token, frm, to)
    if not ok:
        socketio.emit("move_error", {"message": error}, to=request.sid, namespace=NAMESPACE)
        return
    new_state_broadcast()


@socketio.on("attack_through_targets", namespace=NAMESPACE)
def on_attack_through_targets(data):
    token = (data or {}).get("token")
    pos = (data or {}).get("pos")
    if not token or not pos:
        return
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
    if not token or not ability:
        return
    ok, error = game.use_ability(token, ability, params)
    if not ok:
        socketio.emit("ability_error", {"message": error}, to=request.sid, namespace=NAMESPACE)
        return
    new_state_broadcast()


@socketio.on("restart", namespace=NAMESPACE)
def on_restart(data):
    token = (data or {}).get("token")
    if not token:
        return
    if game.players.get(token) is None:
        socketio.emit(
            "move_error",
            {"message": "Рестарт может начать только участник партии"},
            to=request.sid,
            namespace=NAMESPACE,
        )
        return
    game.restart()
    new_state_broadcast()


@socketio.on("disconnect", namespace=NAMESPACE)
def on_disconnect():
    sid = request.sid
    token = sid_to_token.pop(sid, None)
    if not token:
        return
    if token_to_sid.get(token) == sid:
        del token_to_sid[token]
    generation = removal_generation.get(token, 0)

    def delayed_removal():
        socketio.sleep(GRACE_SECONDS)
        if removal_generation.get(token) == generation and token not in token_to_sid:
            game.remove_player(token)
            new_state_broadcast()

    socketio.start_background_task(delayed_removal)

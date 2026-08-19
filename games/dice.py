"""Dice Grid Game: race tokens onto a 6x6 board using paired dice rolls,
in rooms of 2-4 players joined by a room code."""
import json
import random
import string

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from auth import login_required
from db import get_db

dice_bp = Blueprint("dice", __name__, url_prefix="/dice")


def generate_room_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def check_win(board, player):
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]

    for r in range(1, 7):
        for c in range(1, 7):
            if board.get(f"{r}{c}") != player:
                continue
            for dr, dc in dirs:
                count = 1
                for step in range(1, 4):
                    nr, nc = r + dr * step, c + dc * step
                    if nr < 1 or nr > 6 or nc < 1 or nc > 6:
                        break
                    if board.get(f"{nr}{nc}") == player:
                        count += 1
                if count >= 4:
                    return True
    return False


@dice_bp.route("/")
@login_required
def index():
    with get_db() as conn:
        rooms = conn.execute(
            "SELECT code, creator, max_players, status FROM dice_rooms WHERE status != 'finished' ORDER BY id DESC"
        ).fetchall()

        lobbies = []
        for r in rooms:
            players = conn.execute(
                "SELECT login FROM dice_room_players WHERE room_code = ? ORDER BY player_index",
                (r["code"],),
            ).fetchall()
            player_logins = [p["login"] for p in players]
            lobbies.append(
                {
                    "code": r["code"],
                    "creator": r["creator"],
                    "max_players": r["max_players"],
                    "status": r["status"],
                    "players": player_logins,
                    "is_member": session["user"] in player_logins,
                    "is_creator": r["creator"] == session["user"],
                }
            )

    return render_template("dice/menu.html", lobbies=lobbies, error=request.args.get("error"))


@dice_bp.route("/create-room", methods=["POST"])
@login_required
def create_room():
    max_players = int(request.form["max_players"])

    with get_db() as conn:
        old_rooms = conn.execute(
            "SELECT code FROM dice_rooms WHERE creator = ? ORDER BY id ASC",
            (session["user"],),
        ).fetchall()

        if len(old_rooms) >= 3:
            room_to_delete = old_rooms[0]["code"]
            conn.execute("DELETE FROM dice_room_players WHERE room_code = ?", (room_to_delete,))
            conn.execute("DELETE FROM dice_rooms WHERE code = ?", (room_to_delete,))

        code = generate_room_code()

        conn.execute(
            "INSERT INTO dice_rooms (code, creator, max_players, status, board) VALUES (?, ?, ?, 'waiting', '{}')",
            (code, session["user"], max_players),
        )
        conn.execute(
            "INSERT INTO dice_room_players (room_code, login, player_index) VALUES (?, ?, 0)",
            (code, session["user"]),
        )

    return redirect(url_for("dice.room", code=code))


@dice_bp.route("/join-room", methods=["POST"])
@login_required
def join_room_route():
    code = request.form["room_code"].upper().strip()

    with get_db() as conn:
        room = conn.execute(
            "SELECT max_players, status FROM dice_rooms WHERE code = ?", (code,)
        ).fetchone()

        if not room:
            return redirect(url_for("dice.index", error="Комната не найдена"))

        players = conn.execute(
            "SELECT login FROM dice_room_players WHERE room_code = ?", (code,)
        ).fetchall()

        if any(p["login"] == session["user"] for p in players):
            return redirect(url_for("dice.room", code=code))

        if len(players) >= room["max_players"]:
            return redirect(url_for("dice.index", error="Комната уже заполнена"))

        if room["status"] != "waiting":
            return redirect(url_for("dice.index", error="Игра уже началась"))

        player_index = len(players)
        conn.execute(
            "INSERT INTO dice_room_players (room_code, login, player_index) VALUES (?, ?, ?)",
            (code, session["user"], player_index),
        )

        if len(players) + 1 == room["max_players"]:
            conn.execute("UPDATE dice_rooms SET status = 'playing' WHERE code = ?", (code,))

    return redirect(url_for("dice.room", code=code))


@dice_bp.route("/room/<code>")
@login_required
def room(code):
    with get_db() as conn:
        r = conn.execute("SELECT creator FROM dice_rooms WHERE code = ?", (code,)).fetchone()

    if not r:
        return redirect(url_for("dice.index", error="Лобби закрыто или не найдено"))

    return render_template("dice/room.html", room_code=code, is_creator=(r["creator"] == session["user"]))


@dice_bp.route("/room/<code>/leave", methods=["POST"])
@login_required
def leave_room(code):
    with get_db() as conn:
        r = conn.execute("SELECT creator, status FROM dice_rooms WHERE code = ?", (code,)).fetchone()

        if not r:
            return redirect(url_for("dice.index"))

        if r["creator"] == session["user"]:
            # the creator leaving closes the lobby for everyone in it
            conn.execute("DELETE FROM dice_room_players WHERE room_code = ?", (code,))
            conn.execute("DELETE FROM dice_rooms WHERE code = ?", (code,))
        elif r["status"] == "waiting":
            conn.execute(
                "DELETE FROM dice_room_players WHERE room_code = ? AND login = ?",
                (code, session["user"]),
            )
        # leaving mid-game as a non-creator isn't supported: the seat stays,
        # matching how the board already tolerates a player going idle.

    return redirect(url_for("dice.index"))


@dice_bp.route("/api/room/<code>")
@login_required
def api_room(code):
    with get_db() as conn:
        room = conn.execute(
            """
            SELECT code, max_players, status, current_player, dice, can_move, board, rolling
            FROM dice_rooms WHERE code = ?
            """,
            (code,),
        ).fetchone()

        players = conn.execute(
            "SELECT login, player_index FROM dice_room_players WHERE room_code = ? ORDER BY player_index",
            (code,),
        ).fetchall()

    if not room:
        return jsonify({"error": "room not found"}), 404

    return jsonify(
        {
            "code": room["code"],
            "max_players": room["max_players"],
            "status": room["status"],
            "current_player": room["current_player"],
            "dice": json.loads(room["dice"]) if room["dice"] else None,
            "can_move": bool(room["can_move"]),
            "rolling": bool(room["rolling"]),
            "board": json.loads(room["board"]) if room["board"] else {},
            "players": [{"login": p["login"], "player_index": p["player_index"]} for p in players],
        }
    )


@dice_bp.route("/api/room/<code>/roll", methods=["POST"])
@login_required
def api_roll(code):
    with get_db() as conn:
        room = conn.execute(
            "SELECT current_player, status, board, max_players FROM dice_rooms WHERE code = ?",
            (code,),
        ).fetchone()

        players = conn.execute(
            "SELECT login, player_index FROM dice_room_players WHERE room_code = ?", (code,)
        ).fetchall()

        my_player = next((p for p in players if p["login"] == session["user"]), None)

        if not room or not my_player:
            return jsonify({"error": "access denied"}), 403

        if room["status"] != "playing":
            return jsonify({"error": "game not started"}), 400

        if my_player["player_index"] != room["current_player"]:
            return jsonify({"error": "not your turn"}), 400

        board = json.loads(room["board"]) if room["board"] else {}
        current_player = room["current_player"]
        max_players = room["max_players"]

        x = random.randint(1, 6)
        y = random.randint(1, 6)
        keys = [f"{x}{y}"] if x == y else [f"{x}{y}", f"{y}{x}"]

        all_own = all(key in board and board[key] == current_player for key in keys)

        if all_own:
            next_player = current_player if x == y else (current_player + 1) % max_players
            conn.execute(
                "UPDATE dice_rooms SET dice = ?, can_move = 0, current_player = ?, rolling = 0 WHERE code = ?",
                (json.dumps([x, y]), next_player, code),
            )
            return jsonify({"dice": [x, y], "skipped": True})

        conn.execute(
            "UPDATE dice_rooms SET dice = ?, can_move = 1, rolling = 0 WHERE code = ?",
            (json.dumps([x, y]), code),
        )

    return jsonify({"dice": [x, y], "skipped": False})


@dice_bp.route("/api/room/<code>/move", methods=["POST"])
@login_required
def api_move(code):
    key = (request.json or {}).get("key")

    with get_db() as conn:
        room = conn.execute(
            "SELECT current_player, dice, can_move, board, max_players FROM dice_rooms WHERE code = ?",
            (code,),
        ).fetchone()

        players = conn.execute(
            "SELECT login, player_index FROM dice_room_players WHERE room_code = ?", (code,)
        ).fetchall()

        my_player = next((p for p in players if p["login"] == session["user"]), None)

        if not room or not my_player:
            return jsonify({"error": "access denied"}), 403

        if my_player["player_index"] != room["current_player"]:
            return jsonify({"error": "not your turn"}), 400

        if not room["can_move"] or not room["dice"]:
            return jsonify({"error": "roll first"}), 400

        dice = json.loads(room["dice"])
        board = json.loads(room["board"]) if room["board"] else {}
        current_player = room["current_player"]
        max_players = room["max_players"]

        x, y = dice
        valid = [f"{x}{y}"] if x == y else [f"{x}{y}", f"{y}{x}"]

        if key not in valid:
            return jsonify({"error": "invalid cell"}), 400

        if key not in board:
            board[key] = current_player
        elif board[key] != current_player:
            del board[key]
        else:
            return jsonify({"error": "your own token"}), 400

        if check_win(board, current_player):
            conn.execute(
                "UPDATE dice_rooms SET board = ?, status = 'finished', can_move = 0 WHERE code = ?",
                (json.dumps(board), code),
            )
            return jsonify({"winner": current_player})

        next_player = current_player if x == y else (current_player + 1) % max_players
        conn.execute(
            "UPDATE dice_rooms SET board = ?, current_player = ?, dice = NULL, can_move = 0 WHERE code = ?",
            (json.dumps(board), next_player, code),
        )

    return jsonify({"success": True})

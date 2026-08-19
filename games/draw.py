import base64
import io
import os
import random
import threading
import time
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for
from PIL import Image
import numpy as np

from auth import login_required
from extensions import socketio

draw_bp = Blueprint("draw", __name__, url_prefix="/draw")
NAMESPACE = "/draw"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCES_DIR = os.path.join(BASE_DIR, "static", "draw", "references")
REFERENCE_IMAGES = sorted(
    f for f in os.listdir(REFERENCES_DIR) if f.lower().endswith(".png")
) if os.path.isdir(REFERENCES_DIR) else []

ROUND_DURATION = 90      # seconds per round
TOTAL_ROUNDS = 3
CANVAS_SIZE = 300
WHITE_DIST_THRESHOLD = 60            # RGB distance from white below which a pixel is "drawn"
PIXEL_TOLERANCE = 5                  # px of positional slack allowed when matching the outline
COLOR_MAX_DIST = 255.0 * (3 ** 0.5)  # max possible Euclidean distance between two RGB colors
SHAPE_WEIGHT = 0.6
COLOR_WEIGHT = 0.4

rooms = {}              # room_id -> room state (players identified by username)
username_to_sid = {}    # username -> current connected sid (namespace /draw)
sid_to_username = {}    # sid -> username
lock = threading.Lock()


def new_room_id():
    return uuid.uuid4().hex[:8]


def new_room(creator):
    return {
        "creator": creator,
        "players": [creator],
        "round": 0,
        "reference": None,
        "submissions": {},
        "round_finished": True,
        "finished_match": False,
        "total_scores": {},
        "rematch_votes": set(),
        "next_round_votes": set(),
        "end_time": None,
    }


def active_room_for(username):
    return next(
        (rid for rid, r in rooms.items() if username in r["players"] and not r["finished_match"]),
        None,
    )


def pick_reference():
    return random.choice(REFERENCE_IMAGES) if REFERENCE_IMAGES else None


def non_white_mask(rgb: np.ndarray) -> np.ndarray:
    dist = np.sqrt(((rgb.astype(np.float64) - 255.0) ** 2).sum(axis=-1))
    return dist > WHITE_DIST_THRESHOLD


def color_dilate(rgb: np.ndarray, mask: np.ndarray, iterations: int):
    """Grow `mask` outward by `iterations` pixels, carrying the nearest ink color with it.

    Returns (filled_color, filled_mask): filled_mask is the dilated mask (a
    positional-tolerance band around the original ink), and filled_color
    gives, for every pixel in that band, the color of the ink it grew from.
    """
    filled_color = rgb.astype(np.float64).copy()
    filled_mask = mask.copy()
    for _ in range(iterations):
        new_mask = filled_mask.copy()
        new_color = filled_color.copy()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted_mask = np.roll(filled_mask, shift=(dy, dx), axis=(0, 1))
            shifted_color = np.roll(filled_color, shift=(dy, dx), axis=(0, 1))
            grow = shifted_mask & ~new_mask
            new_color[grow] = shifted_color[grow]
            new_mask = new_mask | shifted_mask
        filled_mask, filled_color = new_mask, new_color
    return filled_color, filled_mask


def score_drawing(data_url: str, reference_path: str) -> float:
    """Compare a base64 canvas drawing against the reference image, 0-100.

    Combines a shape score (does the drawn outline line up with the
    reference, within a small pixel tolerance) with a color score (do
    matched pixels use roughly the same color as the reference there).
    """
    if not data_url or "," not in data_url:
        return 0.0
    try:
        _, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded)
        drawn = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return 0.0

    background = Image.new("RGBA", drawn.size, (255, 255, 255, 255))
    drawn_rgb = Image.alpha_composite(background, drawn).convert("RGB").resize(
        (CANVAS_SIZE, CANVAS_SIZE)
    )
    reference_rgb = Image.open(reference_path).convert("RGB").resize((CANVAS_SIZE, CANVAS_SIZE))

    player_arr = np.array(drawn_rgb)
    ref_arr = np.array(reference_rgb)

    player_mask = non_white_mask(player_arr)
    ref_mask = non_white_mask(ref_arr)

    player_ink = int(player_mask.sum())
    ref_ink = int(ref_mask.sum())
    if player_ink == 0 or ref_ink == 0:
        return 0.0

    ref_filled_color, ref_tolerant_mask = color_dilate(ref_arr, ref_mask, PIXEL_TOLERANCE)

    hits = player_mask & ref_tolerant_mask
    hit_count = int(hits.sum())

    shape_score = (2 * hit_count) / (player_ink + ref_ink)

    if hit_count:
        diffs = player_arr.astype(np.float64)[hits] - ref_filled_color[hits]
        dists = np.linalg.norm(diffs, axis=1)
        color_score = float(np.mean(np.clip(1 - dists / COLOR_MAX_DIST, 0.0, 1.0)))
    else:
        color_score = 0.0

    final = SHAPE_WEIGHT * shape_score + COLOR_WEIGHT * color_score
    return round(min(final, 1.0) * 100, 1)


def emit_to(username, event, payload):
    sid = username_to_sid.get(username)
    if sid:
        socketio.emit(event, payload, to=sid, namespace=NAMESPACE)


def opponent_of(room, username):
    return next((p for p in room["players"] if p != username), None)


def close_room(room_id, reason_for_remaining=None):
    """Tear down a room. If `reason_for_remaining` is set, tell whoever else
    is still in it (there is at most one other player, since draw is 1v1)."""
    room = rooms.pop(room_id, None)
    if not room:
        return
    if reason_for_remaining:
        for username in room["players"]:
            if username in username_to_sid:
                emit_to(username, "lobby_closed", {"message": reason_for_remaining})


def start_round(room_id):
    room = rooms.get(room_id)
    if not room or room["finished_match"]:
        return

    ref = pick_reference()
    room["round"] += 1
    room["reference"] = ref
    room["submissions"] = {}
    room["round_finished"] = False
    room["next_round_votes"] = set()
    end_time = time.time() + ROUND_DURATION
    room["end_time"] = end_time

    for username in room["players"]:
        opponent = opponent_of(room, username)
        emit_to(
            username,
            "start_round",
            {
                "round": room["round"],
                "total_rounds": TOTAL_ROUNDS,
                "reference_url": f"/static/draw/references/{ref}",
                "duration": ROUND_DURATION,
                "end_time": end_time,
                "opponent_name": opponent,
            },
        )

    socketio.start_background_task(force_finish_round, room_id, room["round"], end_time)


def force_finish_round(room_id, round_num, end_time):
    delay = max(0.0, end_time - time.time()) + 1.5
    socketio.sleep(delay)
    with lock:
        room = rooms.get(room_id)
        if not room or room["round"] != round_num or room["round_finished"]:
            return
        finish_round(room_id)


def finish_round(room_id):
    room = rooms.get(room_id)
    if not room or room["round_finished"]:
        return
    room["round_finished"] = True
    reference_path = os.path.join(REFERENCES_DIR, room["reference"])

    results = {}
    for username in room["players"]:
        data_url = room["submissions"].get(username, "")
        score = score_drawing(data_url, reference_path)
        room["total_scores"][username] = room["total_scores"].get(username, 0.0) + score
        results[username] = {"score": score, "image": data_url}

    p1, p2 = room["players"]
    if results[p1]["score"] > results[p2]["score"]:
        winner = p1
    elif results[p2]["score"] > results[p1]["score"]:
        winner = p2
    else:
        winner = None

    match_over = room["round"] >= TOTAL_ROUNDS
    room["finished_match"] = match_over

    for username in room["players"]:
        opponent = opponent_of(room, username)
        payload = {
            "round": room["round"],
            "total_rounds": TOTAL_ROUNDS,
            "reference_url": f"/static/draw/references/{room['reference']}",
            "your_score": results[username]["score"],
            "opponent_score": results[opponent]["score"],
            "your_image": results[username]["image"],
            "opponent_image": results[opponent]["image"],
            "round_winner": "you" if winner == username else ("opponent" if winner else "draw"),
            "total_scores": {
                "you": round(room["total_scores"][username], 1),
                "opponent": round(room["total_scores"][opponent], 1),
            },
            "match_over": match_over,
        }
        if match_over:
            if room["total_scores"][username] > room["total_scores"][opponent]:
                payload["match_winner"] = "you"
            elif room["total_scores"][username] < room["total_scores"][opponent]:
                payload["match_winner"] = "opponent"
            else:
                payload["match_winner"] = "draw"
        emit_to(username, "round_result", payload)


@draw_bp.route("/")
@login_required
def lobbies():
    username = session["user"]
    with lock:
        open_lobbies = [
            {"room_id": rid, "creator": r["creator"]}
            for rid, r in rooms.items()
            if len(r["players"]) == 1 and r["creator"] != username
        ]
        my_room = active_room_for(username)
    return render_template("draw/lobbies.html", lobbies=open_lobbies, my_room=my_room)


@draw_bp.route("/create", methods=["POST"])
@login_required
def create():
    username = session["user"]
    with lock:
        existing = active_room_for(username)
        if existing:
            return redirect(url_for("draw.room", room_id=existing))
        room_id = new_room_id()
        rooms[room_id] = new_room(username)
    return redirect(url_for("draw.room", room_id=room_id))


@draw_bp.route("/join/<room_id>", methods=["POST"])
@login_required
def join(room_id):
    username = session["user"]
    with lock:
        room = rooms.get(room_id)
        if room and username not in room["players"] and len(room["players"]) == 1:
            room["players"].append(username)
    return redirect(url_for("draw.room", room_id=room_id))


@draw_bp.route("/room/<room_id>")
@login_required
def room(room_id):
    with lock:
        r = rooms.get(room_id)
        if not r or session["user"] not in r["players"]:
            return redirect(url_for("draw.lobbies"))
    return render_template("draw/room.html", room_id=room_id)


@socketio.on("enter_room", namespace=NAMESPACE)
def on_enter_room(data):
    username = session.get("user")
    room_id = (data or {}).get("room_id")
    if not username or not room_id:
        return
    sid = request.sid

    with lock:
        room = rooms.get(room_id)
        if not room or username not in room["players"]:
            return
        username_to_sid[username] = sid
        sid_to_username[sid] = username

        if len(room["players"]) < 2:
            socketio.emit("waiting", {}, to=sid, namespace=NAMESPACE)
            return

        if room["round"] == 0 and all(p in username_to_sid for p in room["players"]):
            start_round(room_id)


@socketio.on("draw_batch", namespace=NAMESPACE)
def on_draw_batch(data):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    room_id = active_room_for(username)
    room = rooms.get(room_id) if room_id else None
    if not room or room["round_finished"]:
        return
    points = (data or {}).get("points")
    if not points:
        return
    opponent = opponent_of(room, username)
    if opponent:
        emit_to(opponent, "opponent_draw_batch", {"points": points})


@socketio.on("clear_canvas", namespace=NAMESPACE)
def on_clear_canvas(_data=None):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    room_id = active_room_for(username)
    room = rooms.get(room_id) if room_id else None
    if not room or room["round_finished"]:
        return
    opponent = opponent_of(room, username)
    if opponent:
        emit_to(opponent, "opponent_clear_canvas", {})


@socketio.on("redraw_canvas", namespace=NAMESPACE)
def on_redraw_canvas(data):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    room_id = active_room_for(username)
    room = rooms.get(room_id) if room_id else None
    if not room or room["round_finished"]:
        return
    points = (data or {}).get("points", [])
    opponent = opponent_of(room, username)
    if opponent:
        emit_to(opponent, "opponent_redraw_canvas", {"points": points})


@socketio.on("submit", namespace=NAMESPACE)
def on_submit(data):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    with lock:
        room_id = active_room_for(username)
        room = rooms.get(room_id) if room_id else None
        if not room or room["round_finished"]:
            return
        room["submissions"][username] = (data or {}).get("image", "")
        opponent = opponent_of(room, username)
        if opponent:
            emit_to(opponent, "opponent_submitted", {})
        if len(room["submissions"]) == len(room["players"]):
            finish_round(room_id)


@socketio.on("ready_next_round", namespace=NAMESPACE)
def on_ready_next_round(_data=None):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    with lock:
        room_id = active_room_for(username)
        room = rooms.get(room_id) if room_id else None
        if not room or room["finished_match"] or not room["round_finished"]:
            return
        room["next_round_votes"].add(username)
        if len(room["next_round_votes"]) == len(room["players"]):
            start_round(room_id)
        else:
            opponent = opponent_of(room, username)
            if opponent:
                emit_to(opponent, "opponent_ready_next_round", {})


@socketio.on("play_again", namespace=NAMESPACE)
def on_play_again(_data=None):
    username = sid_to_username.get(request.sid)
    if not username:
        return
    with lock:
        room_id = active_room_for(username)
        room = rooms.get(room_id) if room_id else None
        if not room or not room["finished_match"]:
            return
        room["rematch_votes"].add(username)
        if len(room["rematch_votes"]) == len(room["players"]):
            room["round"] = 0
            room["finished_match"] = False
            room["total_scores"] = {p: 0.0 for p in room["players"]}
            room["rematch_votes"] = set()
            start_round(room_id)
        else:
            opponent = opponent_of(room, username)
            if opponent:
                emit_to(opponent, "opponent_wants_rematch", {})


@socketio.on("disconnect", namespace=NAMESPACE)
def on_disconnect():
    sid = request.sid
    username = sid_to_username.pop(sid, None)
    if not username:
        return
    if username_to_sid.get(username) == sid:
        del username_to_sid[username]

    with lock:
        room_id = active_room_for(username)
        if not room_id:
            return
        # draw is strictly 1v1: either player leaving ends the room for both.
        close_room(room_id, reason_for_remaining="Соперник покинул игру. Лобби закрыто.")

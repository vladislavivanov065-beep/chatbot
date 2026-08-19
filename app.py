import base64
import io
import os
import random
import threading
import time
import uuid

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room
from PIL import Image
import numpy as np

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCES_DIR = os.path.join(BASE_DIR, "static", "references")
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

rooms = {}          # room_id -> room state
waiting_queue = []  # sids waiting for an opponent
sid_to_room = {}    # sid -> room_id
names = {}          # sid -> display name
lock = threading.Lock()


def new_room_id():
    return uuid.uuid4().hex[:8]


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


def start_round(room_id):
    room = rooms.get(room_id)
    if not room or room["finished_match"]:
        return

    ref = pick_reference()
    room["round"] += 1
    room["reference"] = ref
    room["submissions"] = {}
    room["round_finished"] = False
    end_time = time.time() + ROUND_DURATION
    room["end_time"] = end_time

    sides = {room["players"][0]: "left", room["players"][1]: "right"}
    for sid in room["players"]:
        opponent_sid = next(s for s in room["players"] if s != sid)
        socketio.emit(
            "start_round",
            {
                "round": room["round"],
                "total_rounds": TOTAL_ROUNDS,
                "reference_url": f"/static/references/{ref}",
                "duration": ROUND_DURATION,
                "end_time": end_time,
                "your_side": sides[sid],
                "your_name": room["names"][sid],
                "opponent_name": room["names"][opponent_sid],
            },
            to=sid,
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
    for sid in room["players"]:
        data_url = room["submissions"].get(sid, "")
        score = score_drawing(data_url, reference_path)
        room["total_scores"][sid] += score
        results[sid] = {"score": score, "image": data_url}

    p1, p2 = room["players"]
    if results[p1]["score"] > results[p2]["score"]:
        winner_sid = p1
    elif results[p2]["score"] > results[p1]["score"]:
        winner_sid = p2
    else:
        winner_sid = None

    match_over = room["round"] >= TOTAL_ROUNDS
    room["finished_match"] = match_over

    for sid in room["players"]:
        opponent_sid = next(s for s in room["players"] if s != sid)
        payload = {
            "round": room["round"],
            "total_rounds": TOTAL_ROUNDS,
            "reference_url": f"/static/references/{room['reference']}",
            "your_score": results[sid]["score"],
            "opponent_score": results[opponent_sid]["score"],
            "your_image": results[sid]["image"],
            "opponent_image": results[opponent_sid]["image"],
            "round_winner": "you" if winner_sid == sid else ("opponent" if winner_sid else "draw"),
            "total_scores": {
                "you": round(room["total_scores"][sid], 1),
                "opponent": round(room["total_scores"][opponent_sid], 1),
            },
            "match_over": match_over,
        }
        if match_over:
            if room["total_scores"][sid] > room["total_scores"][opponent_sid]:
                payload["match_winner"] = "you"
            elif room["total_scores"][sid] < room["total_scores"][opponent_sid]:
                payload["match_winner"] = "opponent"
            else:
                payload["match_winner"] = "draw"
        socketio.emit("round_result", payload, to=sid)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@socketio.on("join_game")
def on_join_game(data):
    sid = request.sid
    name = (data or {}).get("name", "").strip()[:20] or f"Игрок-{sid[:4]}"
    names[sid] = name

    with lock:
        if sid in waiting_queue or sid in sid_to_room:
            return
        if waiting_queue:
            opponent_sid = waiting_queue.pop(0)
            room_id = new_room_id()
            rooms[room_id] = {
                "players": [opponent_sid, sid],
                "names": {opponent_sid: names.get(opponent_sid, "Игрок 1"), sid: name},
                "total_scores": {opponent_sid: 0.0, sid: 0.0},
                "round": 0,
                "finished_match": False,
                "round_finished": True,
                "rematch_votes": set(),
            }
            sid_to_room[opponent_sid] = room_id
            sid_to_room[sid] = room_id
            join_room(room_id, sid=opponent_sid)
            join_room(room_id, sid=sid)
            start_round(room_id)
        else:
            waiting_queue.append(sid)
            socketio.emit("waiting", {}, to=sid)


@socketio.on("submit")
def on_submit(data):
    sid = request.sid
    room_id = sid_to_room.get(sid)
    if not room_id:
        return
    with lock:
        room = rooms.get(room_id)
        if not room or room["round_finished"]:
            return
        room["submissions"][sid] = (data or {}).get("image", "")
        opponent_sid = next((s for s in room["players"] if s != sid), None)
        if opponent_sid:
            socketio.emit("opponent_submitted", {}, to=opponent_sid)
        if len(room["submissions"]) == len(room["players"]):
            finish_round(room_id)


@socketio.on("play_again")
def on_play_again(_data):
    sid = request.sid
    room_id = sid_to_room.get(sid)
    if not room_id:
        return
    with lock:
        room = rooms.get(room_id)
        if not room or not room["finished_match"]:
            return
        room["rematch_votes"].add(sid)
        if len(room["rematch_votes"]) == len(room["players"]):
            room["round"] = 0
            room["finished_match"] = False
            room["total_scores"] = {s: 0.0 for s in room["players"]}
            room["rematch_votes"] = set()
            start_round(room_id)
        else:
            opponent_sid = next((s for s in room["players"] if s != sid), None)
            if opponent_sid:
                socketio.emit("opponent_wants_rematch", {}, to=opponent_sid)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with lock:
        if sid in waiting_queue:
            waiting_queue.remove(sid)
        room_id = sid_to_room.pop(sid, None)
        names.pop(sid, None)
        if room_id and room_id in rooms:
            room = rooms.pop(room_id, None)
            if room:
                opponent_sid = next((s for s in room["players"] if s != sid), None)
                if opponent_sid:
                    sid_to_room.pop(opponent_sid, None)
                    socketio.emit("opponent_left", {}, to=opponent_sid)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)

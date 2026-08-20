import eventlet
eventlet.monkey_patch()

import os

from flask import Flask, redirect, render_template, session, url_for

from auth import auth_bp, login_required
from db import init_db
from extensions import socketio
from games.chess import chess_bp
from games.dice import dice_bp
from games.draw import draw_bp
from games.dungeon import dungeon_bp
from games.durak import durak_bp

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

socketio.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(draw_bp)
app.register_blueprint(dice_bp)
app.register_blueprint(chess_bp)
app.register_blueprint(durak_bp)
app.register_blueprint(dungeon_bp)

init_db()


@app.route("/")
def home():
    return redirect(url_for("lobby") if session.get("user") else url_for("auth.login"))


@app.route("/lobby")
@login_required
def lobby():
    return render_template("lobby.html", user=session["user"])


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)

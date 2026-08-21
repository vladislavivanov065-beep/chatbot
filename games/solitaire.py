"""Single-player Klondike solitaire ("Пасьянс — Косынка").

Fully client-side — there's no opponent and nothing to synchronize, so
unlike the other games this blueprint carries no game state or socket
namespace at all; it just serves the page and the browser plays out
the whole game in static/solitaire/main.js.
"""
from flask import Blueprint, render_template

from auth import login_required

solitaire_bp = Blueprint("solitaire", __name__, url_prefix="/solitaire")


@solitaire_bp.route("/")
@login_required
def index():
    return render_template("solitaire/index.html")

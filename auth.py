"""Account registration and login. No email is collected or verified."""
import sqlite3
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

auth_bp = Blueprint("auth", __name__)

MIN_LOGIN_LENGTH = 3
MIN_PASSWORD_LENGTH = 6


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user"):
        return redirect(url_for("lobby"))

    if request.method == "GET":
        return render_template("auth/register.html", error=None, login_value="")

    login_value = request.form.get("login", "").strip()
    password1 = request.form.get("password1", "")
    password2 = request.form.get("password2", "")

    if len(login_value) < MIN_LOGIN_LENGTH:
        error = f"Логин должен быть не короче {MIN_LOGIN_LENGTH} символов"
    elif password1 != password2:
        error = "Пароли не совпадают"
    elif len(password1) < MIN_PASSWORD_LENGTH:
        error = f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    else:
        error = None

    if error:
        return render_template("auth/register.html", error=error, login_value=login_value)

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (login, password_hash) VALUES (?, ?)",
                (login_value, generate_password_hash(password1)),
            )
    except sqlite3.IntegrityError:
        return render_template(
            "auth/register.html",
            error="Такой логин уже занят",
            login_value=login_value,
        )

    session["user"] = login_value
    return redirect(url_for("lobby"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("lobby"))

    if request.method == "GET":
        return render_template("auth/login.html", error=None, login_value="")

    login_value = request.form.get("login", "").strip()
    password = request.form.get("password", "")

    with get_db() as conn:
        user = conn.execute(
            "SELECT login, password_hash FROM users WHERE login = ?",
            (login_value,),
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template(
            "auth/login.html",
            error="Неверный логин или пароль",
            login_value=login_value,
        )

    session["user"] = user["login"]
    return redirect(request.args.get("next") or url_for("lobby"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

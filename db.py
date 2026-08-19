"""Shared SQLite database for the whole site (accounts + the dice game's rooms)."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dice_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                creator TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'waiting',
                current_player INTEGER DEFAULT 0,
                dice TEXT,
                can_move INTEGER DEFAULT 0,
                rolling INTEGER DEFAULT 0,
                board TEXT DEFAULT '{}'
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dice_room_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_code TEXT NOT NULL,
                login TEXT NOT NULL,
                player_index INTEGER NOT NULL,
                UNIQUE(room_code, login)
            )
            """
        )

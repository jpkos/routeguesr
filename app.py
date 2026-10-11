import copy
import hashlib
import logging
import os
import random
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import folium
import pandas as pd
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import draw_stuff as ds
from ui_config import LINE_COLOR, ZOOM_LVL

ROOT = Path(__file__).resolve().parent
MODE_LABELS = {
    "bus": "Bussi",
    "metro": "Metro",
    "tram": "Ratikka",
    "train": "Juna",
    "ferry": "Lautta",
}
HSL_ZONES = ("A", "B", "C", "D", "E")
# Published by HSL at https://www.hsl.fi/matkustaminen/lahibussit
LAHIBUSSI_ROUTES = frozenset({
    "31", "32", "33", "34", "35", "36",
    "116", "117", "119", "137", "138", "148", "149", "168", "169",
    "201", "207", "229", "232", "313", "413",
    "701", "702", "713", "713B", "723", "805", "812", "813", "814", "815", "816", "817",
    "912", "912K", "913A", "913B", "914", "914T", "915A", "915B", "915T",
    "916", "916K", "917", "918", "919",
})


class GameConflict(Exception):
    pass


class MemoryGameStore:
    """Process-local store for development and automated tests."""

    def __init__(self):
        self.games = {}
        self.lock = threading.RLock()

    def create(self, game):
        with self.lock:
            if game["id"] in self.games:
                raise GameConflict
            self.games[game["id"]] = copy.deepcopy(game)

    def get(self, game_id):
        with self.lock:
            game = self.games.get(game_id)
            return copy.deepcopy(game) if game else None

    def update(self, game_id, mutate):
        with self.lock:
            game = copy.deepcopy(self.games.get(game_id))
            if not game:
                return None
            mutate(game)
            self.games[game_id] = copy.deepcopy(game)
            return game

    def accept_rematch(self, game_id, accepting_role, new_game):
        with self.lock:
            game = self.games.get(game_id)
            if not game:
                return None
            if game["rematch_id"]:
                return game["rematch_id"]
            if game["status"] != "finished":
                raise GameConflict
            if (
                game.get("rematch_status") != "pending"
                or game.get("rematch_requested_by") == accepting_role
            ):
                raise GameConflict
            self.games[new_game["id"]] = copy.deepcopy(new_game)
            game["rematch_id"] = new_game["id"]
            game["rematch_status"] = "accepted"
            return new_game["id"]


class FirestoreGameStore:
    """Shared production store with atomic multiplayer state transitions."""

    def __init__(self):
        from google.cloud import firestore

        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        self.firestore = firestore
        self.client = firestore.Client(database=database)
        self.games = self.client.collection("games")

    def create(self, game):
        self.games.document(game["id"]).create(game)

    def get(self, game_id):
        snapshot = self.games.document(game_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def update(self, game_id, mutate):
        reference = self.games.document(game_id)
        transaction = self.client.transaction()

        @self.firestore.transactional
        def apply(transaction):
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return None
            game = snapshot.to_dict()
            mutate(game)
            transaction.set(reference, game)
            return game

        return apply(transaction)

    def accept_rematch(self, game_id, accepting_role, new_game):
        old_reference = self.games.document(game_id)
        new_reference = self.games.document(new_game["id"])
        transaction = self.client.transaction()

        @self.firestore.transactional
        def apply(transaction):
            snapshot = old_reference.get(transaction=transaction)
            if not snapshot.exists:
                return None
            game = snapshot.to_dict()
            if game["rematch_id"]:
                return game["rematch_id"]
            if game["status"] != "finished":
                raise GameConflict
            if (
                game.get("rematch_status") != "pending"
                or game.get("rematch_requested_by") == accepting_role
            ):
                raise GameConflict
            transaction.create(new_reference, new_game)
            transaction.update(old_reference, {
                "rematch_id": new_game["id"],
                "rematch_status": "accepted",
            })
            return new_game["id"]

        return apply(transaction)


def cloud_project_id():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    if project:
        return project
    application = os.environ.get("GAE_APPLICATION", "")
    return application.split("~")[-1] if application else None


def load_secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    secret_file = ROOT / "secrets.txt"
    if secret_file.exists():
        return secret_file.read_text().strip()
    if os.environ.get("GAE_ENV"):
        from google.cloud import secretmanager

        project = cloud_project_id()
        secret_id = os.environ.get("FLASK_SECRET_ID", "flask-secret-key")
        version = os.environ.get("FLASK_SECRET_VERSION", "1")
        name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
        response = secretmanager.SecretManagerServiceClient().access_secret_version(
            request={"name": name}
        )
        return response.payload.data.decode("utf-8")
    logging.warning("Using an ephemeral Flask secret. Set SECRET_KEY for stable local sessions.")
    return secrets.token_hex(32)


def create_game_store():
    backend = os.environ.get("GAME_BACKEND", "firestore" if os.environ.get("GAE_ENV") else "memory")
    if backend == "firestore":
        return FirestoreGameStore()
    if backend == "memory":
        return MemoryGameStore()
    raise RuntimeError(f"Unsupported GAME_BACKEND: {backend}")


app = Flask(__name__)
app.secret_key = load_secret_key()
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("GAE_ENV")),
)
game_store = create_game_store()

loaded_lines = pd.read_pickle(ROOT / "data/processed/lines.pkl")
geometry_coordinate_order = loaded_lines.attrs.get(
    "geometry_coordinate_order", "latitude_longitude"
)
route_zones_by_name = {
    route_name: tuple(
        zone
        for zone in HSL_ZONES
        if any(zone in route_zones for route_zones in group["zones"])
    )
    for route_name, group in loaded_lines.groupby("route_short_name")
}
lines = loaded_lines.drop_duplicates("route_short_name", keep="last").dropna(subset=["route_short_name"]).copy()
lines["route_short_name"] = lines["route_short_name"].astype(str)
lines["zones"] = lines["route_short_name"].map(route_zones_by_name)
def mode_for_route_type(value):
    """Map both basic and extended GTFS route types used by HSL."""
    value = int(value)
    if value in (0, 900):
        return "tram"
    if value == 1:
        return "metro"
    if value == 2 or 100 <= value < 200:
        return "train"
    if value == 3 or 700 <= value < 800:
        return "bus"
    if value in (4, 1000, 1200):
        return "ferry"
    return None


lines["mode"] = lines["route_type"].map(mode_for_route_type)
lines = lines[lines["mode"].notna()].set_index("route_short_name", drop=False)
possible_lines = sorted(lines.index.tolist(), key=lambda x: (len(x), x))

def player_id():
    if "player_id" not in session: session["player_id"] = secrets.token_urlsafe(18)
    return session["player_id"]

def get_game(game_id):
    return game_store.get(game_id)


def new_game_document(
    game_id,
    count,
    modes,
    routes,
    round_options,
    host_id,
    host_name,
    *,
    include_night_routes=True,
    include_alternative_routes=True,
    include_lahibussi_routes=True,
    zones=HSL_ZONES,
    status="waiting",
    guest_id=None,
    guest_name=None,
):
    now = datetime.now(timezone.utc)
    return {
        "id": game_id,
        "created_at": now,
        "expires_at": now + timedelta(days=1),
        "status": status,
        "route_count": count,
        "modes": modes,
        "include_night_routes": include_night_routes,
        "include_alternative_routes": include_alternative_routes,
        "include_lahibussi_routes": include_lahibussi_routes,
        "zones": list(zones),
        "routes": routes,
        "round_options": round_options,
        "current_round": 0,
        "host_id": host_id,
        "host_name": host_name,
        "guest_id": guest_id,
        "guest_name": guest_name,
        "guesses": {},
        "rematch_id": None,
        "rematch_status": None,
        "rematch_requested_by": None,
        "left_by": None,
        "left_name": None,
        "left_at": None,
    }

def role_for(game):
    pid = player_id()
    return "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None

def state_for(game):
    role = role_for(game)
    if not role: abort(403)
    other = "guest" if role == "host" else "host"
    guesses = game["guesses"].get(str(game["current_round"]), {})
    rematch_requested_by = game.get("rematch_requested_by")
    return {"status": game["status"], "round": game["current_round"], "route_count": game["route_count"],
      "options": options_for_round(game, game["current_round"]),
      "has_guessed": role in guesses, "opponent_has_guessed": other in guesses,
      "opponent_name": game[f"{other}_name"], "rematch_id": game["rematch_id"],
      "rematch_status": game.get("rematch_status"),
      "rematch_requested_by_opponent": rematch_requested_by == other,
      "rematch_requested_by_you": rematch_requested_by == role,
      "rematch_requested_name": game.get(f"{rematch_requested_by}_name") if rematch_requested_by else None,
      "opponent_left": game.get("left_by") == other,
      "left_name": game.get("left_name"),
      "results_url": url_for("results", game_id=game["id"])}

def filtered_routes(
    modes,
    include_night_routes=True,
    include_alternative_routes=True,
    include_lahibussi_routes=True,
    zones=None,
):
    """Return routes matching the selected modes and special-route settings."""
    candidates = lines[lines["mode"].isin(modes)]
    selected_zones = frozenset(HSL_ZONES if zones is None else zones)
    candidates = candidates[
        candidates["zones"].apply(
            lambda route_zones: bool(route_zones)
            and set(route_zones).issubset(selected_zones)
        )
    ]
    labels = candidates["route_short_name"].str.upper()

    if not include_night_routes:
        candidates = candidates[~labels.str.endswith("N")]

    if not include_alternative_routes:
        labels = candidates["route_short_name"].str.upper()
        candidates = candidates[
            ~((candidates["mode"] == "tram") & labels.str.endswith(("H", "T")))
        ]

    if not include_lahibussi_routes:
        labels = candidates["route_short_name"].str.upper()
        candidates = candidates[
            ~((candidates["mode"] == "bus") & labels.isin(LAHIBUSSI_ROUTES))
        ]

    return candidates


def choose_routes(
    count,
    modes,
    include_night_routes=True,
    include_alternative_routes=True,
    include_lahibussi_routes=True,
    zones=None,
):
    candidates = filtered_routes(
        modes,
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    )
    return None if len(candidates) < count else candidates.sample(count)["route_short_name"].tolist()


def route_options(
    modes,
    include_night_routes=True,
    include_alternative_routes=True,
    include_lahibussi_routes=True,
    zones=None,
):
    """Return answer options limited to the settings enabled for a match."""
    options = filtered_routes(
        modes,
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    ).index.tolist()
    return sorted(options, key=lambda value: (len(value), value))


def build_round_options(routes, candidates, rng=None):
    """Build four choices per route, including a same-mode distractor."""
    candidate_routes = list(dict.fromkeys(candidates))
    if len(candidate_routes) < 4:
        return None

    rng = rng or random.SystemRandom()
    choices_by_round = []
    for correct_route in routes:
        correct_mode = lines.loc[correct_route, "mode"]
        same_mode = [
            route
            for route in candidate_routes
            if route != correct_route and lines.loc[route, "mode"] == correct_mode
        ]
        if not same_mode:
            return None

        same_mode_distractor = rng.choice(same_mode)
        other_distractors = rng.sample(
            [
                route
                for route in candidate_routes
                if route not in (correct_route, same_mode_distractor)
            ],
            2,
        )
        choices = [correct_route, same_mode_distractor, *other_distractors]
        rng.shuffle(choices)
        choices_by_round.append(choices)

    return choices_by_round


def choose_game_routes(
    count,
    modes,
    include_night_routes=True,
    include_alternative_routes=True,
    include_lahibussi_routes=True,
    zones=None,
):
    """Choose guessable routes and four filtered answer choices for each one."""
    candidates = filtered_routes(
        modes,
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    )
    if len(candidates) < 4:
        return None

    mode_counts = candidates.groupby("mode")["route_short_name"].transform("size")
    guessable_routes = candidates[mode_counts >= 2]
    if len(guessable_routes) < count:
        return None

    routes = guessable_routes.sample(count)["route_short_name"].tolist()
    round_options = build_round_options(routes, candidates.index.tolist())
    return (routes, round_options) if round_options else None


def options_for_round(game, round_number):
    """Return stored choices, with deterministic support for older game records."""
    if not 0 <= round_number < len(game["routes"]):
        return []
    stored_options = game.get("round_options")
    if stored_options and round_number < len(stored_options):
        return stored_options[round_number]

    candidates = route_options(
        game["modes"],
        game.get("include_night_routes", True),
        game.get("include_alternative_routes", True),
        game.get("include_lahibussi_routes", True),
        game.get("zones", HSL_ZONES),
    )
    seed = int.from_bytes(
        hashlib.sha256(str(game.get("id", game["routes"])).encode()).digest(),
        "big",
    )
    legacy_options = build_round_options(game["routes"], candidates, random.Random(seed))
    return legacy_options[round_number] if legacy_options else candidates

def render_map(route):
    geometry_coords = list(lines.loc[route, "geometry"].coords)
    coords = (
        [(latitude, longitude) for longitude, latitude in geometry_coords]
        if geometry_coordinate_order == "longitude_latitude"
        else geometry_coords
    )
    fmap = folium.Map(location=coords[len(coords)//2], zoom_start=ZOOM_LVL, control_scale=True)
    ds.draw_route(coords, color=LINE_COLOR).add_to(fmap)
    return fmap.get_root().render()

@app.get("/")
def index():
    return render_template("index.html", mode_labels=MODE_LABELS, zones=HSL_ZONES)

@app.post("/games")
def create_game():
    name = " ".join(request.form.get("nickname", "").strip().split())[:24]
    try: count = max(1, min(int(request.form.get("route_count", 5)), 30))
    except ValueError: count = 5
    modes = [m for m in MODE_LABELS if m in request.form.getlist("modes")]
    include_night_routes = bool(request.form.get("include_night_routes"))
    include_alternative_routes = bool(request.form.get("include_alternative_routes"))
    include_lahibussi_routes = bool(request.form.get("include_lahibussi_routes"))
    zones = [zone for zone in HSL_ZONES if zone in request.form.getlist("zones")]
    if not name or not modes or not zones:
        return render_template(
            "index.html",
            mode_labels=MODE_LABELS,
            zones=HSL_ZONES,
            error="Anna nimimerkki ja valitse vähintään yksi kulkumuoto ja vyöhyke.",
        ), 400
    game_content = choose_game_routes(
        count,
        modes,
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    )
    if game_content is None:
        return render_template(
            "index.html",
            mode_labels=MODE_LABELS,
            zones=HSL_ZONES,
            error="Valituissa asetuksissa ei ole tarpeeksi reittejä neljään vastausvaihtoehtoon.",
        ), 400
    routes, round_options = game_content
    game_id = secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:9]
    game_store.create(new_game_document(
        game_id,
        count,
        modes,
        routes,
        round_options,
        player_id(),
        name,
        include_night_routes=include_night_routes,
        include_alternative_routes=include_alternative_routes,
        include_lahibussi_routes=include_lahibussi_routes,
        zones=zones,
    ))
    return redirect(url_for("lobby", game_id=game_id))

@app.get("/games/<game_id>")
def lobby(game_id):
    game = get_game(game_id)
    if not game: abort(404)
    role = role_for(game)
    if game["status"] == "finished" and role: return redirect(url_for("results", game_id=game_id))
    if game["status"] == "playing" and role: return redirect(url_for("play", game_id=game_id))
    if game["status"] != "waiting":
        return render_template("message.html", title="Peli on jo käynnissä", message="Tähän peliin on jo liittynyt kaksi pelaajaa."), 409
    return render_template("lobby.html", game=game, role=role, mode_labels=MODE_LABELS, invite_url=url_for("lobby", game_id=game_id, _external=True))

@app.post("/games/<game_id>/join")
def join(game_id):
    name = " ".join(request.form.get("nickname", "").strip().split())[:24]
    if not name: return redirect(url_for("lobby", game_id=game_id, error="nickname"))
    pid = player_id()

    def add_guest(game):
        role = "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None
        if role:
            return
        if game["status"] != "waiting" or game["guest_id"]:
            raise GameConflict
        game["guest_id"] = pid
        game["guest_name"] = name
        game["status"] = "playing"

    try:
        game = game_store.update(game_id, add_guest)
    except GameConflict:
        return render_template("message.html", title="Peli on täynnä", message="Tähän peliin on jo liittynyt kaksi pelaajaa."), 409
    if not game:
        abort(404)
    role = role_for(game)
    if role and game["status"] != "playing":
        return redirect(url_for("lobby", game_id=game_id))
    return redirect(url_for("play", game_id=game_id))

@app.get("/games/<game_id>/play")
def play(game_id):
    game = get_game(game_id)
    if not game: abort(404)
    role = role_for(game)
    if not role: return redirect(url_for("lobby", game_id=game_id))
    if game["status"] == "waiting": return redirect(url_for("lobby", game_id=game_id))
    if game["status"] == "finished": return redirect(url_for("results", game_id=game_id))
    other = "guest" if role == "host" else "host"
    return render_template("game.html", game=game, possible_lines=options_for_round(
        game, game["current_round"]
    ),
      player_name=game[f"{role}_name"], opponent_name=game[f"{other}_name"])

@app.get("/games/<game_id>/state")
def game_state(game_id):
    game = get_game(game_id)
    if not game: abort(404)
    return jsonify(state_for(game))


@app.post("/games/<game_id>/leave")
def leave_game(game_id):
    pid = player_id()

    def abandon_game(game):
        role = "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None
        if not role:
            abort(403)
        if game["status"] != "playing":
            return
        game["status"] = "abandoned"
        game["left_by"] = role
        game["left_name"] = game[f"{role}_name"]
        game["left_at"] = datetime.now(timezone.utc)

    if not game_store.update(game_id, abandon_game):
        abort(404)
    return redirect(url_for("index"))

@app.get("/games/<game_id>/map/<int:round_number>")
def game_map(game_id, round_number):
    game = get_game(game_id)
    if not game or not role_for(game) or not 0 <= round_number < game["route_count"]: abort(404)
    return render_map(game["routes"][round_number])

@app.post("/games/<game_id>/guess")
def guess(game_id):
    answer = request.form.get("guess", "").strip()
    pid = player_id()

    def record_guess(game):
        role = "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None
        if not role:
            abort(403)
        if game["status"] != "playing":
            return
        if answer not in options_for_round(game, game["current_round"]):
            abort(400)
        current = game["guesses"].setdefault(str(game["current_round"]), {})
        current.setdefault(role, answer)
        if "host" in current and "guest" in current:
            game["current_round"] += 1
            if game["current_round"] >= game["route_count"]:
                game["status"] = "finished"

    updated = game_store.update(game_id, record_guess)
    if not updated:
        abort(404)
    return jsonify(state_for(updated))

def result_rows(game):
    rows = []
    for i, route in enumerate(game["routes"]):
        guesses = game["guesses"].get(str(i), {})
        rows.append({"number": i+1, "route": route, "host_guess": guesses.get("host", "—"), "guest_guess": guesses.get("guest", "—"),
          "host_correct": guesses.get("host") == route, "guest_correct": guesses.get("guest") == route})
    return rows

@app.get("/games/<game_id>/results")
def results(game_id):
    game = get_game(game_id)
    role = role_for(game) if game else None
    if not game or not role: abort(404)
    if game["status"] != "finished": return redirect(url_for("play", game_id=game_id))
    if game.get("rematch_status") == "declined":
        return redirect(url_for("index"))
    if game.get("rematch_id"):
        return redirect(url_for("play", game_id=game["rematch_id"]))
    rows = result_rows(game)
    scores = {r: sum(row[f"{r}_correct"] for row in rows) for r in ("host", "guest")}
    return render_template("results.html", game=game, rows=rows, scores=scores, role=role)

@app.post("/games/<game_id>/rematch")
def rematch(game_id):
    pid = player_id()

    def request_rematch(game):
        role = "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None
        if not role:
            abort(403)
        if game["status"] != "finished":
            raise GameConflict
        if game.get("rematch_status") is None:
            game["rematch_status"] = "pending"
            game["rematch_requested_by"] = role

    try:
        game = game_store.update(game_id, request_rematch)
    except GameConflict:
        abort(409)
    if not game:
        abort(404)
    return redirect(url_for("results", game_id=game_id))


@app.post("/games/<game_id>/rematch/accept")
def accept_rematch(game_id):
    game = get_game(game_id)
    if not game:
        abort(404)
    role = role_for(game)
    if not role:
        abort(404)
    if game["status"] != "finished":
        abort(409)
    include_night_routes = game.get("include_night_routes", True)
    include_alternative_routes = game.get("include_alternative_routes", True)
    include_lahibussi_routes = game.get("include_lahibussi_routes", True)
    zones = game.get("zones", HSL_ZONES)
    new_id = secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:9]
    game_content = choose_game_routes(
        game["route_count"],
        game["modes"],
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    )
    if game_content is None:
        abort(409)
    routes, round_options = game_content
    new_game = new_game_document(
        new_id,
        game["route_count"],
        game["modes"],
        routes,
        round_options,
        game["host_id"],
        game["host_name"],
        include_night_routes=include_night_routes,
        include_alternative_routes=include_alternative_routes,
        include_lahibussi_routes=include_lahibussi_routes,
        zones=zones,
        status="playing",
        guest_id=game["guest_id"], guest_name=game["guest_name"]
    )
    try:
        rematch_id = game_store.accept_rematch(game_id, role, new_game)
    except GameConflict:
        abort(409)
    if not rematch_id:
        abort(404)
    return redirect(url_for("play", game_id=rematch_id))


@app.post("/games/<game_id>/rematch/decline")
def decline_rematch(game_id):
    pid = player_id()

    def decline(game):
        role = "host" if pid == game["host_id"] else "guest" if pid == game["guest_id"] else None
        if not role:
            abort(403)
        if (
            game["status"] != "finished"
            or game.get("rematch_status") != "pending"
            or game.get("rematch_requested_by") == role
        ):
            raise GameConflict
        game["rematch_status"] = "declined"

    try:
        game = game_store.update(game_id, decline)
    except GameConflict:
        abort(409)
    if not game:
        abort(404)
    return redirect(url_for("index"))

@app.post("/solo/start")
def start_solo():
    try:
        count = max(1, min(int(request.form.get("route_count", 5)), 30))
    except ValueError:
        count = 5
    modes = [mode for mode in MODE_LABELS if mode in request.form.getlist("modes")]
    include_night_routes = bool(request.form.get("include_night_routes"))
    include_alternative_routes = bool(request.form.get("include_alternative_routes"))
    include_lahibussi_routes = bool(request.form.get("include_lahibussi_routes"))
    zones = [zone for zone in HSL_ZONES if zone in request.form.getlist("zones")]
    if not modes or not zones:
        return render_template(
            "index.html",
            mode_labels=MODE_LABELS,
            zones=HSL_ZONES,
            error="Valitse harjoitteluun vähintään yksi kulkumuoto ja vyöhyke.",
        ), 400
    game_content = choose_game_routes(
        count,
        modes,
        include_night_routes,
        include_alternative_routes,
        include_lahibussi_routes,
        zones,
    )
    if game_content is None:
        return render_template(
            "index.html",
            mode_labels=MODE_LABELS,
            zones=HSL_ZONES,
            error="Valituissa asetuksissa ei ole tarpeeksi reittejä neljään vastausvaihtoehtoon.",
        ), 400
    routes, round_options = game_content
    session["solo_game"] = {
        "routes": routes,
        "round_options": round_options,
        "modes": modes,
        "include_night_routes": include_night_routes,
        "include_alternative_routes": include_alternative_routes,
        "include_lahibussi_routes": include_lahibussi_routes,
        "zones": zones,
        "round": 0,
        "answers": [],
    }
    return redirect(url_for("solo"))


@app.get("/solo")
def solo():
    game = session.get("solo_game")
    if not game:
        routes, round_options = choose_game_routes(5, list(MODE_LABELS))
        game = {
            "routes": routes,
            "round_options": round_options,
            "modes": list(MODE_LABELS),
            "include_night_routes": True,
            "include_alternative_routes": True,
            "include_lahibussi_routes": True,
            "zones": list(HSL_ZONES),
            "round": 0,
            "answers": [],
        }
        session["solo_game"] = game
    if game["round"] >= len(game["routes"]):
        return redirect(url_for("solo_results"))
    return render_template(
        "solo.html",
        possible_lines=options_for_round(game, game["round"]),
        game=game,
    )

@app.get("/solo/map")
def solo_map():
    game = session.get("solo_game")
    route = game["routes"][game["round"]] if game and game["round"] < len(game["routes"]) else None
    if route not in lines.index: return redirect(url_for("solo"))
    return render_map(route)


@app.post("/solo/leave")
def leave_solo():
    session.pop("solo_game", None)
    return redirect(url_for("index"))

@app.post("/solo/guess")
def solo_guess():
    game = session.get("solo_game")
    if not game or game["round"] >= len(game["routes"]): abort(409)
    correct = game["routes"][game["round"]]
    if correct not in lines.index: abort(409)
    answer = request.form.get("guess", "").strip()
    if answer not in options_for_round(game, game["round"]):
        abort(400)
    is_correct = answer == correct
    game["answers"].append({"route": correct, "guess": answer, "correct": is_correct})
    game["round"] += 1
    session["solo_game"] = game
    next_url = url_for("solo_results") if game["round"] >= len(game["routes"]) else url_for("solo")
    return jsonify(correct=is_correct, route=correct, next_url=next_url)


@app.get("/solo/results")
def solo_results():
    game = session.get("solo_game")
    if not game or game["round"] < len(game["routes"]):
        return redirect(url_for("solo"))
    score = sum(answer["correct"] for answer in game["answers"])
    return render_template("solo_results.html", game=game, score=score)

if __name__ == "__main__": app.run(debug=True)

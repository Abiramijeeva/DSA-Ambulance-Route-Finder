import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, url_for
from flask_socketio import SocketIO, join_room

from dijkstra import k_shortest_routes
from graph_data import LOCATION_NAMES, ROAD_GRAPH
from osm_routing import (
    RoutingServiceError,
    geocode_location,
    get_hospital,
    get_hospitals,
    get_osrm_routes,
    location_from_coordinates,
    make_route_options,
    search_hospitals,
)
from trip_tracking import (
    authorize_trip,
    change_trip_status,
    create_trip,
    get_trip,
    get_trip_events,
    public_trip,
    purge_stale_locations,
    update_trip_location,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
socketio = SocketIO(app, async_mode="threading")
os.makedirs(app.instance_path, exist_ok=True)
DATABASE_PATH = os.environ.get(
    "DATABASE_PATH", os.path.join(app.instance_path, "routes.db")
)
os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)

PRIORITIES = ("Low", "Medium", "High", "Critical")
NODE_POSITIONS = {
    "H": (80, 210),
    "A": (250, 100),
    "B": (250, 300),
    "C": (440, 100),
    "D": (440, 300),
    "P": (610, 210),
}


def road_key(first, second):
    return ":".join(sorted((first, second)))


def get_base_roads():
    return [
        (first, second, minutes)
        for first, neighbors in ROAD_GRAPH.items()
        for second, minutes in neighbors
        if first < second
    ]


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def database_connection():
    connection = connect_database()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with database_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS road_conditions (
                road_key TEXT PRIMARY KEY,
                is_closed INTEGER NOT NULL DEFAULT 0,
                added_minutes INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS route_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                route_codes TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                priority TEXT NOT NULL,
                departure_time TEXT NOT NULL,
                arrival_time TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                data_source TEXT NOT NULL DEFAULT 'demo',
                estimated_distance_km REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_cache (
                normalized_address TEXT PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                display_name TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_request_state (
                service_name TEXT PRIMARY KEY,
                next_request_at REAL NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(route_history)")
        }
        if "data_source" not in columns:
            connection.execute(
                "ALTER TABLE route_history ADD COLUMN data_source TEXT NOT NULL DEFAULT 'demo'"
            )
        if "estimated_distance_km" not in columns:
            connection.execute(
                "ALTER TABLE route_history ADD COLUMN estimated_distance_km REAL"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY,
                ambulance_id TEXT NOT NULL,
                origin_name TEXT NOT NULL,
                origin_lat REAL NOT NULL,
                origin_lon REAL NOT NULL,
                destination_name TEXT NOT NULL,
                destination_lat REAL NOT NULL,
                destination_lon REAL NOT NULL,
                priority TEXT NOT NULL CHECK(priority IN ('Low', 'Medium', 'High', 'Critical')),
                status TEXT NOT NULL CHECK(status IN ('planned', 'tracking', 'stopped', 'completed')),
                driver_token_hash TEXT NOT NULL,
                viewer_token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                last_lat REAL,
                last_lon REAL,
                last_accuracy_m REAL,
                last_location_at TEXT,
                actual_distance_m REAL NOT NULL DEFAULT 0,
                location_update_count INTEGER NOT NULL DEFAULT 0,
                route_distance_m REAL NOT NULL,
                route_duration_s REAL NOT NULL,
                route_geometry TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trip_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (
                    event_type IN (
                        'created', 'tracking_started',
                        'tracking_stopped', 'completed'
                    )
                ),
                event_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS trip_events_trip_time
            ON trip_events (trip_id, event_at, id)
            """
        )
        connection.execute(
            """
            INSERT INTO trip_events (trip_id, event_type, event_at)
            SELECT trip.id, 'created', trip.created_at
            FROM trips AS trip
            WHERE NOT EXISTS (
                SELECT 1 FROM trip_events AS event
                WHERE event.trip_id = trip.id
            )
            """
        )
        connection.execute(
            """
            INSERT INTO trip_events (trip_id, event_type, event_at)
            SELECT trip.id, 'tracking_started', trip.started_at
            FROM trips AS trip
            WHERE trip.started_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM trip_events AS event
                  WHERE event.trip_id = trip.id
                    AND event.event_type = 'tracking_started'
              )
            """
        )
        connection.execute(
            """
            INSERT INTO trip_events (trip_id, event_type, event_at)
            SELECT trip.id, 'completed', trip.completed_at
            FROM trips AS trip
            WHERE trip.completed_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM trip_events AS event
                  WHERE event.trip_id = trip.id
                    AND event.event_type = 'completed'
              )
            """
        )


def load_road_conditions():
    with database_connection() as connection:
        stored = {
            row["road_key"]: {
                "closed": bool(row["is_closed"]),
                "added_minutes": row["added_minutes"],
            }
            for row in connection.execute("SELECT * FROM road_conditions")
        }

    return {
        road_key(first, second): stored.get(
            road_key(first, second), {"closed": False, "added_minutes": 0}
        )
        for first, second, _ in get_base_roads()
    }


def save_road_conditions(conditions):
    with database_connection() as connection:
        connection.execute("DELETE FROM road_conditions")
        connection.executemany(
            """
            INSERT INTO road_conditions (road_key, is_closed, added_minutes)
            VALUES (?, ?, ?)
            """,
            [
                (key, int(values["closed"]), values["added_minutes"])
                for key, values in conditions.items()
            ],
        )


def restore_road_conditions():
    with database_connection() as connection:
        connection.execute("DELETE FROM road_conditions")


def get_effective_graph(conditions):
    graph = {node: [] for node in ROAD_GRAPH}
    for first, second, base_minutes in get_base_roads():
        condition = conditions[road_key(first, second)]
        if not condition["closed"]:
            adjusted_minutes = base_minutes + condition["added_minutes"]
            graph[first].append((second, adjusted_minutes))
            graph[second].append((first, adjusted_minutes))
    return graph


def build_route(path, graph):
    duration = sum(
        next(minutes for neighbor, minutes in graph[first] if neighbor == second)
        for first, second in zip(path, path[1:])
    )
    return {
        "path": path,
        "path_names": [LOCATION_NAMES[node] for node in path],
        "duration": duration,
        "roads": [
            {
                "from_code": first,
                "to_code": second,
                "from_name": LOCATION_NAMES[first],
                "to_name": LOCATION_NAMES[second],
                "minutes": next(
                    minutes for neighbor, minutes in graph[first]
                    if neighbor == second
                ),
            }
            for first, second in zip(path, path[1:])
        ],
    }


def add_history(source, destination, route, priority, departure, arrival, data_source):
    with database_connection() as connection:
        connection.execute(
            """
            INSERT INTO route_history (
                source, destination, route_codes, duration_minutes, priority,
                departure_time, arrival_time, searched_at, data_source,
                estimated_distance_km
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                destination,
                json.dumps(route.get("history_path", route["path"])),
                route["duration"],
                priority,
                departure.isoformat(timespec="minutes"),
                arrival.isoformat(timespec="minutes"),
                datetime.now().astimezone().isoformat(timespec="seconds"),
                data_source,
                route.get("distance_km"),
            ),
        )


def load_history():
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM route_history
            ORDER BY id DESC
            LIMIT 30
            """
        ).fetchall()

    history = []
    for row in rows:
        path = json.loads(row["route_codes"])
        history.append(
            {
                "source": LOCATION_NAMES.get(row["source"], row["source"]),
                "destination": LOCATION_NAMES.get(
                    row["destination"], row["destination"]
                ),
                "route": " → ".join(LOCATION_NAMES.get(node, node) for node in path),
                "duration": row["duration_minutes"],
                "arrival": row["arrival_time"].replace("T", " "),
                "distance_km": row["estimated_distance_km"],
                "priority": row["priority"],
                "data_source": row["data_source"],
                "searched_at": row["searched_at"].replace("T", " "),
            }
        )
    return history


def load_analytics():
    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*), AVG(duration_minutes), AVG(estimated_distance_km)
            FROM route_history
            """
        ).fetchone()
    return {
        "journey_count": row[0],
        "average_duration": round(row[1]) if row[1] is not None else None,
        "average_distance_km": row[2],
    }


def make_roads_for_ui(conditions):
    roads = []
    for first, second, base_minutes in get_base_roads():
        condition = conditions[road_key(first, second)]
        roads.append(
            {
                "first": first,
                "second": second,
                "key": road_key(first, second),
                "base_minutes": base_minutes,
                "closed": condition["closed"],
                "added_minutes": condition["added_minutes"],
                "effective_minutes": base_minutes + condition["added_minutes"],
            }
        )
    return roads


def graph_for_ui(roads):
    return {
        "nodes": [
            {
                "id": code,
                "name": LOCATION_NAMES[code],
                "x": coordinates[0],
                "y": coordinates[1],
            }
            for code, coordinates in NODE_POSITIONS.items()
        ],
        "edges": [
            {
                "from": road["first"],
                "to": road["second"],
                "weight": road["effective_minutes"],
                "closed": road["closed"],
            }
            for road in roads
        ],
    }


def render_page(
    source="H",
    destination="P",
    priority="Low",
    departure_value=None,
    routing_mode="demo",
    origin_text="",
    hospital_id="adarsh",
    destination_mode="hospital",
    destination_text="",
    origin_lat="",
    origin_lon="",
    result=None,
    error=None,
    notice=None,
):
    conditions = load_road_conditions()
    roads = make_roads_for_ui(conditions)
    if departure_value is None:
        departure_value = datetime.now().replace(second=0, microsecond=0).isoformat(
            timespec="minutes"
        )

    return render_template(
        "index.html",
        locations=[
            {"code": code, "name": name}
            for code, name in LOCATION_NAMES.items()
        ],
        source=source,
        destination=destination,
        routing_mode=routing_mode,
        origin_text=origin_text,
        hospital_id=hospital_id,
        destination_mode=destination_mode,
        destination_text=destination_text,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        hospitals=get_hospitals(),
        priority=priority,
        priorities=PRIORITIES,
        departure_value=departure_value,
        result=result,
        error=error,
        notice=notice,
        roads=roads,
        graph=graph_for_ui(roads),
        history=load_history(),
        analytics=load_analytics(),
    )


def _trip_token_from_request():
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        return token.strip()
    return None


def _trip_api_error(message, status):
    return jsonify({"error": message}), status


@app.after_request
def protect_trip_responses(response):
    if request.path.startswith(("/api/trips/", "/trips/")):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Referrer-Policy"] = (
            "no-referrer"
            if request.path.startswith("/api/trips/")
            else "strict-origin-when-cross-origin"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/dispatch", methods=["GET", "POST"])
def dispatch_home():
    if request.method == "GET":
        return render_template("dispatch.html", priorities=PRIORITIES)

    ambulance_id = request.form.get("ambulance_id", "").strip()
    origin_text = request.form.get("origin", "").strip()
    destination_text = request.form.get("destination", "").strip()
    destination_lat = request.form.get("destination_lat", "").strip()
    destination_lon = request.form.get("destination_lon", "").strip()
    priority = request.form.get("priority", "")
    error = None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", ambulance_id):
        error = "Enter an ambulance ID using up to 32 letters, numbers, hyphens, or underscores."
    elif not origin_text or len(origin_text) > 256:
        error = "Enter a starting address up to 256 characters."
    elif not destination_text or len(destination_text) > 256:
        error = "Enter a destination up to 256 characters."
    elif priority not in PRIORITIES:
        error = "Choose a valid emergency priority."
    if error:
        return render_template(
            "dispatch.html",
            priorities=PRIORITIES,
            error=error,
            ambulance_id=ambulance_id,
            origin=origin_text,
            destination=destination_text,
            priority=priority,
        ), 400

    try:
        origin = geocode_location(origin_text, DATABASE_PATH)
        if destination_lat or destination_lon:
            if not destination_lat or not destination_lon:
                raise ValueError("Both selected hospital coordinates are required.")
            destination = location_from_coordinates(
                destination_lat, destination_lon
            )
            destination["display_name"] = destination_text
        else:
            destination = geocode_location(destination_text, DATABASE_PATH)
        raw_routes = get_osrm_routes(origin, destination)
        routes = make_route_options(raw_routes, origin, destination)
        selected_route = min(routes, key=lambda route: route["duration_seconds"])
        trip_id, driver_token, viewer_token = create_trip(
            DATABASE_PATH,
            ambulance_id,
            origin["display_name"],
            origin["lat"],
            origin["lon"],
            destination["display_name"],
            destination["lat"],
            destination["lon"],
            priority,
            selected_route["distance_km"] * 1000,
            selected_route["duration_seconds"],
            json.dumps(selected_route["geometry"]),
        )
    except RoutingServiceError as exc:
        return render_template(
            "dispatch.html",
            priorities=PRIORITIES,
            error=exc.message,
            ambulance_id=ambulance_id,
            origin=origin_text,
            destination=destination_text,
            priority=priority,
        ), exc.status_code
    except ValueError as exc:
        return render_template(
            "dispatch.html",
            priorities=PRIORITIES,
            error=str(exc),
            ambulance_id=ambulance_id,
            origin=origin_text,
            destination=destination_text,
            priority=priority,
        ), 400

    base_url = os.environ.get("PUBLIC_BASE_URL", request.host_url).rstrip("/")
    driver_url = (
        f"{base_url}{url_for('driver_trip', trip_id=trip_id)}#token={driver_token}"
    )
    viewer_url = (
        f"{base_url}{url_for('dispatcher_trip', trip_id=trip_id)}#token={viewer_token}"
    )
    return render_template(
        "dispatch.html",
        priorities=PRIORITIES,
        created_trip={
            "id": trip_id,
            "ambulance_id": ambulance_id,
            "priority": priority,
            "distance_km": selected_route["distance_km"],
            "duration_minutes": selected_route["duration"],
            "driver_url": driver_url,
            "viewer_url": viewer_url,
        },
    )


@app.get("/trips/<trip_id>/driver")
def driver_trip(trip_id):
    if get_trip(DATABASE_PATH, trip_id) is None:
        return "Trip not found.", 404
    return render_template("driver.html", trip_id=trip_id)


@app.get("/trips/<trip_id>/dispatcher")
def dispatcher_trip(trip_id):
    if get_trip(DATABASE_PATH, trip_id) is None:
        return "Trip not found.", 404
    return render_template("dispatcher.html", trip_id=trip_id)


@app.get("/api/trips/<trip_id>")
def trip_snapshot(trip_id):
    role = authorize_trip(
        DATABASE_PATH, trip_id, _trip_token_from_request()
    )
    if role is None:
        return _trip_api_error("A valid trip access token is required.", 401)
    purge_stale_locations(DATABASE_PATH)
    trip = get_trip(DATABASE_PATH, trip_id)
    return jsonify(public_trip(trip))


@app.get("/api/trips/<trip_id>/summary")
def trip_summary(trip_id):
    if authorize_trip(
        DATABASE_PATH, trip_id, _trip_token_from_request(), role="viewer"
    ) is None:
        return _trip_api_error("A dispatcher access token is required.", 401)
    trip = get_trip(DATABASE_PATH, trip_id)
    return jsonify(
        {
            "id": trip["id"],
            "status": trip["status"],
            "started_at": trip["started_at"],
            "completed_at": trip["completed_at"],
            "location_update_count": trip["location_update_count"],
            "actual_distance_m": round(trip["actual_distance_m"]),
            "distance_source": "straight-line distance between accepted GPS updates",
            "events": get_trip_events(DATABASE_PATH, trip_id),
        }
    )


@app.post("/api/trips/<trip_id>/location")
def trip_location_update(trip_id):
    if authorize_trip(
        DATABASE_PATH, trip_id, _trip_token_from_request(), role="driver"
    ) is None:
        return _trip_api_error("A driver access token is required.", 401)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _trip_api_error("Send a JSON GPS location update.", 400)
    try:
        trip = update_trip_location(
            DATABASE_PATH,
            trip_id,
            payload.get("latitude"),
            payload.get("longitude"),
            payload.get("accuracy"),
            payload.get("timestamp"),
        )
    except ValueError as exc:
        return _trip_api_error(str(exc), 422)
    if trip is None:
        return _trip_api_error("Trip not found.", 404)
    update = public_trip(trip)
    socketio.emit("trip_update", update, to=f"trip:{trip_id}")
    return jsonify(update)


@app.post("/api/trips/<trip_id>/action")
def trip_action(trip_id):
    if authorize_trip(
        DATABASE_PATH, trip_id, _trip_token_from_request(), role="driver"
    ) is None:
        return _trip_api_error("A driver access token is required.", 401)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _trip_api_error("Send a JSON trip action.", 400)
    try:
        trip = change_trip_status(
            DATABASE_PATH, trip_id, payload.get("action")
        )
    except ValueError as exc:
        return _trip_api_error(str(exc), 409)
    if trip is None:
        return _trip_api_error("Trip not found.", 404)
    update = public_trip(trip)
    socketio.emit("trip_update", update, to=f"trip:{trip_id}")
    return jsonify(update)


@app.get("/api/hospitals/search")
def hospital_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2 or len(query) > 120:
        return _trip_api_error(
            "Enter a hospital name or area from 2 to 120 characters.", 400
        )
    try:
        results = search_hospitals(query, DATABASE_PATH)
    except RoutingServiceError as exc:
        return _trip_api_error(exc.message, exc.status_code)
    return jsonify({"results": results})


@socketio.on("subscribe_trip")
def subscribe_trip(payload):
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Trip access token is required."}
    trip_id = payload.get("trip_id")
    token = payload.get("token")
    if not isinstance(trip_id, str) or authorize_trip(
        DATABASE_PATH, trip_id, token, role="viewer"
    ) is None:
        return {"ok": False, "error": "Valid dispatcher access is required."}
    trip = get_trip(DATABASE_PATH, trip_id)
    join_room(f"trip:{trip_id}")
    return {"ok": True, "trip": public_trip(trip)}


def routes_for_mode(
    source,
    destination,
    routing_mode,
    origin_text,
    hospital_id,
    destination_mode,
    destination_text,
    origin_lat,
    origin_lon,
):
    if routing_mode == "demo":
        graph = get_effective_graph(load_road_conditions())
        paths = k_shortest_routes(graph, source, destination, limit=3)
        if not paths:
            raise ValueError(
                "No route exists between these locations under the current road conditions. Restore roads or change the closures."
            )
        routes = []
        for index, (path, _) in enumerate(paths):
            route = build_route(path, graph)
            route["duration_seconds"] = route["duration"] * 60
            route["label"] = (
                "Fastest demo route"
                if index == 0
                else f"Alternative route {index}"
            )
            route["mode"] = "demo"
            route["distance_km"] = None
            route["instructions"] = []
            routes.append(route)
        return routes, "demo"

    if routing_mode != "osm":
        raise ValueError("Choose either Demo network or OpenStreetMap / OSRM routing.")
    if origin_lat or origin_lon:
        if not origin_lat or not origin_lon:
            raise ValueError("Both current-location coordinates are required.")
        origin = location_from_coordinates(origin_lat, origin_lon)
    else:
        if not origin_text or len(origin_text) > 256:
            raise ValueError("Enter a starting address up to 256 characters.")
        origin = geocode_location(origin_text, DATABASE_PATH)
    if destination_mode == "hospital":
        destination = get_hospital(hospital_id)
        if destination is None:
            raise ValueError("Choose a valid hospital from the list.")
        destination = {
            **destination,
            "display_name": f"{destination['name']}, {destination['address']}",
        }
    elif destination_mode == "custom":
        if not destination_text or len(destination_text) > 256:
            raise ValueError("Enter a destination up to 256 characters.")
        destination = geocode_location(destination_text, DATABASE_PATH)
        destination["name"] = destination["display_name"]
    else:
        raise ValueError("Choose a hospital destination or enter a custom destination.")
    api_routes = get_osrm_routes(origin, destination)
    routes = make_route_options(api_routes, origin, destination)
    for route in routes:
        route["origin"] = origin
        route["destination"] = destination
    return routes, "osm_osrm"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_page()

    action = request.form.get("action", "find")
    if action == "restore_conditions":
        restore_road_conditions()
        return render_page(notice="All roads have been restored to their original conditions.")

    if action == "update_conditions":
        conditions = {}
        for first, second, _ in get_base_roads():
            key = road_key(first, second)
            delay_text = request.form.get(f"delay_{key}", "0")
            try:
                delay = int(delay_text)
            except ValueError:
                return render_page(error="Traffic increases must be whole numbers from 0 to 10000.")
            if not 0 <= delay <= 10000:
                return render_page(error="Traffic increases must be whole numbers from 0 to 10000.")
            conditions[key] = {
                "closed": request.form.get(f"close_{key}") == "on",
                "added_minutes": delay,
            }
        save_road_conditions(conditions)
        return render_page(notice="Road conditions updated and saved.")

    if action not in {"find", "select_route"}:
        return render_page(error="Please choose a valid route planning action.")

    routing_mode = request.form.get("routing_mode", "demo")
    source = request.form.get("source", "H")
    destination = request.form.get("destination", "P")
    origin_text = request.form.get("origin_text", "").strip()
    hospital_id = request.form.get("hospital_id", "adarsh")
    destination_mode = request.form.get("destination_mode", "hospital")
    destination_text = request.form.get("destination_text", "").strip()
    origin_lat = request.form.get("origin_lat", "").strip()
    origin_lon = request.form.get("origin_lon", "").strip()
    priority = request.form.get("priority", "Low")
    departure_value = request.form.get("departure_time", "")

    if routing_mode not in {"demo", "osm"}:
        return render_page(error="Please choose a valid routing mode.")
    if routing_mode == "demo" and (
        source not in ROAD_GRAPH or destination not in ROAD_GRAPH
    ):
        return render_page(error="Please select valid locations.")
    if routing_mode == "demo" and source == destination:
        return render_page(
            source, destination, priority, departure_value, routing_mode,
            origin_text, hospital_id,
            error="Choose two different locations.",
        )
    if priority not in PRIORITIES:
        return render_page(
            source, destination, "Low", departure_value, routing_mode,
            origin_text, hospital_id,
            error="Please select a valid emergency priority.",
        )
    if routing_mode == "osm" and (
        (not origin_lat and (not origin_text or len(origin_text) > 256))
        or (origin_lat and (not origin_lon or not origin_text))
        or (
            destination_mode == "hospital"
            and get_hospital(hospital_id) is None
        )
        or (
            destination_mode == "custom"
            and (not destination_text or len(destination_text) > 256)
        )
        or destination_mode not in {"hospital", "custom"}
    ):
        return render_page(
            source, destination, priority, departure_value, routing_mode,
            origin_text, hospital_id, destination_mode, destination_text,
            origin_lat, origin_lon,
            error="Enter valid starting and destination locations, or choose a listed hospital.",
        )
    try:
        departure = datetime.fromisoformat(departure_value)
    except (TypeError, ValueError):
        return render_page(
            source, destination, priority, routing_mode=routing_mode,
            origin_text=origin_text, hospital_id=hospital_id,
            destination_mode=destination_mode,
            destination_text=destination_text,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            error="Enter a valid departure date and time.",
        )
    if departure.tzinfo is not None:
        return render_page(
            source, destination, priority, departure_value, routing_mode,
            origin_text, hospital_id, destination_mode, destination_text,
            origin_lat, origin_lon,
            error="Use a local departure time without a timezone.",
        )

    try:
        routes, data_source = routes_for_mode(
            source,
            destination,
            routing_mode,
            origin_text,
            hospital_id,
            destination_mode,
            destination_text,
            origin_lat,
            origin_lon,
        )
    except ValueError as exc:
        return render_page(
            source, destination, priority, departure_value, routing_mode,
            origin_text, hospital_id, destination_mode, destination_text,
            origin_lat, origin_lon, error=str(exc),
        )
    except RoutingServiceError as exc:
        return render_page(
            source, destination, priority, departure_value, routing_mode,
            origin_text, hospital_id, destination_mode, destination_text,
            origin_lat, origin_lon, error=exc.message,
        )

    route_index = next(
        (index for index, route in enumerate(routes) if route.get("is_selected")),
        0,
    )
    if action == "select_route":
        try:
            route_index = int(request.form.get("route_index", ""))
        except ValueError:
            route_index = -1
        if not 0 <= route_index < len(routes):
            return render_page(
                source, destination, priority, departure_value, routing_mode,
                origin_text, hospital_id, destination_mode, destination_text,
                origin_lat, origin_lon,
                error="That route is no longer available. Search again to refresh route options.",
            )

    selected_route = routes[route_index]
    selected_arrival = departure + timedelta(
        seconds=selected_route["duration_seconds"]
    )
    for route in routes:
        route["arrival"] = (
            departure + timedelta(seconds=route["duration_seconds"])
        ).strftime("%Y-%m-%d %H:%M")
        route["is_selected"] = route is selected_route
    if routing_mode == "demo":
        history_source = source
        history_destination = destination
    else:
        history_source = selected_route["origin"]["display_name"]
        history_destination = selected_route["destination"]["name"]
    add_history(
        history_source,
        history_destination,
        selected_route,
        priority,
        departure,
        selected_arrival,
        data_source,
    )
    result = {
        "routes": routes,
        "selected": selected_route,
        "priority": priority,
        "departure": departure.strftime("%Y-%m-%d %H:%M"),
        "mode": routing_mode,
    }
    return render_page(
        source, destination, priority, departure_value, routing_mode,
        origin_text, hospital_id, destination_mode, destination_text,
        origin_lat, origin_lon, result=result,
    )


initialize_database()


if __name__ == "__main__":
    def expire_stale_trip_locations():
        while True:
            purge_stale_locations(DATABASE_PATH)
            socketio.sleep(900)

    purge_stale_locations(DATABASE_PATH)
    socketio.start_background_task(expire_stale_trip_locations)
    socketio.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
        allow_unsafe_werkzeug=True,
    )

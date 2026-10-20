import hashlib
import hmac
import math
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


TRIP_STATUSES = {"planned", "tracking", "stopped", "completed"}


@contextmanager
def _database_connection(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_trip(
    database_path,
    ambulance_id,
    origin_name,
    origin_lat,
    origin_lon,
    destination_name,
    destination_lat,
    destination_lon,
    priority,
    route_distance_m,
    route_duration_s,
    route_geometry,
):
    trip_id = str(uuid.uuid4())
    driver_token = secrets.token_urlsafe(32)
    viewer_token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _database_connection(database_path) as connection:
        connection.execute(
            """
            INSERT INTO trips (
                id, ambulance_id, origin_name, origin_lat, origin_lon,
                destination_name, destination_lat, destination_lon, priority,
                status, driver_token_hash, viewer_token_hash, created_at,
                route_distance_m, route_duration_s, route_geometry
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                ambulance_id,
                origin_name,
                origin_lat,
                origin_lon,
                destination_name,
                destination_lat,
                destination_lon,
                priority,
                _token_hash(driver_token),
                _token_hash(viewer_token),
                created_at,
                route_distance_m,
                route_duration_s,
                route_geometry,
            ),
        )
        connection.execute(
            """
            INSERT INTO trip_events (trip_id, event_type, event_at)
            VALUES (?, 'created', ?)
            """,
            (trip_id, created_at),
        )
    return trip_id, driver_token, viewer_token


def get_trip(database_path, trip_id):
    with _database_connection(database_path) as connection:
        return connection.execute(
            "SELECT * FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()


def get_trip_events(database_path, trip_id):
    with _database_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT event_type, event_at
            FROM trip_events
            WHERE trip_id = ?
            ORDER BY event_at, id
            """,
            (trip_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def purge_stale_locations(database_path, older_than_seconds=86_400):
    cutoff = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - older_than_seconds,
        timezone.utc,
    ).isoformat(timespec="seconds")
    with _database_connection(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE trips
            SET last_lat = NULL, last_lon = NULL, last_accuracy_m = NULL,
                last_location_at = NULL
            WHERE last_location_at IS NOT NULL AND last_location_at < ?
            """,
            (cutoff,),
        )
        return cursor.rowcount


def authorize_trip(database_path, trip_id, token, role=None):
    if not isinstance(token, str) or len(token) < 32 or len(token) > 128:
        return None
    trip = get_trip(database_path, trip_id)
    if trip is None:
        return None
    token_digest = _token_hash(token)
    if role in (None, "driver") and hmac.compare_digest(
        token_digest, trip["driver_token_hash"]
    ):
        return "driver"
    if role in (None, "viewer") and hmac.compare_digest(
        token_digest, trip["viewer_token_hash"]
    ):
        return "viewer"
    return None


def public_trip(trip):
    if trip is None:
        return None
    return {
        "id": trip["id"],
        "ambulance_id": trip["ambulance_id"],
        "origin": {
            "name": trip["origin_name"],
            "lat": trip["origin_lat"],
            "lon": trip["origin_lon"],
        },
        "destination": {
            "name": trip["destination_name"],
            "lat": trip["destination_lat"],
            "lon": trip["destination_lon"],
        },
        "priority": trip["priority"],
        "status": trip["status"],
        "created_at": trip["created_at"],
        "started_at": trip["started_at"],
        "completed_at": trip["completed_at"],
        "last_lat": trip["last_lat"],
        "last_lon": trip["last_lon"],
        "last_accuracy_m": trip["last_accuracy_m"],
        "last_location_at": trip["last_location_at"],
        "actual_distance_m": trip["actual_distance_m"],
        "location_update_count": trip["location_update_count"],
        "planned_distance_m": trip["route_distance_m"],
        "planned_duration_s": trip["route_duration_s"],
        "route_geometry": trip["route_geometry"],
    }


def change_trip_status(database_path, trip_id, action):
    status_by_action = {
        "start": (
            "tracking",
            "started_at = COALESCE(started_at, ?)",
            "tracking_started",
        ),
        "stop": ("stopped", "started_at = started_at", "tracking_stopped"),
        "complete": ("completed", "completed_at = ?", "completed"),
    }
    if action not in status_by_action:
        raise ValueError("Choose Start Trip, Stop Tracking, or Complete Trip.")
    next_status, timestamp_column, event_type = status_by_action[action]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _database_connection(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()
        if row is None:
            return None
        current_status = row[0]
        allowed = {
            "start": {"planned", "stopped"},
            "stop": {"tracking"},
            "complete": {"planned", "tracking", "stopped"},
        }
        if current_status not in allowed[action]:
            raise ValueError(f"Cannot {action} a {current_status} trip.")
        assignments = f"status = ?, {timestamp_column}"
        values = [next_status]
        if action in {"start", "complete"}:
            values.append(now)
        if action in {"stop", "complete"}:
            assignments += ", last_lat = NULL, last_lon = NULL, last_accuracy_m = NULL, last_location_at = NULL"
        values.append(trip_id)
        connection.execute(
            f"UPDATE trips SET {assignments} WHERE id = ?", values
        )
        connection.execute(
            """
            INSERT INTO trip_events (trip_id, event_type, event_at)
            VALUES (?, ?, ?)
            """,
            (trip_id, event_type, now),
        )
    return get_trip(database_path, trip_id)


def _haversine_meters(first_lat, first_lon, second_lat, second_lon):
    earth_radius_m = 6_371_000
    lat1, lat2 = math.radians(first_lat), math.radians(second_lat)
    lat_delta = math.radians(second_lat - first_lat)
    lon_delta = math.radians(second_lon - first_lon)
    value = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(lon_delta / 2) ** 2
    )
    return 2 * earth_radius_m * math.asin(math.sqrt(value))


def update_trip_location(database_path, trip_id, latitude, longitude, accuracy, timestamp_ms):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
        accuracy = float(accuracy)
        timestamp_ms = float(timestamp_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError("Location must include numeric coordinates, accuracy, and timestamp.") from exc
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not math.isfinite(accuracy)
        or not math.isfinite(timestamp_ms)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
        or not 0 <= accuracy <= 10_000
    ):
        raise ValueError("GPS coordinates or accuracy are outside valid ranges.")
    timestamp_s = timestamp_ms / 1000
    now_s = datetime.now(timezone.utc).timestamp()
    if abs(now_s - timestamp_s) > 300:
        raise ValueError("GPS timestamp is stale or too far in the future. Check device time and retry.")
    timestamp = datetime.fromtimestamp(timestamp_s, timezone.utc).isoformat(
        timespec="milliseconds"
    )
    with _database_connection(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, last_lat, last_lon, last_location_at, actual_distance_m FROM trips WHERE id = ?",
            (trip_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "tracking":
            raise ValueError("Start trip tracking before sending GPS updates.")
        distance_increment = 0.0
        if row["last_location_at"] is not None:
            previous_timestamp = datetime.fromisoformat(
                row["last_location_at"]
            ).timestamp()
            if timestamp_s <= previous_timestamp:
                raise ValueError("GPS update is older than the last accepted location.")
            distance_increment = _haversine_meters(
                row["last_lat"], row["last_lon"], latitude, longitude
            )
            elapsed_s = timestamp_s - previous_timestamp
            if distance_increment / elapsed_s > 100:
                raise ValueError("GPS update implies an implausible vehicle speed.")
        connection.execute(
            """
            UPDATE trips SET last_lat = ?, last_lon = ?, last_accuracy_m = ?,
                last_location_at = ?, actual_distance_m = ?,
                location_update_count = location_update_count + 1
            WHERE id = ?
            """,
            (
                latitude,
                longitude,
                accuracy,
                timestamp,
                row["actual_distance_m"] + distance_increment,
                trip_id,
            ),
        )
    return get_trip(database_path, trip_id)

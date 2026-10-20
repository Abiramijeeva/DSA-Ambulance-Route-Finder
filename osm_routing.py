import math
import os
import sqlite3
import time
from contextlib import closing

import requests

from dijkstra import dijkstra


class RoutingServiceError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


HOSPITALS = (
    {
        "id": "shreya",
        "name": "Shreya Hospital",
        "address": "2nd Main Road, Kengeri",
        "lat": 12.9215104,
        "lon": 77.4832503,
    },
    {
        "id": "adarsh",
        "name": "Adarsh Hospital",
        "address": "Kengeri Satellite Town",
        "lat": 12.9208444,
        "lon": 77.4847891,
    },
    {
        "id": "annapoorna",
        "name": "Sri Annapoorneshwari Hospital",
        "address": "Kengeri Satellite Town",
        "lat": 12.9255704,
        "lon": 77.4857756,
    },
    {
        "id": "sree-ranga",
        "name": "Sree Ranga Hospital",
        "address": "Kengeri Main Road, Nagadevanahalli",
        "lat": 12.9358669,
        "lon": 77.4927128,
    },
    {
        "id": "medsol",
        "name": "MEDSOL Hospital",
        "address": "Dubasi Palya, Kengeri",
        "lat": 12.9309944,
        "lon": 77.4929837,
    },
    {
        "id": "kengeri-government",
        "name": "Kengeri Upanagara Government Hospital",
        "address": "Kengal Hanumanthaiah West",
        "lat": 12.9156896,
        "lon": 77.4808065,
    },
    {
        "id": "medical-centre",
        "name": "Medical Centre",
        "address": "RV University Road, Pattanagere",
        "lat": 12.9246164,
        "lon": 77.5006520,
    },
    {
        "id": "vijaya",
        "name": "Vijaya Hospital",
        "address": "Sonnenahalli, Nagadevanahalli",
        "lat": 12.9418827,
        "lon": 77.4837600,
    },
)

def get_hospitals():
    return [hospital.copy() for hospital in HOSPITALS]


def get_hospital(hospital_id):
    return next((place for place in HOSPITALS if place["id"] == hospital_id), None)


def _geocode_from_cache(address, database_path):
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            row = connection.execute(
                """
                SELECT latitude, longitude, display_name
                FROM geocode_cache
                WHERE normalized_address = ?
                """,
                (" ".join(address.casefold().split()),),
            ).fetchone()
    if row is None:
        return None
    return {"lat": row[0], "lon": row[1], "display_name": row[2]}


def _save_geocode(address, location, database_path):
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO geocode_cache
                    (normalized_address, latitude, longitude, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (
                    " ".join(address.casefold().split()),
                    location["lat"],
                    location["lon"],
                    location["display_name"],
                ),
            )


def _wait_for_geocoder_slot(database_path):
    now = time.time()
    with closing(sqlite3.connect(database_path, timeout=15)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT next_request_at
            FROM geocode_request_state
            WHERE service_name = 'nominatim'
            """
        ).fetchone()
        request_at = max(now, row[0] if row is not None else now)
        connection.execute(
            """
            INSERT OR REPLACE INTO geocode_request_state
                (service_name, next_request_at)
            VALUES ('nominatim', ?)
            """,
            (request_at + 1.05,),
        )
        connection.commit()
    delay = request_at - now
    if delay > 0:
        time.sleep(delay)


def geocode_location(address, database_path):
    cached = _geocode_from_cache(address, database_path)
    if cached is not None:
        return cached

    base_url = os.environ.get(
        "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
    ).rstrip("/")
    _wait_for_geocoder_slot(database_path)
    try:
        response = requests.get(
            f"{base_url}/search",
            params={
                "q": address,
                "format": "jsonv2",
                "limit": 1,
            },
            headers={
                "User-Agent": (
                    "AmbulanceRouteFinder/2.0 "
                    "(educational Flask route-planning project)"
                )
            },
            timeout=(3.05, 10),
        )
    except requests.Timeout as exc:
        raise RoutingServiceError(
            "OpenStreetMap address lookup timed out. Try again shortly.", 504
        ) from exc
    except requests.RequestException as exc:
        raise RoutingServiceError(
            "OpenStreetMap address lookup is temporarily unavailable.", 503
        ) from exc

    if response.status_code == 429:
        raise RoutingServiceError(
            "OpenStreetMap address lookup is rate-limited. Wait a moment and try again.",
            429,
        )
    if response.status_code >= 500:
        raise RoutingServiceError(
            "OpenStreetMap address lookup is temporarily unavailable.",
            503,
        )
    if response.status_code >= 400:
        raise RoutingServiceError(
            "OpenStreetMap rejected the address lookup request.", 502
        )
    try:
        matches = response.json()
    except ValueError as exc:
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid address response.", 502
        ) from exc
    if not isinstance(matches, list) or not matches:
        raise RoutingServiceError(
            "Address not found. Enter a more complete address, city, landmark, or place name.",
            400,
        )
    match = matches[0]
    if not isinstance(match, dict):
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid location.", 502
        )
    try:
        latitude = float(match["lat"])
        longitude = float(match["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid location.", 502
        ) from exc
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid location.", 502
        )
    display_name = match.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = address
    location = {
        "lat": latitude,
        "lon": longitude,
        "display_name": display_name[:512],
    }
    _save_geocode(address, location, database_path)
    return location


def search_hospitals(query, database_path):
    base_url = os.environ.get(
        "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
    ).rstrip("/")
    _wait_for_geocoder_slot(database_path)
    try:
        response = requests.get(
            f"{base_url}/search",
            params={
                "q": f"hospital {query}",
                "format": "jsonv2",
                "limit": 10,
                "addressdetails": 1,
                "extratags": 1,
                "namedetails": 1,
            },
            headers={
                "User-Agent": (
                    "AmbulanceRouteFinder/2.0 "
                    "(educational Flask route-planning project)"
                )
            },
            timeout=(3.05, 10),
        )
    except requests.Timeout as exc:
        raise RoutingServiceError(
            "OpenStreetMap hospital search timed out. Try again shortly.", 504
        ) from exc
    except requests.RequestException as exc:
        raise RoutingServiceError(
            "OpenStreetMap hospital search is temporarily unavailable.", 503
        ) from exc

    if response.status_code == 429:
        raise RoutingServiceError(
            "OpenStreetMap hospital search is rate-limited. Wait a moment and try again.",
            429,
        )
    if response.status_code >= 500:
        raise RoutingServiceError(
            "OpenStreetMap hospital search is temporarily unavailable.", 503
        )
    if response.status_code >= 400:
        raise RoutingServiceError(
            "OpenStreetMap rejected the hospital search request.", 502
        )
    try:
        matches = response.json()
    except ValueError as exc:
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid hospital response.", 502
        ) from exc
    if not isinstance(matches, list):
        raise RoutingServiceError(
            "OpenStreetMap returned an invalid hospital response.", 502
        )

    results = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        category = match.get("type") or match.get("category")
        tags = match.get("extratags")
        tags = tags if isinstance(tags, dict) else {}
        if category != "hospital" and tags.get("healthcare") != "hospital":
            continue
        try:
            latitude = float(match["lat"])
            longitude = float(match["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            continue
        names = match.get("namedetails")
        names = names if isinstance(names, dict) else {}
        address = match.get("address")
        address = address if isinstance(address, dict) else {}
        name = names.get("name") or match.get("name") or "Unnamed hospital"
        display_name = match.get("display_name", "Address unavailable")
        photo = _hospital_photo(name, display_name)
        item = {
            "name": name,
            "display_name": display_name,
            "lat": latitude,
            "lon": longitude,
            "public_details": {
                key: tags[key]
                for key in ("phone", "website", "emergency")
                if isinstance(tags.get(key), str)
            },
            "osm_url": (
                f"https://www.openstreetmap.org/{match['osm_type']}/{match['osm_id']}"
                if match.get("osm_type") in {"node", "way", "relation"}
                and isinstance(match.get("osm_id"), (int, str))
                else None
            ),
        }
        if photo is not None:
            item["photo"] = photo
        results.append(item)
    return results


def _hospital_photo(name, display_name):
    place = f"{name} {display_name}".casefold()
    if "apollo" in place and "bannerghatta" in place and "bengaluru" in place:
        return {
            "url": "/static/images/apollo-hospitals-bengaluru.jpg",
            "source_url": (
                "https://commons.wikimedia.org/wiki/"
                "File:Apollo_Hospitals_Bengaluru.jpg"
            ),
            "credit": "Keerthishivanand · CC BY-SA 4.0",
        }
    return None


def location_from_coordinates(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise RoutingServiceError("Current-location coordinates are invalid.", 400) from exc
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise RoutingServiceError("Current-location coordinates are invalid.", 400)
    return {
        "lat": latitude,
        "lon": longitude,
        "display_name": "Current location",
    }


def get_osrm_routes(origin, destination):
    base_url = os.environ.get(
        "OSRM_BASE_URL", "https://router.project-osrm.org"
    ).rstrip("/")
    coordinates = (
        f"{origin['lon']},{origin['lat']};"
        f"{destination['lon']},{destination['lat']}"
    )
    try:
        response = requests.get(
            f"{base_url}/route/v1/driving/{coordinates}",
            params={
                "alternatives": "3",
                "overview": "full",
                "geometries": "geojson",
                "steps": "true",
            },
            headers={"User-Agent": "AmbulanceRouteFinder/2.0"},
            timeout=(3.05, 15),
        )
    except requests.Timeout as exc:
        raise RoutingServiceError(
            "OSRM route request timed out. Try again shortly.", 504
        ) from exc
    except requests.RequestException as exc:
        raise RoutingServiceError(
            "OSRM routing is temporarily unavailable.", 503
        ) from exc

    if response.status_code == 429:
        raise RoutingServiceError(
            "OSRM is rate-limiting route requests. Wait a moment and try again.",
            429,
        )
    if response.status_code >= 500:
        raise RoutingServiceError("OSRM routing is temporarily unavailable.", 503)
    if response.status_code >= 400:
        raise RoutingServiceError("OSRM rejected the route request.", 502)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RoutingServiceError("OSRM returned an invalid route response.", 502) from exc
    if not isinstance(payload, dict):
        raise RoutingServiceError("OSRM returned an invalid route response.", 502)
    if payload.get("code") == "NoRoute":
        raise RoutingServiceError(
            "OSRM could not find a drivable route between these locations.",
            400,
        )
    if payload.get("code") == "NoSegment":
        raise RoutingServiceError(
            "OSRM could not match one of these coordinates to a drivable road. Choose a more specific address or another location.",
            400,
        )
    routes = payload.get("routes")
    if payload.get("code") != "Ok" or not isinstance(routes, list) or not routes:
        raise RoutingServiceError("OSRM returned no usable driving routes.", 502)
    return routes


def make_route_options(api_routes, origin, destination):
    start_node = "OSRM_START"
    end_node = "OSRM_END"
    route_graph = {start_node: [], end_node: []}
    routes_by_node = {}
    seen_geometries = set()

    for index, api_route in enumerate(api_routes):
        if not isinstance(api_route, dict):
            continue
        try:
            duration_seconds = float(api_route["duration"])
            distance_meters = float(api_route["distance"])
            coordinates = api_route["geometry"]["coordinates"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RoutingServiceError(
                "OSRM returned a route with incomplete travel data.", 502
            ) from exc
        if (
            not math.isfinite(duration_seconds)
            or not math.isfinite(distance_meters)
            or duration_seconds < 0
            or distance_meters < 0
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            raise RoutingServiceError(
                "OSRM returned a route with invalid travel data.", 502
            )
        node = f"OSRM_ROUTE_{index}"
        route_graph[node] = []
        route_graph[start_node].append((node, duration_seconds))
        route_graph[node].append((end_node, 0))
        normalized_coordinates = []
        for point in coordinates:
            if not isinstance(point, list) or len(point) != 2:
                raise RoutingServiceError(
                    "OSRM returned invalid route geometry.", 502
                )
            try:
                longitude, latitude = map(float, point)
            except (TypeError, ValueError) as exc:
                raise RoutingServiceError(
                    "OSRM returned invalid route geometry.", 502
                ) from exc
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise RoutingServiceError(
                    "OSRM returned invalid route geometry.", 502
                )
            normalized_coordinates.append([longitude, latitude])
        geometry_signature = tuple(
            (round(longitude, 5), round(latitude, 5))
            for longitude, latitude in normalized_coordinates
        )
        if geometry_signature in seen_geometries:
            continue
        seen_geometries.add(geometry_signature)

        routes_by_node[node] = {
            "duration_seconds": duration_seconds,
            "duration": math.ceil(duration_seconds / 60),
            "distance_km": distance_meters / 1000,
            "path": [
                origin["display_name"],
                destination.get("name", destination["display_name"]),
            ],
            "path_names": [
                origin["display_name"],
                destination.get("name", destination["display_name"]),
            ],
            "history_path": [
                origin["display_name"],
                destination.get("name", destination["display_name"]),
            ],
            "roads": [],
            "instructions": [],
            "geometry": normalized_coordinates,
            "label": "OSRM road route",
            "mode": "osm",
        }
        legs = api_route.get("legs", [])
        if not isinstance(legs, list) or any(
            not isinstance(leg, dict) for leg in legs
        ):
            raise RoutingServiceError("OSRM returned invalid route steps.", 502)
        for leg in legs:
            steps = leg.get("steps", [])
            if not isinstance(steps, list) or any(
                not isinstance(step, dict) for step in steps
            ):
                raise RoutingServiceError("OSRM returned invalid route steps.", 502)
            for step in steps:
                try:
                    seconds = float(step.get("duration", 0))
                    distance = float(step.get("distance", 0))
                except (TypeError, ValueError) as exc:
                    raise RoutingServiceError(
                        "OSRM returned invalid route-step data.", 502
                    ) from exc
                name = step.get("name")
                if not math.isfinite(seconds) or not math.isfinite(distance):
                    raise RoutingServiceError(
                        "OSRM returned invalid route-step data.", 502
                    )
                if seconds < 0 or distance < 0:
                    raise RoutingServiceError(
                        "OSRM returned invalid route-step data.", 502
                    )
                instruction = _maneuver_instruction(step)
                if instruction:
                    routes_by_node[node]["instructions"].append(instruction)
                routes_by_node[node]["roads"].append(
                    {
                        "from_name": name.strip() if isinstance(name, str) and name.strip() else "Unnamed road segment",
                        "to_name": f"{distance / 1000:.1f} km segment",
                        "minutes": math.ceil(seconds / 60),
                    }
                )

    if not routes_by_node:
        raise RoutingServiceError("OSRM returned no usable driving routes.", 502)
    path, _ = dijkstra(route_graph, start_node, end_node)
    if path is None or len(path) < 3:
        raise RoutingServiceError("OSRM routes could not be compared.", 502)
    selected_node = path[1]
    sorted_nodes = sorted(
        routes_by_node,
        key=lambda node: routes_by_node[node]["duration_seconds"],
    )[:3]
    options = []
    for index, node in enumerate(sorted_nodes):
        route = routes_by_node[node]
        route["label"] = "Recommended road route" if index == 0 else f"Alternative {index}"
        route["is_selected"] = node == selected_node
        options.append(route)
    return options


def _maneuver_instruction(step):
    maneuver = step.get("maneuver")
    if not isinstance(maneuver, dict):
        return None

    maneuver_type = maneuver.get("type")
    modifier = maneuver.get("modifier")
    supported_types = {
        "depart": "Depart",
        "arrive": "Arrive at your destination",
        "turn": "Turn",
        "new name": "Continue",
        "continue": "Continue",
        "merge": "Merge",
        "on ramp": "Take the ramp",
        "off ramp": "Take the exit ramp",
        "fork": "Take the fork",
        "end of road": "At the end of the road, turn",
        "roundabout": "Enter the roundabout",
        "rotary": "Enter the rotary",
        "exit roundabout": "Leave the roundabout",
        "use lane": "Use the indicated lane",
    }
    instruction = supported_types.get(maneuver_type)
    if instruction is None:
        return None

    if isinstance(modifier, str) and modifier.strip() and maneuver_type != "arrive":
        instruction = f"{instruction} {modifier.strip()}"
    name = step.get("name")
    if (
        maneuver_type not in {"arrive", "depart"}
        and isinstance(name, str)
        and name.strip()
    ):
        instruction = f"{instruction} onto {name.strip()}"
    exit_number = maneuver.get("exit")
    if maneuver_type in {"roundabout", "rotary", "exit roundabout"}:
        if isinstance(exit_number, (int, str)) and str(exit_number).strip():
            instruction = f"{instruction}, exit {exit_number}"
    return instruction

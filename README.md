# Ambulance Shortest Route Finder

An educational Flask application for comparing ambulance routes with Dijkstra's
algorithm and OpenStreetMap road data. Includes an interactive Leaflet map and
a prototype for permission-based live trip tracking.

> **Prototype only:** This project is not a certified emergency dispatch
> system. It does not provide live traffic, verify ambulance identity, or
> report hospital capacity. Do not use it to handle a real emergency.

## Features

- **Dijkstra demo:** Explore a six-location weighted road graph, compare up to
  three routes, and simulate road closures or delays.
- **OSM / OSRM route planner:** Search worldwide addresses, use browser
  geolocation, compare available mapped driving routes, and view distance,
  estimated duration, and ETA.
- **Interactive maps:** Leaflet maps display routes and markers over standard
  OpenStreetMap tiles.
- **Hospital search:** Search public OpenStreetMap hospital listings and use a
  result as a destination. The included Kengeri-area hospital list is a local
  snapshot, not a global directory.
- **Trip history and analytics:** Save route searches and view journey
  summaries.
- **Live trip prototype:** Create private driver and dispatcher links. The
  driver can explicitly share browser GPS with the authorized dispatcher;
  Socket.IO updates fall back to periodic polling.
- **Voice directions:** Read OSRM maneuvers aloud when route data and browser
  speech support are available.

## Requirements

- Python 3
- Internet access for the public geocoding, routing, and map services
- A modern web browser

No map API key is required.

## Run on Windows

Open PowerShell in the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. Keep PowerShell open while using the application;
press **Ctrl+C** to stop the server.

## Run on macOS or Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Then open <http://127.0.0.1:5000>.

## Use the application

1. Choose **Demo network · simulated** to compare Dijkstra routes and adjust
   sample-road conditions.
2. Choose **OpenStreetMap + OSRM · road estimate** to search mapped addresses
   and compare available driving routes.
3. Open `/dispatch` to create a trip and generate separate private driver and
   dispatcher links. Share them only with their intended recipients.
4. The driver must open the private driver link, grant browser location
   permission, and press **Start Trip** before GPS is shared.

The public OSRM service provides estimated routes, not current traffic. Browser
geolocation generally requires HTTPS except on localhost.

## Map and public-service usage

The interactive maps use the standard OpenStreetMap tile service and display
OpenStreetMap attribution. Follow the
[OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/):
the application requests tiles as maps are viewed and navigated; do not
prefetch or bulk-download them. The public tile service is best-effort and is
not intended for high-volume production deployments. If your usage or
reliability needs exceed its capacity, use a compliant tile provider or
self-hosted service.

Address search uses public
[Nominatim](https://operations.osmfoundation.org/policies/nominatim/) and route
estimates use the public [OSRM demo service](https://project-osrm.org/).
These community/demo services have usage policies and availability limits.
Review their current policies before deployment.

## Configuration

The app uses `instance/routes.db` by default. To use a different database:

```powershell
$env:DATABASE_PATH = "C:\path\to\routes.db"
```

```bash
export DATABASE_PATH="/path/to/routes.db"
```

Compatible Nominatim and OSRM service URLs can also be set with
`NOMINATIM_BASE_URL` and `OSRM_BASE_URL`. See [README.txt](README.txt) for
additional configuration, usage, privacy, and deployment details.

## Tests

Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS/Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Privacy and limitations

Trip links are bearer links: anyone who obtains one has that link's
role-specific access. SQLite stores token hashes. During tracking, only the
latest accepted position and aggregate distance/update count are retained;
exact last coordinates are cleared when tracking stops or completes. Route
history and trip data are stored locally in SQLite.

This prototype uses one SQLite database and one Flask-SocketIO process. Public
deployment requires HTTPS, a production host configured for Flask-SocketIO,
persistent storage, and operational monitoring. Do not expose Flask's
development server directly to the public internet.

## Image credits

- "Ambulance in India" by Oleg Yunakov,
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/):
  [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ambulance_in_India.jpg)
- Apollo Hospitals Bengaluru photo by Keerthishivanand,
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/):
  [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Apollo_Hospitals_Bengaluru.jpg)
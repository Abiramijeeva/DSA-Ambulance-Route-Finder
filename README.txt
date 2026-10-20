AMBULANCE SHORTEST ROUTE FINDER

This educational Flask project provides a route planner and a separate live-trip prototype:
- Dijkstra demo: a six-location weighted sample graph with persistent road
  closure and delay simulation.
- OpenStreetMap / OSRM: worldwide text address search, browser geolocation,
  up to three distinct mapped driving routes where available, an interactive
  Leaflet map, distance, duration, and ETA. Voice directions are spoken only
  when OSRM returns maneuver data and the browser supports speech synthesis.
- Live trip prototype: create an OSRM-planned trip, issue separate private
  driver and dispatcher links, and share permission-based browser GPS updates
  with the authorized dispatcher through Flask-SocketIO and polling fallback.

The route planner offers a list of sample hospitals around Kengeri, Bengaluru,
or a custom destination field that accepts any address, city, landmark, or
hospital supported by OpenStreetMap. A custom destination can be used for
hospitals anywhere. The Kengeri list is a local snapshot and is not a worldwide
hospital directory.

OSRM calculates estimated driving routes from its available mapped road data.
It does not provide live traffic conditions or emergency dispatch services.
The optional GPS tracking feature is reported by a consenting browser device,
not OSRM. Public routing/geocoding/map services are best-effort; global
coverage and route alternatives are not
guaranteed. Do not use this prototype for a real emergency.

No Google API key, Google billing account, or payment details are needed.
Worldwide address search uses public OpenStreetMap Nominatim; route requests
use the public OSRM demo server; the map uses Leaflet and the standard
OpenStreetMap tile service. Internet access is required for these services
and for the map library.

Images and attribution
The home page ambulance photograph is "Ambulance in India" by Oleg Yunakov,
from Wikimedia Commons, licensed CC BY-SA 4.0:
https://commons.wikimedia.org/wiki/File:Ambulance_in_India.jpg

Hospital search displays a photo only for the verified Apollo Hospitals
location on Bannerghatta Road in Bengaluru. The locally stored Apollo
photograph is by Keerthishivanand, licensed CC BY-SA 4.0:
https://commons.wikimedia.org/wiki/File:Apollo_Hospitals_Bengaluru.jpg
Listings without a verified, associated photograph do not show a substitute.

Installation and running (Windows PowerShell)
1. Open PowerShell in the project folder.
2. Create a virtual environment:
     py -m venv .venv
3. Install dependencies without activating it. This works when PowerShell
   script execution is restricted:
     .\.venv\Scripts\python.exe -m pip install -r requirements.txt
4. Run the app:
     .\.venv\Scripts\python.exe app.py
5. Open http://127.0.0.1:5000 in a browser.
   The SQLite file defaults to `instance/routes.db`. To use a different
   persistent location, set `DATABASE_PATH` before starting the app:
     $env:DATABASE_PATH = "C:\path\to\routes.db"
   On macOS/Linux:
     export DATABASE_PATH="/path/to/routes.db"

macOS/Linux
1. In the project folder:
     python3 -m venv .venv
     .venv/bin/python -m pip install -r requirements.txt
2. Run:
     .venv/bin/python app.py
3. Open http://127.0.0.1:5000.

The service URLs can be changed through environment variables if you operate
compatible services:
  Windows PowerShell:
     $env:NOMINATIM_BASE_URL = "https://your-nominatim-host"
     $env:OSRM_BASE_URL = "https://your-osrm-host"
  macOS/Linux:
     export NOMINATIM_BASE_URL="https://your-nominatim-host"
     export OSRM_BASE_URL="https://your-osrm-host"
Defaults are https://nominatim.openstreetmap.org and
https://router.project-osrm.org. The OSRM host must implement the OSRM v1 Route
service, including GeoJSON route geometry.
Using the features
1. Dijkstra demo: select "Demo network · simulated", choose two different
   sample locations, set priority and departure, then find and compare routes.
   Dijkstra uses the weighted sample graph and a min-heap to return up to
   three distinct loopless routes. The sample graph stores travel time only,
   not distance.

2. Simulated road closure/traffic: close a sample road or add minutes in the
   road-condition table, apply the changes, and search again in Demo mode.
   Restore the original conditions when finished. These controls do not affect
   OSM/OSRM routes.

3. Worldwide OSM route: select "OpenStreetMap + OSRM · road estimate".
   Enter a starting address, city, landmark, or place. Choose a hospital in
   the Kengeri sample list, or select custom destination and enter any
   supported destination worldwide. Submit the form to geocode the locations
   and request OSRM driving route options. The map shows start/destination
   markers and distinct route lines. Cards show distance, estimated driving
   duration, and arrival time from the selected departure time. If only one
   distinct route is available, the page says so. Choose an alternative to save
   it as the selected route.

4. Current location: on localhost or an HTTPS site, click "Use My Current
   Location" and grant permission in the browser prompt. The browser geolocation
   API returns coordinates to this page; coordinates are sent to OSRM for
   route calculation and do not need Nominatim lookup. Permission denied,
   unavailable location, timeout, or unsupported browser messages are shown
   next to the button. You can always enter a starting address instead.

5. Route history: every submitted route and explicit alternative selection is
   saved locally with source, destination, route, distance when supplied by
   OSRM, estimated duration and arrival, priority, and search time. Demo
   distances are shown as unavailable because the sample graph contains no
   distance data. The analytics panel summarizes saved journey count, average
   duration, and average OSRM distance. Restart Flask to confirm history and
   simulated conditions persist.

6. Voice directions: on an OSRM route, use "Read directions aloud" only when
   the route includes OSRM maneuver data. The browser speech engine reads
   those maneuvers; when OSRM supplies none, the page says voice directions
   are unavailable rather than inventing them. The Dijkstra demo contains no
   turn-by-turn road data.

7. Live trip dispatch prototype: open /dispatch, enter an ambulance ID,
   starting address, destination, and priority. Calculate an OSRM route to
   create the trip. The confirmation displays two distinct, unguessable links:
   share the driver link only with the driver and the dispatcher link only
   with authorized dispatchers. The driver explicitly starts GPS sharing from
   their device. The dispatcher dashboard receives Socket.IO events when
   connected and falls back to periodic authenticated polling. Stop Tracking
   pauses sharing; Complete Trip closes the trip. A dispatcher can view a trip
   only with that trip's dispatcher link. The dashboard shows a persisted
   lifecycle timeline and summary from accepted GPS update counts and
   straight-line sample distance.

8. OpenStreetMap hospital search: on /dispatch, search a hospital name or
   area. Results and map markers come from public OSM/Nominatim records.
   Select a result to use its mapped coordinates. Public details such as
   phone or website appear only if mapped; beds, emergency capacity, and
   operating status are not provided.

Trip privacy and summary
- Driver and dispatcher links contain separate random bearer tokens in the
  URL fragment. Fragments are not sent in HTTP requests; JavaScript sends the
  token in an Authorization header or Socket.IO event. SQLite stores only
  token hashes. Anyone who obtains a link has that link's role-specific
  access, so share links privately.
- During tracking, SQLite stores only the latest accepted latitude/longitude,
  accuracy, and device timestamp plus accumulated distance and update count.
  It does not retain a breadcrumb GPS track. Exact last coordinates are
  cleared on Stop Tracking or Complete Trip, and stale positions are cleared
  after 24 hours. Trip metadata, lifecycle event timestamps, and aggregate
  summary remain in the database; lifecycle events do not include coordinates.
- Summary distance is straight-line distance between accepted GPS samples,
  not traveled road distance. Planned route distance and duration are OSRM
  estimates. No traffic feed, automatic dispatch, ambulance identity
  verification, hospital availability feed, or certified emergency workflow
  is provided.
- The prototype uses one SQLite database and one Flask-SocketIO process. Do
  not run multiple app workers against this setup without a shared Socket.IO
  message queue and a suitable shared database. Trip-link revocation and
  account-based identity are not implemented.

Two-device testing and remote deployment
1. Run the application on a publicly reachable server with a valid HTTPS
   hostname. Browser GPS generally requires HTTPS outside localhost.
2. Set the external origin so generated private links point to your HTTPS
   address:
     Windows PowerShell:
       $env:PUBLIC_BASE_URL = "https://your-domain.example"
       $env:HOST = "0.0.0.0"
       $env:PORT = "5000"
     macOS/Linux:
       export PUBLIC_BASE_URL="https://your-domain.example"
       export HOST="0.0.0.0"
       export PORT="5000"
3. Terminate HTTPS at a maintained reverse proxy/hosting platform and forward
   WebSocket upgrades for /socket.io/ to Flask-SocketIO. Keep the app server
   private behind the proxy; do not expose the Flask development server
   directly to the public internet.
4. From a dispatcher computer, open /dispatch, create a trip, and securely
   share its driver and dispatcher links with the two devices.
5. On the driver device, open the driver link, grant GPS permission, and press
   Start Trip. Confirm the dispatcher map moves without a page refresh.
   Temporarily disable network or location and verify reconnect/stale warnings.
   Finally test Stop Tracking and Complete Trip.
6. The built-in server command is for prototype testing only. Production needs
   HTTPS, a production server or managed host configured for Flask-SocketIO,
   persistent storage, and operational monitoring.

Nominatim, OSRM, and map usage
- Automated address autocomplete is not used. Each address lookup occurs only
  after the user submits the route form.
- Successful geocoding lookups are cached in SQLite. Uncached requests are
  serialized and spaced by at least 1.05 seconds across application workers.
- Nominatim is a low-volume community service with a published maximum of one
  request per second. Keep use moderate and follow its current policy.
- The browser location itself is not sent to Nominatim. A custom destination
  and manually entered start address are sent to Nominatim for coordinates.
  OSRM receives coordinates, not the original address text.
- Route geometry comes from the OSRM service's current road dataset, not live
  traffic or live closures. A road route can fail when mapped data or a
  connection is unavailable.
- Browser location is sent to OSRM as route coordinates when calculating a
  journey. It is not sent to Nominatim; journey history is stored locally in
  `instance/routes.db` and labels the origin "Current location" rather than
  storing exact coordinates as display text.
- OpenStreetMap tile attribution is shown on every Leaflet map. Follow the
  tile usage policy: https://operations.osmfoundation.org/policies/tiles/
  This app requests only the visible tiles as users view or navigate a map;
  do not prefetch or bulk-download tiles. The public tile service is
  best-effort and intended for normal interactive use, not high-volume
  production deployments. Use a compliant tile provider or self-hosted
  service if your deployment volume or reliability requirements exceed the
  public service's capacity.
- Nominatim policy:
  https://operations.osmfoundation.org/policies/nominatim/
- Nominatim Search API:
  https://nominatim.org/release-docs/latest/api/Search/
- OSRM API:
  https://project-osrm.org/docs/v5.24.0/api/
- Leaflet:
  https://leafletjs.com/

Tests
Run all automated tests:
     .\.venv\Scripts\python.exe -m unittest discover -s tests -v
(On macOS/Linux, substitute .venv/bin/python.)
The service integration tests mock HTTP responses and do not depend on network
availability.

Storage and source files
- instance/routes.db stores route history, simulated road conditions,
  geocoding cache entries, and shared Nominatim request spacing state.
- dijkstra.py and graph_data.py power the original sample graph demo.
- osm_routing.py contains worldwide geocoding, OSRM requests, response
  validation, and the sample Kengeri hospital coordinates.
- app.py handles form validation and the Flask/SQLite integration.
- No Google APIs, keys, billing, or payment details are used.

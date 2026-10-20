(() => {
    const root = document.querySelector("[data-trip-id][data-role]");
    if (!root) {
        return;
    }
    const tripId = root.dataset.tripId;
    const role = root.dataset.role;
    const tokenKey = `routecare:${tripId}:${role}`;
    const tokenFromLink = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (tokenFromLink) {
        sessionStorage.setItem(tokenKey, tokenFromLink);
        window.history.replaceState(null, "", window.location.pathname);
    }
    const token = tokenFromLink || sessionStorage.getItem(tokenKey);
    const connectionState = document.getElementById("connection-state");
    const errorBox = document.getElementById("trip-error");
    const warning = document.getElementById("tracking-warning");
    const summary = document.getElementById("trip-summary");
    const historySummary = document.getElementById("trip-history-summary");
    const tripEventList = document.getElementById("trip-event-list");
    const startButton = document.getElementById("start-trip");
    const stopButton = document.getElementById("stop-tracking");
    const completeButton = document.getElementById("complete-trip");
    let trip = null;
    let map = null;
    let baseMapInitialized = false;
    let hasFittedMap = false;
    let routeLayer = null;
    let ambulanceMarker = null;
    let destinationMarker = null;
    let positionWatch = null;
    let locationRequest = Promise.resolve();
    let socket = null;
    let lastSentAt = 0;
    let networkAvailable = navigator.onLine;
    let serverReachable = false;

    function showError(message) {
        errorBox.hidden = !message;
        errorBox.textContent = message || "";
    }

    async function requestJson(path, options = {}) {
        let response;
        try {
            response = await fetch(path, {
                ...options,
                headers: {
                    Accept: "application/json",
                    ...(options.body ? {"Content-Type": "application/json"} : {}),
                    Authorization: `Bearer ${token}`,
                    ...options.headers,
                },
                cache: "no-store",
            });
            serverReachable = true;
        } catch (error) {
            serverReachable = false;
            throw error;
        }
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Trip request failed.");
        }
        return payload;
    }

    function displayTime(value) {
        if (!value) {
            return "Not recorded";
        }
        const date = new Date(value);
        return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
    }

    function makeSummaryCard(label, value, extra = "") {
        const card = document.createElement("article");
        card.className = "stat-card";
        const caption = document.createElement("div");
        caption.className = "stat-label";
        caption.textContent = label;
        const content = document.createElement("div");
        content.className = "trip-card-value";
        content.textContent = value;
        const foot = document.createElement("div");
        foot.className = "stat-foot";
        foot.textContent = extra;
        card.append(caption, content, foot);
        return card;
    }

    function initializeMap() {
        if (map || typeof L === "undefined") {
            return;
        }
        map = L.map("trip-map");
    }

    function updateMap(data) {
        initializeMap();
        if (!map) {
            return;
        }
        const points = [];
        if (routeLayer) {
            routeLayer.remove();
            routeLayer = null;
        }
        let geometry = [];
        try {
            geometry = JSON.parse(data.route_geometry || "[]");
        } catch {
            geometry = [];
        }
        if (geometry.length > 1) {
            const latLngs = geometry.map(([longitude, latitude]) => [latitude, longitude]);
            routeLayer = L.polyline(latLngs, {
                color: "#457eb3",
                weight: 5,
                opacity: 0.75,
            }).addTo(map);
            points.push(...latLngs);
        }
        if (!destinationMarker) {
            destinationMarker = L.circleMarker(
                [data.destination.lat, data.destination.lon],
                {
                    radius: 8,
                    color: "#a85720",
                    fillColor: "#e99a4c",
                    fillOpacity: 0.9,
                }
            ).addTo(map);
        }
        destinationMarker.bindPopup(data.destination.name);
        points.push([data.destination.lat, data.destination.lon]);
        if (data.last_lat !== null && data.last_lon !== null) {
            const location = [data.last_lat, data.last_lon];
            if (!ambulanceMarker) {
                ambulanceMarker = L.marker(location).addTo(map);
            } else {
                ambulanceMarker.setLatLng(location);
            }
            ambulanceMarker.bindPopup(`${data.ambulance_id} · last reported position`);
            points.push(location);
        } else if (ambulanceMarker) {
            ambulanceMarker.remove();
            ambulanceMarker = null;
        }
        if (points.length) {
            const bounds = L.latLngBounds(points);
            if (!hasFittedMap || !map.getBounds().contains(bounds)) {
                map.fitBounds(bounds, {
                    padding: [24, 24],
                    maxZoom: 15,
                    animate: false,
                });
                hasFittedMap = true;
            }
        } else {
            map.setView([data.origin.lat, data.origin.lon], 13);
        }
        if (!baseMapInitialized) {
            window.addOpenStreetMapBaseLayer(map);
            baseMapInitialized = true;
        }
        window.setTimeout(() => map.invalidateSize(), 0);
    }

    function renderTrip(data) {
        const statusChanged = trip && trip.status !== data.status;
        trip = data;
        summary.replaceChildren(
            makeSummaryCard("AMBULANCE ID", data.ambulance_id, `Trip ${data.id.slice(0, 8)}`),
            makeSummaryCard("TRIP STATUS", data.status.toUpperCase(), `Priority: ${data.priority}`),
            makeSummaryCard("DESTINATION", data.destination.name, `From: ${data.origin.name}`),
            makeSummaryCard(
                "LAST GPS UPDATE",
                displayTime(data.last_location_at),
                data.last_accuracy_m === null ? "No position received" : `Accuracy ±${Math.round(data.last_accuracy_m)} m`
            )
        );
        if (statusChanged && role === "dispatcher") {
            loadTripHistory();
        }
        if (role === "driver") {
            startButton.disabled = data.status === "tracking" || data.status === "completed";
            stopButton.disabled = data.status !== "tracking";
            completeButton.disabled = data.status === "completed";
        }
        updateMap(data);
        refreshWarnings();
    }

    async function loadTripHistory() {
        if (role !== "dispatcher" || !historySummary) {
            return;
        }
        try {
            const data = await requestJson(
                `/api/trips/${encodeURIComponent(tripId)}/summary`
            );
            historySummary.textContent =
                `${data.location_update_count} accepted GPS update(s) · ` +
                `${(data.actual_distance_m / 1000).toFixed(2)} km straight-line sampled distance · ` +
                `started ${displayTime(data.started_at)} · completed ${displayTime(data.completed_at)}.`;
            if (tripEventList) {
                tripEventList.replaceChildren();
                const labels = {
                    created: "Trip created",
                    tracking_started: "GPS tracking started",
                    tracking_stopped: "GPS tracking stopped",
                    completed: "Trip completed",
                };
                data.events.forEach(event => {
                    const item = document.createElement("li");
                    const label = document.createElement("strong");
                    label.textContent = labels[event.event_type] || "Trip event";
                    const timestamp = document.createElement("time");
                    timestamp.dateTime = event.event_at;
                    timestamp.textContent = displayTime(event.event_at);
                    item.append(label, timestamp);
                    tripEventList.append(item);
                });
            }
        } catch (error) {
            showError(error.message);
        }
    }

    function refreshWarnings() {
        if (!trip) {
            return;
        }
        const now = Date.now();
        const updateAt = trip.last_location_at
            ? new Date(trip.last_location_at).getTime()
            : null;
        const stale = trip.status === "tracking" &&
            (updateAt === null || now - updateAt > 30_000);
        const updateAge = updateAt === null ? null : Math.max(0, now - updateAt);
        if (!networkAvailable) {
            warning.textContent = "Network disconnected. Live position updates are paused until this device reconnects.";
            warning.classList.add("warning");
        } else if (stale) {
            warning.textContent = updateAge === null
                ? "Tracking is active but no GPS fix has been received yet."
                : `GPS location is stale; last accepted update ${Math.floor(updateAge / 1000)} seconds ago.`;
            warning.classList.add("warning");
        } else {
            warning.classList.remove("warning");
            if (trip.status === "tracking") {
                warning.textContent = role === "driver"
                    ? "Tracking is active. GPS updates are shared with the authorized dispatcher."
                    : "Tracking active. Ambulance marker shows the latest accepted GPS position.";
            } else {
                warning.textContent = `Trip status: ${trip.status}.`;
            }
        }
        if (role === "dispatcher" && socket && socket.connected) {
            connectionState.textContent = "Live connection connected";
        } else if (!serverReachable) {
            connectionState.textContent = "Server connection unavailable";
        } else if (role === "dispatcher" && networkAvailable) {
            connectionState.textContent = "Connected via periodic refresh";
        } else {
            connectionState.textContent = networkAvailable
                ? "Server reachable"
                : "Connection offline";
        }
    }

    async function loadSnapshot() {
        try {
            const data = await requestJson(`/api/trips/${encodeURIComponent(tripId)}`);
            showError("");
            renderTrip(data);
            await loadTripHistory();
            return true;
        } catch (error) {
            showError(error.message);
            connectionState.textContent = "Trip access unavailable";
            return false;
        }
    }

    async function sendAction(action) {
        showError("");
        const data = await requestJson(
            `/api/trips/${encodeURIComponent(tripId)}/action`,
            {method: "POST", body: JSON.stringify({action})}
        );
        renderTrip(data);
    }

    function transmitPosition(position) {
        const now = Date.now();
        if (now - lastSentAt < 2500) {
            return;
        }
        lastSentAt = now;
        const payload = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
            timestamp: position.timestamp,
        };
        locationRequest = locationRequest.then(async () => {
            const data = await requestJson(
                `/api/trips/${encodeURIComponent(tripId)}/location`,
                {method: "POST", body: JSON.stringify(payload)}
            );
            showError("");
            renderTrip(data);
        }).catch(error => {
            showError(error.message);
            warning.textContent = "Unable to send GPS update. Check connection and device time.";
            warning.classList.add("warning");
        });
    }

    function startPositionWatch() {
        if (!navigator.geolocation) {
            throw new Error("This browser does not support GPS. Tracking was not started.");
        }
        positionWatch = navigator.geolocation.watchPosition(
            transmitPosition,
            error => {
                const messages = {
                    1: "Location permission denied. Allow GPS access to start or resume tracking.",
                    2: "GPS location is unavailable. Check device location services.",
                    3: "GPS request timed out. Keep tracking active while the device retries.",
                };
                showError(messages[error.code] || "Unable to read GPS location.");
            },
            {enableHighAccuracy: true, maximumAge: 0, timeout: 20_000}
        );
    }

    if (!token) {
        showError("This private trip link has no access token. Ask the dispatcher to share the correct trip link.");
        connectionState.textContent = "Access token missing";
        if (startButton) {
            startButton.disabled = true;
        }
    } else {
        loadSnapshot().then(authorized => {
            if (!authorized) {
                return;
            }
            if (role === "driver" && trip.status === "tracking") {
                try {
                    startPositionWatch();
                } catch (error) {
                    showError(error.message);
                }
            }
            if (role !== "dispatcher") {
                return;
            }
            if (typeof io === "function") {
                socket = io({transports: ["websocket", "polling"]});
                socket.on("connect", () => {
                    connectionState.textContent = "Live connection connected";
                    socket.emit("subscribe_trip", {trip_id: tripId, token}, response => {
                        if (response && response.ok) {
                            renderTrip(response.trip);
                        } else {
                            showError(response?.error || "Dispatcher subscription was rejected.");
                            socket.disconnect();
                        }
                    });
                });
                socket.on("trip_update", renderTrip);
                socket.on("disconnect", () => {
                    connectionState.textContent = "Reconnecting; periodic refresh remains active";
                });
                socket.on("connect_error", () => {
                    connectionState.textContent = "Live socket unavailable; periodic refresh remains active";
                });
            }
        });
    }

    if (startButton && token) {
        startButton.addEventListener("click", async () => {
            if (!navigator.geolocation) {
                showError("This browser does not support GPS tracking.");
                return;
            }
            startButton.disabled = true;
            showError("");
            try {
                await new Promise((resolve, reject) => {
                    navigator.geolocation.getCurrentPosition(resolve, reject, {
                        enableHighAccuracy: true,
                        maximumAge: 0,
                        timeout: 20_000,
                    });
                });
                await sendAction("start");
                startPositionWatch();
            } catch (error) {
                startButton.disabled = false;
                showError(error.code === 1
                    ? "Location permission denied. Allow GPS access before starting the trip."
                    : error.message || "Could not start GPS tracking.");
            }
        });
        stopButton.addEventListener("click", async () => {
            if (positionWatch !== null) {
                navigator.geolocation.clearWatch(positionWatch);
                positionWatch = null;
            }
            try {
                await sendAction("stop");
            } catch (error) {
                showError(error.message);
            }
        });
        completeButton.addEventListener("click", async () => {
            if (!window.confirm("Complete this trip and stop sharing GPS?")) {
                return;
            }
            if (positionWatch !== null) {
                navigator.geolocation.clearWatch(positionWatch);
                positionWatch = null;
            }
            try {
                await sendAction("complete");
            } catch (error) {
                showError(error.message);
            }
        });
    }

    window.addEventListener("online", () => {
        networkAvailable = true;
        refreshWarnings();
        loadSnapshot();
    });
    window.addEventListener("offline", () => {
        networkAvailable = false;
        refreshWarnings();
    });
    window.setInterval(() => {
        refreshWarnings();
        if (token && networkAvailable) {
            loadSnapshot();
        }
    }, 5000);
})();

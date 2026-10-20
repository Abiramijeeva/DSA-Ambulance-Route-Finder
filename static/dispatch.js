(() => {
    const searchButton = document.getElementById("hospital-search-button");
    if (searchButton) {
        const queryInput = document.getElementById("hospital-query");
        const resultContainer = document.getElementById("hospital-results");
        const searchStatus = document.getElementById("hospital-search-status");
        const mapElement = document.getElementById("hospital-search-map");
        let hospitalMap = null;
        let hospitalMarkers = null;
        let baseMapInitialized = false;

        searchButton.addEventListener("click", async () => {
            const query = queryInput.value.trim();
            if (query.length < 2 || query.length > 120) {
                searchStatus.hidden = false;
                searchStatus.textContent = "Enter at least two characters for the hospital search.";
                resultContainer.replaceChildren();
                return;
            }
            searchButton.disabled = true;
            searchStatus.hidden = false;
            searchStatus.textContent = "Searching OpenStreetMap hospital listings…";
            resultContainer.replaceChildren();
            try {
                const response = await fetch(
                    `/api/hospitals/search?q=${encodeURIComponent(query)}`,
                    {headers: {Accept: "application/json"}}
                );
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || "Hospital search failed.");
                }
                if (!payload.results.length) {
                    searchStatus.textContent = "No hospital listings found. Try another area or enter the destination manually.";
                    return;
                }
                searchStatus.textContent = `${payload.results.length} public OSM listing(s). Verify details independently; availability is not provided.`;
                if (typeof L === "undefined") {
                    searchStatus.textContent += " The map library could not load.";
                } else {
                    mapElement.hidden = false;
                }
                if (typeof L !== "undefined" && !hospitalMap) {
                    hospitalMap = L.map(mapElement).setView(
                        [payload.results[0].lat, payload.results[0].lon],
                        12
                    );
                    hospitalMarkers = L.layerGroup().addTo(hospitalMap);
                }
                if (hospitalMap) {
                    mapElement.hidden = false;
                    hospitalMarkers.clearLayers();
                }
                const bounds = [];
                payload.results.forEach(hospital => {
                    let marker = null;
                    if (hospitalMap) {
                        marker = L.marker([hospital.lat, hospital.lon]).addTo(hospitalMarkers);
                        const popup = document.createElement("div");
                        popup.textContent = `${hospital.name} — ${hospital.display_name}`;
                        marker.bindPopup(popup);
                        bounds.push([hospital.lat, hospital.lon]);
                    }
                    const card = document.createElement("article");
                    card.className = "hospital-result";
                    const name = document.createElement("strong");
                    name.textContent = hospital.name;
                    const address = document.createElement("p");
                    address.textContent = hospital.display_name;
                    card.append(name, address);
                    if (hospital.photo && hospital.photo.url && hospital.photo.source_url) {
                        const figure = document.createElement("figure");
                        figure.className = "hospital-result-photo";
                        const image = document.createElement("img");
                        image.src = hospital.photo.url;
                        image.alt = `Photograph of ${hospital.name}`;
                        image.loading = "lazy";
                        image.width = 960;
                        image.height = 720;
                        image.addEventListener("error", () => figure.remove(), {once: true});
                        const caption = document.createElement("figcaption");
                        const source = document.createElement("a");
                        source.href = hospital.photo.source_url;
                        source.target = "_blank";
                        source.rel = "noopener noreferrer";
                        source.textContent = hospital.photo.credit || "Photo source";
                        caption.append(source);
                        figure.append(image, caption);
                        card.append(figure);
                    }
                    const details = Object.entries(hospital.public_details || {});
                    if (details.length) {
                        const publicDetails = document.createElement("p");
                        publicDetails.textContent = details
                            .map(([key, value]) => `${key}: ${value}`)
                            .join(" · ");
                        card.append(publicDetails);
                    }
                    const actions = document.createElement("div");
                    actions.className = "hospital-result-actions";
                    const selectButton = document.createElement("button");
                    selectButton.type = "button";
                    selectButton.className = "secondary-button";
                    selectButton.textContent = "Use this destination";
                    selectButton.addEventListener("click", () => {
                        document.getElementById("destination").value =
                            hospital.display_name;
                        document.getElementById("destination_lat").value =
                            hospital.lat;
                        document.getElementById("destination_lon").value =
                            hospital.lon;
                        if (hospitalMap && marker) {
                            hospitalMap.setView([hospital.lat, hospital.lon], 15);
                            marker.openPopup();
                        }
                    });
                    actions.append(selectButton);
                    if (hospital.osm_url) {
                        const mapLink = document.createElement("a");
                        mapLink.href = hospital.osm_url;
                        mapLink.target = "_blank";
                        mapLink.rel = "noopener noreferrer";
                        mapLink.textContent = "View OpenStreetMap record";
                        actions.append(mapLink);
                    }
                    card.append(actions);
                    resultContainer.append(card);
                });
                if (bounds.length) {
                    hospitalMap.fitBounds(bounds, {padding: [20, 20], maxZoom: 14});
                    window.setTimeout(() => hospitalMap.invalidateSize(), 0);
                }
                if (hospitalMap && !baseMapInitialized) {
                    window.addOpenStreetMapBaseLayer(hospitalMap);
                    baseMapInitialized = true;
                }
            } catch (error) {
                searchStatus.textContent = error.message || "Hospital search is temporarily unavailable.";
            } finally {
                searchButton.disabled = false;
            }
        });
    }

    document.querySelectorAll(".copy-link").forEach(button => {
        button.addEventListener("click", async () => {
            const input = document.getElementById(button.dataset.copy);
            try {
                await navigator.clipboard.writeText(input.value);
                button.textContent = "Copied";
                window.setTimeout(() => {
                    button.textContent = "Copy link";
                }, 1500);
            } catch {
                input.focus();
                input.select();
                document.execCommand("copy");
                button.textContent = "Link selected";
            }
        });
    });
})();

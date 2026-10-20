(() => {
    const OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
    const OSM_ATTRIBUTION =
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>';

    function showUnavailableMessage(map) {
        const control = L.control({position: "topright"});
        control.onAdd = () => {
            const notice = L.DomUtil.create("div", "map-tile-notice");
            notice.setAttribute("role", "status");
            notice.textContent =
                "OpenStreetMap tiles are unavailable. Check the connection or tile-service status.";
            return notice;
        };
        control.addTo(map);
    }

    window.addOpenStreetMapBaseLayer = map => {
        const tileLayer = L.tileLayer(OSM_TILE_URL, {
            attribution: OSM_ATTRIBUTION,
            maxZoom: 19,
        });
        let unavailable = false;
        const fail = () => {
            if (unavailable) {
                return;
            }
            unavailable = true;
            window.clearTimeout(loadTimeout);
            if (map.hasLayer(tileLayer)) {
                map.removeLayer(tileLayer);
            }
            showUnavailableMessage(map);
        };
        const loadTimeout = window.setTimeout(fail, 15000);

        tileLayer.on("tileerror", fail);
        tileLayer.on("load", () => {
            window.clearTimeout(loadTimeout);
        });
        tileLayer.addTo(map);
        return tileLayer;
    };
})();

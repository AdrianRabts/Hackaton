// static/map.js
(function () {
  function initPickerMap(opts) {
    const {
      mapId,
      latInputId,
      lngInputId,
      startLat = -1.8312,
      startLng = -78.1834,
      zoom = 6,
    } = opts;

    const latInput = document.getElementById(latInputId);
    const lngInput = document.getElementById(lngInputId);
    const mapEl = document.getElementById(mapId);

    if (!mapEl || !window.L) return;

    const map = L.map(mapId).setView([startLat, startLng], zoom);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    let marker = L.marker([startLat, startLng], { draggable: true }).addTo(map);

    function setLatLng(lat, lng) {
      if (latInput) latInput.value = String(lat.toFixed(6));
      if (lngInput) lngInput.value = String(lng.toFixed(6));
      marker.setLatLng([lat, lng]);
      map.panTo([lat, lng]);
    }

    setLatLng(startLat, startLng);

    map.on("click", function (e) {
      setLatLng(e.latlng.lat, e.latlng.lng);
    });

    marker.on("dragend", function (e) {
      const p = e.target.getLatLng();
      setLatLng(p.lat, p.lng);
    });
  }

  function initPublicMap(opts) {
    const {
      mapId,
      markers = [],
      path = [],
      startLat = -1.8312,
      startLng = -78.1834,
      zoom = 6,
    } = opts;

    const mapEl = document.getElementById(mapId);
    if (!mapEl || !window.L) return;

    const map = L.map(mapId).setView([startLat, startLng], zoom);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    const bounds = [];

    // Ruta demo-safe (línea)
    if (Array.isArray(path) && path.length >= 2) {
      try {
        const line = L.polyline(path, { weight: 4, opacity: 0.85 }).addTo(map);
        const lb = line.getBounds();
        if (lb && lb.isValid()) map.fitBounds(lb, { padding: [30, 30] });
      } catch (_) {}
    }

    markers.forEach((m) => {
      if (typeof m.lat !== "number" || typeof m.lng !== "number") return;

      const popup = `
        <div style="min-width:220px">
          <div style="font-weight:700">${escapeHtml(m.name || "Negocio")}</div>
          <div style="font-size:12px;color:#64748b">${escapeHtml(m.route || "")}</div>
          <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
            <a href="/listings?route=${encodeURIComponent(m.route || "")}"
               style="font-size:12px;padding:6px 10px;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;">
               Ver lugares
            </a>
            ${m.maps_url ? `<a href="${m.maps_url}" target="_blank"
               style="font-size:12px;padding:6px 10px;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;">
               Maps
            </a>` : ""}
            ${m.phone_whatsapp ? `<a href="https://wa.me/${String(m.phone_whatsapp).replace("+","")}" target="_blank"
               style="font-size:12px;padding:6px 10px;border:1px solid #e2e8f0;border-radius:10px;text-decoration:none;">
               WhatsApp
            </a>` : ""}
          </div>
        </div>
      `;

      L.marker([m.lat, m.lng]).addTo(map).bindPopup(popup);
      bounds.push([m.lat, m.lng]);
    });

    if (bounds.length >= 2) map.fitBounds(bounds, { padding: [30, 30] });
    if (bounds.length === 1) map.setView(bounds[0], 14);
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[c]));
  }

  window.CRMaps = { initPickerMap, initPublicMap };
})();

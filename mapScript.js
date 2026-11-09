ZOOM = true; // true to display zoom controls, false otherwise

// The area visitors are allowed to see on the main campus map: [southwest corner, northeast corner]
const campusBounds_halfWindow = L.latLngBounds(
  [42.8130, -73.9375], // southwest
  [42.8220, -73.9205]  // northeast
);

const campusBounds_fullWindow = L.latLngBounds(
  [42.8130, -73.9380], // southwest
  [42.8220, -73.9160]  // northeast
);

// Kelly Adirondack Center coordinates and threshold check
const KELLY_CENTER = [42.789116, -73.882045];

// Kelly Adirondack Center tight bounds (~70m box)
const kellyBounds = L.latLngBounds(
  [42.7887, -73.8826], // southwest
  [42.7895, -73.8815]  // northeast
);

function isKellyCenter(lat, lon) {
  return lat < 42.80 && lon > -73.90;
}

// ---------------------------------------------------------------------------
// 1. Initialize Main Campus Map
// ---------------------------------------------------------------------------
const map = L.map("map", {
  center: [42.8175, -73.9300], // Union College latitude and longitude
  zoom: 17,
  maxZoom: 18,
  minZoom: 17,
  zoomControl: ZOOM,
  maxBounds: campusBounds_fullWindow,   // visitor can't pan outside this box
  maxBoundsViscosity: 1.0              // 1.0 = hard wall, lower = bouncy edge
});

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  minZoom: 17,
  bounds: campusBounds_fullWindow,      // never request tiles outside this box
  updateWhenZooming: false,
  updateWhenIdle: true,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// ---------------------------------------------------------------------------
// 2. Initialize Inset Map (Kelly Adirondack Center)
// ---------------------------------------------------------------------------
const insetMap = L.map("inset-map", {
  center: KELLY_CENTER,
  zoom: 18,
  minZoom: 18,
  maxZoom: 19,
  zoomControl: false,
  maxBounds: kellyBounds,
  maxBoundsViscosity: 1.0,
  attributionControl: false
});

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  minZoom: 18
}).addTo(insetMap);

// ---------------------------------------------------------------------------
// Custom Icons
// ---------------------------------------------------------------------------
const pinIcon = L.icon({
  iconUrl: "pin1.png",
  iconSize: [30, 30]
});

const buttonIcon = L.icon({
  iconUrl: "button.png",
  iconSize: [15, 15]
});

const frenchIcon = L.icon({
  iconUrl: "franceFlag.png",
  iconSize: [20, 20]
});

// ---------------------------------------------------------------------------
// Helpers & CSV Loading
// ---------------------------------------------------------------------------
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function capitalize(text) {
  return text.replace(/\b\w/g, letter => letter.toUpperCase());
}

// The three csv files written by build_points.py
const POINT_FILES = [
  "student_points.csv",
  "staff_points.csv",
  "faculty_points.csv"
];

function plotPoints(url) {
  return fetch(url)
    .then(response => {
      if (!response.ok) {
        throw new Error(`Could not load ${url} (${response.status})`);
      }
      return response.text();
    })
    .then(text => {
      const lines = text.trim().split(/\r?\n/);
      let count = 0;

      // Skip header row: Id,Language,Latitude,Longitude
      for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line === "") continue;

        const [id, language, lat, lon] = line.split(",");
        const latitude = Number(lat);
        const longitude = Number(lon);

        if (Number.isNaN(latitude) || Number.isNaN(longitude)) {
          console.warn(`Skipping row ${i + 1} of ${url}: ${line}`);
          continue;
        }

        // Send point to the inset map if it is at Kelly Adirondack Center, else main map
        const targetMap = isKellyCenter(latitude, longitude) ? insetMap : map;

        L.marker([latitude, longitude], { icon: buttonIcon })
          .addTo(targetMap)
          .bindPopup(`<h3>${escapeHtml(capitalize(language))}</h3>`);
        count++;
      }

      console.log(`Added ${count} pins from ${url}`);
      return count;
    })
    .catch(error => {
      console.error(error);
      return 0;
    });
}

// Plot markers across all categories
Promise.all(POINT_FILES.map(plotPoints)).then(counts => {
  const total = counts.reduce((sum, count) => sum + count, 0);
  console.log(`Added ${total} language pins to the maps`);
});

ZOOM = true // true to display zoom controls, false otherwise


// The area visitors are allowed to see: [southwest corner, northeast corner]
const campusBounds_halfWindow = L.latLngBounds(
  [42.8130, -73.9375], // southwest
  [42.8220, -73.9205]  // northeast
);

const campusBounds_fullWindow = L.latLngBounds(
  [42.8130, -73.9380], // southwest
  [42.8220, -73.9160]  // northeast
);


// initialize the map
const map = L.map("map", {
  center: [42.8175, -73.9300], // Union College latitude and longitude
  zoom: 17, // Default zoom
  maxZoom: 18,
  minZoom: 17,
  zoomControl: ZOOM,
  maxBounds: campusBounds_fullWindow,   // visitor can't pan outside this box
  maxBoundsViscosity: 1.0    // 1.0 = hard wall, lower = bouncy edge
});


const tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
 maxZoom: 18,
 minZoom: 17,
 zoomControl: ZOOM,
 bounds: campusBounds_fullWindow,      // never request tiles outside this box
 updateWhenZooming: false,  // skip intermediate tiles while zoom animates
 updateWhenIdle: true,      // load tiles when panning stops, not during the drag
 attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' // attribute OpenStreetMap
}).addTo(map);

// Count number of tiles downloaded - DOES NOT WORK YET
// let tilesRequested = 0;
// tileLayer.on("tileloadstart", () => {
//   tilesRequested++;
//   console.log(`Tiles requested this page view: ${tilesRequested}`);
// });

// var tileLayer = L.tileLayer('https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}{r}.{ext}', {
// 	minZoom: 17,
// 	maxZoom: 18,
//   zoomControl: ZOOM,
//   bounds: campusBounds,
//   updateWhenZooming: false,
//   updateWhenIdle: true,
// 	attribution: '&copy; CNES, Distribution Airbus DS, © Airbus DS, © PlanetObserver (Contains Copernicus Data) | &copy; <a href="https://www.stadiamaps.com/" target="_blank">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
// 	ext: 'jpg'
// }).addTo(map);


// custom pin marker icon
const pinIcon = L.icon({
  iconUrl: "icons/pin1.png",
  iconSize: [30, 30]
});

// custom button marker icon
const buttonIcon = L.icon({
  iconUrl: "icons/button.png",
  iconSize: [15, 15]
});

// custom flag marker icon (example: french flag)
const frenchIcon = L.icon({
  iconUrl: "icons/flags/franceFlag.png",
  iconSize: [20, 20]
});

// example markers with location name popups
// const pinMarker = L.marker([42.817290, -73.92995], { icon: pinIcon }).addTo(map).bindPopup('<h3>Nott Memorial</h3>');
// const flagMarker = L.marker([42.819306, -73.9323], { icon: frenchIcon }).addTo(map).bindPopup('<h3>311 Seward St</h3>');

// ---------------------------------------------------------------------------
// Language points from build_points.py
// ---------------------------------------------------------------------------

// Make survey text safe to put inside popup HTML
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// "sign language" -> "Sign Language"
function capitalize(text) {
  return text.replace(/\b\w/g, letter => letter.toUpperCase());
}


// The three csv files written by build_points.py
// Each has a header row: Id,Language,Latitude,Longitude
const POINT_FILES = [
  "student_points.csv",
  "staff_points.csv",
  "faculty_points.csv"
];
 
// Plot every marker in one csv file. Returns the number of markers added.
// Each file is loaded on its own, so one missing file doesn't stop the others.
function plotPoints(url) {
  return fetch(url)
    .then(response => {
      if (!response.ok) {
        throw new Error(`Could not load ${url} (${response.status})`);
      }
      return response.text();
    })
    .then(text => {
      const lines = text.trim().split(/\r?\n/); // works with Windows or Mac line endings
      let count = 0;
 
      // start at 1 to skip the header row: Id,Language,Latitude,Longitude
      for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line === "") continue; // skip blank lines
 
        const [id, language, lat, lon] = line.split(",");
        const latitude = Number(lat);
        const longitude = Number(lon);
 
        // skip any row with missing or broken coordinates
        if (Number.isNaN(latitude) || Number.isNaN(longitude)) {
          console.warn(`Skipping row ${i + 1} of ${url}: ${line}`);
          continue;
        }
 
        L.marker([latitude, longitude], { icon: buttonIcon })
          .addTo(map)
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
 
// Plot markers
Promise.all(POINT_FILES.map(plotPoints)).then(counts => {
  const total = counts.reduce((sum, count) => sum + count, 0);
  console.log(`Added ${total} language pins to the map`);
});

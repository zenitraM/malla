// OpenFreeMap vector-tile basemap for Leaflet maps, rendered via a MapLibre GL WebGL overlay.
const OFM_LIGHT_STYLE = 'https://tiles.openfreemap.org/styles/liberty';
const OFM_DARK_STYLE = 'https://tiles.openfreemap.org/styles/dark';
const OFM_ATTRIBUTION = '© <a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
const TERRAIN_DEM_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';

// Recommended Leaflet map options for the GL adapter (see plugin README: maxBounds avoids
// the latitude-sync issue, minZoom avoids zoom-0 sync issues).
window.openFreeMapLeafletMapOptions = {
    maxBounds: [[180, -Infinity], [-180, Infinity]],
    maxBoundsViscosity: 1,
    minZoom: 1,
    maxZoom: 20,
};

function addTerrainLayers(glMap, contourSource) {
    try {
        glMap.addSource('terrarium-dem', { type: 'raster-dem', tiles: [TERRAIN_DEM_URL], tileSize: 256, encoding: 'terrarium', maxzoom: 15 });
        glMap.addLayer({ id: 'terrain-hillshade', type: 'hillshade', source: 'terrarium-dem',
            paint: { 'hillshade-exaggeration': 0.6, 'hillshade-illumination-direction': 315,
                     'hillshade-shadow-color': '#263238', 'hillshade-highlight-color': '#ffffff',
                     'hillshade-accent-color': '#607d8b' } });
        if (contourSource) {
            glMap.addSource('contours-dem', { type: 'raster-dem', tiles: [contourSource.sharedDemProtocolUrl], encoding: 'terrarium', tileSize: 256, maxzoom: 12 });
            glMap.addSource('contours', { type: 'vector', tiles: [contourSource.contourProtocolUrl({ thresholds: { 11: [200, 1000], 12: [100, 500], 13: [100, 500], 14: [50, 200], 15: [20, 100] } })], maxzoom: 15 });
            glMap.addLayer({ id: 'terrain-contours', type: 'line', source: 'contours', 'source-layer': 'contours',
                paint: { 'line-color': '#444444', 'line-opacity': 0.5, 'line-width': ['match', ['get', 'level'], 1, 1.2, 0.6] } });
        }
    } catch (err) {
        console.warn('OpenFreeMap terrain layers failed; continuing with plain basemap.', err);
    }
}

window.createOpenFreeMapOverlay = function (options = {}) {
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';

    // maplibre-contour must register its tile protocol BEFORE the GL map is created.
    let contourSource = null;
    if (options.terrain && window.mlcontour) {
        contourSource = new mlcontour.DemSource({ url: TERRAIN_DEM_URL, encoding: 'terrarium', maxzoom: 12, worker: true });
        contourSource.setupMaplibre(maplibregl);
    }

    if (typeof L.maplibreGL !== 'function') {
        console.warn('maplibre-gl-leaflet failed to load; map basemap disabled.');
        return null;
    }
    const overlay = L.maplibreGL({
        style: isDark ? OFM_DARK_STYLE : OFM_LIGHT_STYLE,
        attributionControl: { customAttribution: OFM_ATTRIBUTION },
    });
    if (options.terrain) {
        // Inner GL map is created in Leaflet's onAdd, i.e. only after overlay.addTo(map):
        // attach the terrain 'load' listener once the layer is actually added to the map.
        overlay.once('add', () => {
            const glMap = overlay.getMaplibreMap();
            if (glMap) glMap.on('load', () => addTerrainLayers(glMap, contourSource));
        });
    }
    return overlay;
};
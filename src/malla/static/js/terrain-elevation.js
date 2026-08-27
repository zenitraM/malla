/**
 * terrain-elevation.js
 *
 * Client-side terrain elevation sampling for the Line of Sight page.
 *
 * Samples the same Mapzen/AWS terrarium DEM tiles that the page's terrain
 * overlay already uses:
 *
 *     https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
 *
 * A terrarium tile is a 256x256 RGB PNG encoding elevation in meters:
 *
 *     elevation = (r * 256 + g + b / 256) - 32768
 *
 * Tiles are fetched, decoded once into Float32Array buffers, and cached in
 * memory (keyed by z/x/y) so concurrent samplePath() calls share fetches.
 * In-flight tile fetches are capped at MAX_INFLIGHT_FETCHES.
 *
 * Public API:
 *     window.TerrainElevation.samplePath({ lat1, lon1, lat2, lon2 })
 *         -> Promise<{
 *              geoPoints: [{ latitude, longitude, elevation,
 *                            distanceFromOriginMeters }, ...],
 *              metrics: { distance, climb, descent },
 *              dataSet: { description, resolutionMeters, publicUrl }
 *            }>
 *
 * If any tile fetch returns non-200 (including 404) or fails to decode, the
 * samplePath() promise rejects with an Error naming the failing tile, which
 * the template's existing try/catch surfaces as the terrain error state.
 */
(function () {
    'use strict';

    var TILE_SIZE = 256;
    var MAX_ZOOM = 15;
    var MAX_INFLIGHT_FETCHES = 6;
    var TILE_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/';
    var EARTH_RADIUS_METERS = 6371008.8;
    var METERS_PER_PX_EQUATOR = 156543.03392; // Web-Mercator meters per pixel at z0
    var MAX_SAMPLES = 700;

    // z/x/y -> Promise<Float32Array> (tile decoded once; shared across samples)
    var tileCache = new Map();

    // Simple semaphore state for the in-flight fetch cap.
    var inflightFetches = 0;
    var fetchQueue = [];

    // Diagnostic counter: number of actual HTTP tile fetches issued (cache misses).
    var tileFetchCount = 0;

    /** Great-circle distance between two points, in meters (haversine). */
    function haversineMeters(lat1, lon1, lat2, lon2) {
        var toRad = Math.PI / 180;
        var dLat = (lat2 - lat1) * toRad;
        var dLon = (lon2 - lon1) * toRad;
        var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
        return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(a));
    }

    /**
     * Fractional slippy-map tile coordinates for a lat/lon at zoom z.
     * x and y are NOT floored; the integer part selects the tile, the
     * fractional part addresses pixels within it.
     */
    function fractionalTileCoords(lat, lon, z) {
        var n = Math.pow(2, z);
        var latRad = lat * Math.PI / 180;
        var fx = ((lon + 180) / 360) * n;
        var fy = ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n;
        return { fx: fx, fy: fy, n: n };
    }

    /** Positive modulo (handles longitudes outside [-180, 180]). */
    function positiveModulo(value, modulus) {
        return ((value % modulus) + modulus) % modulus;
    }

    /** Clamp a value to [min, max]. */
    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    /** Choose a DEM zoom from the great-circle path distance in meters. */
    function zoomForDistance(distanceMeters) {
        var km = distanceMeters / 1000;
        if (km <= 2) {
            return MAX_ZOOM; // 15
        }
        if (km <= 10) {
            return 14;
        }
        if (km <= 60) {
            return 13;
        }
        return 12;
    }

    /** Free a fetch slot and wake the next queued fetch, if any. */
    function releaseFetchSlot() {
        inflightFetches -= 1;
        if (fetchQueue.length > 0) {
            fetchQueue.shift()();
        }
    }

    /**
     * Run `task` under the in-flight fetch cap: wait for a free slot, run,
     * then release the slot when the task settles.
     */
    function withFetchSlot(task) {
        return new Promise(function (resolve, reject) {
            var start = function () {
                if (inflightFetches >= MAX_INFLIGHT_FETCHES) {
                    fetchQueue.push(start);
                    return;
                }
                inflightFetches += 1;
                task().then(
                    function (value) { releaseFetchSlot(); resolve(value); },
                    function (err) { releaseFetchSlot(); reject(err); }
                );
            };
            start();
        });
    }

    /** Fetch + decode one terrarium tile into a Float32Array of 256*256 elevations. */
    function decodeTile(z, x, y) {
        var url = TILE_URL + z + '/' + x + '/' + y + '.png';
        tileFetchCount += 1;
        return fetch(url)
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.blob();
            })
            .then(function (blob) {
                if (typeof createImageBitmap !== 'function') {
                    throw new Error('createImageBitmap unsupported');
                }
                return createImageBitmap(blob);
            })
            .then(function (bitmap) {
                try {
                    var canvas = document.createElement('canvas');
                    canvas.width = TILE_SIZE;
                    canvas.height = TILE_SIZE;
                    var ctx = canvas.getContext('2d', { willReadFrequently: true });
                    if (!ctx) {
                        throw new Error('2d canvas context unavailable');
                    }
                    ctx.drawImage(bitmap, 0, 0, TILE_SIZE, TILE_SIZE);
                    var imageData = ctx.getImageData(0, 0, TILE_SIZE, TILE_SIZE);
                    var rgba = imageData.data;
                    var elevations = new Float32Array(TILE_SIZE * TILE_SIZE);
                    for (var i = 0, j = 0; i < rgba.length; i += 4, j += 1) {
                        elevations[j] = (rgba[i] * 256 + rgba[i + 1] + rgba[i + 2] / 256) - 32768;
                    }
                    return elevations;
                } finally {
                    if (typeof bitmap.close === 'function') {
                        bitmap.close();
                    }
                }
            });
    }

    /**
     * Get the decoded tile for z/x/y, sharing fetches via the in-memory cache.
     * Returns a Promise resolving to the Float32Array.
     */
    function loadTile(z, x, y) {
        var key = z + '/' + x + '/' + y;
        var cached = tileCache.get(key);
        if (cached) {
            return cached;
        }
        var promise = withFetchSlot(function () {
            return decodeTile(z, x, y);
        });
        tileCache.set(key, promise);
        return promise;
    }

    /**
     * Like loadTile, but rejects with the required user-facing error message
     * (including the tile id) if the tile fails to load or decode.
     */
    function loadTileChecked(z, x, y) {
        return loadTile(z, x, y).catch(function () {
            throw new Error(
                'Terrain data unavailable (tile ' + z + '/' + x + '/' + y + ' failed to load)'
            );
        });
    }

    /**
     * Bilinear elevation sample for a lat/lon from its fractional tile coords.
     * `tileData` is the Float32Array of the tile containing the sample.
     * Pixel positions are derived from the fractional tile coords; the four
     * surrounding pixels are interpolated with nearest-clamp at tile edges.
     */
    function sampleElevation(tileData, fx, fy, n) {
        // Clamp y to the valid tile range (paths near the poles).
        var fyClamped = clamp(fy, 0, n - 1);
        // Wrap x around the antimeridian so any longitude maps to a valid tile.
        var fxMod = positiveModulo(fx, n);

        // Pixel position within the 256x256 tile: [0, 256).
        var px = (fxMod - Math.floor(fxMod)) * TILE_SIZE;
        var py = (fyClamped - Math.floor(fyClamped)) * TILE_SIZE;

        var x0 = clamp(Math.floor(px), 0, TILE_SIZE - 1);
        var y0 = clamp(Math.floor(py), 0, TILE_SIZE - 1);
        var x1 = clamp(x0 + 1, 0, TILE_SIZE - 1);
        var y1 = clamp(y0 + 1, 0, TILE_SIZE - 1);

        var wx = px - Math.floor(px); // [0, 1)
        var wy = py - Math.floor(py); // [0, 1)

        var idx00 = y0 * TILE_SIZE + x0;
        var idx01 = y0 * TILE_SIZE + x1;
        var idx10 = y1 * TILE_SIZE + x0;
        var idx11 = y1 * TILE_SIZE + x1;

        var top = tileData[idx00] * (1 - wx) + tileData[idx01] * wx;
        var bottom = tileData[idx10] * (1 - wx) + tileData[idx11] * wx;
        return top * (1 - wy) + bottom * wy;
    }

    /**
     * Build the elevation profile for the path (lat1, lon1) -> (lat2, lon2).
     * Returns a Promise resolving to the contract object consumed by the
     * Line of Sight template.
     */
    function samplePath(params) {
        var lat1 = params.lat1;
        var lon1 = params.lon1;
        var lat2 = params.lat2;
        var lon2 = params.lon2;

        return Promise.resolve().then(function () {
            var distanceMeters = haversineMeters(lat1, lon1, lat2, lon2);
            var z = zoomForDistance(distanceMeters);

            // Meters per pixel at the path's mid-latitude and chosen zoom.
            var midLatRad = ((lat1 + lat2) / 2) * Math.PI / 180;
            var metersPerPx = METERS_PER_PX_EQUATOR * Math.cos(midLatRad) / Math.pow(2, z);

            // Sample spacing: 2 x meters-per-pixel; cap sample count at 700.
            var spacing = 2 * metersPerPx;
            var sampleCount = clamp(Math.round(distanceMeters / spacing), 2, MAX_SAMPLES);

            // Compute the fractional tile coords of every sample and collect
            // the set of unique tiles the path needs.
            var samples = [];
            var uniqueTiles = new Map(); // "z/x/y" -> { z, x, y }
            for (var i = 0; i < sampleCount; i += 1) {
                var t = i / (sampleCount - 1);
                var lat = lat1 + (lat2 - lat1) * t;
                var lon = lon1 + (lon2 - lon1) * t;
                var frac = fractionalTileCoords(lat, lon, z);
                var tx = Math.floor(positiveModulo(frac.fx, frac.n));
                var ty = clamp(Math.floor(frac.fy), 0, frac.n - 1);
                var key = z + '/' + tx + '/' + ty;
                if (!uniqueTiles.has(key)) {
                    uniqueTiles.set(key, { z: z, x: tx, y: ty });
                }
                samples.push({ lat: lat, lon: lon, frac: frac, tileKey: key });
            }

            // Preload every required tile (bounded by the fetch cap); any
            // failure rejects the whole profile.
            var tileEntries = [];
            var tileIndex = new Map(); // "z/x/y" -> index into tileEntries
            uniqueTiles.forEach(function (tile, key) {
                tileIndex.set(key, tileEntries.length);
                tileEntries.push({ z: tile.z, x: tile.x, y: tile.y, data: null });
            });

            var tileLoads = tileEntries.map(function (entry) {
                return loadTileChecked(entry.z, entry.x, entry.y).then(function (data) {
                    entry.data = data;
                });
            });
            return Promise.all(tileLoads).then(function () {
                return buildProfile(samples, tileIndex, tileEntries, z, distanceMeters, metersPerPx);
            });
        });
    }

    /** Assemble geoPoints + metrics from preloaded tile data (synchronous). */
    function buildProfile(samples, tileIndex, tileEntries, z, distanceMeters, metersPerPx) {
        var geoPoints = [];
        var cumulativeMeters = 0;
        var previous = null;
        var climb = 0;
        var descent = 0;

        for (var s = 0; s < samples.length; s += 1) {
            var sample = samples[s];
            if (previous) {
                cumulativeMeters += haversineMeters(
                    previous.lat, previous.lon, sample.lat, sample.lon
                );
            }
            var tile = tileEntries[tileIndex.get(sample.tileKey)];
            var elevation = sampleElevation(tile.data, sample.frac.fx, sample.frac.fy, sample.frac.n);

            if (previous) {
                var delta = elevation - previous.elevation;
                if (delta > 0) {
                    climb += delta;
                } else {
                    descent += delta;
                }
            }

            geoPoints.push({
                latitude: sample.lat,
                longitude: sample.lon,
                elevation: elevation,
                distanceFromOriginMeters: cumulativeMeters
            });
            previous = { lat: sample.lat, lon: sample.lon, elevation: elevation };
        }

        return {
            geoPoints: geoPoints,
            metrics: {
                distance: distanceMeters,
                climb: climb,
                descent: descent
            },
            dataSet: {
                description: 'Mapzen Terrain Tiles (SRTM/NASADEM via AWS Open Data)',
                resolutionMeters: Math.round(metersPerPx),
                publicUrl: 'https://registry.opendata.aws/terrain-tiles/'
            }
        };
    }

    // Public surface.
    window.TerrainElevation = {
        samplePath: samplePath,
        // Internal diagnostic counter (cache-miss tile fetches), used by tests.
        _tileFetchCount: function () {
            return tileFetchCount;
        }
    };
})();
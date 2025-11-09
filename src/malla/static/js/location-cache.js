(function () {
    const CACHE_KEY = 'malla_locations_cache_v1';
    const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes

    // Internal state
    let _locations = null;          // Map of node_id -> location object
    let _loaded = false;
    let _loadPromise = null;

    /**
     * Restore cached locations from localStorage
     */
    function _restoreFromLocalStorage() {
        try {
            const raw = localStorage.getItem(CACHE_KEY);
            if (!raw) return null;

            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed.locations !== 'object') return null;
            if (Date.now() - (parsed.timestamp || 0) > CACHE_TTL_MS) return null;

            return parsed.locations;
        } catch (err) {
            console.warn('LocationCache: Failed to restore from localStorage:', err);
            return null;
        }
    }

    /**
     * Persist locations to localStorage
     */
    function _persistToLocalStorage(locations) {
        try {
            const payload = { timestamp: Date.now(), locations };
            localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
        } catch (err) {
            console.warn('LocationCache: Failed to persist to localStorage:', err);
        }
    }

    const LocationCache = {
        /**
         * Load all locations from API and cache them
         */
        load() {
            if (_loaded) return Promise.resolve(_locations || {});
            if (_loadPromise) return _loadPromise;

            _loadPromise = (async () => {
                // Try localStorage first
                const cached = _restoreFromLocalStorage();
                if (cached) {
                    _locations = cached;
                    _loaded = true;
                    return _locations;
                }

                // Fetch from API
                try {
                    const resp = await fetch('/api/locations');
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const data = await resp.json();

                    // Convert array to map for fast lookup
                    _locations = {};
                    if (Array.isArray(data.locations)) {
                        data.locations.forEach(loc => {
                            if (loc && loc.node_id) {
                                _locations[loc.node_id] = loc;
                            }
                        });
                    }

                    _persistToLocalStorage(_locations);
                } catch (err) {
                    console.error('LocationCache: Failed to fetch locations:', err);
                    _locations = {};
                }

                _loaded = true;
                return _locations;
            })();

            return _loadPromise;
        },

        /**
         * Get location for a specific node ID
         */
        async getLocation(nodeId) {
            await this.load();
            return _locations[nodeId] || null;
        },

        /**
         * Get locations for multiple node IDs
         */
        async getLocations(nodeIds) {
            await this.load();
            const result = [];
            nodeIds.forEach(id => {
                const loc = _locations[id];
                if (loc) result.push(loc);
            });
            return result;
        },

        /**
         * Get all locations with coordinates
         */
        async getLocationsWithCoordinates() {
            await this.load();
            return Object.values(_locations).filter(loc =>
                loc && loc.latitude != null && loc.longitude != null
            );
        },

        /**
         * Add or update a location in the cache
         */
        addLocation(location) {
            if (!location || !location.node_id) return;
            if (!_locations) _locations = {};
            _locations[location.node_id] = location;
            _persistToLocalStorage(_locations);
        },

        /**
         * Clear the cache
         */
        clear() {
            _locations = {};
            _loaded = false;
            _loadPromise = null;
            try {
                localStorage.removeItem(CACHE_KEY);
            } catch (err) {
                console.warn('LocationCache: Failed to clear localStorage:', err);
            }
        }
    };

    // Expose globally
    window.LocationCache = LocationCache;

    // Start loading immediately
    LocationCache.load();
})();

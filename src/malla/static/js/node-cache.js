(function () {
    const CACHE_KEY = 'malla_nodes_cache_v2'; // v2: /api/v1 Node schema
    const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes

    // Internal state shared across the page
    let _nodes = null;              // Array of node objects
    let _loaded = false;            // Whether we attempted to load
    let _loadPromise = null;        // Promise that resolves once loading finished

    /**
     * Attempt to restore cached node list from localStorage.
     * Returns the cached array if it exists and is still fresh, otherwise null.
     */
    function _restoreFromLocalStorage() {
        try {
            const raw = localStorage.getItem(CACHE_KEY);
            if (!raw) return null;

            const parsed = JSON.parse(raw);
            if (!parsed || !Array.isArray(parsed.nodes)) return null;
            if (Date.now() - (parsed.timestamp || 0) > CACHE_TTL_MS) return null; // stale

            return parsed.nodes;
        } catch (err) {
            console.warn('NodeCache: Failed to restore from localStorage:', err);
            return null;
        }
    }

    /**
     * Persist node list to localStorage together with a timestamp.
     */
    function _persistToLocalStorage(nodes) {
        try {
            const payload = { timestamp: Date.now(), nodes };
            localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
        } catch (err) {
            // If storage quota exceeded or disabled, fail silently.
            console.warn('NodeCache: Failed to persist to localStorage:', err);
        }
    }

    /**
     * GET a /api/v1 collection. Prefers the shared api-client (envelope
     * handling, silent retry); falls back to a direct fetch with inline
     * envelope unwrapping for calls before the module bundle has evaluated.
     */
    async function _getEnvelope(path) {
        if (window.MallaAPI && typeof window.MallaAPI.getDetailed === 'function') {
            return window.MallaAPI.getDetailed(path, { silent: true });
        }
        const resp = await fetch(path, { headers: { Accept: 'application/json' } });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const body = await resp.json();
        if (body && typeof body === 'object' && !Array.isArray(body)
            && 'data' in body && 'meta' in body) {
            return { data: body.data, meta: body.meta };
        }
        return { data: body, meta: null };
    }

    /**
     * Page through a v1 collection endpoint. Bounded: 40 pages x 500 = 20k
     * rows, matching the previous 10k single-shot ceiling with headroom.
     */
    async function _paged(path, { maxPages = 40, pageSize = 500 } = {}) {
        const rows = [];
        let page = 1;
        let hasNext = true;
        let complete = true;
        while (hasNext && page <= maxPages) {
            const sep = path.includes('?') ? '&' : '?';
            try {
                const { data, meta } = await _getEnvelope(
                    `${path}${sep}page=${page}&page_size=${pageSize}`
                );
                rows.push(...(Array.isArray(data) ? data : []));
                hasNext = !!(meta && meta.pagination && meta.pagination.has_next);
            } catch (err) {
                // A mid-list failure must not discard the pages already
                // fetched in-session; report incompleteness so callers do not
                // persist a truncated list.
                console.warn('NodeCache: partial page fetch failed', path, page, err);
                complete = false;
                break;
            }
            page += 1;
        }
        return { rows, complete };
    }

    // Gateway-activity ranking (hex id -> packet count over the window),
    // 60 s memo. The v1 Node schema has no per-node gateway-packet counter;
    // the canonical source is the gateway collection.
    let _gatewayRankingMap = null;
    let _gatewayRankingAt = 0;
    const GATEWAY_RANKING_TTL_MS = 60 * 1000;
    async function _gatewayRanking() {
        const now = Date.now();
        if (_gatewayRankingMap && now - _gatewayRankingAt < GATEWAY_RANKING_TTL_MS) {
            return _gatewayRankingMap;
        }
        try {
            const rows = await _getEnvelope('/api/v1/gateways?hours=24&page_size=500');
            const map = new Map();
            (Array.isArray(rows.data) ? rows.data : []).forEach((gw) => {
                if (!gw || typeof gw.gateway_id !== 'string' || !gw.gateway_id.startsWith('!')) return;
                const id = parseInt(gw.gateway_id.slice(1), 16);
                if (Number.isFinite(id)) map.set(id, gw.packet_count || 0);
            });
            _gatewayRankingMap = map;
            _gatewayRankingAt = now;
        } catch (err) {
            console.warn('NodeCache: gateway ranking unavailable', err);
        }
        return _gatewayRankingMap;
    }

    const NodeCache = {
        /**
         * Load the full node list, restoring from cache if possible.
         * Always returns a Promise which resolves to the array of nodes.
         */
        load() {
            if (_loaded) return Promise.resolve(_nodes || []);
            if (_loadPromise) return _loadPromise;

            _loadPromise = new Promise(async (resolve) => {
                // 1. Try localStorage first
                const cached = _restoreFromLocalStorage();
                if (cached) {
                    _nodes = cached;
                    _loaded = true;
                    resolve(_nodes);
                    return;
                }

                // 2. Fetch from the v1 API (server-side pagination)
                try {
                    const { rows: fetched, complete } = await _paged(
                        '/api/v1/nodes?order=asc'
                    );
                    _nodes = fetched;
                    // Never persist a truncated list: a later page load would
                    // serve it instead of refetching.
                    if (complete && _nodes.length) _persistToLocalStorage(_nodes);
                } catch (err) {
                    console.error('NodeCache: Failed to fetch node list:', err);
                }
                if (!_nodes.length) {
                    const cached = _restoreFromLocalStorage();
                    if (cached) _nodes = cached;
                }

                _loaded = true;
                resolve(_nodes);
            });

            return _loadPromise;
        },

        /**
         * Return the node object with the given numeric ID (as number or string).
         * Resolves to null if not found.
         */
        async getNode(nodeId) {
            await this.load();
            const idStr = nodeId.toString();
            return _nodes.find((n) => n.node_id.toString() === idStr) || null;
        },

        /**
         * Search nodes (client-side). Returns array matching the query.
         * Matches against long_name, short_name, decimal ID and hex ID (with leading '!').
         * Limit optional.
         */
        async search(query, limit = 20) {
            // If we already have the full list, search locally
            if (_loaded) {
                const lower = query.toLowerCase();
                const results = _nodes.filter((node) => {
                    const nameLong = (node.long_name || '').toLowerCase();
                    const nameShort = (node.short_name || '').toLowerCase();
                    const hexId = `!${node.node_id.toString(16).padStart(8, '0')}`.toLowerCase();
                    const decId = node.node_id.toString();
                    return (
                        nameLong.includes(lower) ||
                        nameShort.includes(lower) ||
                        hexId.includes(lower) ||
                        decId.includes(lower)
                    );
                });
                return results.slice(0, limit);
            }

            // If we're still loading the big list, perform a quick focused query to the API
            try {
                const { rows: hits } = await _paged(
                    `/api/v1/nodes?q=${encodeURIComponent(query)}&sort=name`,
                    {
                        maxPages: 1,
                        pageSize: Math.min(limit, 500),
                    }
                );
                if (hits.length > 0) {
                    // Merge the quick results into our cache for future lookups
                    hits.forEach((n) => {
                        if (n && n.node_id !== undefined) {
                            NodeCache.addNode(n);
                        }
                    });
                    return hits;
                }
            } catch (err) {
                console.warn('NodeCache.search: fallback API search failed', err);
            }

            // As a last resort, wait for the full load to finish then search
            await this.load();
            return this.search(query, limit);
        },

        /**
         * Return top nodes ordered by packet_count_24h (desc) – used for "popular" list.
         */
        async topByPackets(limit = 20) {
            await this.load();
            const sorted = [..._nodes].sort((a, b) => (b.packet_count_24h || 0) - (a.packet_count_24h || 0));
            return sorted.slice(0, limit);
        },

        /**
         * Return nodes ordered by gateway activity (packets heard from them
         * as gateway in the last 24h) desc. Ranking comes from the v1
         * gateway collection; nodes it does not know about keep list order.
         */
        async topByGatewayPackets(limit = 20) {
            await this.load();
            const ranking = await _gatewayRanking();
            const score = (node) => (ranking && ranking.get(node.node_id)) || 0;
            const sorted = [..._nodes].sort((a, b) => score(b) - score(a));
            return sorted.slice(0, limit);
        },

        /**
         * Add/merge a node object into the cache (e.g., after individual API fetch).
         */
        addNode(node) {
            if (!node || typeof node.node_id === 'undefined') return;
            const existingIdx = _nodes ? _nodes.findIndex((n) => n.node_id === node.node_id) : -1;
            if (existingIdx >= 0) {
                _nodes[existingIdx] = { ..._nodes[existingIdx], ...node };
            } else {
                if (!_nodes) _nodes = [];
                _nodes.push(node);
            }
            _persistToLocalStorage(_nodes);
        },
    };

    // Expose globally
    window.NodeCache = NodeCache;

    // Start loading once the module bundle (api-client) is available, so the
    // shared envelope client handles the request; DOMContentLoaded fires after
    // deferred module scripts execute.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => NodeCache.load());
    } else {
        NodeCache.load();
    }
})();

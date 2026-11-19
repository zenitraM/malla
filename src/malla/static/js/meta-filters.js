/**
 * MallaFilters — one cached /api/v1/meta/filters fetch per page, shared by
 * every dropdown loader (node/packet/traceroute/map/chat filters).
 *
 * Data shape (data.*): channels[str], packet_channels[str],
 * hardware_models[[value,label]], packet_types[[value,label]],
 * roles[[value,label]].
 *
 * Usage:  const channels = await window.MallaFilters.channels();
 */
(function () {
    'use strict';

    let _promise = null;

    async function fetchFilters() {
        if (window.MallaAPI && typeof window.MallaAPI.getDetailed === 'function') {
            const { data } = await window.MallaAPI.getDetailed('/api/v1/meta/filters', { silent: true });
            return data || {};
        }
        const res = await fetch('/api/v1/meta/filters', { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        return body && body.data ? body.data : body || {};
    }

    const MallaFilters = {
        /** Cached promise resolving to the whole filters payload. */
        get() {
            if (!_promise) {
                // Do not cache the failure: a transient 5xx would strip every
                // dropdown for the page's lifetime. Clear and let the next
                // call retry.
                _promise = fetchFilters().catch((err) => {
                    console.warn('MallaFilters: failed to load filters', err);
                    _promise = null;
                    return {};
                });
            }
            return _promise;
        },
        channels() { return this.get().then((d) => d.channels || []); },
        packetChannels() { return this.get().then((d) => d.packet_channels || []); },
        hardwareModels() { return this.get().then((d) => d.hardware_models || []); },
        packetTypes() { return this.get().then((d) => d.packet_types || []); },
        roles() { return this.get().then((d) => d.roles || []); },
    };

    window.MallaFilters = MallaFilters;
})();

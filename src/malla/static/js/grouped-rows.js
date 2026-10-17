/**
 * Expandable grouped rows for the packets/traceroutes tables.
 *
 * The server-side grouped views (group_by=mesh_packet_id) collapse several
 * receptions into one row carrying group:{reception_count, gateways[]}.
 * This module renders the chevron toggle next to the reception badge and,
 * on demand, inserts a full-width row listing every reception of that mesh
 * packet (the representative/"primary" one first).
 *
 * Reception details come from GET /api/v1/packets/{id} (`other_receptions`
 * plus the packet itself) and are cached in-memory per mesh packet id for
 * the page lifetime; the expansion row itself is plain DOM and disappears
 * on the next table render (sort/page/filter/reload).
 */
(function () {
    'use strict';

    /** mesh_packet_id -> Promise<reception[]>; cleared on failure so it can retry. */
    const detailCache = new Map();

    // Parity with the grouped badge: the N-gateways count comes from the
    // page's filtered grouped query, so the expansion must ask with the same
    // window and membership or the two disagree on screen. Mirrors the
    // table query builders: global range first, explicit form bounds win,
    // "all" clears the window; gateway/portnum from the form filters.
    function expansionQuery() {
        const params = new URLSearchParams();
        const range = window.MallaRange && window.MallaRange.get ? window.MallaRange.get() : null;
        if (range && range.sinceEpoch) {
            params.set('since', new Date(range.sinceEpoch * 1000).toISOString());
        }
        if (range && range.untilEpoch) {
            params.set('until', new Date(range.untilEpoch * 1000).toISOString());
        }
        if (range && range.key === 'all') params.delete('since');
        const um = window.urlManager;
        const filters = um && typeof um.getCurrentFilters === 'function' ? um.getCurrentFilters() : null;
        if (filters) {
            // datetime-local strings need ISO conversion, mirroring the table
            // builder; explicit page times override the global range.
            if (filters.start_time) {
                const d = new Date(filters.start_time);
                if (!Number.isNaN(d.getTime())) params.set('since', d.toISOString());
            }
            if (filters.end_time) {
                const d = new Date(filters.end_time);
                if (!Number.isNaN(d.getTime())) params.set('until', d.toISOString());
            }
            if (filters.gateway_id) params.set('gateway_id', String(filters.gateway_id));
            if (filters.portnum) params.set('portnum', String(filters.portnum));
        }
        const qs = params.toString();
        return qs ? `?${qs}` : '';
    }

    function getJSON(path) {
        if (window.MallaAPI && typeof window.MallaAPI.get === 'function') {
            // silent: the failure UI below is the surfaced error path.
            return window.MallaAPI.get(path, { silent: true });
        }
        return fetch(path, { headers: { Accept: 'application/json' } }).then(
            (response) => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            }
        ).then((payload) => (payload && payload.data !== undefined ? payload.data : payload));
    }

    /** '!433d0c24' -> 1128074276, for /node/ links. */
    function nodeRef(gatewayId) {
        if (typeof gatewayId !== 'string' || !gatewayId.startsWith('!')) return null;
        const id = parseInt(gatewayId.slice(1), 16);
        return Number.isFinite(id) && id > 0 ? id : null;
    }

    function normalizeReception(row, isPrimary) {
        if (!row || typeof row !== 'object') return null;
        const gatewayId = row.gateway_id ?? null;
        const ts = Date.parse(row.timestamp ?? '');
        const rowId = Number(row.id);
        const hopStart = Number(row.hop_start);
        const hopLimit = Number(row.hop_limit);
        const hops = Number.isFinite(hopStart) && Number.isFinite(hopLimit)
            ? hopStart - hopLimit
            : (Number.isFinite(row.hop_count) ? row.hop_count : null);
        const relayNode = Number(row.relay_node);
        return {
            gatewayId,
            name: row.gateway_name || row.gateway_id || 'Unknown gateway',
            nodeRef: nodeRef(gatewayId),
            packetId: Number.isFinite(rowId) && rowId > 0 ? rowId : null,
            rssi: Number.isFinite(row.rssi) ? row.rssi : null,
            snr: Number.isFinite(row.snr) ? row.snr : null,
            hops: Number.isFinite(hops) && hops >= 0 ? hops : null,
            relayHex:
                Number.isFinite(relayNode) && relayNode !== 0
                    ? (relayNode & 0xff).toString(16).padStart(2, '0').toUpperCase()
                    : null,
            ok: row.processed_successfully !== false,
            channel: row.channel_id || null,
            ms: Number.isFinite(ts) ? ts : null,
            isPrimary: Boolean(isPrimary),
        };
    }

    /**
     * Primary (the packet itself) first, then the other receptions.
     * The primary is only a representative; expansion needs company.
     */
    function receptionsFromDetail(detail) {
        const receptions = [];
        const packet = detail && detail.packet;
        if (packet && (packet.gateway_id || packet.rssi != null || packet.snr != null)) {
            const primary = normalizeReception(packet, true);
            if (primary) primary.ms = Date.parse(packet.timestamp ?? '');
            if (primary) receptions.push(primary);
        }
        const others = Array.isArray(detail && detail.other_receptions)
            ? detail.other_receptions
            : [];
        others.forEach((row) => {
            const reception = normalizeReception(row, false);
            if (reception) receptions.push(reception);
        });
        return receptions.filter((r) => r && (r.gatewayId || r.rssi != null || r.snr != null));
    }

    async function loadReceptions(cacheKey, detailPath) {
        if (!detailCache.has(cacheKey)) {
            const pending = getJSON(detailPath).then(receptionsFromDetail);
            pending.catch(() => detailCache.delete(cacheKey));
            detailCache.set(cacheKey, pending);
        }
        return detailCache.get(cacheKey);
    }

    function tableColspan(row) {
        const table = row.closest && row.closest('table');
        const count = table ? table.querySelectorAll('thead th').length : 0;
        return String(Math.max(count, 1));
    }

    function formatOffset(ms) {
        return `${ms >= 0 ? '+' : '−'}${(Math.abs(ms) / 1000).toFixed(2)} s`;
    }

    function receptionRow(reception, primaryMs, showRelay) {
        const cells = [];

        // Gateway + link
        const name = reception.nodeRef
            ? nodeLink(reception.nodeRef, reception.name)
            : el('span', { className: 'group-reception-name' }, reception.name);
        cells.push(el('td', { className: 'group-tl' }, name));

        // Role tag
        cells.push(el('td', null, reception.isPrimary
            ? el('span', { className: 'badge bg-secondary group-reception-tag' }, 'primary')
            : el('span', { className: 'text-muted small' }, 'rx')));

        // RSSI / SNR
        cells.push(el('td', { className: 'num' },
            reception.rssi == null ? '—' : `${reception.rssi.toFixed(1)} dBm`));
        const snrSpan = reception.snr == null
            ? el('span', { className: 'text-muted' }, '—')
            : el('span', {
                className: getSignalClass(reception.snr),
            }, `${reception.snr.toFixed(2)} dB`);
        cells.push(el('td', { className: 'num' }, snrSpan));

        // Hops (0 = direct)
        cells.push(el('td', { className: 'num' },
            reception.hops == null ? '—' : String(reception.hops)));

        // Relay hint
        cells.push(el('td', { className: 'num mono' },
            showRelay ? (reception.relayHex || '—') : '—'));

        // Received at (absolute) + delta from primary
        const abs = reception.ms
            ? new Date(reception.ms).toLocaleTimeString(undefined, {
                hour: '2-digit', minute: '2-digit', second: '2-digit',
            })
            : '—';
        const delta = reception.isPrimary || primaryMs == null || reception.ms == null
            ? (reception.isPrimary ? '+0.00 s' : '—')
            : formatOffset(reception.ms - primaryMs);
        const absCell = el('td', { className: 'num', title: reception.ms ? new Date(reception.ms).toISOString() : '' }, abs);
        cells.push(absCell);
        cells.push(el('td', { className: 'num text-muted' }, delta));

        // Decode ok
        cells.push(el('td', { className: 'num center' }, reception.ok
            ? el('span', { className: 'text-success', title: 'decoded ok' }, '✓')
            : el('span', { className: 'text-warning', title: 'decode failed' }, '⚠')));

        // Per-reception packet link
        const linkCell = el('td', { className: 'num center' });
        if (reception.packetId != null) {
            linkCell.appendChild(el('a', {
                href: `/packet/${encodeURIComponent(reception.packetId)}`,
                className: 'group-reception-open',
                'aria-label': `Open packet ${reception.packetId} (${reception.name})`,
                title: `Open packet ${reception.packetId}`,
            }, icon('bi bi-box-arrow-up-right')));
        } else {
            linkCell.appendChild(el('span', { className: 'text-muted' }, '—'));
        }
        cells.push(linkCell);

        return el('tr', null, cells);
    }

    function getSignalClass(snrDb) {
        if (snrDb == null) return '';
        if (snrDb >= 8) return 'text-success fw-semibold';
        if (snrDb >= 4) return 'text-success';
        if (snrDb >= 0) return 'text-warning';
        return 'text-danger';
    }

    function skeletonContent() {
        return el('div', { className: 'group-receptions-loading' },
            el('span', { className: 'skeleton-line' }),
            el('span', { className: 'skeleton-line short' }));
    }

    function failureContent(packetId) {
        return el('div', { className: 'group-receptions-error' },
            el('span', null, `Receptions for packet ${packetId} failed to load. `),
            el('a', { href: `/packet/${encodeURIComponent(packetId)}`, className: 'group-reception-retry' },
                `Retry from packet ${packetId}`));
    }

    /** Sort state per expanded table; cleared when the expansion row dies. */
    const sortStates = new WeakMap();

    const COLUMN_SORTS = {
        gateway: (a, b) => (a.name || '').localeCompare(b.name || ''),
        role: (a, b) => (b.isPrimary ? 1 : 0) - (a.isPrimary ? 1 : 0),
        rssi: (a, b) => (a.rssi ?? -999) - (b.rssi ?? -999),
        snr: (a, b) => (a.snr ?? -999) - (b.snr ?? -999),
        hops: (a, b) => (a.hops ?? 1e9) - (b.hops ?? 1e9),
        relay: (a, b) => (a.relayHex || '').localeCompare(b.relayHex || ''),
        received: (a, b) => (a.ms ?? 0) - (b.ms ?? 0),
        delta: (a, b) => Math.abs(a.ms - (b._anchor ?? 0)) - Math.abs(b.ms - (a._anchor ?? 0)),
        ok: (a, b) => (a.ok ? 1 : 0) - (b.ok ? 1 : 0),
    };

    function applySort(tbody, key, dir, rows, anchorMs) {
        const cmp = COLUMN_SORTS[key];
        if (!cmp) return;
        const sorted = rows
            .map((r) => ({ ...r, _anchor: anchorMs }))
            .sort((a, b) => (dir === 'asc' ? cmp(a, b) : -cmp(a, b)));
        tbody.replaceChildren(
            ...sorted.map((r) => receptionRow(r, anchorMs, rows.some((x) => x.relayHex)))
        );
    }

    function renderReceptions(cell, receptions, sortState) {
        const primaryMs = receptions.length && receptions[0].isPrimary ? receptions[0].ms : null;
        const others = receptions.filter((r) => !r.isPrimary);
        if (others.length === 0) {
            setChildren(cell, el('div', { className: 'group-receptions-empty text-muted' },
                'No additional reception data'));
            return;
        }
        const showRelay = receptions.some((r) => r.relayHex);

        const table = el('table', { className: 'table table-sm table-borderless group-receptions-table mb-0' });
        const head = [
            { key: 'gateway', label: 'Gateway', cls: 'group-tl' },
            { key: 'role', label: 'Role' },
            { key: 'rssi', label: 'RSSI', num: true },
            { key: 'snr', label: 'SNR', num: true },
            { key: 'hops', label: 'Hops', num: true, title: 'Hops travelled (0 = direct)' },
            { key: 'relay', label: 'Relay', num: true, title: 'Last-byte relay hint' },
            { key: 'received', label: 'Received at', num: true },
            { key: 'delta', label: 'Δ', num: true, title: 'Delta vs primary reception' },
            { key: 'ok', label: 'OK', num: true, center: true, title: 'Payload decode' },
            { key: null, label: '', num: true, center: true },
        ];
        const thead = el('thead', null, el('tr', null, head.map((cidx) => {
            const th = el('th', {
                class: `${cidx.cls || ''} ${cidx.num ? 'num' : ''} ${cidx.center ? 'center' : ''}`
                    .trim() || null,
                scope: 'col',
                title: cidx.title || null,
            }, cidx.label);
            if (cidx.key) {
                th.classList.add('group-sortable');
                th.tabIndex = 0;
                th.setAttribute('role', 'columnheader');
                th.setAttribute('aria-sort', sortState && sortState.key === cidx.key
                    ? (sortState.dir === 'asc' ? 'ascending' : 'descending')
                    : 'none');
                th.dataset.key = cidx.key;
                const arrow = el('span', { className: 'group-sort-arrow', 'aria-hidden': 'true' },
                    sortState && sortState.key === cidx.key ? (sortState.dir === 'asc' ? '▲' : '▼') : '↕');
                th.appendChild(arrow);
                const activate = () => {
                    const cur = sortStates.get(cell) || { key: null, dir: 'desc' };
                    const dir = cur.key === cidx.key && cur.dir === 'asc' ? 'desc' : 'asc';
                    sortStates.set(cell, { key: cidx.key, dir });
                    applySort(tbody, cidx.key, dir, receptions, primaryMs);
                    // Reflect state on the header: a11y + the arrow glyph.
                    thead
                        .querySelectorAll('th.group-sortable')
                        .forEach((th) => {
                            const active = th.dataset.key === cidx.key;
                            th.setAttribute(
                                'aria-sort',
                                active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'
                            );
                            const arrow = th.querySelector('.group-sort-arrow');
                            if (arrow) arrow.textContent = active ? (dir === 'asc' ? '▲' : '▼') : '↕';
                        });
                };
                th.addEventListener('click', activate);
                th.addEventListener('keydown', (ev) => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        activate();
                    }
                });
            }
            return th;
        })));
        const tbody = el('tbody');
        if (sortState) {
            applySort(tbody, sortState.key, sortState.dir, receptions, primaryMs);
        } else {
            receptions.forEach((r) => tbody.appendChild(receptionRow(r, primaryMs, showRelay)));
        }
        table.appendChild(thead);
        table.appendChild(tbody);
        setChildren(cell, el('div', { className: 'group-receptions-wrap table-responsive' }, table));
    }

    function collapse(button) {
        const row = button.closest('tr');
        button.setAttribute('aria-expanded', 'false');
        delete button.dataset.loading;
        if (row) {
            const expansion = row.nextElementSibling;
            if (expansion && expansion.classList.contains('group-receptions-row')) {
                expansion.remove();
            }
        }
    }

    async function expand(button) {
        const row = button.closest('tr');
        if (!row) return;

        const packetId = button.dataset.packetId;
        const cacheKey = button.dataset.meshPacketId || String(packetId);
        const expansionRow = el('tr', { className: 'group-receptions-row' });
        const cell = el('td', { colspan: tableColspan(row) });
        expansionRow.appendChild(cell);
        setChildren(cell, skeletonContent());
        row.insertAdjacentElement('afterend', expansionRow);
        button.setAttribute('aria-expanded', 'true');
        button.setAttribute('aria-controls', `receptions-${encodeURIComponent(cacheKey)}`);
        expansionRow.id = `receptions-${encodeURIComponent(cacheKey)}`;
        button.dataset.loading = '1';

        try {
            const receptions = await loadReceptions(
                cacheKey,
                `/api/v1/packets/${encodeURIComponent(packetId)}${expansionQuery()}`
            );
            if (button.getAttribute('aria-expanded') !== 'true') return; // collapsed meanwhile
            renderReceptions(cell, receptions, sortStates.get(cell));
        } catch (error) {
            console.error('Failed to load receptions for packet', packetId, error);
            if (button.getAttribute('aria-expanded') !== 'true') return;
            setChildren(cell, failureContent(packetId));
            if (window.MallaToast && typeof window.MallaToast.error === 'function') {
                window.MallaToast.error(
                    `Receptions for packet ${packetId} failed to load — retry from the packet page.`,
                    { title: 'Receptions unavailable' }
                );
            }
        } finally {
            delete button.dataset.loading;
        }
    }

    function toggle(button) {
        if (button.dataset.loading === '1') return;
        if (button.getAttribute('aria-expanded') === 'true') {
            collapse(button);
        } else {
            expand(button);
        }
    }

    /**
     * Chevron toggle + reception badge for one grouped row.
     * @param {object} options {meshPacketId, packetId, label, title}
     * @returns {DocumentFragment} fragment for the table cell
     */
    function groupCell(options) {
        const button = el('button', {
            type: 'button',
            className: 'group-expand-btn',
            'aria-expanded': 'false',
            'aria-label': `Toggle receptions for packet ${options.packetId}`,
            title: 'Show receptions',
        }, icon('bi bi-chevron-right'));
        button.dataset.packetId = String(options.packetId);
        if (options.meshPacketId != null) {
            button.dataset.meshPacketId = String(options.meshPacketId);
        }
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            toggle(button);
        });

        const badge = el('span', {
            className: 'badge bg-info',
            title: options.title || options.label,
        }, options.label);

        const fragment = document.createDocumentFragment();
        fragment.appendChild(button);
        fragment.appendChild(document.createTextNode(' '));
        fragment.appendChild(badge);
        return fragment;
    }

    window.MallaGroupedRows = { groupCell };
})();

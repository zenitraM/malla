/**
 * MallaLinkTimeline — right-side drawer with the per-day SNR history of one
 * node pair, served by GET /api/v1/{a}/{b}/link history rollups.
 *
 * MallaLinkTimeline.show(nodeA, nodeB, {indirect}) — node ids in any form the
 * API accepts; `indirect` switches to the route (multi-hop) rollup. The
 * drawer can flip between both modes; ESC, the backdrop or the close button
 * dismiss it and focus returns to the invoking element.
 */
(function () {
    'use strict';

    const HISTORY_DAYS = 90;

    let backdrop = null;
    let drawer = null;
    let chartDiv = null;
    let lastFocus = null;
    let themeDisposer = null;
    let currentKey = null; // `${a}|${b}|${indirect}` of the rendered data
    const dataCache = new Map(); // key -> days[]; page-lifetime

    function h(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text instanceof Node) node.appendChild(text);
        else if (text != null) node.textContent = String(text);
        return node;
    }

    function getJSON(path) {
        if (window.MallaAPI && typeof window.MallaAPI.get === 'function') {
            return window.MallaAPI.get(path, { silent: true });
        }
        return fetch(path, { headers: { Accept: 'application/json' } }).then(
            (r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            }
        ).then((payload) => (payload && payload.data !== undefined ? payload.data : payload));
    }

    function fmtNode(id) {
        const raw = String(id);
        if (/^\d+$/.test(raw)) {
            const hex = parseInt(raw, 10).toString(16).padStart(8, '0');
            return `!${hex.slice(-8)}`;
        }
        return raw.startsWith('!') ? raw : `!${raw}`;
    }

    function chip(label, value, className) {
        const chipEl = h('span', 'lt-chip');
        if (className) chipEl.classList.add(className);
        chipEl.appendChild(h('span', 'lt-chip-label', label));
        chipEl.appendChild(h('strong', 'lt-chip-value', value));
        return chipEl;
    }

    function loadDays(nodeA, nodeB, indirect) {
        const key = `${nodeA}|${nodeB}|${indirect ? 1 : 0}`;
        const path =
            `/api/v1/links/${encodeURIComponent(nodeA)}/` +
            `${encodeURIComponent(nodeB)}/history?days=${HISTORY_DAYS}` +
            `&indirect=${indirect ? 'true' : 'false'}`;
        if (!dataCache.has(key)) {
            const pending = getJSON(path).then((data) =>
                Array.isArray(data && data.days) ? data.days : []
            );
            pending.catch(() => dataCache.delete(key));
            dataCache.set(key, pending);
        }
        return dataCache.get(key);
    }

    function summaryChips(days) {
        const chips = h('div', 'lt-chips');
        chips.setAttribute('role', 'list');
        const add = (label, value) => chips.appendChild(chip(label, value));

        add('days seen', String(days.length));
        add(
            'packets',
            String(days.reduce((sum, row) => sum + (row.packet_count || 0), 0))
        );

        const weighted = [];
        let weight = 0;
        days.forEach((row) => {
            if (row.snr_avg != null && row.packet_count) {
                weighted.push(row.snr_avg * row.packet_count);
                weight += row.packet_count;
            }
        });
        const avg = weight
            ? (weighted.reduce((a, b) => a + b, 0) / weight).toFixed(2) + ' dB'
            : 'n/a';
        add('avg SNR', avg);

        const maxes = days.map((r) => r.snr_max != null ? r.snr_max : r.snr_avg).filter((v) => v != null);
        const mins = days.map((r) => r.snr_min != null ? r.snr_min : r.snr_avg).filter((v) => v != null);
        add('best', maxes.length ? `${Math.max(...maxes).toFixed(1)} dB` : 'n/a');
        add('worst', mins.length ? `${Math.min(...mins).toFixed(1)} dB` : 'n/a');
        return chips;
    }

    function renderChart(days) {
        const hasBand = days.some((r) => r.snr_min != null && r.snr_max != null);
        const x = days.map((r) => r.day);

        const traces = [];
        if (hasBand) {
            const fill = 'rgba(14, 116, 144, 0.18)';
            traces.push(
                {
                    x, y: days.map((r) => r.snr_max),
                    name: 'max', mode: 'lines',
                    line: { color: fill, width: 1 },
                    fillcolor: fill, showlegend: true,
                },
                {
                    x, y: days.map((r) => r.snr_min),
                    name: 'min–max', mode: 'lines', fill: 'tonexty',
                    line: { color: fill, width: 1 },
                    fillcolor: fill, showlegend: true,
                }
            );
        }
        traces.push({
            x,
            y: days.map((r) => (r.snr_avg != null ? r.snr_avg : null)),
            name: 'avg SNR', mode: 'lines+markers',
            line: { color: '#2563eb', width: 2 }, connectgaps: true,
        });
        traces.push({
            type: 'bar', x, y: days.map((r) => r.packet_count),
            name: 'packets', yaxis: 'y2',
            marker: { color: 'rgba(21, 128, 61, 0.45)' },
        });

        const layoutOverrides = {
            margin: { t: 8, r: 8, b: 34, l: 44 },
            legend: { orientation: 'h', y: 1.12 },
            xaxis: { title: { text: 'day' } },
            yaxis: { title: { text: 'SNR (dB)' } },
            yaxis2: {
                overlaying: 'y', side: 'right', showgrid: false,
                title: { text: 'packets' },
            },
            bargap: 0.25,
        };
        const layout = window.MallaPlotlyTheme
            ? window.MallaPlotlyTheme.layout(layoutOverrides)
            : layoutOverrides;
        const config = window.MallaPlotlyTheme
            ? window.MallaPlotlyTheme.config()
            : { responsive: true, displayModeBar: false };
        window.Plotly.react(chartDiv, traces, layout, config);
    }

    function renderBody(nodeA, nodeB, indirect) {
        const body = drawer.querySelector('.lt-body');
        const subtitle = drawer.querySelector('.lt-subtitle');
        subtitle.textContent = `${fmtNode(nodeA)} ⇄ ${fmtNode(nodeB)}`;

        const mode = h('div', 'lt-mode btn-group btn-group-sm');
        mode.setAttribute('role', 'group');
        mode.setAttribute('aria-label', 'History mode');
        const directBtn = h('button', 'btn btn-outline-secondary', 'Direct');
        const indirectBtn = h('button', 'btn btn-outline-secondary', 'Indirect');
        directBtn.type = indirectBtn.type = 'button';
        if (!indirect) directBtn.classList.add('active');
        else indirectBtn.classList.add('active');
        directBtn.addEventListener('click', () => show(nodeA, nodeB, { indirect: false }));
        indirectBtn.addEventListener('click', () => show(nodeA, nodeB, { indirect: true }));
        mode.append(directBtn, indirectBtn);

        const mount = h('div', 'lt-mount');
        setChildren(body, mode, h('div', 'lt-note text-muted',
            indirect
                ? 'Multi-hop route rollup: endpoints of traceroute paths, per-day mean path SNR.'
                : 'Direct receptions between the pair, per-day from the link rollup.'), mount);

        if (themeDisposer) { themeDisposer(); themeDisposer = null; }
        currentKey = `${nodeA}|${nodeB}|${indirect ? 1 : 0}`;

        if (!window.Plotly) {
            setChildren(mount, h('div', 'lt-empty text-muted',
                'Plotly is unavailable on this page.'));
            return;
        }

        setChildren(mount, h('div', 'lt-loading text-muted', 'Loading history…'));
        loadDays(nodeA, nodeB, indirect).then((days) => {
            if (currentKey !== `${nodeA}|${nodeB}|${indirect ? 1 : 0}`) return;
            const chips = summaryChips(days);
            const header = drawer.querySelector('.lt-chipbar');
            setChildren(header, chips);

            if (days.length === 0) {
                const empty = h('div', 'lt-empty');
                empty.appendChild(h('div', 'lt-empty-icon', '◌'));
                empty.appendChild(h('div', null, 'No link history for this pair.'));
                empty.appendChild(h('div', 'text-muted',
                    'Receptions appear once the capture daemon folds them into the daily rollups.'));
                setChildren(mount, empty);
                return;
            }

            mount.replaceChildren();
            const chart = h('div', 'lt-chart');
            mount.appendChild(chart);
            chartDiv = chart;
            renderChart(days);
            if (window.MallaPlotlyTheme) {
                themeDisposer = window.MallaPlotlyTheme.onThemeChange(() => {
                    if (document.contains(chart)) renderChart(days);
                });
            }
        }).catch((error) => {
            console.error('Link history failed:', error);
            if (currentKey !== `${nodeA}|${nodeB}|${indirect ? 1 : 0}`) return;
            const retry = h('button', 'btn btn-sm btn-outline-primary', 'Retry');
            retry.type = 'button';
            retry.addEventListener('click', () => show(nodeA, nodeB, { indirect }));
            setChildren(mount, h('div', 'lt-empty', 'Link history failed to load.'), retry);
        });
    }

    function onKeydown(event) {
        if (!drawer) return;
        if (event.key === 'Escape') {
            event.stopPropagation();
            close();
            return;
        }
        if (event.key !== 'Tab') return;
        // Focus trap: cycle within the drawer.
        const focusables = [...drawer.querySelectorAll(
            'button:not([disabled]), a[href], input, select, [tabindex]:not([tabindex="-1"])'
        )].filter((node) => node.offsetParent !== null);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        } else if (!drawer.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
        }
    }

    function close() {
        if (!backdrop) return;
        document.removeEventListener('keydown', onKeydown, true);
        if (themeDisposer) { themeDisposer(); themeDisposer = null; }
        if (chartDiv && window.Plotly && window.Plotly.purge) {
            try { window.Plotly.purge(chartDiv); } catch (e) { /* already gone */ }
        }
        chartDiv = null;
        drawer = null;
        currentKey = null;
        const closing = backdrop;
        backdrop = null;
        closing.remove();
        if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
        lastFocus = null;
    }

    /**
     * Open the drawer for a node pair.
     * @param {string|number} nodeA
     * @param {string|number} nodeB
     * @param {{indirect?: boolean}} [options]
     */
    function show(nodeA, nodeB, options = {}) {
        const indirect = Boolean(options.indirect);
        // While already open, keep the captured focus: close() clears it and
        // the trigger lives inside the drawer being discarded.
        if (!backdrop) {
            lastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        }
        close();

        backdrop = h('div', 'lt-backdrop');
        drawer = h('aside', 'lt-drawer');
        drawer.setAttribute('role', 'dialog');
        drawer.setAttribute('aria-modal', 'true');
        drawer.setAttribute('aria-label', 'Link history');
        const headingId = 'lt-title';
        drawer.setAttribute('aria-labelledby', headingId);

        const header = h('div', 'lt-header');
        const title = h('h5', 'lt-title', 'Link history');
        title.id = headingId;
        const titleWrap = h('div');
        titleWrap.appendChild(title);
        titleWrap.appendChild(h('div', 'lt-subtitle text-muted', ''));
        const closeBtn = h('button', 'btn-close', '');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close link history');
        closeBtn.addEventListener('click', close);
        header.append(titleWrap, closeBtn);

        const chipbar = h('div', 'lt-chipbar');
        const body = h('div', 'lt-body');
        drawer.append(header, chipbar, body);
        backdrop.appendChild(drawer);
        backdrop.addEventListener('click', (event) => {
            if (event.target === backdrop) close();
        });
        document.body.appendChild(backdrop);
        document.addEventListener('keydown', onKeydown, true);

        closeBtn.focus();
        renderBody(nodeA, nodeB, indirect);
    }

    window.MallaLinkTimeline = { show, close };
})();

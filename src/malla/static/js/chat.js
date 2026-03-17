(function () {
    'use strict';

    const POLL_INTERVAL_MS  = 3000;
    const INITIAL_LIMIT     = 300;
    const POLL_LIMIT        = 100;
    const NICK_COLORS       = 12;
    const BROADCAST         = 4294967295; // 0xFFFFFFFF

    const messagesEl = document.getElementById('chatMessages');
    const statusEl   = document.getElementById('chatStatus');
    const channelSel = document.getElementById('channelFilter');
    const scrollBtn  = document.getElementById('scrollBottomBtn');

    var lastId    = 0;
    var pollTimer = null;

    var nodeCache = {};
    var messagesByMesh = new Map();
    var seenPacketIds = new Set();

    // ----- helpers -----

    function nickColorClass(nodeId) {
        return 'nick-color-' + ((nodeId >>> 0) % NICK_COLORS);
    }

    function chatFormatTime(unixTs) {
        if (typeof formatTimestamp === 'function') {
            return formatTimestamp(unixTs, 'time');
        }
        var d = new Date(unixTs * 1000);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function esc(str) {
        var el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    }

    function nodeName(nodeId) {
        var n = nodeCache[String(nodeId)];
        return n ? n.name : ('!' + (nodeId >>> 0).toString(16).padStart(8, '0'));
    }

    function nodeShort(nodeId) {
        var n = nodeCache[String(nodeId)];
        return n ? (n.short || n.name) : '';
    }

    function gwDisplayName(gwStr) {
        if (!gwStr || !gwStr.startsWith('!')) return gwStr || '?';
        try {
            var nid = parseInt(gwStr.substring(1), 16);
            return nodeShort(nid) || gwStr;
        } catch (e) { return gwStr; }
    }

    function gwNodeId(gwStr) {
        if (!gwStr || !gwStr.startsWith('!')) return null;
        try { return parseInt(gwStr.substring(1), 16); } catch (e) { return null; }
    }

    function computeHops(hs, hl) {
        return (hs != null && hl != null) ? (hs - hl) : null;
    }

    function hopsLabel(msg) {
        if (msg.minHops == null) return '?';
        if (msg.minHops === msg.maxHops) return String(msg.minHops);
        return msg.minHops + '-' + msg.maxHops;
    }

    function isScrolledToBottom() {
        return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 60;
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function sortedRxList(rxList) {
        return rxList.slice().sort(function (a, b) {
            var ha = a.hops != null ? a.hops : 999;
            var hb = b.hops != null ? b.hops : 999;
            if (ha !== hb) return ha - hb;
            var ra = a.rl || 0;
            var rb = b.rl || 0;
            return ra - rb;
        });
    }

    // ----- rx popover -----

    var activePopover = null;  // { el, badge, meshId, pinned }

    function closePopover() {
        if (!activePopover) return;
        activePopover.el.remove();
        activePopover = null;
    }

    function buildPopoverContent(msg) {
        var sorted = sortedRxList(msg.rxList);
        var rows = '';
        for (var k = 0; k < sorted.length; k++) {
            var rx = sorted[k];
            var gwName = esc(gwDisplayName(rx.gw));
            var gwNid = gwNodeId(rx.gw);
            var gwCell = gwNid
                ? '<a href="/node/' + gwNid + '" class="rx-pop-link">' + gwName + '</a>'
                : gwName;

            var relayCell = '';
            if (rx.rl) {
                var rHex = (rx.rl >>> 0).toString(16);
                relayCell = esc(rHex.slice(-2));
            }

            rows +=
                '<tr>' +
                    '<td><a href="/packet/' + rx.id + '" class="rx-pop-link">#' + rx.id + '</a></td>' +
                    '<td>' + gwCell + '</td>' +
                    '<td>' + (rx.hops != null ? rx.hops : '?') + '</td>' +
                    '<td>' + (rx.rs != null ? rx.rs : '') + '</td>' +
                    '<td>' + (rx.sn != null ? (typeof rx.sn === 'number' ? rx.sn.toFixed(1) : rx.sn) : '') + '</td>' +
                    '<td>' + relayCell + '</td>' +
                '</tr>';
        }

        return (
            '<div class="rx-pop-header">' +
                sorted.length + ' reception' + (sorted.length > 1 ? 's' : '') +
            '</div>' +
            '<table class="rx-pop-table">' +
                '<thead><tr>' +
                    '<th>Pkt</th><th>Gateway</th><th>Hops</th><th>RSSI</th><th>SNR</th><th>Relay</th>' +
                '</tr></thead>' +
                '<tbody>' + rows + '</tbody>' +
            '</table>'
        );
    }

    function positionPopover(popEl, badge) {
        var rect = badge.getBoundingClientRect();
        popEl.style.position = 'fixed';
        popEl.style.visibility = 'hidden';
        popEl.style.display = 'block';
        document.body.appendChild(popEl);

        var popRect = popEl.getBoundingClientRect();
        var left = rect.right - popRect.width;
        var top = rect.bottom + 4;

        if (top + popRect.height > window.innerHeight - 8) {
            top = rect.top - popRect.height - 4;
        }
        if (left < 8) left = 8;

        popEl.style.left = left + 'px';
        popEl.style.top = top + 'px';
        popEl.style.visibility = 'visible';
    }

    function showPopover(badge, meshId, pinned) {
        var msg = messagesByMesh.get(meshId);
        if (!msg) return;

        if (activePopover && activePopover.meshId === meshId) {
            if (pinned && !activePopover.pinned) {
                activePopover.pinned = true;
                activePopover.el.classList.add('rx-pop-pinned');
                return;
            }
            if (pinned && activePopover.pinned) {
                closePopover();
                return;
            }
            return;
        }

        closePopover();

        var pop = document.createElement('div');
        pop.className = 'rx-popover' + (pinned ? ' rx-pop-pinned' : '');
        pop.innerHTML = buildPopoverContent(msg);

        pop.addEventListener('mousedown', function (e) { e.stopPropagation(); });

        activePopover = { el: pop, badge: badge, meshId: meshId, pinned: pinned };
        positionPopover(pop, badge);
    }

    function refreshPopover(meshId) {
        if (!activePopover || activePopover.meshId !== meshId) return;
        var msg = messagesByMesh.get(meshId);
        if (!msg) return;
        activePopover.el.innerHTML = buildPopoverContent(msg);
    }

    document.addEventListener('mousedown', function (e) {
        if (!activePopover) return;
        if (activePopover.el.contains(e.target)) return;
        if (activePopover.badge.contains(e.target)) return;
        closePopover();
    });

    // ----- rendering -----

    function buildLine(msg) {
        var line = document.createElement('div');
        line.className = 'chat-line';
        line.dataset.meshId = msg.meshId || msg.firstId;

        var isDm = msg.toId && msg.toId !== BROADCAST;
        var display = esc(nodeShort(msg.fromId) || nodeName(msg.fromId));
        var full = esc(nodeName(msg.fromId));

        line.innerHTML =
            '<span class="chat-ts timestamp-display" data-timestamp="' + msg.timestamp + '" data-timestamp-format="time">' +
                chatFormatTime(msg.timestamp) +
            '</span>' +
            '<span class="chat-nick ' + nickColorClass(msg.fromId) + '">' +
                '<a href="/node/' + msg.fromId + '" class="node-link" ' +
                    'data-node-id="' + msg.fromId + '" ' +
                    'data-bs-toggle="tooltip" data-bs-placement="top" data-bs-html="true" ' +
                    'data-bs-title="Loading..." title="' + full + '">' +
                    display +
                '</a>' +
            '</span>' +
            '<span class="chat-sep">' + (isDm ? '&rarr;' : '|') + '</span>' +
            '<span class="chat-text' + (isDm ? ' chat-dm' : '') + '">' + esc(msg.text) + '</span>' +
            '<span class="chat-meta">' +
                (msg.channel ? '<span class="chat-channel">' + esc(msg.channel) + '</span>' : '') +
                '<a href="/packet/' + msg.firstId + '" title="Packet #' + msg.firstId + '">' +
                    '#' + msg.firstId +
                '</a>' +
                '<span class="chat-rx-badge badge bg-secondary" data-mesh-id="' + (msg.meshId || msg.firstId) + '">' +
                    'rx' + msg.rxList.length + ' h' + hopsLabel(msg) +
                '</span>' +
            '</span>';

        return line;
    }

    function refreshBadge(entry) {
        if (!entry.el) return;
        var badge = entry.el.querySelector('.chat-rx-badge');
        if (!badge) return;
        badge.textContent = 'rx' + entry.rxList.length + ' h' + hopsLabel(entry);
        refreshPopover(entry.meshId);
    }

    // Badge hover / click delegation
    var hoverTimer = null;

    messagesEl.addEventListener('mouseover', function (e) {
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        var meshId = badge.dataset.meshId;
        if (!meshId) return;
        // parse meshId back to number if needed
        var key = isNaN(meshId) ? meshId : Number(meshId);
        if (activePopover && activePopover.pinned) return;
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(function () {
            showPopover(badge, key, false);
        }, 120);
    });

    messagesEl.addEventListener('mouseout', function (e) {
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        clearTimeout(hoverTimer);
        if (activePopover && !activePopover.pinned) {
            setTimeout(function () {
                if (activePopover && !activePopover.pinned) {
                    var popHover = activePopover.el.matches(':hover');
                    var badgeHover = badge.matches(':hover');
                    if (!popHover && !badgeHover) closePopover();
                }
            }, 200);
        }
    });

    document.addEventListener('mouseover', function (e) {
        if (!activePopover || activePopover.pinned) return;
        if (activePopover.el.contains(e.target)) return;
        if (activePopover.badge.contains(e.target)) return;
    });

    document.addEventListener('mouseout', function (e) {
        if (!activePopover || activePopover.pinned) return;
        setTimeout(function () {
            if (!activePopover || activePopover.pinned) return;
            var popHover = activePopover.el.matches(':hover');
            var badgeHover = activePopover.badge.matches(':hover');
            if (!popHover && !badgeHover) closePopover();
        }, 200);
    });

    messagesEl.addEventListener('click', function (e) {
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        e.preventDefault();
        e.stopPropagation();
        var meshId = badge.dataset.meshId;
        if (!meshId) return;
        var key = isNaN(meshId) ? meshId : Number(meshId);
        showPopover(badge, key, true);
    });

    // ----- ingestion -----

    function ingestPacket(p) {
        if (seenPacketIds.has(p.i)) return false;
        seenPacketIds.add(p.i);

        var meshId = p.m || p.i;
        var hops = computeHops(p.hs, p.hl);
        var rxEntry = { gw: p.gw, rs: p.rs, sn: p.sn, hops: hops, rl: p.rl, id: p.i };

        var existing = messagesByMesh.get(meshId);
        if (existing) {
            existing.rxList.push(rxEntry);
            if (hops != null) {
                if (existing.minHops == null || hops < existing.minHops) existing.minHops = hops;
                if (existing.maxHops == null || hops > existing.maxHops) existing.maxHops = hops;
            }
            refreshBadge(existing);
            return false;
        }

        var msg = {
            meshId: meshId,
            firstId: p.i,
            timestamp: p.t,
            fromId: p.f,
            toId: p.d,
            channel: p.ch,
            text: p.tx,
            minHops: hops,
            maxHops: hops,
            rxList: [rxEntry],
            el: null,
        };
        var el = buildLine(msg);
        msg.el = el;
        messagesByMesh.set(meshId, msg);
        messagesEl.appendChild(el);
        return true;
    }

    // ----- API -----

    function fetchUrl(afterId, limit) {
        var params = new URLSearchParams();
        if (afterId > 0) params.set('after_id', afterId);
        params.set('limit', limit);
        var ch = channelSel.value;
        if (ch) params.set('channel', ch);
        return '/api/chat/messages?' + params.toString();
    }

    function removeLoading() {
        var el = document.getElementById('chatLoading');
        if (el) el.remove();
    }

    async function loadInitial() {
        try {
            var resp = await fetch(fetchUrl(0, INITIAL_LIMIT));
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            removeLoading();
            Object.assign(nodeCache, data.nodes || {});
            data.packets.forEach(ingestPacket);

            lastId = data.last_id;
            scrollToBottom();
            setStatus('live', 'Live');

            if (typeof reinitializeTooltips === 'function') reinitializeTooltips();
        } catch (err) {
            console.error('Chat initial load error:', err);
            removeLoading();
            setStatus('error', 'Error');
        }
    }

    async function poll() {
        try {
            var resp = await fetch(fetchUrl(lastId, POLL_LIMIT));
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            var wasAtBottom = isScrolledToBottom();
            Object.assign(nodeCache, data.nodes || {});

            var newLines = 0;
            data.packets.forEach(function (p) {
                if (ingestPacket(p)) newLines++;
            });

            lastId = data.last_id;

            if (newLines > 0) {
                if (typeof reinitializeTooltips === 'function') reinitializeTooltips();
                if (wasAtBottom) scrollToBottom();
                else scrollBtn.classList.remove('d-none');
            }

            setStatus('live', 'Live');
        } catch (err) {
            console.error('Chat poll error:', err);
            setStatus('error', 'Error');
        }
    }

    // ----- UI helpers -----

    function setStatus(type, text) {
        statusEl.textContent = text;
        statusEl.className = 'badge';
        if (type === 'live')    statusEl.classList.add('bg-success');
        if (type === 'error')   statusEl.classList.add('bg-danger');
        if (type === 'loading') statusEl.classList.add('bg-secondary');
    }

    function startPolling() {
        stopPolling();
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function resetChat() {
        stopPolling();
        closePopover();
        lastId = 0;
        seenPacketIds.clear();
        messagesByMesh.clear();

        messagesEl.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
            var tip = bootstrap.Tooltip.getInstance(el);
            if (tip) tip.dispose();
        });

        messagesEl.innerHTML =
            '<div id="chatLoading" class="chat-loading">' +
                '<div class="spinner-border spinner-border-sm text-secondary" role="status"></div>' +
                '<span class="text-muted ms-2">Loading messages…</span>' +
            '</div>';

        setStatus('loading', 'Connecting…');
        loadInitial().then(startPolling);
    }

    async function loadChannels() {
        try {
            var resp = await fetch('/api/meshtastic/channels');
            if (!resp.ok) return;
            var data = await resp.json();
            (data.channels || []).forEach(function (ch) {
                var opt = document.createElement('option');
                opt.value = ch;
                opt.textContent = ch;
                channelSel.appendChild(opt);
            });
        } catch (err) {
            console.error('Failed to load channels:', err);
        }
    }

    // ----- events -----

    messagesEl.addEventListener('scroll', function () {
        if (isScrolledToBottom()) scrollBtn.classList.add('d-none');
    });

    scrollBtn.addEventListener('click', function () {
        scrollToBottom();
        scrollBtn.classList.add('d-none');
    });

    channelSel.addEventListener('change', resetChat);

    if (window.timezoneToggle) {
        window.timezoneToggle.setTimezone = function (tz) {
            if (!['local', 'utc'].includes(tz)) return;
            localStorage.setItem('malla-timezone-preference', tz);
            window.timezoneToggle.updateToggleButton();
            window.currentTimezone = tz;

            document.querySelectorAll('#chatMessages .chat-ts[data-timestamp]').forEach(function (el) {
                var ts = parseFloat(el.getAttribute('data-timestamp'));
                if (!isNaN(ts)) el.textContent = chatFormatTime(ts);
            });

            window.dispatchEvent(new CustomEvent('timezoneChanged', {
                detail: { timezone: tz, skipReload: true }
            }));
        };
    }

    // ----- init -----
    loadChannels();
    loadInitial().then(startPolling);
})();

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

    var nodeCache = {};          // string node_id -> {name, short}
    var messagesByMesh = new Map(); // mesh_packet_id -> msg state
    var seenPacketIds = new Set();

    // mesh_packet_id -> msg state (for reply lookups)
    // Same objects as messagesByMesh but keyed by the Meshtastic mesh_packet_id
    // (the protocol-level ID, not the DB row id).  messagesByMesh uses
    // `p.m || p.i` which falls back to DB id when mesh_packet_id is null.
    var messagesByProtoId = new Map();

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

    // Server provides relay candidates keyed by byte suffix (decimal string).
    // relayCache: { "12": [{id, name, short}, ...], ... }
    var relayCache = {};

    function mergeRelays(relaysDict) {
        for (var key in relaysDict) {
            relayCache[key] = relaysDict[key];
        }
    }

    function relaySuffix(rlVal) {
        if (!rlVal) return '';
        return (rlVal & 0xFF).toString(16).padStart(2, '0');
    }

    function relayCandidates(rlVal) {
        if (!rlVal) return [];
        var byteVal = String(rlVal & 0xFF);
        return relayCache[byteVal] || [];
    }

    // ----- rx popover -----

    var activePopover = null;

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
                ? '<a href="/node/' + gwNid + '" class="rx-pop-link node-link" ' +
                  'data-node-id="' + gwNid + '" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-html="true" ' +
                  'data-bs-title="Loading...">' + gwName + '</a>'
                : gwName;

            var relayCell = '';
            if (rx.rl) {
                var sfx = relaySuffix(rx.rl);
                var candidates = relayCandidates(rx.rl);
                if (candidates.length === 1) {
                    var c = candidates[0];
                    var cName = esc(c.short || c.name);
                    relayCell = '<span class="rx-relay-match" title="' + esc(c.name) + ' (0x' + sfx + ')">' + cName + '</span>';
                } else if (candidates.length > 1) {
                    var cNames = candidates.slice(0, 5).map(function (c) {
                        return esc(c.short || c.name);
                    });
                    var titleText = candidates.length + ' candidates: ' + cNames.join(', ');
                    if (candidates.length > 5) titleText += ', …';
                    relayCell = '<span class="rx-relay-ambig" title="' + esc(titleText) + '">' + sfx + ' <small>(' + candidates.length + ')</small></span>';
                } else {
                    relayCell = sfx;
                }
            }

            rows +=
                '<tr>' +
                    '<td class="rx-col-pkt"><a href="/packet/' + rx.id + '" class="rx-pop-link">#' + rx.id + '</a></td>' +
                    '<td class="rx-col-gw">' + gwCell + '</td>' +
                    '<td class="rx-col-num">' + (rx.hops != null ? rx.hops : '?') + '</td>' +
                    '<td class="rx-col-num">' + (rx.rs != null ? rx.rs : '') + '</td>' +
                    '<td class="rx-col-num">' + (rx.sn != null ? (typeof rx.sn === 'number' ? rx.sn.toFixed(1) : rx.sn) : '') + '</td>' +
                    '<td class="rx-col-relay">' + relayCell + '</td>' +
                '</tr>';
        }

        return (
            '<div class="rx-pop-header">' +
                sorted.length + ' reception' + (sorted.length > 1 ? 's' : '') +
            '</div>' +
            '<table class="rx-pop-table">' +
                '<thead><tr>' +
                    '<th class="rx-col-pkt">Pkt</th>' +
                    '<th class="rx-col-gw">Gateway</th>' +
                    '<th class="rx-col-num">Hops</th>' +
                    '<th class="rx-col-num">RSSI</th>' +
                    '<th class="rx-col-num">SNR</th>' +
                    '<th class="rx-col-relay">Relay</th>' +
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

    function initPopoverTooltips(popEl) {
        popEl.querySelectorAll('.node-link[data-node-id]').forEach(function (link) {
            if (bootstrap.Tooltip.getInstance(link)) return;
            var tip = new bootstrap.Tooltip(link, {
                html: true, trigger: 'hover',
                delay: { show: 200, hide: 100 }, placement: 'top'
            });
            link.addEventListener('mouseenter', function () {
                var nodeId = link.getAttribute('data-node-id');
                if (nodeId && typeof fetchNodeInfo === 'function') {
                    fetchNodeInfo(nodeId).then(function (info) {
                        if (typeof updateTooltipContent === 'function') {
                            updateTooltipContent(link, info);
                        }
                    }).catch(function () {});
                }
            });
        });
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
        initPopoverTooltips(pop);
    }

    function refreshPopover(meshId) {
        if (!activePopover || activePopover.meshId !== meshId) return;
        var msg = messagesByMesh.get(meshId);
        if (!msg) return;
        activePopover.el.innerHTML = buildPopoverContent(msg);
        initPopoverTooltips(activePopover.el);
    }

    document.addEventListener('mousedown', function (e) {
        if (!activePopover) return;
        if (activePopover.el.contains(e.target)) return;
        if (activePopover.badge.contains(e.target)) return;
        closePopover();
    });

    // ----- reply / emoji helpers -----

    function buildReplySnippet(msg) {
        if (!msg.replyId) return '';
        var refMsg = messagesByProtoId.get(msg.replyId);
        var label;
        if (refMsg) {
            var sender = esc(nodeShort(refMsg.fromId) || nodeName(refMsg.fromId));
            var snippet = refMsg.text.length > 60 ? refMsg.text.substring(0, 57) + '…' : refMsg.text;
            label = sender + ': ' + esc(snippet);
        } else {
            label = 'msg #' + msg.replyId;
        }
        var href = refMsg ? '#msg-' + (refMsg.meshId || refMsg.firstId) : '#';
        return '<span class="chat-reply">' +
            '<i class="bi bi-reply"></i> ' +
            '<a href="' + href + '" class="chat-reply-link" data-reply-mesh="' + msg.replyId + '">' +
                label +
            '</a>' +
        '</span>';
    }

    // ----- rendering -----

    function buildLine(msg) {
        var line = document.createElement('div');
        line.className = 'chat-line';
        line.id = 'msg-' + (msg.meshId || msg.firstId);
        line.dataset.meshId = msg.meshId || msg.firstId;

        var isDm = msg.toId && msg.toId !== BROADCAST;
        var display = esc(nodeShort(msg.fromId) || nodeName(msg.fromId));
        var full = esc(nodeName(msg.fromId));

        var isEmoji = msg.isEmoji;
        var textClass = 'chat-text' + (isDm ? ' chat-dm' : '') + (isEmoji ? ' chat-emoji-reaction' : '');
        var textContent = isEmoji ? '  ' + esc(msg.text) : esc(msg.text);

        var replyHtml = buildReplySnippet(msg);

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
            '<span class="' + textClass + '">' +
                replyHtml +
                textContent +
            '</span>' +
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
        // Reply link click — scroll to the referenced message
        var replyLink = e.target.closest('.chat-reply-link');
        if (replyLink) {
            e.preventDefault();
            var rid = replyLink.getAttribute('data-reply-mesh');
            if (rid) {
                var refMsg = messagesByProtoId.get(Number(rid));
                if (refMsg && refMsg.el) {
                    refMsg.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    refMsg.el.classList.add('chat-line-highlight');
                    setTimeout(function () { refMsg.el.classList.remove('chat-line-highlight'); }, 1500);
                }
            }
            return;
        }

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
            replyId: p.ri || null,
            isEmoji: !!p.em,
            el: null,
        };
        var el = buildLine(msg);
        msg.el = el;
        messagesByMesh.set(meshId, msg);
        if (p.m) messagesByProtoId.set(p.m, msg);
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
            mergeRelays(data.relays || {});
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
            mergeRelays(data.relays || {});

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
        messagesByProtoId.clear();
        relayCache = {};

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

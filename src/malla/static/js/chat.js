(function () {
    'use strict';

    var POLL_MS               = 3000;
    var INIT_LIMIT            = 500;
    var INIT_TARGET_TOP_LEVEL = 120;
    var MAX_INITIAL_BATCHES   = 4;
    var POLL_LIMIT            = 100;
    var NICK_COLORS           = 12;
    var BROADCAST             = 4294967295;
    var CONSEC_SEC            = 120;   // collapse nicks if same sender within 2 min

    var messagesEl = document.getElementById('chatMessages');
    var statusEl   = document.getElementById('chatStatus');
    var channelSel = document.getElementById('channelFilter');
    var scrollBtn  = document.getElementById('scrollBottomBtn');
    var unreadEl   = document.getElementById('unreadCount');
    var pauseBtn   = document.getElementById('pauseBtn');
    var soundBtn   = document.getElementById('soundBtn');
    var searchIn   = document.getElementById('chatSearch');
    var statsEl    = document.getElementById('chatStats');

    var lastId = 0, pollTimer = null, paused = false;
    var soundEnabled = localStorage.getItem('malla-chat-sound') === '1';
    var unreadCount = 0;

    var nodeCache = {};
    var messagesByMesh = new Map();
    var seenPacketIds = new Set();
    var messagesByProtoId = new Map();
    var messagesByPacketId = new Map();
    var relayCache = {};
    var orderedMsgs = [];  // all messages, including attached replies/reactions
    var topLevelMsgs = [];
    var searchTerm = '';

    // ----- URL state -----

    function readUrlState() {
        var p = new URLSearchParams(window.location.search);
        return { channel: p.get('channel') || '', search: p.get('q') || '' };
    }

    function pushUrlState() {
        var p = new URLSearchParams();
        if (channelSel.value) p.set('channel', channelSel.value);
        if (searchTerm) p.set('q', searchTerm);
        var qs = p.toString();
        var url = window.location.pathname + (qs ? '?' + qs : '');
        if (url !== window.location.pathname + window.location.search) {
            history.replaceState(null, '', url);
        }
    }

    // ----- helpers -----

    function nickColor(nodeId) { return 'nick-color-' + ((nodeId >>> 0) % NICK_COLORS); }

    function fmtTime(ts) {
        if (typeof formatTimestamp === 'function') return formatTimestamp(ts, 'time');
        return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function fmtDate(ts) {
        var d = new Date(ts * 1000);
        return d.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }

    function esc(s) { var e = document.createElement('span'); e.textContent = s; return e.innerHTML; }

    function nodeName(id) { var n = nodeCache[String(id)]; return n ? n.name : ('!' + (id >>> 0).toString(16).padStart(8, '0')); }
    function nodeShort(id) { var n = nodeCache[String(id)]; return n ? (n.short || n.name) : ''; }

    function gwName(gw) {
        if (!gw || !gw.startsWith('!')) return gw || '?';
        try { var n = parseInt(gw.substring(1), 16); return nodeShort(n) || gw; } catch (e) { return gw; }
    }
    function gwNid(gw) {
        if (!gw || !gw.startsWith('!')) return null;
        try { return parseInt(gw.substring(1), 16); } catch (e) { return null; }
    }

    function hops(hs, hl) { return (hs != null && hl != null) ? (hs - hl) : null; }

    function hopsLabel(m) {
        if (m.minHops == null) return '?';
        return m.minHops === m.maxHops ? String(m.minHops) : m.minHops + '-' + m.maxHops;
    }

    function atBottom() { return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 60; }

    function updateScrollButton() {
        var bottom = atBottom();
        scrollBtn.classList.toggle('d-none', bottom);
        if (bottom || unreadCount <= 0) {
            unreadEl.classList.add('d-none');
        } else {
            unreadEl.textContent = unreadCount > 99 ? '99+' : unreadCount;
            unreadEl.classList.remove('d-none');
        }
    }

    function goBottom(smooth) {
        if (messagesEl.scrollTo) {
            messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
        } else {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }
    }

    function followBottom() {
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                goBottom();
                updateScrollButton();
            });
        });
    }

    function mergeRelays(d) { for (var k in d) relayCache[k] = d[k]; }
    function relaySfx(v) { return v ? (v & 0xFF).toString(16).padStart(2, '0') : ''; }
    function relayCands(v) { return v ? (relayCache[String(v & 0xFF)] || []) : []; }

    function sortRx(list) {
        return list.slice().sort(function (a, b) {
            var ha = a.hops != null ? a.hops : 999, hb = b.hops != null ? b.hops : 999;
            if (ha !== hb) return ha - hb;
            return (a.rl || 0) - (b.rl || 0);
        });
    }

    function linkify(text) {
        return text.replace(/(https?:\/\/[^\s<]+)/g, function (url) {
            var display = url.length > 50 ? url.substring(0, 47) + '…' : url;
            return '<a href="' + esc(url) + '" target="_blank" rel="noopener" class="chat-link">' + esc(display) + '</a>';
        });
    }

    function dayKey(ts) { var d = new Date(ts * 1000); return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate(); }

    // ----- sound -----

    var audioCtx = null;
    function playNotif() {
        if (!soundEnabled) return;
        try {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            var osc = audioCtx.createOscillator();
            var gain = audioCtx.createGain();
            osc.type = 'sine'; osc.frequency.value = 880;
            gain.gain.value = 0.08;
            osc.connect(gain); gain.connect(audioCtx.destination);
            osc.start(); osc.stop(audioCtx.currentTime + 0.08);
        } catch (e) {}
    }

    function updateSoundBtn() {
        var icon = soundBtn.querySelector('i');
        icon.className = soundEnabled ? 'bi bi-bell-fill' : 'bi bi-bell-slash';
        soundBtn.title = soundEnabled ? 'Mute notifications' : 'Unmute notifications';
    }

    // ----- stats -----

    function updateStats() {
        var count = orderedMsgs.length;
        var senders = new Set();
        orderedMsgs.forEach(function (m) { senders.add(m.fromId); });
        statsEl.textContent = count + ' msgs · ' + senders.size + ' nodes';
        statsEl.classList.remove('d-none');
    }

    function attachmentParent(msg) {
        if (!msg.replyId) return null;
        return resolveReplyTarget(msg.replyId);
    }

    function resolveReplyTarget(replyId) {
        return messagesByProtoId.get(replyId) || messagesByPacketId.get(replyId) || messagesByMesh.get(replyId) || null;
    }

    // ----- rx popover (unchanged logic) -----

    var activePop = null;

    function closePop() { if (activePop) { activePop.el.remove(); activePop = null; } }

    function popContent(msg) {
        var sorted = sortRx(msg.rxList), rows = '';
        for (var k = 0; k < sorted.length; k++) {
            var rx = sorted[k];
            var gn = esc(gwName(rx.gw)), gid = gwNid(rx.gw);
            var gc = gid
                ? '<a href="/node/' + gid + '" class="rx-pop-link node-link" data-node-id="' + gid + '" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-html="true" data-bs-title="Loading...">' + gn + '</a>'
                : gn;
            var rc = '';
            if (rx.rl) {
                var sfx = relaySfx(rx.rl), cands = relayCands(rx.rl);
                if (cands.length === 1) {
                    rc = '<span class="rx-relay-match" title="' + esc(cands[0].name) + ' (0x' + sfx + ')">' + esc(cands[0].short || cands[0].name) + '</span>';
                } else if (cands.length > 1) {
                    var cn = cands.slice(0, 5).map(function (c) { return esc(c.short || c.name); });
                    rc = '<span class="rx-relay-ambig" title="' + esc(cands.length + ': ' + cn.join(', ')) + '">' + sfx + ' <small>(' + cands.length + ')</small></span>';
                } else { rc = sfx; }
            }
            rows += '<tr><td class="rx-col-pkt"><a href="/packet/' + rx.id + '" class="rx-pop-link">#' + rx.id + '</a></td>' +
                '<td class="rx-col-gw">' + gc + '</td>' +
                '<td class="rx-col-num">' + (rx.hops != null ? rx.hops : '?') + '</td>' +
                '<td class="rx-col-num">' + (rx.rs != null ? rx.rs : '') + '</td>' +
                '<td class="rx-col-num">' + (rx.sn != null ? (typeof rx.sn === 'number' ? rx.sn.toFixed(1) : rx.sn) : '') + '</td>' +
                '<td class="rx-col-relay">' + rc + '</td></tr>';
        }
        return '<div class="rx-pop-header">' + sorted.length + ' reception' + (sorted.length > 1 ? 's' : '') + '</div>' +
            '<table class="rx-pop-table"><thead><tr><th class="rx-col-pkt">Pkt</th><th class="rx-col-gw">Gateway</th><th class="rx-col-num">Hops</th><th class="rx-col-num">RSSI</th><th class="rx-col-num">SNR</th><th class="rx-col-relay">Relay</th></tr></thead><tbody>' + rows + '</tbody></table>';
    }

    function posPop(el, badge) {
        el.style.position = 'fixed'; el.style.visibility = 'hidden'; el.style.display = 'block';
        document.body.appendChild(el);
        var br = badge.getBoundingClientRect(), pr = el.getBoundingClientRect();
        var left = br.right - pr.width, top = br.bottom + 4;
        if (top + pr.height > window.innerHeight - 8) top = br.top - pr.height - 4;
        if (left < 8) left = 8;
        el.style.left = left + 'px'; el.style.top = top + 'px'; el.style.visibility = 'visible';
    }

    function initPopTips(el) {
        el.querySelectorAll('.node-link[data-node-id]').forEach(function (link) {
            if (bootstrap.Tooltip.getInstance(link)) return;
            new bootstrap.Tooltip(link, { html: true, trigger: 'hover', delay: { show: 200, hide: 100 }, placement: 'top' });
            link.addEventListener('mouseenter', function () {
                var nid = link.getAttribute('data-node-id');
                if (nid && typeof fetchNodeInfo === 'function') fetchNodeInfo(nid).then(function (info) { if (typeof updateTooltipContent === 'function') updateTooltipContent(link, info); }).catch(function () {});
            });
        });
    }

    function showPop(badge, meshId, pinned) {
        var msg = messagesByMesh.get(meshId);
        if (!msg) return;
        if (activePop && activePop.meshId === meshId) {
            if (pinned && !activePop.pinned) { activePop.pinned = true; activePop.el.classList.add('rx-pop-pinned'); return; }
            if (pinned && activePop.pinned) { closePop(); return; }
            return;
        }
        closePop();
        var pop = document.createElement('div');
        pop.className = 'rx-popover' + (pinned ? ' rx-pop-pinned' : '');
        pop.innerHTML = popContent(msg);
        pop.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        activePop = { el: pop, badge: badge, meshId: meshId, pinned: pinned };
        posPop(pop, badge);
        initPopTips(pop);
    }

    function refreshPop(meshId) {
        if (!activePop || activePop.meshId !== meshId) return;
        var msg = messagesByMesh.get(meshId);
        if (!msg) return;
        activePop.el.innerHTML = popContent(msg);
        initPopTips(activePop.el);
    }

    document.addEventListener('mousedown', function (e) {
        if (!activePop) return;
        if (activePop.el.contains(e.target) || activePop.badge.contains(e.target)) return;
        closePop();
    });

    // ----- reply helper -----

    function replySnippet(msg) {
        if (!msg.replyId) return '';
        var ref = resolveReplyTarget(msg.replyId);
        var label;
        if (ref) {
            var sender = esc(nodeShort(ref.fromId) || nodeName(ref.fromId));
            var snip = ref.text.length > 50 ? ref.text.substring(0, 47) + '…' : ref.text;
            label = sender + ': ' + esc(snip);
        } else { label = 'msg #' + msg.replyId; }
        var href = ref ? '#msg-' + (ref.meshId || ref.firstId) : '#';
        return '<span class="chat-reply"><i class="bi bi-reply"></i> <a href="' + href + '" class="chat-reply-link" data-reply-mesh="' + msg.replyId + '">' + label + '</a></span>';
    }

    function packetLinkHtml(msg) {
        return '<a href="/packet/' + msg.firstId + '" class="chat-packet-link" title="Open packet details (Malla ID#' + msg.firstId + ')"><i class="bi bi-box-arrow-up-right"></i><span></span></a>';
    }

    // ----- rendering -----

    function metaHtml(msg) {
        return '<span class="chat-meta">' +
            '<span class="chat-rx-badge badge bg-secondary" data-mesh-id="' + (msg.meshId || msg.firstId) + '">rx' + msg.rxList.length + ' h' + hopsLabel(msg) + '</span>' +
            (msg.channel ? '<span class="chat-channel">' + esc(msg.channel) + '</span>' : '') +
            packetLinkHtml(msg) +
        '</span>';
    }

    function buildLine(msg, isConsec) {
        var line = document.createElement('div');
        line.className = 'chat-line' + (isConsec ? ' chat-consec' : '');
        line.id = 'msg-' + (msg.meshId || msg.firstId);
        line.dataset.meshId = msg.meshId || msg.firstId;

        var isDm = msg.toId && msg.toId !== BROADCAST;
        var display = esc(nodeShort(msg.fromId) || nodeName(msg.fromId));
        var full = esc(nodeName(msg.fromId));
        var textClass = 'chat-text' + (isDm ? ' chat-dm' : '');

        var replyHtml = replySnippet(msg);
        var textHtml = linkify(esc(msg.text));

        line.innerHTML =
            '<span class="chat-ts timestamp-display" data-timestamp="' + msg.timestamp + '" data-timestamp-format="time">' + fmtTime(msg.timestamp) + '</span>' +
            '<span class="chat-nick ' + nickColor(msg.fromId) + '">' +
                '<a href="/node/' + msg.fromId + '" class="node-link" data-node-id="' + msg.fromId + '" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-html="true" data-bs-title="Loading..." title="' + full + '">' + display + '</a>' +
            '</span>' +
            '<span class="chat-sep">' + (isDm ? '&rarr;' : '|') + '</span>' +
            '<div class="chat-body">' +
                '<div class="chat-main">' +
                    '<span class="' + textClass + '">' + replyHtml + textHtml + '</span>' +
                    metaHtml(msg) +
                '</div>' +
                '<div class="chat-children"></div>' +
            '</div>';

        msg.childrenEl = line.querySelector('.chat-children');

        return line;
    }

    function buildAttachedLine(msg) {
        var line = document.createElement('div');
        line.className = 'chat-child chat-child-' + (msg.isEmoji ? 'reaction' : 'reply');
        line.id = 'msg-' + (msg.meshId || msg.firstId);
        line.dataset.meshId = msg.meshId || msg.firstId;

        var display = esc(nodeShort(msg.fromId) || nodeName(msg.fromId));
        var full = esc(nodeName(msg.fromId));
        var authorHtml =
            '<span class="chat-child-author ' + nickColor(msg.fromId) + '">' +
                '<a href="/node/' + msg.fromId + '" class="node-link" data-node-id="' + msg.fromId + '" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-html="true" data-bs-title="Loading..." title="' + full + '">' + display + '</a>' +
            '</span>';
        var labelHtml = msg.isEmoji
            ? '<span class="chat-child-label"><i class="bi bi-emoji-smile"></i> reacted</span>'
            : '<span class="chat-child-label"><i class="bi bi-reply"></i> replied</span>';
        var textClass = 'chat-child-text' + (msg.toId && msg.toId !== BROADCAST ? ' chat-dm' : '') + (msg.isEmoji ? ' chat-emoji-reaction' : '');
        var textHtml = msg.isEmoji ? esc(msg.text) : linkify(esc(msg.text));

        line.innerHTML =
            labelHtml +
            authorHtml +
            '<span class="' + textClass + '">' + textHtml + '</span>' +
            metaHtml(msg);

        return line;
    }

    function insertDateSep(ts) {
        var sep = document.createElement('div');
        sep.className = 'chat-date-sep';
        sep.innerHTML = '<span>' + fmtDate(ts) + '</span>';
        messagesEl.appendChild(sep);
    }

    var lastDayKey = null, lastSender = null, lastTs = 0;

    function refreshBadge(entry) {
        if (!entry.el) return;
        var badge = entry.el.querySelector('.chat-rx-badge');
        if (!badge) return;
        badge.textContent = 'rx' + entry.rxList.length + ' h' + hopsLabel(entry);
        refreshPop(entry.meshId);
    }

    function matchesSearch(msg) {
        if (!searchTerm) return true;
        var t = searchTerm.toLowerCase();
        if (msg.text.toLowerCase().indexOf(t) !== -1) return true;
        var sn = nodeShort(msg.fromId) || nodeName(msg.fromId);
        if (sn.toLowerCase().indexOf(t) !== -1) return true;
        return false;
    }

    // ----- ingestion -----

    function ingestPacket(p) {
        if (seenPacketIds.has(p.i)) return false;
        seenPacketIds.add(p.i);

        var meshId = p.m || p.i;
        var h = hops(p.hs, p.hl);
        var rxEntry = { gw: p.gw, rs: p.rs, sn: p.sn, hops: h, rl: p.rl, id: p.i };

        var existing = messagesByMesh.get(meshId);
        if (existing) {
            existing.rxList.push(rxEntry);
            if (h != null) {
                if (existing.minHops == null || h < existing.minHops) existing.minHops = h;
                if (existing.maxHops == null || h > existing.maxHops) existing.maxHops = h;
            }
            refreshBadge(existing);
            return false;
        }

        var msg = {
            meshId: meshId, firstId: p.i, timestamp: p.t, fromId: p.f,
            toId: p.d, channel: p.ch, text: p.tx,
            minHops: h, maxHops: h, rxList: [rxEntry],
            replyId: p.ri || null, isEmoji: !!p.em, el: null,
            parentMessage: null, children: [], childrenEl: null,
        };

        var parent = attachmentParent(msg);
        if (parent) msg.parentMessage = parent;

        messagesByMesh.set(meshId, msg);
        if (p.m) messagesByProtoId.set(p.m, msg);
        messagesByPacketId.set(p.i, msg);
        orderedMsgs.push(msg);

        if (parent) {
            parent.children.push(msg);
            var childEl = buildAttachedLine(msg);
            msg.el = childEl;
            if (!matchesSearch(msg)) childEl.classList.add('chat-hidden');
            if (parent.childrenEl) parent.childrenEl.appendChild(childEl);
            return true;
        }

        var dk = dayKey(p.t);
        if (dk !== lastDayKey) { insertDateSep(p.t); lastDayKey = dk; lastSender = null; }

        var isConsec = (msg.fromId === lastSender && (msg.timestamp - lastTs) < CONSEC_SEC && !msg.replyId && !msg.isEmoji);

        var el = buildLine(msg, isConsec);
        msg.el = el;

        if (!matchesSearch(msg)) el.classList.add('chat-hidden');

        topLevelMsgs.push(msg);
        messagesEl.appendChild(el);

        lastSender = msg.fromId;
        lastTs = msg.timestamp;
        return true;
    }

    // ----- API -----

    function apiUrl(afterId, limit, beforeId) {
        var p = new URLSearchParams();
        if (afterId > 0) p.set('after_id', afterId);
        else if (beforeId > 0) p.set('before_id', beforeId);
        p.set('limit', limit);
        var ch = channelSel.value;
        if (ch) p.set('channel', ch);
        return '/api/chat/messages?' + p.toString();
    }

    function removeLoading() { var el = document.getElementById('chatLoading'); if (el) el.remove(); }

    async function loadInitial() {
        try {
            var beforeId = 0;
            var batches = 0;
            var data = null;
            var initialPackets = [];
            var initialTopLevelMeshIds = new Set();

            removeLoading();

            while (batches < MAX_INITIAL_BATCHES && initialTopLevelMeshIds.size < INIT_TARGET_TOP_LEVEL) {
                var resp = await fetch(apiUrl(0, INIT_LIMIT, beforeId));
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                data = await resp.json();

                Object.assign(nodeCache, data.nodes || {});
                mergeRelays(data.relays || {});
                initialPackets = data.packets.concat(initialPackets);
                data.packets.forEach(function (p) {
                    if (!p.ri) initialTopLevelMeshIds.add(p.m || p.i);
                });
                lastId = Math.max(lastId, data.last_id || 0);
                batches += 1;

                if (!data.packets.length || data.packets.length < INIT_LIMIT) break;
                beforeId = data.packets[0].i;
            }

            initialPackets.forEach(ingestPacket);

            removeLoading();
            if (searchTerm) applySearch();
            followBottom();
            setStatus('live');
            updateStats();
            if (typeof reinitializeTooltips === 'function') reinitializeTooltips();
        } catch (err) {
            console.error('Chat load error:', err);
            removeLoading();
            setStatus('error');
        }
    }

    async function poll() {
        if (paused) return;
        try {
            var resp = await fetch(apiUrl(lastId, POLL_LIMIT, 0));
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            var wasBottom = atBottom();
            Object.assign(nodeCache, data.nodes || {});
            mergeRelays(data.relays || {});
            var newCount = 0;
            data.packets.forEach(function (p) { if (ingestPacket(p)) newCount++; });
            lastId = data.last_id;
            if (newCount > 0) {
                if (searchTerm) applySearch();
                updateStats();
                if (typeof reinitializeTooltips === 'function') reinitializeTooltips();
                if (wasBottom) followBottom();
                else {
                    unreadCount += newCount;
                    updateScrollButton();
                }
                playNotif();
            }
            setStatus('live');
        } catch (err) {
            console.error('Chat poll error:', err);
            setStatus('error');
        }
    }

    // ----- status -----

    function setStatus(type) {
        if (type === 'live') {
            statusEl.textContent = paused ? 'Paused' : 'Live';
            statusEl.className = 'badge ' + (paused ? 'bg-warning text-dark' : 'bg-success');
        } else if (type === 'error') {
            statusEl.textContent = 'Error'; statusEl.className = 'badge bg-danger';
        } else {
            statusEl.textContent = 'Connecting…'; statusEl.className = 'badge bg-secondary';
        }
    }

    function startPolling() { stopPolling(); pollTimer = setInterval(poll, POLL_MS); }
    function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

    function resetChat() {
        stopPolling(); closePop();
        lastId = 0; lastDayKey = null; lastSender = null; lastTs = 0;
        unreadCount = 0; unreadEl.classList.add('d-none');
        seenPacketIds.clear(); messagesByMesh.clear(); messagesByProtoId.clear();
        messagesByPacketId.clear();
        relayCache = {}; orderedMsgs = []; topLevelMsgs = [];
        scrollBtn.classList.add('d-none');
        messagesEl.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
            var tip = bootstrap.Tooltip.getInstance(el);
            if (tip) tip.dispose();
        });
        messagesEl.innerHTML = '<div id="chatLoading" class="chat-loading"><div class="spinner-border spinner-border-sm text-secondary" role="status"></div><span class="text-muted ms-2">Loading messages…</span></div>';
        setStatus('loading');
        pushUrlState();
        loadInitial().then(startPolling);
    }

    async function loadChannels() {
        try {
            var resp = await fetch('/api/meshtastic/channels');
            if (!resp.ok) return;
            var data = await resp.json();
            (data.channels || []).forEach(function (ch) {
                var opt = document.createElement('option');
                opt.value = ch; opt.textContent = ch;
                channelSel.appendChild(opt);
            });
        } catch (e) {}
    }

    // ----- search -----

    var searchTimer = null;
    function applySearch() {
        searchTerm = searchIn.value.trim();
        pushUrlState();
        orderedMsgs.forEach(function (m) {
            if (!m.el || !m.parentMessage) return;
            if (matchesSearch(m)) m.el.classList.remove('chat-hidden');
            else m.el.classList.add('chat-hidden');
        });
        topLevelMsgs.forEach(function (m) {
            if (!m.el) return;
            var childMatch = m.children.some(matchesSearch);
            if (matchesSearch(m) || childMatch) m.el.classList.remove('chat-hidden');
            else m.el.classList.add('chat-hidden');
        });
    }

    searchIn.addEventListener('input', function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(applySearch, 200);
    });

    // Ctrl+F / Cmd+F focuses the search box
    document.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            searchIn.focus();
            searchIn.select();
        }
        if (e.key === 'Escape' && document.activeElement === searchIn) {
            searchIn.value = '';
            applySearch();
            searchIn.blur();
        }
    });

    // ----- events -----

    messagesEl.addEventListener('scroll', function () {
        if (atBottom()) {
            unreadCount = 0;
        }
        updateScrollButton();
        // Show pause button when user scrolls up away from bottom
        if (!atBottom() && !paused) pauseBtn.classList.remove('d-none');
        else if (atBottom()) pauseBtn.classList.add('d-none');
    });

    scrollBtn.addEventListener('click', function () {
        unreadCount = 0;
        goBottom(true);
        updateScrollButton();
    });

    channelSel.addEventListener('change', resetChat);

    pauseBtn.addEventListener('click', function () {
        paused = !paused;
        var icon = pauseBtn.querySelector('i');
        if (paused) {
            icon.className = 'bi bi-play-fill';
            pauseBtn.title = 'Resume live updates';
            pauseBtn.classList.add('active');
        } else {
            icon.className = 'bi bi-pause-fill';
            pauseBtn.title = 'Pause live updates';
            pauseBtn.classList.remove('active');
            poll(); // catch up immediately
        }
        setStatus('live');
    });

    soundBtn.addEventListener('click', function () {
        soundEnabled = !soundEnabled;
        localStorage.setItem('malla-chat-sound', soundEnabled ? '1' : '0');
        updateSoundBtn();
        if (soundEnabled) playNotif(); // preview
    });

    // Badge hover / click delegation
    var hoverTimer = null;

    messagesEl.addEventListener('mouseover', function (e) {
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        var id = badge.dataset.meshId; if (!id) return;
        var key = isNaN(id) ? id : Number(id);
        if (activePop && activePop.pinned) return;
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(function () { showPop(badge, key, false); }, 120);
    });

    messagesEl.addEventListener('mouseout', function (e) {
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        clearTimeout(hoverTimer);
        if (activePop && !activePop.pinned) {
            setTimeout(function () {
                if (activePop && !activePop.pinned && !activePop.el.matches(':hover') && !badge.matches(':hover')) closePop();
            }, 200);
        }
    });

    document.addEventListener('mouseout', function (e) {
        if (!activePop || activePop.pinned) return;
        setTimeout(function () {
            if (!activePop || activePop.pinned) return;
            if (!activePop.el.matches(':hover') && !activePop.badge.matches(':hover')) closePop();
        }, 200);
    });

    messagesEl.addEventListener('click', function (e) {
        var reply = e.target.closest('.chat-reply-link');
        if (reply) {
            e.preventDefault();
            var rid = reply.getAttribute('data-reply-mesh');
            if (rid) {
                var ref = resolveReplyTarget(Number(rid));
                if (ref && ref.el) {
                    ref.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    ref.el.classList.add('chat-line-highlight');
                    setTimeout(function () { ref.el.classList.remove('chat-line-highlight'); }, 1500);
                }
            }
            return;
        }
        var badge = e.target.closest('.chat-rx-badge');
        if (!badge) return;
        e.preventDefault(); e.stopPropagation();
        var id = badge.dataset.meshId; if (!id) return;
        showPop(badge, isNaN(id) ? id : Number(id), true);
    });

    // Timezone in-place update
    if (window.timezoneToggle) {
        window.timezoneToggle.setTimezone = function (tz) {
            if (!['local', 'utc'].includes(tz)) return;
            localStorage.setItem('malla-timezone-preference', tz);
            window.timezoneToggle.updateToggleButton();
            window.currentTimezone = tz;
            document.querySelectorAll('#chatMessages .chat-ts[data-timestamp]').forEach(function (el) {
                var ts = parseFloat(el.getAttribute('data-timestamp'));
                if (!isNaN(ts)) el.textContent = fmtTime(ts);
            });
            window.dispatchEvent(new CustomEvent('timezoneChanged', { detail: { timezone: tz, skipReload: true } }));
        };
    }

    // Handle browser back/forward
    window.addEventListener('popstate', function () {
        var s = readUrlState();
        channelSel.value = s.channel;
        searchIn.value = s.search;
        searchTerm = s.search;
        resetChat();
    });

    // ----- init -----

    (async function init() {
        await loadChannels();
        var s = readUrlState();
        if (s.channel) channelSel.value = s.channel;
        if (s.search) { searchIn.value = s.search; searchTerm = s.search; }
        updateSoundBtn();
        await loadInitial();
        startPolling();
    })();

})();

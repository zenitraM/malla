/**
 * Global time-range context.
 *
 * One range control shared by every opting-in page. Precedence: URL ?range=
 * (also persisted on change) > localStorage malla.range > 7d.
 *
 * Ranges: 15m 1h 6h 24h 7d 30d all (+ 'custom' with since/until datetimes).
 * Pages integrate by:
 *   - window.MallaRange.get()            -> {key, sinceEpoch?, untilEpoch?}
 *   - window.MallaRange.onRangeChange(cb) -> unsubscribe; cb(rangeObj, meta)
 *     where meta.overridden is true when the page's own controls changed the
 *     effective window after the last global change.
 *   - window.MallaRange.override({since, until}|null) - page-local override;
 *     cleared automatically on the next global change.
 * Tables translate the window into their native params in requestParams
 * (since/until ISO); the dashboard maps preset keys onto its selector.
 *
 * A page-local override chip appears next to the navbar control while active.
 */
(function (global) {
    "use strict";

    var PRESETS = ["15m", "1h", "6h", "24h", "7d", "30d", "all"];
    var LABELS = {
        "15m": "Last 15 minutes", "1h": "Last hour", "6h": "Last 6 hours",
        "24h": "Last 24 hours", "7d": "Last 7 days", "30d": "Last 30 days",
        "all": "All time", "custom": "Custom range",
    };
    var SECONDS = { "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000 };
    var STORAGE_KEY = "malla.range";

    var listeners = [];
    var override = null; // {sinceEpoch, untilEpoch} or null
    var current = null;

    function safeGet(key) { try { return global.localStorage.getItem(key); } catch (e) { return null; } }
    function safeSet(key, val) { try { global.localStorage.setItem(key, val); } catch (e) { /* private mode */ } }

    function valid(key) { return key === "custom" || SECONDS[key] || key === "all"; }

    function fromUrl() {
        var p = new URLSearchParams(global.location.search);
        var key = p.get("range");
        if (!key || !valid(key)) return null;
        if (key === "custom") {
            var since = p.get("range_since"), until = p.get("range_until");
            var s = since ? Date.parse(since) : NaN, u = until ? Date.parse(until) : NaN;
            if (Number.isNaN(s) && Number.isNaN(u)) return null;
            return { key: "custom", sinceEpoch: Number.isNaN(s) ? null : s / 1000, untilEpoch: Number.isNaN(u) ? null : u / 1000 };
        }
        return { key: key };
    }

    function bound(value) {
        return typeof value === "number" && Number.isFinite(value) ? value : null;
    }

    function compute(key, custom) {
        if (key === "custom") {
            var since = custom ? bound(custom.sinceEpoch) : null;
            var until = custom ? bound(custom.untilEpoch) : null;
            if (since == null && until == null) {
                // A bare custom key has no usable window; fall back instead of
                // producing a NaN since that consumers silently drop.
                key = "7d";
            } else {
                return { key: "custom", sinceEpoch: since, untilEpoch: until };
            }
        }
        if (key === "all") return { key: "all" };
        var now = Date.now() / 1000;
        return { key: key, sinceEpoch: now - SECONDS[key], untilEpoch: null };
    }

    function resolve() {
        var fromURL = fromUrl();
        var stored = safeGet(STORAGE_KEY);
        var storedKey = stored && valid(stored) ? stored : null;
        if (storedKey === "custom" && (!fromURL || fromURL.key !== "custom")) {
            // Storage keeps only the key, not the bounds. A bare custom key
            // would otherwise resolve to NaN; see compute().
            storedKey = null;
        }
        var key = (fromURL && fromURL.key) || storedKey || "7d";
        var custom = fromURL && fromURL.key === "custom" ? fromURL
            : (key === "custom" ? current && current.key === "custom" ? current : null : null);
        return compute(key, custom);
    }

    function publish(meta) {
        meta = meta || { changed: true };
        var snapshot = get();
        listeners.forEach(function (cb) {
            try { cb(snapshot, meta); } catch (e) { console.error("range listener failed", e); }
        });
    }

    function get() {
        if (override) {
            return { key: "custom", sinceEpoch: override.sinceEpoch, untilEpoch: override.untilEpoch, overridden: true };
        }
        if (!current) current = resolve();
        // Relative presets are anchored at "now"; recompute their start on
        // every read so a long-lived page does not keep the original window.
        // Custom windows and "all" are stable and stay cached.
        if (current.key !== "custom" && current.key !== "all") {
            current = compute(current.key, null);
        }
        return current;
    }

    function set(key, custom, opts) {
        if (!valid(key)) return;
        var since = key === "custom" ? bound(custom && custom.sinceEpoch) : null;
        var until = key === "custom" ? bound(custom && custom.untilEpoch) : null;
        if (key === "custom" && since == null && until == null) key = "7d";
        var url = new URL(global.location);
        if (key === "custom") {
            url.searchParams.set("range", "custom");
            if (since != null) url.searchParams.set("range_since", new Date(since * 1000).toISOString());
            else url.searchParams.delete("range_since");
            if (until != null) url.searchParams.set("range_until", new Date(until * 1000).toISOString());
            else url.searchParams.delete("range_until");
        } else {
            url.searchParams.set("range", key);
            url.searchParams.delete("range_since");
            url.searchParams.delete("range_until");
        }
        global.history.replaceState({}, "", url);
        safeSet(STORAGE_KEY, key);
        override = null;
        hideOverrideChip();
        current = compute(key, key === "custom" ? { sinceEpoch: since, untilEpoch: until } : null);
        syncButton();
        publish({ changed: true, via: (opts && opts.via) || "ui" });
    }

    function overrideRange(o) {
        override = o;
        if (o) showOverrideChip();
        else hideOverrideChip();
        publish({ changed: true, via: "override" });
    }

    function onRangeChange(cb) {
        listeners.push(cb);
        return function () {
            var i = listeners.indexOf(cb);
            if (i >= 0) listeners.splice(i, 1);
        };
    }

    // ------- navbar UI -------------------------------------------------------
    function ensureButton() {
        var nav = document.querySelector(".navbar-nav.flex-row");
        var bar = document.getElementById("globalRangeBar");
        if (!nav) return null;
        if (!bar) {
            bar = document.createElement("div");
            bar.id = "globalRangeBar";
            bar.className = "navbar-nav flex-row align-items-center gap-1 ms-lg-2";
            bar.innerHTML =
                '<div class="dropdown">' +
                '  <button id="globalRangeButton" class="btn btn-outline-secondary btn-sm dropdown-toggle" data-bs-toggle="dropdown" aria-expanded="false" aria-haspopup="true" title="Global time range" aria-label="Global time range">' +
                '    <i class="bi bi-clock-history" aria-hidden="true"></i><span id="globalRangeLabel" class="ms-1 d-none d-xl-inline">7d</span>' +
                "  </button>" +
                '  <div class="dropdown-menu dropdown-menu-end p-2" style="min-width: 230px" aria-labelledby="globalRangeButton">' +
                '    <div id="globalRangePresets" class="d-grid gap-1"></div>' +
                '    <hr class="dropdown-divider">' +
                '    <form id="globalRangeCustom" class="px-1 pb-1">' +
                '      <label class="form-label small mb-1" for="grcSince">Custom from</label>' +
                '      <input type="datetime-local" class="form-control form-control-sm mb-2" id="grcSince">' +
                '      <label class="form-label small mb-1" for="grcUntil">Until (optional)</label>' +
                '      <input type="datetime-local" class="form-control form-control-sm mb-2" id="grcUntil">' +
                '      <button type="button" id="globalRangeApply" class="btn btn-sm btn-primary w-100">Apply</button>' +
                "    </form>" +
                "  </div>" +
                "</div>";
            nav.parentNode.insertBefore(bar, nav);
        }
        var presets = bar.querySelector("#globalRangePresets");
        if (!presets.childElementCount) {
            PRESETS.concat(["custom"]).forEach(function (key) {
                var b = document.createElement("button");
                b.type = "button";
                b.className = "btn btn-sm btn-outline-secondary text-start global-range-item";
                b.dataset.key = key;
                b.textContent = LABELS[key];
                b.addEventListener("click", function () {
                    if (key === "custom") {
                        var form = bar.querySelector("#globalRangeCustom");
                        var s = form.querySelector("#grcSince").value;
                        var u = form.querySelector("#grcUntil").value;
                        var se = s ? new Date(s).getTime() / 1000 : null;
                        var ue = u ? new Date(u).getTime() / 1000 : null;
                        if (se == null && ue == null) return;
                        set("custom", { sinceEpoch: se, untilEpoch: ue });
                    } else {
                        set(key);
                    }
                    hideDropdown();
                });
                presets.appendChild(b);
            });
        }
        var form = bar.querySelector("#globalRangeCustom");
        var applyCustom = function (ev) {
            if (ev && ev.preventDefault) ev.preventDefault();
            var s = form.querySelector("#grcSince").value, u = form.querySelector("#grcUntil").value;
            if (!s && !u) return;
            set("custom", { sinceEpoch: s ? new Date(s).getTime() / 1000 : null, untilEpoch: u ? new Date(u).getTime() / 1000 : null });
            hideDropdown();
        };
        form.addEventListener("submit", applyCustom);
        var applyBtn = bar.querySelector("#globalRangeApply");
        if (applyBtn) applyBtn.addEventListener("click", applyCustom);
        return bar;
    }

    function hideDropdown() {
        var el = document.getElementById("globalRangeButton");
        if (el && global.bootstrap && global.bootstrap.Dropdown) global.bootstrap.Dropdown.getOrCreateInstance(el).hide();
    }

    function ensureOverrideChip() {
        var chip = document.getElementById("globalRangeOverride");
        if (chip) return chip;
        var bar = ensureButton();
        if (!bar) return null;
        chip = document.createElement("span");
        chip.id = "globalRangeOverride";
        chip.className = "badge text-bg-warning ms-1 d-none";
        chip.title = "This page is showing a locally overridden time range";
        chip.textContent = "overridden";
        var btn = bar.querySelector("#globalRangeButton");
        btn.parentNode.insertBefore(chip, btn.nextSibling);
        return chip;
    }
    function showOverrideChip() { var c = ensureOverrideChip(); if (c) c.classList.remove("d-none"); }
    function hideOverrideChip() { var c = document.getElementById("globalRangeOverride"); if (c) c.classList.add("d-none"); }

    function syncButton() {
        var label = document.getElementById("globalRangeLabel");
        var btn = document.getElementById("globalRangeButton");
        if (!btn) return;
        var cur = get();
        var text = cur.key === "custom" ? "custom" : cur.key;
        if (label) label.textContent = text;
        if (btn) btn.setAttribute("title", "Global time range: " + (LABELS[cur.key] || cur.key));
        document.querySelectorAll(".global-range-item").forEach(function (b) {
            var active = b.dataset.key === (cur.overridden ? "custom" : cur.key);
            b.classList.toggle("active", active);
            b.setAttribute("aria-pressed", String(active));
        });
    }

    // Cross-tab sync.
    global.addEventListener("storage", function (ev) {
        if (ev.key === STORAGE_KEY) {
            current = resolve();
            override = null;
            hideOverrideChip();
            syncButton();
            publish({ changed: true, via: "storage" });
        }
    });

    function init() {
        current = resolve();
        // Reflect the resolved range into the URL so reloads and shared links
        // carry the same window (custom keeps its two params). An unusable
        // ?range (unknown key, or custom without bounds) is removed so the URL
        // cannot advertise a window the page is not using.
        var url = new URL(global.location);
        var changed = false;
        if (!fromUrl()) {
            ["range", "range_since", "range_until"].forEach(function (param) {
                if (url.searchParams.has(param)) {
                    url.searchParams.delete(param);
                    changed = true;
                }
            });
            if (current.key !== "7d") {
                url.searchParams.set("range", current.key);
                if (current.key === "custom") {
                    if (current.sinceEpoch) url.searchParams.set("range_since", new Date(current.sinceEpoch * 1000).toISOString());
                    if (current.untilEpoch) url.searchParams.set("range_until", new Date(current.untilEpoch * 1000).toISOString());
                }
                changed = true;
            }
        }
        if (changed) global.history.replaceState({}, "", url);
        ensureButton();
        ensureOverrideChip();
        syncButton();
    }

    global.MallaRange = {
        PRESETS: PRESETS.slice(),
        get: get,
        set: set,
        override: overrideRange,
        setOverrideVisible: function (visible) {
            if (visible) showOverrideChip();
            else if (!override) hideOverrideChip();
        },
        onRangeChange: onRangeChange,
        init: init,
        label: function (key) { return LABELS[key] || key; },
    };

    document.addEventListener("DOMContentLoaded", init);
})(window);

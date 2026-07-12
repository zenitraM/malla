/*
 * Node telemetry history charts.
 *
 * Renders one full-width Chart.js line chart per metric group (Environment /
 * Power / Radio) the node reports. Features: range buttons, drag/double-click/
 * button zoom (1-day minimum, synced across charts), per-metric summary stats
 * over the visible window, a synced crosshair + tooltip across all charts,
 * legend hover to highlight a metric and reveal its axis, a zero-baseline
 * toggle, an offline note, dark-mode-aware colours, smooth (monotone) curves,
 * and line breaks across gaps longer than 24 hours.
 *
 * Resolution follows the view: a wide window is served as a smooth average line
 * with a faded min/max band; zooming in refetches that window and, once it is
 * small enough, shows the raw points instead.
 */
(function () {
  "use strict";

  const METRIC_LABELS = {
    temperature: "Temperature",
    relative_humidity: "Humidity",
    barometric_pressure: "Pressure",
    gas_resistance: "Gas Resistance",
    iaq: "IAQ",
    lux: "Lux",
    battery_level: "Battery",
    voltage: "Voltage",
    channel_utilization: "Channel Util",
    air_util_tx: "Air Util TX",
  };

  // One chart per group; only related metrics share a chart.
  const CHART_GROUPS = [
    {
      title: "Environment",
      metrics: ["temperature", "relative_humidity", "barometric_pressure", "gas_resistance", "iaq", "lux"],
    },
    { title: "Power", metrics: ["battery_level", "voltage"] },
    { title: "Radio", metrics: ["channel_utilization", "air_util_tx"] },
  ];

  const COLORS = ["#0e7490", "#f59e0b", "#6366f1", "#16a34a", "#dc3545", "#0891b2"];
  const MIN_WINDOW = 86400; // smallest zoom window: one day
  const GAP_LIMIT = 86400; // break the line across gaps longer than 24h
  const OFFLINE_AFTER = 86400; // flag "offline" only after 24h without telemetry

  function fmt(ts, format) {
    if (typeof window.formatTimestamp === "function") return window.formatTimestamp(ts, format);
    return new Date(ts * 1000).toLocaleString();
  }
  function isDark() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark";
  }
  function themeColors() {
    const d = isDark();
    return {
      tick: d ? "#adb5bd" : "#6c757d",
      grid: d ? "rgba(255,255,255,0.09)" : "rgba(0,0,0,0.06)",
      text: d ? "#dee2e6" : "#495057",
      crosshair: d ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.3)",
    };
  }
  function fade(color, alpha) {
    if (alpha == null) alpha = 0.15;
    if (typeof color === "string" && color[0] === "#" && color.length === 7) {
      const r = parseInt(color.slice(1, 3), 16);
      const g = parseInt(color.slice(3, 5), 16);
      const b = parseInt(color.slice(5, 7), 16);
      return `rgba(${r},${g},${b},${alpha})`;
    }
    return color;
  }

  // --- Perceptual band opacity ---------------------------------------------
  // A translucent band's prominence is its perceptual contrast against the
  // surface, which varies a lot by hue at a fixed alpha (a light amber barely
  // marks white; a dark teal barely marks a dark surface — and the two swap
  // when the theme flips). So instead of a fixed alpha we solve, per hue and
  // per surface, the alpha that hits a constant OKLab ΔE — every band then
  // reads with the same weight, in light and dark.
  const BAND_CONTRAST = 0.1; // target OKLab ΔE between band and surface
  function hexRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  function srgbToLinear(c) {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }
  function oklab(rgb) {
    const r = srgbToLinear(rgb[0]), g = srgbToLinear(rgb[1]), b = srgbToLinear(rgb[2]);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ];
  }
  // First opaque background walking up from the chart container = the surface
  // the bands actually sit on (falls back to the theme's canonical surface).
  function surfaceRgb() {
    let el = document.getElementById("telemetry-charts");
    while (el) {
      const m = getComputedStyle(el).backgroundColor.match(
        /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/
      );
      if (m && (m[4] === undefined || parseFloat(m[4]) > 0.99)) return [+m[1], +m[2], +m[3]];
      el = el.parentElement;
    }
    return isDark() ? [33, 37, 41] : [255, 255, 255];
  }
  function bandAlpha(hexColor) {
    const c = hexRgb(hexColor);
    const bg = surfaceRgb();
    const labBg = oklab(bg);
    const dE = (a) => {
      const bl = [bg[0] + (c[0] - bg[0]) * a, bg[1] + (c[1] - bg[1]) * a, bg[2] + (c[2] - bg[2]) * a];
      const l = oklab(bl);
      return Math.hypot(l[0] - labBg[0], l[1] - labBg[1], l[2] - labBg[2]);
    };
    let lo = 0, hi = 1;
    for (let i = 0; i < 24; i++) {
      const mid = (lo + hi) / 2;
      if (dE(mid) < BAND_CONTRAST) lo = mid;
      else hi = mid;
    }
    // Clamp so a band never vanishes nor turns opaque enough to hide others.
    return Math.max(0.1, Math.min(0.45, (lo + hi) / 2));
  }
  function round(v) {
    if (!isFinite(v)) return "–";
    const a = Math.abs(v);
    return a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(1) : v.toFixed(2);
  }

  // Vertical crosshair drawn at chart._crosshairX (a timestamp) on every chart.
  const crosshairPlugin = {
    id: "telemetryCrosshair",
    afterDatasetsDraw(chart) {
      const x = chart._crosshairX;
      if (x == null) return;
      const xs = chart.scales.x;
      if (!xs || x < xs.min || x > xs.max) return;
      const px = xs.getPixelForValue(x);
      const area = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(px, area.top);
      ctx.lineTo(px, area.bottom);
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = themeColors().crosshair;
      ctx.stroke();
      ctx.restore();
    },
  };

  class NodeTelemetryChart {
    constructor(nodeId) {
      this.nodeId = nodeId;
      this.range = "7d";
      this.charts = [];
      this.syncing = false;
      this.zeroBase = false;
      // Zoom-out is clamped to the range extent (stable); the loaded window is
      // what is currently fetched. When they diverge we refetch at the right
      // resolution — raw when zoomed in, aggregated when zoomed out.
      this.rangeMin = null;
      this.rangeMax = null;
      this.loadedMin = null;
      this.loadedMax = null;
      this.latestTs = -Infinity;
      this._detailTimer = null;
      this.card = document.getElementById("telemetry-card");
      this.chartsEl = document.getElementById("telemetry-charts");
      this.loadingEl = document.getElementById("telemetry-loading");
      this.emptyEl = document.getElementById("telemetry-empty");
      this.hintEl = document.getElementById("telemetry-hint");
      this.offlineEl = document.getElementById("telemetry-offline");
      this.rangeEl = document.getElementById("telemetry-range");
      this.zoomEl = document.getElementById("telemetry-zoom");
    }

    initialize() {
      if (!this.card) return;
      if (this.rangeEl) {
        this.rangeEl.addEventListener("click", (e) => {
          const btn = e.target.closest("button[data-range]");
          if (!btn) return;
          this.range = btn.dataset.range;
          this.rangeEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
          this.load();
        });
      }
      if (this.zoomEl) {
        this.zoomEl.addEventListener("click", (e) => {
          const btn = e.target.closest("button[data-zoom], button[data-zero]");
          if (!btn) return;
          if (btn.dataset.zero != null) {
            this.toggleZero(btn);
            return;
          }
          const a = btn.dataset.zoom;
          if (a === "in") this.zoomBy(1.6);
          else if (a === "out") this.zoomBy(1 / 1.6);
          else this.resetZoom();
        });
      }
      // Re-render with new colours if the light/dark theme changes.
      new MutationObserver(() => this.load()).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-bs-theme"],
      });
      this.load();
    }

    async load() {
      this.destroyCharts();
      this.showEmpty(false);
      if (this.loadingEl) this.loadingEl.style.display = "flex";
      // Recompute the range extent from this range's data.
      this.rangeMin = null;
      this.rangeMax = null;
      try {
        const res = await fetch(`/api/node/${this.nodeId}/telemetry?range=${this.range}`);
        const data = await res.json();
        if (this.loadingEl) this.loadingEl.style.display = "none";
        this.render((data && data.series) || {});
        this.rangeMin = this.fullMin;
        this.rangeMax = this.fullMax;
        this.loadedMin = this.fullMin;
        this.loadedMax = this.fullMax;
        // Prefer the true latest reading; on aggregated views the last plotted
        // point is a bucket centre that lags the real last reading.
        this.latestTs = data && data.latest != null ? data.latest : this.fullMax;
        this.updateOffline(this.latestTs);
      } catch (err) {
        console.error("Failed to load telemetry", err);
        if (this.loadingEl) this.loadingEl.style.display = "none";
        this.showEmpty(true, "Failed to load telemetry.");
      }
    }

    // Refetch just the visible window so the backend serves it at native
    // resolution: raw points when the window is small, an aggregated average +
    // min/max band when it is wide. Keeps the range extent (zoom bounds) intact.
    async loadWindow(min, max) {
      min = Math.floor(min);
      max = Math.ceil(max);
      try {
        const res = await fetch(`/api/node/${this.nodeId}/telemetry?start=${min}&end=${max}`);
        const data = await res.json();
        const series = (data && data.series) || {};
        if (!Object.keys(series).length) return; // keep the current view
        this.destroyCharts();
        this.render(series);
        this.loadedMin = this.fullMin;
        this.loadedMax = this.fullMax;
      } catch (err) {
        console.error("Failed to load telemetry window", err);
      }
    }

    showEmpty(show, text) {
      if (!this.emptyEl) return;
      if (text) this.emptyEl.textContent = text;
      this.emptyEl.style.display = show ? "flex" : "none";
    }

    render(series) {
      this.fullMin = Infinity;
      this.fullMax = -Infinity;
      for (const group of CHART_GROUPS) {
        const metrics = group.metrics.filter((m) => series[m] && series[m].points && series[m].points.length);
        if (!metrics.length) continue;
        metrics.forEach((m) => {
          const pts = series[m].points;
          this.fullMin = Math.min(this.fullMin, pts[0][0]);
          this.fullMax = Math.max(this.fullMax, pts[pts.length - 1][0]);
        });
        this.charts.push(this.buildChart(group, metrics, series));
      }
      if (this.hintEl) this.hintEl.style.display = this.charts.length ? "" : "none";
      if (!this.charts.length) this.showEmpty(true, "No telemetry reported by this node.");
      this.updateStats();
    }

    updateOffline(latest) {
      if (!this.offlineEl) return;
      if (!isFinite(latest) || Date.now() / 1000 - latest <= OFFLINE_AFTER) {
        this.offlineEl.style.display = "none";
        return;
      }
      this.offlineEl.innerHTML =
        '<i class="bi bi-exclamation-triangle"></i> No telemetry since ' + fmt(latest, "datetime");
      this.offlineEl.style.display = "";
    }

    buildChart(group, metrics, series) {
      const col = document.createElement("div");
      col.className = "col-12";
      const heading = document.createElement("h6");
      heading.className = "text-muted mb-1";
      heading.textContent = group.title;
      const wrap = document.createElement("div");
      wrap.style.height = "320px";
      const canvas = document.createElement("canvas");
      wrap.appendChild(canvas);
      const statsEl = document.createElement("div");
      statsEl.className = "tele-stats small mt-1 mb-2";
      col.appendChild(heading);
      col.appendChild(wrap);
      col.appendChild(statsEl);
      this.chartsEl.appendChild(col);

      const tc = themeColors();
      let minX = Infinity;
      let maxX = -Infinity;
      metrics.forEach((m) => {
        const pts = series[m].points;
        if (pts.length) {
          minX = Math.min(minX, pts[0][0]);
          maxX = Math.max(maxX, pts[pts.length - 1][0]);
        }
      });
      // Zoom-out reaches the full range extent, not just the loaded window.
      const limitMin = this.rangeMin != null ? this.rangeMin : minX;
      const limitMax = this.rangeMax != null ? this.rangeMax : maxX;

      const datasets = [];
      const axisOrigDisplay = {};
      const axisUnits = {};
      const scales = {
        x: {
          type: "linear",
          min: minX,
          max: maxX,
          ticks: {
            maxRotation: 0,
            autoSkip: false,
            color: tc.tick,
            callback: (value, index, ticks) => {
              const span = ticks.length > 1 ? ticks[ticks.length - 1].value - ticks[0].value : 0;
              return fmt(value, span <= 2 * 86400 ? "time" : "date");
            },
          },
          grid: { color: tc.grid },
          afterBuildTicks: (axis) => {
            const n = 6;
            const lo = axis.min;
            const hi = axis.max;
            if (!(hi > lo)) {
              axis.ticks = [{ value: lo }];
              return;
            }
            const step = (hi - lo) / (n - 1);
            axis.ticks = Array.from({ length: n }, (_, i) => ({ value: lo + i * step }));
          },
        },
      };

      metrics.forEach((metric, idx) => {
        const s = series[metric];
        const color = COLORS[idx % COLORS.length];
        const axisId = "y_" + metric;
        const hasBand = !!(s.band && s.band.length);
        // Faded min/max envelope for aggregated (wide-range) data. Two hidden
        // datasets — lower (min) then upper (max) filled down to it. The backend
        // marks real data gaps with null band entries, so spanGaps:false breaks
        // the fill there instead of drawing across an outage.
        if (hasBand) {
          const bandCommon = {
            _band: true,
            yAxisID: axisId,
            borderColor: "transparent",
            pointRadius: 0,
            spanGaps: false,
            tension: 0.4,
            cubicInterpolationMode: "monotone",
          };
          datasets.push({
            ...bandCommon,
            data: s.band.map((b) => ({ x: b[0], y: b[1] })),
            fill: false,
          });
          datasets.push({
            ...bandCommon,
            data: s.band.map((b) => ({ x: b[0], y: b[2] })),
            backgroundColor: fade(color, bandAlpha(color)),
            fill: "-1",
          });
        }
        datasets.push({
          _metric: metric,
          _band_data: s.band || null,
          label: (METRIC_LABELS[metric] || metric) + (s.unit ? ` (${s.unit})` : ""),
          data: s.points.map((p) => ({ x: p[0], y: p[1] })),
          yAxisID: axisId,
          borderColor: color,
          backgroundColor: color + "22",
          borderWidth: 2,
          pointRadius: hasBand ? 0 : 2,
          pointHoverRadius: 5,
          cubicInterpolationMode: "monotone",
          tension: 0.4,
          spanGaps: false,
          // Aggregated data breaks at the backend's null markers; raw points
          // (buckets naturally many hours apart) break by wall-clock distance.
          segment: hasBand
            ? {}
            : {
                borderColor: (ctx) =>
                  ctx.p1.parsed.x - ctx.p0.parsed.x > GAP_LIMIT ? "rgba(0,0,0,0)" : undefined,
              },
        });
        const visible = idx < 2;
        axisOrigDisplay[axisId] = visible;
        axisUnits[axisId] = s.unit || "";
        scales[axisId] = {
          position: idx === 1 ? "right" : "left",
          display: visible,
          title: { display: visible, text: s.unit || METRIC_LABELS[metric] || metric, color: tc.text },
          ticks: { color: tc.tick },
          grid: { drawOnChartArea: idx === 0, color: tc.grid },
        };
        this.applyZeroScale(scales[axisId], s.unit || "");
      });

      const self = this;
      const chart = new Chart(canvas, {
        type: "line",
        data: { datasets },
        plugins: [crosshairPlugin],
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          onHover: (evt) => {
            const t = chart.scales.x.getValueForPixel(evt.x);
            if (isFinite(t)) self.syncHover(t);
          },
          plugins: {
            legend: {
              display: true,
              position: "bottom",
              labels: {
                color: tc.text,
                filter: (item, data) => !data.datasets[item.datasetIndex]._band,
              },
              onHover: (e, item, legend) => self.highlightMetric(legend.chart, item.datasetIndex),
              onLeave: (e, item, legend) => self.unhighlight(legend.chart),
              onClick: (e, item, legend) => self.toggleLegend(legend.chart, item.datasetIndex),
            },
            tooltip: {
              filter: (item) => !item.dataset._band,
              callbacks: {
                title: (items) => (items.length ? fmt(items[0].parsed.x, "datetime") : ""),
                label: (item) => {
                  const ds = item.dataset;
                  let out = ds.label + ": " + round(item.parsed.y);
                  if (ds._band_data && ds._band_data[item.dataIndex]) {
                    const b = ds._band_data[item.dataIndex];
                    out += ` (${round(b[1])}–${round(b[2])})`;
                  }
                  return out;
                },
              },
            },
            zoom: {
              limits: { x: { min: limitMin, max: limitMax, minRange: MIN_WINDOW } },
              pan: { enabled: false },
              zoom: {
                mode: "x",
                drag: {
                  enabled: true,
                  threshold: 10,
                  backgroundColor: "rgba(14, 116, 144, 0.15)",
                  borderColor: "rgba(14, 116, 144, 0.6)",
                  borderWidth: 1,
                },
                onZoomComplete: ({ chart }) => {
                  if (self.syncing) return;
                  self.applyWindow(chart.scales.x.min, chart.scales.x.max);
                },
              },
            },
          },
          scales,
        },
      });
      chart.$statsEl = statsEl;
      chart.$axisOrigDisplay = axisOrigDisplay;
      chart.$axisUnits = axisUnits;
      chart.$origMin = minX;
      chart.$origMax = maxX;

      canvas.addEventListener("dblclick", (e) => {
        const rect = canvas.getBoundingClientRect();
        const focus = chart.scales.x.getValueForPixel(e.clientX - rect.left);
        this.zoomAround(focus, 0.5);
      });
      canvas.addEventListener("mouseleave", () => this.clearHover());
      return chart;
    }

    applyWindow(min, max) {
      if (max - min < MIN_WINDOW) {
        const center = (min + max) / 2;
        min = center - MIN_WINDOW / 2;
        max = center + MIN_WINDOW / 2;
      }
      const lo = this.rangeMin != null ? this.rangeMin : this.fullMin;
      const hi = this.rangeMax != null ? this.rangeMax : this.fullMax;
      if (isFinite(lo)) min = Math.max(min, lo);
      if (isFinite(hi)) max = Math.min(max, hi);
      this.syncing = true;
      this.charts.forEach((c) => c.zoomScale("x", { min, max }, "none"));
      this.syncing = false;
      this.updateStats();
      this.scheduleDetail();
    }

    // After the view settles, refetch the visible window if it no longer matches
    // the resolution we have loaded (debounced so rapid zoom steps fetch once).
    scheduleDetail() {
      if (this._detailTimer) clearTimeout(this._detailTimer);
      this._detailTimer = setTimeout(() => {
        this._detailTimer = null;
        this.maybeFetchWindow();
      }, 350);
    }

    maybeFetchWindow() {
      if (!this.charts.length) return;
      const xs = this.charts[0].scales.x;
      const min = xs.min;
      const max = xs.max;
      const tol = (max - min) * 0.05;
      if (
        this.loadedMin != null &&
        this.loadedMax != null &&
        Math.abs(min - this.loadedMin) <= tol &&
        Math.abs(max - this.loadedMax) <= tol
      ) {
        return; // already showing this window at native resolution
      }
      this.loadWindow(min, max);
    }

    zoomBy(factor) {
      if (!this.charts.length) return;
      const x = this.charts[0].scales.x;
      const center = (x.min + x.max) / 2;
      const half = (x.max - x.min) / 2 / factor;
      this.applyWindow(center - half, center + half);
    }

    zoomAround(focus, factor) {
      if (!this.charts.length || !isFinite(focus)) return;
      const x = this.charts[0].scales.x;
      const half = ((x.max - x.min) / 2) * factor;
      this.applyWindow(focus - half, focus + half);
    }

    resetZoom() {
      // Back to the full range at its native (aggregated) resolution.
      this.load();
    }

    // Per-metric current value plus min / max / average over the visible window.
    updateStats() {
      this.charts.forEach((chart) => {
        const el = chart.$statsEl;
        if (!el) return;
        const xs = chart.scales.x;
        const parts = [];
        chart.data.datasets.forEach((ds) => {
          if (ds._band) return;
          let mn = Infinity;
          let mx = -Infinity;
          let sum = 0;
          let count = 0;
          ds.data.forEach((p, i) => {
            if (p.y == null || p.x < xs.min || p.x > xs.max) return;
            sum += p.y;
            count++;
            // Use the true min/max envelope when the data is aggregated.
            const b = ds._band_data && ds._band_data[i];
            if (b && b[1] != null) {
              if (b[1] < mn) mn = b[1];
              if (b[2] > mx) mx = b[2];
            } else {
              if (p.y < mn) mn = p.y;
              if (p.y > mx) mx = p.y;
            }
          });
          if (!count) return;
          let cur = null;
          for (let i = ds.data.length - 1; i >= 0; i--) {
            if (ds.data[i].y != null) {
              cur = ds.data[i].y;
              break;
            }
          }
          const label = ds.label.replace(/\s*\([^)]*\)$/, "");
          const unitMatch = ds.label.match(/\(([^)]*)\)$/);
          const unit = unitMatch ? unitMatch[1] : "";
          parts.push(
            '<span class="tele-stat me-3"><span class="tele-dot" style="background:' +
              ds.borderColor +
              '"></span>' +
              label +
              " <b>" +
              round(cur) +
              (unit ? " " + unit : "") +
              '</b> <span class="text-muted">' +
              round(mn) +
              "–" +
              round(mx) +
              " · μ" +
              round(sum / count) +
              "</span></span>"
          );
        });
        el.innerHTML = parts.join("");
      });
    }

    // Synced crosshair + tooltip across all charts at time t (throttled to rAF).
    syncHover(t) {
      this._pendingHover = t;
      if (this._hoverRAF) return;
      this._hoverRAF = requestAnimationFrame(() => {
        this._hoverRAF = null;
        this._applyHover(this._pendingHover);
      });
    }

    _applyHover(t) {
      this.charts.forEach((chart) => {
        chart._crosshairX = t;
        const line = chart.data.datasets.find((d) => !d._band);
        if (!line || !line.data.length) {
          chart.draw();
          return;
        }
        let idx = 0;
        let best = Infinity;
        for (let i = 0; i < line.data.length; i++) {
          const d = Math.abs(line.data[i].x - t);
          if (d < best) {
            best = d;
            idx = i;
          }
        }
        const active = [];
        chart.data.datasets.forEach((ds, di) => {
          if (!ds._band) active.push({ datasetIndex: di, index: idx });
        });
        chart.setActiveElements(active);
        if (chart.tooltip) {
          const px = chart.scales.x.getPixelForValue(t);
          chart.tooltip.setActiveElements(active, { x: px, y: chart.chartArea.top });
        }
        chart.update("none");
      });
    }

    clearHover() {
      this.charts.forEach((chart) => {
        chart._crosshairX = null;
        chart.setActiveElements([]);
        if (chart.tooltip) chart.tooltip.setActiveElements([], { x: 0, y: 0 });
        chart.update("none");
      });
    }

    // Legend hover: emphasise one metric (dim the rest) and reveal its axis.
    highlightMetric(chart, datasetIndex) {
      chart.data.datasets.forEach((ds, i) => {
        if (ds._fullColor == null) ds._fullColor = ds.borderColor;
        ds.borderColor = i === datasetIndex ? ds._fullColor : fade(ds._fullColor);
      });
      const axisId = chart.data.datasets[datasetIndex].yAxisID;
      if (chart.options.scales[axisId]) chart.options.scales[axisId].display = true;
      chart.update("none");
    }

    unhighlight(chart) {
      chart.data.datasets.forEach((ds) => {
        if (ds._fullColor != null) ds.borderColor = ds._fullColor;
      });
      const orig = chart.$axisOrigDisplay || {};
      Object.keys(orig).forEach((axisId) => {
        if (chart.options.scales[axisId]) chart.options.scales[axisId].display = orig[axisId];
      });
      chart.update("none");
    }

    // Legend click: hide/show the metric line together with its faded band
    // (the band datasets are hidden from the legend but share the line's axis).
    toggleLegend(chart, datasetIndex) {
      const line = chart.data.datasets[datasetIndex];
      if (!line) return;
      const axisId = line.yAxisID;
      const show = !chart.isDatasetVisible(datasetIndex);
      chart.setDatasetVisibility(datasetIndex, show);
      chart.data.datasets.forEach((ds, i) => {
        if (ds._band && ds.yAxisID === axisId) chart.setDatasetVisibility(i, show);
      });
      chart.update();
    }

    // When the zero-baseline toggle is on, pin each axis to its natural full
    // scale: percentages 0–100, cell voltage 0–4.6 V, anything else 0–auto.
    // When off, clear the fixed bounds so the axis auto-fits the data again.
    applyZeroScale(scale, unit) {
      if (!this.zeroBase) {
        scale.min = undefined;
        scale.max = undefined;
        scale.beginAtZero = false;
        return;
      }
      scale.beginAtZero = true;
      if (unit === "%") {
        scale.min = 0;
        scale.max = 100;
      } else if (unit === "V") {
        scale.min = 0;
        scale.max = 4.6;
      } else {
        scale.min = 0;
        scale.max = undefined;
      }
    }

    toggleZero(btn) {
      this.zeroBase = !this.zeroBase;
      if (btn) btn.classList.toggle("active", this.zeroBase);
      this.charts.forEach((chart) => {
        const units = chart.$axisUnits || {};
        Object.keys(chart.options.scales).forEach((id) => {
          if (id !== "x") this.applyZeroScale(chart.options.scales[id], units[id]);
        });
        chart.update("none");
      });
    }

    destroyCharts() {
      this.charts.forEach((c) => c.destroy());
      this.charts = [];
      if (this.chartsEl) this.chartsEl.innerHTML = "";
    }
  }

  window.NodeTelemetryChart = NodeTelemetryChart;
})();

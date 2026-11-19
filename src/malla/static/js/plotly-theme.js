/**
 * MallaPlotlyTheme — shared token bridge for Plotly charts (legacy-page
 * companion to the design system in malla.css).
 *
 * Resolves --malla-* CSS custom properties at call time, so charts re-theme
 * instantly when [data-bs-theme] flips; pair with onThemeChange() to re-render.
 *
 * const t = window.MallaPlotlyTheme;
 * Plotly.newPlot(div, traces, t.layout({
 *   xaxis: { title: '...' }, ...
 * }), { responsive: true });
 * t.onThemeChange(() => Plotly.react(div, traces, t.layout({...})));
 */
(function () {
    'use strict';

    function token(name, fallback) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fallback || null;
    }

    function isDark() {
        return document.documentElement.getAttribute('data-bs-theme') === 'dark';
    }

    /** rgba() from #hex/#rgb/#rgba with alpha override — for series fills. */
    function alpha(color, a) {
        if (!color) return color;
        const assign = (r, g, b) => `rgba(${r}, ${g}, ${b}, ${a})`;
        let m = String(color).trim().match(/^#([0-9a-f]{3})$/i);
        if (m) return assign(...m[1].split('').map((c) => parseInt(c + c, 16)));
        m = String(color).trim().match(/^#([0-9a-f]{6})$/i);
        if (m) return assign(...[0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)));
        m = color.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
        if (m) return assign(+m[1], +m[2], +m[3]);
        return color;
    }

    function colors() {
        return {
            text: token('--malla-text', '#17212e'),
            muted: token('--malla-text-muted', '#5b6b7c'),
            border: token('--malla-border', '#dfe5ec'),
            surface: token('--malla-surface', '#ffffff'),
            primary: token('--malla-primary', '#2563eb'),
            success: token('--malla-success', '#15803d'),
            warning: token('--malla-warning-strong', '#d97706'),
            danger: token('--malla-danger', '#c0392b'),
            info: token('--malla-info', '#0e7490'),
        };
    }

    /** Tokenized base layout; per-axis colors injected unless overridden. */
    function layout(overrides = {}) {
        const c = colors();
        const base = {
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {
                family: getComputedStyle(document.body).fontFamily,
                size: 12,
                color: c.text,
            },
            colorway: [c.primary, c.warning, c.success, c.info, c.danger],
        };

        const merged = { ...base, ...overrides };
        // Theme every axis present in the override (or a default one).
        const axisKeys = Object.keys(merged).filter(
            (k) => k === 'xaxis' || k === 'yaxis' || /^([xyz])axis\d*$|^ polar$/.test(k)
        );
        const axisDefaults = {
            gridcolor: alpha(c.text, 0.12),
            linecolor: c.border,
            tickfont: { size: 11, color: c.muted },
        };
        for (const key of axisKeys) {
            const user = merged[key] || {};
            // Title accepts the string shorthand Plotly documents.
            const rawTitle = user.title;
            const title =
                typeof rawTitle === 'string'
                    ? { text: rawTitle, font: { size: 12, color: c.muted } }
                    : rawTitle
                      ? { font: { size: 12, color: c.muted }, ...rawTitle }
                      : undefined;
            merged[key] = { ...axisDefaults, ...user, title };
            if (merged[key].title && merged[key].title.font === undefined) {
                delete merged[key].title;
            }
        }
        if (merged.title) {
            merged.title = { font: { size: 14, color: c.text }, ...merged.title };
        }
        return merged;
    }

    /** Default config: no modebar chrome, responsive. */
    function config(overrides = {}) {
        return { displayModeBar: false, responsive: true, ...overrides };
    }

    /** Invoke `render()` now and on every theme flip. Returns a disposer. */
    function onThemeChange(render) {
        render();
        const handler = () => render();
        window.addEventListener('themeChanged', handler);
        return () => window.removeEventListener('themeChanged', handler);
    }

    window.MallaPlotlyTheme = {
        token,
        alpha,
        colors,
        layout,
        config,
        onThemeChange,
        isDark,
    };
})();

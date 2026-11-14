/**
 * AutoRefresh — periodic data refresh with explicit user control.
 *
 * - interval tick calls `onRefresh` (may be async; overlapping ticks skip)
 * - pause/play button wiring (label, icon, aria-pressed)
 * - tab visibility honored: hidden tabs do not tick; resumes on focus
 * - optional status element showing a live "Updated <time>" stamp
 *
 * Usage:
 *   const refresher = new AutoRefresh({
 *     intervalMs: 30000,
 *     onRefresh: () => loadDashboardData({ silent: true }),
 *     pauseButton: document.getElementById('refresh-toggle'),
 *     statusEl: document.getElementById('refresh-status'),
 *   });
 *   refresher.start();
 */

const DEFAULTS = {
    intervalMs: 30000,
    pauseLabel: 'Pause auto-refresh',
    playLabel: 'Resume auto-refresh',
};

export class AutoRefresh {
    constructor(options = {}) {
        this.options = { ...DEFAULTS, ...options };
        this.timer = null;
        this.userPaused = false;
        this.refreshing = false;
        this.lastUpdated = null;

        if (this.options.pauseButton) {
            this.pauseButton = this.options.pauseButton;
            this.pauseButton.addEventListener('click', () => this.toggle());
        }

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.stopTimer();
            } else if (!this.userPaused) {
                this.startTimer();
            }
        });
    }

    start() {
        this.userPaused = false;
        this.startTimer();
        this.renderButton();
        // Refresh immediately so a page opened in a background tab is current
        // when first viewed? No: caller controls the initial load. Only the
        // interval is managed here.
        return this;
    }

    startTimer() {
        this.stopTimer();
        this.timer = setInterval(() => this.tick(), this.options.intervalMs);
    }

    stopTimer() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    async tick() {
        if (this.refreshing) return;
        if (typeof this.options.onRefresh !== 'function') return;
        this.refreshing = true;
        try {
            await this.options.onRefresh();
            this.lastUpdated = new Date();
            this.renderStatus();
        } finally {
            this.refreshing = false;
        }
    }

    toggle() {
        this.userPaused = !this.userPaused;
        if (this.userPaused) {
            this.stopTimer();
        } else {
            this.startTimer();
        }
        this.renderButton();
        this.renderStatus();
    }

    /** Force an immediate refresh (also resets the interval). */
    async refreshNow() {
        if (!this.userPaused) this.startTimer();
        await this.tick();
    }

    renderButton() {
        const button = this.pauseButton;
        if (!button) return;
        const paused = this.userPaused;
        button.setAttribute('aria-pressed', String(paused));
        button.title = paused ? this.options.playLabel : this.options.pauseLabel;
        button.setAttribute(
            'aria-label',
            paused ? this.options.playLabel : this.options.pauseLabel
        );
        const icon = button.querySelector('i');
        if (icon) {
            icon.className = paused ? 'bi bi-play-fill' : 'bi bi-pause-fill';
        }
    }

    renderStatus() {
        const el = this.options.statusEl
            ?? (this.options.statusElId
                ? document.getElementById(this.options.statusElId)
                : null);
        if (!el) return;

        el.classList.toggle('paused', this.userPaused);
        const dot = el.querySelector('.refresh-dot');
        if (dot) dot.style.display = this.userPaused ? 'none' : '';

        const timeEl = el.querySelector('.refresh-time');
        const stamp = this.lastUpdated
            ? this.lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            : '—';
        if (timeEl) {
            timeEl.textContent = stamp;
        } else {
            el.lastChild && (el.lastChild.textContent = '');
        }
    }

    destroy() {
        this.stopTimer();
        if (this.pauseButton) {
            this.pauseButton.replaceWith(this.pauseButton.cloneNode(true));
        }
    }
}

window.AutoRefresh = AutoRefresh;

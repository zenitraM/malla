/**
 * Timezone Toggle Component
 * Provides persistent timezone functionality using localStorage
 * Allows switching between browser's local timezone and UTC
 */

class TimezoneToggle {
    constructor() {
        this.storageKey = 'malla-timezone-preference';
        this.init();
    }

    init() {
        // Apply saved timezone preference on page load
        this.applyTimezone(this.getTimezonePreference());

        // Initialize toggle button if it exists
        this.initToggleButton();
    }

    /**
     * Get the user's timezone preference from localStorage
     * @returns {string} 'local' or 'utc'
     */
    getTimezonePreference() {
        const saved = localStorage.getItem(this.storageKey);
        if (saved && ['local', 'utc'].includes(saved)) {
            return saved;
        }
        return 'local'; // Default to local (browser) timezone
    }

    /**
     * Set timezone preference and apply it
     * @param {string} timezone - 'local' or 'utc'
     */
    setTimezone(timezone) {
        if (!['local', 'utc'].includes(timezone)) {
            console.warn('Invalid timezone:', timezone);
            return;
        }

        // Save to localStorage first
        localStorage.setItem(this.storageKey, timezone);

        // Update button state
        this.updateToggleButton();

        // Dispatch custom event for other components to listen to
        // This will trigger a page reload in timezone-utils.js
        window.dispatchEvent(new CustomEvent('timezoneChanged', {
            detail: {
                timezone: timezone
            }
        }));
    }

    /**
     * Apply timezone preference to the page
     * @param {string} timezone - 'local' or 'utc'
     */
    applyTimezone(timezone) {
        // Store current preference on window for easy access
        window.currentTimezone = timezone;

        // Update all existing timestamps on the page
        this.updateAllTimestamps();

        // Update all datetime-local inputs
        this.updateAllDateTimeInputs();
    }

    /**
     * Initialize the toggle button functionality
     */
    initToggleButton() {
        const toggleButton = document.getElementById('timezone-toggle');
        if (!toggleButton) return;

        toggleButton.addEventListener('click', () => {
            this.toggleTimezone();
        });

        this.updateToggleButton();
    }

    /**
     * Toggle between local and UTC
     */
    toggleTimezone() {
        const current = this.getTimezonePreference();
        const next = current === 'local' ? 'utc' : 'local';
        this.setTimezone(next);
    }

    /**
     * Update toggle button appearance and tooltip
     */
    updateToggleButton() {
        const toggleButton = document.getElementById('timezone-toggle');
        if (!toggleButton) return;

        const preference = this.getTimezonePreference();

        // Update icon
        const icon = toggleButton.querySelector('i');
        if (icon) {
            icon.className = this.getTimezoneIcon(preference);
        }

        // Update tooltip
        const tooltip = bootstrap.Tooltip.getInstance(toggleButton);
        if (tooltip) {
            tooltip.setContent({
                '.tooltip-inner': this.getTimezoneTooltip(preference)
            });
        } else {
            toggleButton.setAttribute('title', this.getTimezoneTooltip(preference));
        }

        // Update aria-label for accessibility
        toggleButton.setAttribute('aria-label', this.getTimezoneAriaLabel(preference));
    }

    /**
     * Get icon class for timezone
     * @param {string} preference - 'local' or 'utc'
     * @returns {string} Bootstrap icon class
     */
    getTimezoneIcon(preference) {
        const icons = {
            'local': 'bi bi-globe',
            'utc': 'bi bi-clock-history'
        };
        return icons[preference] || icons.local;
    }

    /**
     * Get tooltip text for timezone
     * @param {string} preference - 'local' or 'utc'
     * @returns {string} Tooltip text
     */
    getTimezoneTooltip(preference) {
        const tooltips = {
            'local': 'Switch to UTC timezone',
            'utc': 'Switch to browser timezone'
        };
        return tooltips[preference] || 'Toggle timezone';
    }

    /**
     * Get aria-label for timezone button
     * @param {string} preference - 'local' or 'utc'
     * @returns {string} Aria label text
     */
    getTimezoneAriaLabel(preference) {
        const labels = {
            'local': 'Currently showing local time, click to switch to UTC',
            'utc': 'Currently showing UTC time, click to switch to local time'
        };
        return labels[preference] || 'Toggle timezone';
    }

    /**
     * Update all timestamps on the page based on current timezone preference
     */
    updateAllTimestamps() {
        // This will be called by individual components when they render
        // We dispatch an event so tables and other components can update
        const event = new CustomEvent('timezonePreferenceChanged', {
            detail: { timezone: this.getTimezonePreference() }
        });
        document.dispatchEvent(event);
    }

    /**
     * Update all datetime-local inputs based on current timezone preference
     */
    updateAllDateTimeInputs() {
        // No action needed: <input type="datetime-local"> values are always in local time per HTML spec.
        // If timezone conversion is required, handle it during form submission, not here.
    }

    /**
     * Format a Unix timestamp according to current timezone preference
     * @param {number} timestamp - Unix timestamp in seconds
     * @param {string} format - 'datetime' or 'time' or 'date'
     * @returns {string} Formatted time string
     */
    formatTimestamp(timestamp, format = 'datetime') {
        if (!timestamp) return '';

        const preference = this.getTimezonePreference();
        const date = new Date(timestamp * 1000);

        if (preference === 'utc') {
            // Format as UTC
            if (format === 'datetime') {
                return this.formatUTCDateTime(date);
            } else if (format === 'date') {
                return this.formatUTCDate(date);
            } else if (format === 'time') {
                return this.formatUTCTime(date);
            }
        } else {
            // Format as local time
            if (format === 'datetime') {
                return this.formatLocalDateTime(date);
            } else if (format === 'date') {
                return this.formatLocalDate(date);
            } else if (format === 'time') {
                return this.formatLocalTime(date);
            }
        }

        return date.toISOString();
    }

    /**
     * Format date as UTC datetime string
     */
    formatUTCDateTime(date) {
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, '0');
        const day = String(date.getUTCDate()).padStart(2, '0');
        const hours = String(date.getUTCHours()).padStart(2, '0');
        const minutes = String(date.getUTCMinutes()).padStart(2, '0');
        const seconds = String(date.getUTCSeconds()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
    }

    /**
     * Format date as UTC date string
     */
    formatUTCDate(date) {
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, '0');
        const day = String(date.getUTCDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    /**
     * Format date as UTC time string
     */
    formatUTCTime(date) {
        const hours = String(date.getUTCHours()).padStart(2, '0');
        const minutes = String(date.getUTCMinutes()).padStart(2, '0');
        const seconds = String(date.getUTCSeconds()).padStart(2, '0');
        return `${hours}:${minutes}:${seconds} UTC`;
    }

    /**
     * Format date as local datetime string
     */
    formatLocalDateTime(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }

    /**
     * Format date as local date string
     */
    formatLocalDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    /**
     * Format date as local time string
     */
    formatLocalTime(date) {
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${hours}:${minutes}:${seconds}`;
    }

    /**
     * Convert datetime-local input value to Unix timestamp
     * datetime-local is always in the browser's local timezone
     * @param {string} datetimeLocalValue - Value from datetime-local input
     * @returns {number} Unix timestamp in seconds
     */
    datetimeLocalToTimestamp(datetimeLocalValue) {
        if (!datetimeLocalValue) return null;
        const date = new Date(datetimeLocalValue);
        return date.getTime() / 1000;
    }

    /**
     * Convert Unix timestamp to datetime-local input value
     * @param {number} timestamp - Unix timestamp in seconds
     * @returns {string} Value for datetime-local input (always in local time)
     */
    timestampToDatetimeLocal(timestamp) {
        if (!timestamp) return '';

        const date = new Date(timestamp * 1000);
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');

        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }
}

// Initialize timezone toggle when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.timezoneToggle = new TimezoneToggle();
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimezoneToggle;
}

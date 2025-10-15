/**
 * Dark Mode Toggle Component
 * Provides persistent dark mode functionality using localStorage and Bootstrap's data-bs-theme system
 */

class DarkModeToggle {
    constructor() {
        this.storageKey = 'malla-theme-preference';
        this.init();
    }

    init() {
        // Apply saved theme or system preference on page load
        this.applyTheme(this.getThemePreference());

        // Listen for system theme changes
        this.watchSystemTheme();

        // Initialize toggle button if it exists
        this.initToggleButton();
    }

    /**
     * Get the user's theme preference from localStorage or system preference
     * @returns {string} 'light', 'dark', or 'auto'
     */
    getThemePreference() {
        const saved = localStorage.getItem(this.storageKey);
        if (saved && ['light', 'dark', 'auto'].includes(saved)) {
            return saved;
        }
        return 'auto'; // Default to auto (system preference)
    }

    /**
     * Get the effective theme (resolves 'auto' to actual theme)
     * @returns {string} 'light' or 'dark'
     */
    getEffectiveTheme() {
        const preference = this.getThemePreference();
        if (preference === 'auto') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return preference;
    }

    /**
     * Set theme preference and apply it
     * @param {string} theme - 'light', 'dark', or 'auto'
     */
    setTheme(theme) {
        if (!['light', 'dark', 'auto'].includes(theme)) {
            console.warn('Invalid theme:', theme);
            return;
        }

        localStorage.setItem(this.storageKey, theme);
        this.applyTheme(theme);
        this.updateToggleButton();

        // Dispatch custom event for other components to listen to
        window.dispatchEvent(new CustomEvent('themeChanged', {
            detail: {
                preference: theme,
                effective: this.getEffectiveTheme()
            }
        }));
    }

    /**
     * Apply theme to the document
     * @param {string} theme - 'light', 'dark', or 'auto'
     */
    applyTheme(theme) {
        const effectiveTheme = theme === 'auto'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : theme;

        document.documentElement.setAttribute('data-bs-theme', effectiveTheme);

        // Update meta theme-color for mobile browsers
        this.updateMetaThemeColor(effectiveTheme);
    }

    /**
     * Update meta theme-color for mobile browsers
     * @param {string} theme - 'light' or 'dark'
     */
    updateMetaThemeColor(theme) {
        let metaThemeColor = document.querySelector('meta[name="theme-color"]');
        if (!metaThemeColor) {
            metaThemeColor = document.createElement('meta');
            metaThemeColor.name = 'theme-color';
            document.head.appendChild(metaThemeColor);
        }

        // Use Bootstrap's primary color for light mode, dark background for dark mode
        metaThemeColor.content = theme === 'dark' ? '#212529' : '#0d6efd';
    }

    /**
     * Watch for system theme changes
     */
    watchSystemTheme() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', () => {
            if (this.getThemePreference() === 'auto') {
                this.applyTheme('auto');
                this.updateToggleButton();
            }
        });
    }

    /**
     * Initialize the toggle button functionality
     */
    initToggleButton() {
        const toggleButton = document.getElementById('theme-toggle');
        if (!toggleButton) return;

        toggleButton.addEventListener('click', () => {
            this.cycleTheme();
        });

        this.updateToggleButton();
    }

    /**
     * Cycle through theme options: light → dark → auto → light
     */
    cycleTheme() {
        const current = this.getThemePreference();
        const next = {
            'light': 'dark',
            'dark': 'auto',
            'auto': 'light'
        }[current] || 'light';

        this.setTheme(next);
    }

    /**
     * Toggle between light and dark (skipping auto)
     */
    toggleTheme() {
        const effective = this.getEffectiveTheme();
        this.setTheme(effective === 'light' ? 'dark' : 'light');
    }

    /**
     * Update toggle button appearance and tooltip
     */
    updateToggleButton() {
        const toggleButton = document.getElementById('theme-toggle');
        if (!toggleButton) return;

        const preference = this.getThemePreference();
        const effective = this.getEffectiveTheme();

        // Update icon
        const icon = toggleButton.querySelector('i');
        if (icon) {
            icon.className = this.getThemeIcon(preference);
        }

        // Update tooltip
        const tooltip = bootstrap.Tooltip.getInstance(toggleButton);
        if (tooltip) {
            tooltip.setContent({
                '.tooltip-inner': this.getThemeTooltip(preference, effective)
            });
        } else {
            toggleButton.setAttribute('title', this.getThemeTooltip(preference, effective));
        }

        // Update aria-label for accessibility
        toggleButton.setAttribute('aria-label', this.getThemeAriaLabel(preference, effective));
    }

    /**
     * Get icon class for theme
     * @param {string} preference - 'light', 'dark', or 'auto'
     * @returns {string} Bootstrap icon class
     */
    getThemeIcon(preference) {
        const icons = {
            'light': 'bi bi-sun-fill',
            'dark': 'bi bi-moon-stars-fill',
            'auto': 'bi bi-circle-half'
        };
        return icons[preference] || icons.auto;
    }

    /**
     * Get tooltip text for theme
     * @param {string} preference - 'light', 'dark', or 'auto'
     * @param {string} effective - 'light' or 'dark'
     * @returns {string} Tooltip text
     */
    getThemeTooltip(preference, effective) {
        const tooltips = {
            'light': 'Switch to dark mode',
            'dark': 'Switch to auto mode',
            'auto': `Auto mode (currently ${effective}) - Switch to light mode`
        };
        return tooltips[preference] || 'Toggle theme';
    }

    /**
     * Get aria-label for theme button
     * @param {string} preference - 'light', 'dark', or 'auto'
     * @param {string} effective - 'light' or 'dark'
     * @returns {string} Aria label text
     */
    getThemeAriaLabel(preference, effective) {
        const labels = {
            'light': 'Currently light mode, click to switch to dark mode',
            'dark': 'Currently dark mode, click to switch to auto mode',
            'auto': `Currently auto mode (${effective}), click to switch to light mode`
        };
        return labels[preference] || 'Toggle theme mode';
    }
}

// Initialize dark mode toggle when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.darkModeToggle = new DarkModeToggle();
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DarkModeToggle;
}


/**
 * Theme toggle module — handles dark/light mode switching
 * Persists preference in localStorage and respects system preference
 */
import { on, qs } from './lib/dom.js';

const THEME_KEY = 'backlink-publisher-theme';
const THEME_TRANSITION_CLASS = 'theme-transition';

/**
 * Get the initial theme preference
 * Priority: localStorage > system preference > light (default)
 */
function getInitialTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'dark' || stored === 'light') {
        return stored;
    }
    // Respect system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

/**
 * Apply theme to document
 */
function applyTheme(theme, animate = false) {
    if (animate) {
        document.documentElement.classList.add(THEME_TRANSITION_CLASS);
        setTimeout(() => {
            document.documentElement.classList.remove(THEME_TRANSITION_CLASS);
        }, 300);
    }
    
    document.documentElement.setAttribute('data-theme', theme);
    // Keep Bootstrap's own theming attribute in sync so its components (modals,
    // dropdowns) track the same theme as our custom tokens. base.html ships
    // data-bs-theme="dark"; without this, toggling to light left them dark.
    document.documentElement.setAttribute('data-bs-theme', theme);

    // Update toggle button icon
    const toggle = qs('#themeToggle');
    if (toggle) {
        const icon = toggle.querySelector('i');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
        }
        toggle.setAttribute('aria-label', 
            theme === 'dark' ? '切换到浅色模式' : '切换到深色模式');
    }
}

/**
 * Toggle between dark and light themes
 */
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    
    applyTheme(next, true);
    localStorage.setItem(THEME_KEY, next);
}

/**
 * Initialize theme on page load
 */
function initTheme() {
    const theme = getInitialTheme();
    applyTheme(theme, false);
    
    // Bind toggle button
    const toggle = qs('#themeToggle');
    if (toggle) {
        on(toggle, 'click', toggleTheme);
    }
    
    // Listen for system preference changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            // Only auto-switch if user hasn't manually set a preference
            if (!localStorage.getItem(THEME_KEY)) {
                applyTheme(e.matches ? 'dark' : 'light', true);
            }
        });
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
} else {
    initTheme();
}
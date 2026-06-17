/**
 * Navigation module — handles mobile drawer, search, and keyboard shortcuts
 */
import { on, qs, qsa } from './lib/dom.js';

/**
 * Search data — pages and their descriptions
 */
const SEARCH_DATA = [
    { title: '发布', desc: '创建新的发布任务', url: '/', icon: 'bi-send' },
    { title: '批量任务', desc: '批量发布多个URL', url: '/batch-campaign', icon: 'bi-stack' },
    { title: '保活', desc: '外链存活监控', url: '/ce:keep-alive', icon: 'bi-shield-check' },
    { title: '存活率', desc: '链接存活率统计', url: '/survival-dashboard', icon: 'bi-graph-up' },
    { title: '健康', desc: '发布健康仪表盘', url: '/ce:health', icon: 'bi-heart-pulse' },
    { title: '指挥', desc: '命令中心', url: '/ce:command-center', icon: 'bi-speedometer2' },
    { title: '站点', desc: '站点配置管理', url: '/sites', icon: 'bi-globe2' },
    { title: '排程', desc: '定时发布排程', url: '/schedule', icon: 'bi-calendar-week' },
    { title: '权益', desc: '外链权益记账', url: '/ce:equity-ledger', icon: 'bi-graph-up-arrow' },
    { title: 'PR队列', desc: 'PR外联机会', url: '/pr-queue', icon: 'bi-newspaper' },
    { title: '设置', desc: '系统设置', url: '/settings', icon: 'bi-gear' },
];

/**
 * Mobile drawer management
 */
class MobileDrawer {
    constructor() {
        this.sidebar = qs('#appSidebar');
        this.backdrop = qs('.app-sidebar__backdrop');
        this.hamburger = qs('#navHamburger');
        this.isOpen = false;

        if (this.sidebar && this.hamburger) {
            this.init();
        }
    }

    init() {
        on(this.hamburger, 'click', () => this.toggle());

        // Close on backdrop / close-button click
        qsa('[data-action="close-sidebar"]').forEach(el => {
            on(el, 'click', () => this.close());
        });

        // Close on escape
        on(document, 'keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    toggle() {
        this.isOpen ? this.close() : this.open();
    }

    open() {
        this.sidebar.classList.add('open');
        if (this.backdrop) this.backdrop.classList.add('show');
        this.hamburger.setAttribute('aria-expanded', 'true');
        this.isOpen = true;
        document.body.style.overflow = 'hidden';
    }

    close() {
        this.sidebar.classList.remove('open');
        if (this.backdrop) this.backdrop.classList.remove('show');
        this.hamburger.setAttribute('aria-expanded', 'false');
        this.isOpen = false;
        document.body.style.overflow = '';
    }
}

/**
 * Search modal management
 */
class SearchModal {
    constructor() {
        this.modal = qs('#searchModal');
        this.input = qs('#searchInput');
        this.results = qs('#searchResults');
        this.searchBtn = qs('#searchToggle');
        this.isOpen = false;
        this.activeIndex = -1;
        
        if (this.modal && this.input && this.results) {
            this.init();
        }
    }
    
    init() {
        // Open search
        if (this.searchBtn) {
            on(this.searchBtn, 'click', () => this.open());
        }
        
        // Close on overlay click
        qsa('[data-action="close-search"]').forEach(el => {
            on(el, 'click', () => this.close());
        });
        
        // Keyboard shortcuts
        on(document, 'keydown', (e) => {
            // Ctrl+K or Cmd+K to open search
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.isOpen ? this.close() : this.open();
            }
            
            // Escape to close
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
            
            // Arrow keys to navigate results
            if (this.isOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
                e.preventDefault();
                this.navigateResults(e.key === 'ArrowDown' ? 1 : -1);
            }
            
            // Enter to select result
            if (this.isOpen && e.key === 'Enter' && this.activeIndex >= 0) {
                e.preventDefault();
                this.selectResult();
            }
        });
        
        // Search on input
        on(this.input, 'input', () => this.search());
    }
    
    open() {
        this.modal.setAttribute('aria-hidden', 'false');
        this.isOpen = true;
        this.input.value = '';
        this.input.focus();
        this.showDefaultResults();
        document.body.style.overflow = 'hidden';
    }
    
    close() {
        this.modal.setAttribute('aria-hidden', 'true');
        this.isOpen = false;
        this.activeIndex = -1;
        document.body.style.overflow = '';
    }
    
    search() {
        const query = this.input.value.toLowerCase().trim();
        
        if (!query) {
            this.showDefaultResults();
            return;
        }
        
        const filtered = SEARCH_DATA.filter(item => 
            item.title.toLowerCase().includes(query) ||
            item.desc.toLowerCase().includes(query)
        );
        
        this.renderResults(filtered);
    }
    
    showDefaultResults() {
        this.renderResults(SEARCH_DATA.slice(0, 6));
    }
    
    renderResults(items) {
        this.activeIndex = -1;
        
        if (items.length === 0) {
            this.results.innerHTML = '<div class="search-modal__empty">未找到匹配结果</div>';
            return;
        }
        
        this.results.innerHTML = items.map((item, index) => `
            <a href="${item.url}" class="search-modal__item" data-index="${index}">
                <div class="search-modal__item-icon">
                    <i class="bi ${item.icon}"></i>
                </div>
                <div class="search-modal__item-text">
                    <div class="search-modal__item-title">${item.title}</div>
                    <div class="search-modal__item-desc">${item.desc}</div>
                </div>
            </a>
        `).join('');
        
        // Add click handlers
        qsa('.search-modal__item', this.results).forEach(el => {
            on(el, 'click', () => this.close());
        });
    }
    
    navigateResults(direction) {
        const items = qsa('.search-modal__item', this.results);
        if (items.length === 0) return;
        
        // Remove active from current
        if (this.activeIndex >= 0 && items[this.activeIndex]) {
            items[this.activeIndex].classList.remove('active');
        }
        
        // Calculate new index
        this.activeIndex += direction;
        if (this.activeIndex < 0) this.activeIndex = items.length - 1;
        if (this.activeIndex >= items.length) this.activeIndex = 0;
        
        // Add active to new
        items[this.activeIndex].classList.add('active');
        items[this.activeIndex].scrollIntoView({ block: 'nearest' });
    }
    
    selectResult() {
        const items = qsa('.search-modal__item', this.results);
        if (this.activeIndex >= 0 && items[this.activeIndex]) {
            items[this.activeIndex].click();
        }
    }
}

/**
 * Initialize navigation
 */
function initNav() {
    new MobileDrawer();
    new SearchModal();
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNav);
} else {
    initNav();
}
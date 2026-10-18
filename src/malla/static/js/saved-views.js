/**
 * Saved views for the table filter sidebars.
 *
 * Persists named snapshots of the filter form per page in
 * localStorage (`malla.savedViews.<page>`). Apply writes the snapshot back
 * through the EXISTING url-filter-manager/table-filter-controller path
 * (set inputs, then trigger the page's applyCurrentFilters) — no parallel
 * filter state. The same widget mounts in the sidebar footer and, while the
 * sidebar is collapsed, next to the table header controls.
 *
 * All dynamic strings render via textContent (XSS-safe); no innerHTML of
 * user data.
 */
(function () {
    'use strict';

    const pageSegment = location.pathname.replace(/^\/+|\/+$/g, '').split('/')[0];
    const STORE_KEY = `malla.savedViews.${pageSegment || 'default'}`;
    const NODE_PICKERS = ['from_node', 'to_node', 'route_node', 'exclude_from', 'exclude_to'];
    const GATEWAY_PICKER = 'gateway_id';
    const MAX_CHIPS = 4;

    const instances = [];

    function h(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = String(text);
        return node;
    }

    function loadViews() {
        try {
            const raw = JSON.parse(localStorage.getItem(STORE_KEY) || '[]');
            return Array.isArray(raw) ? raw : [];
        } catch (error) {
            return [];
        }
    }

    function persist(views) {
        let persisted = true;
        try {
            localStorage.setItem(STORE_KEY, JSON.stringify(views));
        } catch (error) {
            /* private mode: views stay session-only */
            persisted = false;
        }
        instances.forEach((render) => render());
        return persisted;
    }

    function toast(message, variant) {
        if (window.MallaToast && window.MallaToast[variant || 'success']) {
            window.MallaToast[variant || 'success'](message, { title: 'Saved views' });
        }
    }

    function summaryChips(filters) {
        const wrap = h('span', 'sv-chips');
        const keys = Object.keys(filters || {})
            .filter((k) => k !== 'group_packets')
            .slice(0, MAX_CHIPS);
        keys.forEach((key) => {
            wrap.appendChild(h('span', 'badge bg-light text-dark border sv-chip',
                `${key}: ${String(filters[key]).slice(0, 18)}`));
        });
        const total = Object.keys(filters || {}).length;
        if (total > MAX_CHIPS) {
            wrap.appendChild(h('span', 'badge bg-secondary sv-chip', `+${total - MAX_CHIPS}`));
        }
        if (filters && filters.group_packets) {
            wrap.appendChild(h('span', 'badge bg-info sv-chip', 'grouped'));
        }
        if (total === 0 && !(filters && filters.group_packets)) {
            wrap.appendChild(h('span', 'badge bg-secondary sv-chip', 'no filters'));
        }
        return wrap;
    }

    async function applyView(view) {
        const filters = view && view.filters ? view.filters : {};
        const form = document.querySelector('#filtersForm');
        const urlManager = window.urlManager;

        if (form) {
            form.querySelectorAll('input, select, textarea').forEach((input) => {
                const key = input.name;
                if (!key) return;
                if (key === 'group_packets') {
                    const value = filters.group_packets;
                    input.checked = value === undefined ? true : value === true || value === 'true';
                    return;
                }
                if (!(key in filters)) {
                    if (input.type === 'checkbox') input.checked = false;
                    else if (!input.disabled) input.value = '';
                    return;
                }
                const value = filters[key];
                if (input.type === 'checkbox') {
                    input.checked = value === true || value === 'true' || value === '1' || value === 'on';
                } else {
                    input.value = value == null ? '' : String(value);
                }
            });
        }

        // The grouping checkbox lives outside #filtersForm, so the form loop
        // above cannot restore it; without this the applied view silently
        // keeps the current grouping and its row count disagrees.
        const grouping = document.getElementById('group_packets')
            || document.getElementById('groupPackets')
            || document.getElementById('groupTraceroutes');
        if (grouping && 'group_packets' in filters) {
            const value = filters.group_packets;
            grouping.checked = value === true || value === 'true' || value === '1' || value === 'on';
        }

        // Existing apply path: table.setFilters + URL sync from the form state.
        if (typeof window.applyCurrentFilters === 'function') {
            window.applyCurrentFilters();
        }

        // Picker widgets need their visible labels refreshed; cosmetic, so
        // best effort after the data apply.
        if (urlManager) {
            NODE_PICKERS.forEach((field) => {
                if (filters[field]) {
                    Promise.resolve(urlManager.setNodePickerValue(field, filters[field]))
                        .catch(() => {});
                }
            });
            if (filters[GATEWAY_PICKER]) {
                Promise.resolve(urlManager.setGatewayPickerValue(GATEWAY_PICKER, filters[GATEWAY_PICKER]))
                    .catch(() => {});
            }
        }
        // Visible pickers are deliberately unnamed inputs: sync their shown
        // text with the (possibly cleared) hidden values.
        document.querySelectorAll('.node-picker-clear').forEach((btn) => {
            if (btn instanceof HTMLElement) btn.click();
        });
        document.querySelectorAll('.node-picker-input').forEach((input) => {
            if (input instanceof HTMLInputElement) input.value = '';
        });
        toast(`Applied view “${view.name}”`, 'success');
    }

    function saveCurrent(name) {
        const trimmed = String(name || '').trim();
        if (!trimmed) return false;
        const urlManager = window.urlManager;
        const filters = urlManager && typeof urlManager.getCurrentFilters === 'function'
            ? urlManager.getCurrentFilters()
            : {};
        const views = loadViews();
        const existing = views.findIndex((v) => v.name === trimmed);
        const entry = { name: trimmed, filters, savedAt: Date.now() };
        if (existing >= 0) views[existing] = entry;
        else views.push(entry);
        const ok = persist(views);
        toast(
            ok ? `Saved view “${trimmed}”` : 'Storage unavailable — view kept for this session',
            ok ? 'success' : 'warning'
        );
        return ok;
    }

    function deleteView(name) {
        const ok = persist(loadViews().filter((v) => v.name !== name));
        toast(
            ok ? `Deleted view “${name}”` : 'Storage unavailable — view deleted for this session',
            ok ? 'success' : 'warning'
        );
    }

    function copyShareLink() {
        const url = location.href;
        const done = () => toast('Link copied to clipboard', 'success');
        const fallback = () => {
            const scratch = h('textarea', 'sv-scratch');
            scratch.value = url;
            document.body.appendChild(scratch);
            scratch.select();
            try {
                document.execCommand('copy');
                done();
            } catch (error) {
                toast('Copy failed — use the address bar', 'warning');
            }
            scratch.remove();
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(done, fallback);
        } else {
            fallback();
        }
    }

    /** One widget instance (dropdown + inline save input). */
    function buildWidget(inline) {
        const root = h('div', inline ? 'sv-inline d-inline-flex align-items-center gap-1' : 'sv-block w-100');

        const toggle = h('button', 'btn btn-outline-secondary btn-sm sv-toggle');
        toggle.type = 'button';
        toggle.setAttribute('data-bs-toggle', 'dropdown');
        toggle.setAttribute('data-bs-auto-close', 'outside');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-haspopup', 'true');
        toggle.title = 'Saved views';
        const icon = h('i', 'bi bi-collection');
        icon.setAttribute('aria-hidden', 'true');
        toggle.appendChild(icon);
        toggle.appendChild(document.createTextNode(' Views'));

        const menu = h('div', 'dropdown-menu sv-menu');
        menu.setAttribute('aria-label', 'Saved views');

        const saveRow = h('div', 'sv-save-row px-3 py-1 d-flex gap-1 align-items-center');
        const saveBtn = h('button', 'btn btn-sm btn-outline-primary sv-save-btn', 'Save current');
        saveBtn.type = 'button';
        const nameInput = h('input', 'form-control form-control-sm sv-name-input d-none');
        nameInput.placeholder = 'View name…';
        nameInput.setAttribute('aria-label', 'View name');
        // no name attribute: must stay out of the filter form state
        saveRow.append(saveBtn, nameInput);

        const list = h('div', 'sv-list');
        const divider = h('div', 'dropdown-divider');
        const shareBtn = h('button', 'dropdown-item sv-share', 'Copy share link');
        shareBtn.type = 'button';

        menu.append(saveRow, h('div', 'dropdown-divider'), list, divider, shareBtn);

        const wrap = h('div', 'dropdown');
        wrap.append(toggle, menu);
        root.appendChild(wrap);

        let saving = false;
        const hideInput = () => {
            saving = false;
            nameInput.classList.add('d-none');
        };
        saveBtn.addEventListener('click', () => {
            // Always show (never toggle): repeated clicks refocus the input.
            saving = true;
            nameInput.classList.remove('d-none');
            nameInput.focus();
        });
        const confirmSave = () => {
            if (saveCurrent(nameInput.value)) {
                nameInput.value = '';
                hideInput();
            } else {
                nameInput.focus();
            }
        };
        nameInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                confirmSave();
            } else if (event.key === 'Escape') {
                hideInput();
            }
        });
        nameInput.addEventListener('blur', () => {
            if (nameInput.value.trim()) confirmSave();
            else hideInput();
        });

        shareBtn.addEventListener('click', () => {
            copyShareLink();
            const dd = bootstrap.Dropdown.getInstance(toggle);
            if (dd) dd.hide();
        });

        function render() {
            const views = loadViews();
            setChildrenList(list, views.map((view) => {
                const item = h('div', 'd-flex align-items-center justify-content-between gap-2 px-3 py-1 sv-item');
                const applyBtn = h('button', 'btn btn-link btn-sm text-decoration-none p-0 text-start sv-apply');
                applyBtn.type = 'button';
                applyBtn.dataset.view = view.name;
                const label = h('span', 'sv-name');
                label.textContent = view.name; // textContent: user data
                applyBtn.appendChild(label);
                applyBtn.appendChild(summaryChips(view.filters));
                applyBtn.addEventListener('click', () => {
                    applyView(view);
                    const dd = bootstrap.Dropdown.getInstance(toggle);
                    if (dd) dd.hide();
                });

                const del = h('button', 'btn btn-sm btn-outline-secondary border-0 lh-1 sv-delete');
                del.type = 'button';
                del.dataset.view = view.name;
                del.title = `Delete view ${view.name}`;
                del.setAttribute('aria-label', `Delete view ${view.name}`);
                del.textContent = '×';
                del.addEventListener('click', (event) => {
                    event.stopPropagation();
                    deleteView(view.name);
                });

                item.append(applyBtn, del);
                return item;
            }));
            if (views.length === 0) {
                list.appendChild(h('div', 'dropdown-item-text small text-muted px-3', 'No saved views yet'));
            }
        }

        render();
        instances.push(render);
        return root;
    }

    function setChildrenList(list, nodes) {
        list.replaceChildren(...nodes);
    }

    function mount() {
        // Idempotence: the table pages clone their sidebar template via
        // innerHTML on DOMContentLoaded, so mount only after that settles
        // and never twice.
        if (document.querySelector('.sv-sidebar-section')) return;
        const form = document.querySelector('#filtersForm');
        if (form) {
            const section = form.closest('.sidebar-section');
            if (section) {
                const block = h('div', 'sidebar-section sv-sidebar-section');
                block.appendChild(h('h2', 'h6', 'Saved Views'));
                block.appendChild(buildWidget(false));
                section.insertAdjacentElement('afterend', block);
            }
        }

        // Near the table controls for the collapsed-sidebar state.
        const headerRow = document.querySelector('.table-header .d-flex');
        if (headerRow) {
            headerRow.insertBefore(buildWidget(true), headerRow.querySelector('button'));
        }
    }

    if (document.readyState === 'loading') {
        // setTimeout(0): run after the page's own DOMContentLoaded handler
        // that moves the sidebar template into place.
        document.addEventListener('DOMContentLoaded', () => setTimeout(mount, 0));
    } else {
        setTimeout(mount, 0);
    }

    window.MallaSavedViews = { loadViews, saveCurrent, applyView, deleteView, STORE_KEY };
})();

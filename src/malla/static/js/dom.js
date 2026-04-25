(function() {
    function text(value) {
        return document.createTextNode(value == null ? '' : String(value));
    }

    function appendChild(parent, child) {
        if (child == null || child === false) {
            return;
        }

        if (Array.isArray(child)) {
            child.forEach((item) => appendChild(parent, item));
            return;
        }

        if (child instanceof Node) {
            parent.appendChild(child);
            return;
        }

        parent.appendChild(text(child));
    }

    function appendChildren(parent, ...children) {
        children.forEach((child) => appendChild(parent, child));
        return parent;
    }

    function setChildren(parent, ...children) {
        parent.replaceChildren();
        return appendChildren(parent, ...children);
    }

    function el(tagName, attrs, ...children) {
        const element = document.createElement(tagName);
        const options = attrs && typeof attrs === 'object' && !Array.isArray(attrs) && !(attrs instanceof Node) ? attrs : null;
        const childItems = options ? children : [attrs, ...children];

        if (options) {
            Object.entries(options).forEach(([key, value]) => {
                if (value == null || value === false) {
                    return;
                }

                if (key === 'className') {
                    element.className = value;
                    return;
                }

                if (key === 'text') {
                    element.textContent = String(value);
                    return;
                }

                if (key === 'dataset' && value && typeof value === 'object') {
                    Object.entries(value).forEach(([dataKey, dataValue]) => {
                        if (dataValue != null) {
                            element.dataset[dataKey] = String(dataValue);
                        }
                    });
                    return;
                }

                if (key === 'style' && value && typeof value === 'object') {
                    Object.entries(value).forEach(([styleKey, styleValue]) => {
                        element.style[styleKey] = styleValue;
                    });
                    return;
                }

                if (key in element && key !== 'title') {
                    element[key] = value;
                    return;
                }

                element.setAttribute(key, String(value));
            });
        }

        appendChildren(element, ...childItems);
        return element;
    }

    function fragment(...children) {
        const frag = document.createDocumentFragment();
        appendChildren(frag, ...children);
        return frag;
    }

    function icon(className) {
        return el('i', { className });
    }

    function badge(value, className) {
        return el('span', { className: `badge ${className || 'bg-secondary'}` }, value == null ? '' : String(value));
    }

    function safePath(pathname, params) {
        const url = new URL(pathname, window.location.origin);

        if (params && typeof params === 'object') {
            Object.entries(params).forEach(([key, value]) => {
                if (value == null) {
                    return;
                }

                const stringValue = String(value).trim();
                if (stringValue) {
                    url.searchParams.set(key, stringValue);
                }
            });
        }

        return `${url.pathname}${url.search}${url.hash}`;
    }

    function safeUrl(value, options = {}) {
        if (value == null) {
            return null;
        }

        const raw = String(value).trim();
        if (!raw) {
            return null;
        }

        const allowRelative = options.allowRelative !== false;
        const allowedProtocols = options.allowedProtocols || ['http:', 'https:'];

        try {
            const url = new URL(raw, window.location.origin);
            const isRelativeInput = !/^[a-zA-Z][a-zA-Z\d+.-]*:/.test(raw);

            if (isRelativeInput && allowRelative) {
                return `${url.pathname}${url.search}${url.hash}`;
            }

            if (url.origin === window.location.origin && allowRelative) {
                return `${url.pathname}${url.search}${url.hash}`;
            }

            return allowedProtocols.includes(url.protocol) ? url.toString() : null;
        } catch (_) {
            return null;
        }
    }

    function buttonLink(options) {
        const link = el('a', {
            href: options.href || '#',
            className: options.className || 'btn btn-sm btn-outline-secondary',
            title: options.title || '',
            target: options.target,
            rel: options.rel,
            ariaLabel: options.ariaLabel
        });

        if (options.iconClass) {
            link.appendChild(icon(options.iconClass));
        }

        if (options.text) {
            if (link.childNodes.length > 0) {
                link.appendChild(text(' '));
            }
            link.appendChild(text(options.text));
        }

        return link;
    }

    function nodeLink(nodeId, displayText, options = {}) {
        if (nodeId == null || nodeId === '') {
            return el('span', { className: 'text-muted' }, displayText || 'Unknown');
        }

        const link = el('a', {
            href: safePath(`/node/${encodeURIComponent(String(nodeId))}`),
            className: options.className || 'text-decoration-none node-link',
            title: options.title || 'View node details'
        }, displayText || 'Unknown');

        if (options.tooltip !== false) {
            link.dataset.nodeId = String(nodeId);
            link.dataset.bsToggle = 'tooltip';
            link.dataset.bsPlacement = options.tooltipPlacement || 'top';
            link.dataset.bsHtml = 'true';
            link.dataset.bsTitle = 'Loading...';
        }

        return link;
    }

    function joinNodes(items, separator) {
        const frag = document.createDocumentFragment();
        items.forEach((item, index) => {
            if (index > 0) {
                appendChild(frag, separator == null ? ' ' : separator);
            }
            appendChild(frag, item);
        });
        return frag;
    }

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    }

    window.el = el;
    window.fragment = fragment;
    window.icon = icon;
    window.badge = badge;
    window.textNode = text;
    window.appendChildren = appendChildren;
    window.setChildren = setChildren;
    window.safePath = safePath;
    window.safeUrl = safeUrl;
    window.buttonLink = buttonLink;
    window.nodeLink = nodeLink;
    window.joinNodes = joinNodes;
    window.escapeHtml = escapeHtml;
})();

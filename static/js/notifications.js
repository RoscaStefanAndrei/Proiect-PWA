/**
 * SmartVest Notification Bell
 * Handles dropdown fetching, mark-read, and badge updates.
 */
(function () {
    const bell = document.getElementById('notifBell');
    const dropdown = document.getElementById('notifDropdown');
    const badge = document.getElementById('notifBadge');
    if (!bell || !dropdown) return;

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value
        || document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

    const ICONS = {
        price_alert: 'fa-chart-line',
        portfolio_alert: 'fa-briefcase',
        unicorn_found: 'fa-horse-head',
    };

    const COLORS = {
        price_alert: 'var(--yellow)',
        portfolio_alert: 'var(--accent)',
        unicorn_found: 'var(--green)',
    };

    let loaded = false;

    bell.addEventListener('click', function (e) {
        e.stopPropagation();
        const opening = !dropdown.classList.contains('show');
        dropdown.classList.toggle('show');
        if (opening) fetchNotifications();
    });

    document.addEventListener('click', function (e) {
        if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
            dropdown.classList.remove('show');
        }
    });

    function fetchNotifications() {
        fetch('/api/notifications/')
            .then(r => r.json())
            .then(data => {
                loaded = true;
                renderNotifications(data.notifications);
                updateBadge(data.unread_count);
            })
            .catch(() => {
                dropdown.innerHTML = '<div class="p-3 text-center" style="color:var(--text-muted);">Failed to load</div>';
            });
    }

    function renderNotifications(items) {
        if (!items.length) {
            dropdown.innerHTML = `
                <div class="notif-header">
                    <span class="fw-bold">Notifications</span>
                </div>
                <div class="p-4 text-center">
                    <i class="fas fa-bell-slash fa-2x mb-2" style="color: var(--text-muted);"></i>
                    <p style="color: var(--text-muted); margin: 0; font-size: 0.85rem;">No notifications yet</p>
                </div>` + scanButtonHtml();
            return;
        }

        const hasUnread = items.some(n => !n.is_read);
        let html = `
            <div class="notif-header">
                <span class="fw-bold">Notifications</span>
                ${hasUnread ? `<button class="btn btn-sm btn-link p-0" onclick="markAllRead()" style="color: var(--accent); font-size: 0.78rem; text-decoration: none;">Mark all read</button>` : ''}
            </div>
            <div class="notif-list">`;

        items.forEach(n => {
            const icon = ICONS[n.type] || 'fa-bell';
            const color = COLORS[n.type] || 'var(--accent)';
            html += `
                <a href="${n.link || '#'}" class="notif-item ${n.is_read ? '' : 'unread'}"
                   onclick="markRead(event, ${n.id}, '${n.link || ''}')">
                    <div class="notif-icon" style="color: ${color};">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="notif-content">
                        <div class="notif-title">${n.title}</div>
                        <div class="notif-message">${n.message}</div>
                        <div class="notif-time">${n.created_at}</div>
                    </div>
                    ${n.is_read ? '' : '<div class="notif-dot"></div>'}
                </a>`;
        });

        html += '</div>';
        html += scanButtonHtml();
        dropdown.innerHTML = html;
    }

    function updateBadge(count) {
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.style.display = '';
        } else {
            badge.style.display = 'none';
        }
    }

    function scanButtonHtml() {
        return `
            <div class="notif-scan-footer">
                <button onclick="runAlertScan(this)" class="notif-scan-btn">
                    <i class="fas fa-radar me-1"></i>Run Alert Scan
                </button>
            </div>`;
    }

    // Expose globally for inline onclick handlers
    window.markRead = function (e, id, link) {
        e.preventDefault();
        fetch(`/api/notifications/read/${id}/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
        }).then(() => {
            if (link) window.location.href = link;
            else {
                loaded = false;
                fetchNotifications();
            }
        });
    };

    window.runAlertScan = function (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Scanning...';
        fetch('/api/notifications/scan/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
        }).then(() => {
            btn.innerHTML = '<i class="fas fa-check me-1"></i>Scan started';
            // Refresh notifications after a short delay to let tasks complete
            setTimeout(function () {
                fetchNotifications();
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-satellite-dish me-1"></i>Run Alert Scan';
            }, 5000);
        }).catch(() => {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-satellite-dish me-1"></i>Run Alert Scan';
        });
    };

    window.markAllRead = function () {
        fetch('/api/notifications/read/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
        }).then(() => {
            loaded = false;
            fetchNotifications();
        });
    };

    // Poll for new notifications every 60 seconds
    setInterval(function () {
        fetch('/api/notifications/')
            .then(r => r.json())
            .then(data => {
                updateBadge(data.unread_count);
                if (dropdown.classList.contains('show')) {
                    renderNotifications(data.notifications);
                }
            })
            .catch(() => {});
    }, 60000);
})();

/* ── Toast 通知系统 ── */
function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), duration);
}

/* ── HTMX 事件：监听服务端 HX-Trigger 触发 Toast ── */
document.addEventListener('showToast', function(evt) {
    const detail = evt.detail || {};
    showToast(detail.message || 'Done', detail.type || 'info');
});

/* ── HTMX 全局事件 ── */
document.addEventListener('htmx:afterRequest', function(evt) {
    // POST 请求成功后刷新邮件列表
    if (evt.detail.requestConfig && evt.detail.requestConfig.verb === 'post') {
        const emailList = document.getElementById('email-list');
        if (emailList) {
            htmx.trigger(emailList, 'refresh');
        }
    }
});

/* ── Alpine.js: 真实邮件拉取面板 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('fetchPanel', () => ({
        status: { enabled: false, authorized: false, credentials_exists: false },
        opts: { limit: 10 },
        fetching: false,
        lastResult: '',
        lastOk: false,

        async loadStatus() {
            try {
                const resp = await fetch('/api/google/status');
                this.status = await resp.json();
            } catch (e) { /* 静默 */ }
        },
        statusLabel() {
            if (!this.status.enabled) return 'IMAP 模式';
            return this.status.authorized ? 'Google 已连接' : 'Google 未授权';
        },
        async fetchEmails() {
            this.fetching = true;
            this.lastResult = '';
            try {
                const resp = await fetch('/api/emails/fetch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.opts)
                });
                const data = await resp.json();
                this.lastOk = !!data.success && resp.ok;
                this.lastResult = data.message || (this.lastOk ? '完成' : '失败');
                showToast(this.lastResult, this.lastOk ? 'success' : 'error');
                if (this.lastOk) {
                    htmx.ajax('GET', '/api/emails/partial', '#email-list');
                }
            } catch (e) {
                this.lastOk = false;
                this.lastResult = '请求失败';
                showToast('请求失败', 'error');
            } finally {
                this.fetching = false;
            }
        }
    }));
});

/* ── Alpine.js: 导航栏 Google 状态点 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('googleStatusDot', () => ({
        state: 'unknown',
        title: '检查中…',
        async init() {
            try {
                const resp = await fetch('/api/google/status');
                const d = await resp.json();
                if (!d.enabled) { this.state = 'off'; this.title = 'Google 未启用（IMAP 模式）'; }
                else if (d.authorized) { this.state = 'ok'; this.title = 'Google 已连接'; }
                else { this.state = 'warn'; this.title = 'Google 未授权'; }
            } catch (e) { this.state = 'off'; this.title = '状态未知'; }
        }
    }));
});

/* ── Alpine.js: 导航栏提醒徽章 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('badgeCounter', () => ({
        count: 0,
        async startPolling() {
            await this.fetchCount();
            setInterval(() => this.fetchCount(), 30000);
        },
        async fetchCount() {
            try {
                const resp = await fetch('/api/reminders/count');
                const data = await resp.json();
                this.count = data.count;
            } catch (e) {
                // 静默失败
            }
        }
    }));
});

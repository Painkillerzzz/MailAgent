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

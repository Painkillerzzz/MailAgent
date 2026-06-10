/* ── Alpine.js: 设置页面组件 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('settingsApp', () => ({
        settings: {
            llm: { api_key: '', model: 'glm-4.6', base_url: '', temperature: 0.7, max_tokens: 1024 },
            imap: { host: '', port: 993, username: '', password: '' },
            user: { name: '', email: '', tone: 'polite and concise', signature: '' },
            google: { enabled: false, calendar_id: 'primary', authorized: false, credentials_exists: false },
            testing: { redirect_to: '' }
        },
        testing: { llm: false, imap: false },
        testResults: { llm: '', llmOk: false, imap: '', imapOk: false },
        saving: false,
        loaded: false,
        checkingGoogle: false,

        async loadSettings() {
            try {
                const resp = await fetch('/api/settings');
                const data = await resp.json();
                for (const section of ['llm', 'imap', 'user', 'google', 'testing']) {
                    if (data[section]) {
                        this.settings[section] = { ...this.settings[section], ...data[section] };
                    }
                }
                this.loaded = true;
            } catch (e) {
                showToast('Failed to load settings', 'error');
            }
        },

        async testLLM() {
            this.testing.llm = true;
            this.testResults.llm = '';
            try {
                const resp = await fetch('/api/settings/test-llm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: this.settings.llm.api_key,
                        model: this.settings.llm.model,
                        base_url: this.settings.llm.base_url
                    })
                });
                const data = await resp.json();
                this.testResults.llm = data.message;
                this.testResults.llmOk = data.success;
            } catch (e) {
                this.testResults.llm = 'Request failed';
                this.testResults.llmOk = false;
            } finally {
                this.testing.llm = false;
            }
        },

        async testIMAP() {
            this.testing.imap = true;
            this.testResults.imap = '';
            try {
                const resp = await fetch('/api/settings/test-imap', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.settings.imap)
                });
                const data = await resp.json();
                this.testResults.imap = data.message;
                this.testResults.imapOk = data.success;
            } catch (e) {
                this.testResults.imap = 'Request failed';
                this.testResults.imapOk = false;
            } finally {
                this.testing.imap = false;
            }
        },

        async checkGoogle() {
            this.checkingGoogle = true;
            try {
                const resp = await fetch('/api/google/status');
                const d = await resp.json();
                this.settings.google = { ...this.settings.google, ...d };
                showToast(d.authorized ? 'Google 已连接' : (d.enabled ? 'Google 未授权' : 'Google 未启用'),
                          d.authorized ? 'success' : 'info');
            } catch (e) {
                showToast('状态检查失败', 'error');
            } finally {
                this.checkingGoogle = false;
            }
        },

        async saveSettings() {
            this.saving = true;
            try {
                // 不持久化运行时计算字段，避免覆盖实时状态
                const payload = JSON.parse(JSON.stringify(this.settings));
                if (payload.google) {
                    delete payload.google.authorized;
                    delete payload.google.credentials_exists;
                }
                const resp = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                showToast(data.message, data.success ? 'success' : 'error');
            } catch (e) {
                showToast('Save failed', 'error');
            } finally {
                this.saving = false;
            }
        }
    }));
});

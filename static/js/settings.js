/* ── Alpine.js: 设置页面组件 ── */
document.addEventListener('alpine:init', () => {
    Alpine.data('settingsApp', () => ({
        settings: {
            llm: { api_key: '', model: 'glm-5', temperature: 0.7, max_tokens: 1024 },
            imap: { host: '', port: 993, username: '', password: '' },
            user: { name: '', email: '', tone: 'polite and concise', signature: '' }
        },
        testing: { llm: false, imap: false },
        testResults: { llm: '', llmOk: false, imap: '', imapOk: false },
        saving: false,
        loaded: false,

        async loadSettings() {
            try {
                const resp = await fetch('/api/settings');
                const data = await resp.json();
                // 深合并
                for (const section of ['llm', 'imap', 'user']) {
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
                    body: JSON.stringify({ api_key: this.settings.llm.api_key })
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

        async saveSettings() {
            this.saving = true;
            try {
                const resp = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.settings)
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

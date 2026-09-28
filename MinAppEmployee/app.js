document.addEventListener('DOMContentLoaded', () => {
    if (window.WebApp && window.WebApp.ready) window.WebApp.ready();

    const params = new URLSearchParams(window.location.search);
    let isClosing = params.get('closing') === '1';

    const slotSelect = document.getElementById('slot-select');

    async function loadUserData() {
        const initData = window.WebApp?.initData || '';
        if (!initData) {
            document.getElementById('store-code').textContent = 'нет initData';
            return null;
        }
        try {
            const r = await fetch('/api/me', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ init_data: initData })
            });
            const d = await r.json();

            if (d.pending_closing) {
                isClosing = true;
            }

            if (d.has_active_shift && d.store_code) {
                document.getElementById('store-code').textContent = d.store_code;
                return d.store_code;
            }
            document.getElementById('store-code').textContent = 'нет активной смены';
            return null;
        } catch (e) {
            document.getElementById('store-code').textContent = 'ошибка';
            return null;
        }
    }

    const storePromise = loadUserData().then(code => {
        if (isClosing) {
            document.getElementById('title').textContent = '📝 Последний отчёт за смену';
            slotSelect.value = 'closing';
        } else {
            const slots = ['11:30', '13:30', '15:30', '17:30'];
            const now = new Date();
            const cur = now.getHours() * 60 + now.getMinutes();
            let nearest = slots[0], minDiff = Infinity;
            slots.forEach(s => {
                const [h, m] = s.split(':').map(Number);
                const diff = Math.abs(h * 60 + m - cur);
                if (diff < minDiff) { minDiff = diff; nearest = s; }
            });
            slotSelect.value = nearest;
        }
        return code;
    });

    const form = document.getElementById('report-form');
    const numberInputs = form.querySelectorAll('input[type="number"]');
    numberInputs.forEach(input => {
        input.addEventListener('focus', () => {
            if (input.value === '0') input.value = '';
            else input.select();
        });
        input.addEventListener('blur', () => {
            if (input.value === '') input.value = '0';
        });
    });

    let isSubmitting = false;
    const submitBtn = form.querySelector('.submit-btn');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (isSubmitting) return;
        isSubmitting = true;

        const orig = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending...';

        try {
            const storeCode = await storePromise;
            if (!storeCode) throw new Error('Нет активной смены.');

            const fd = new FormData(form);
            const metrics = {};
            fd.forEach((v, k) => {
                if (k !== 'slot_time') metrics[k] = v === '' ? 0 : Math.round(Number(v));
            });

            const initData = window.WebApp?.initData || '';
            if (!initData) throw new Error('No initData from MAX.');

            const payload = {
                slot_time: fd.get('slot_time'),
                metrics: metrics,
                is_closing: isClosing
            };

            const r = await fetch('/api/report', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-max-init-data': initData
                },
                body: JSON.stringify(payload)
            });
            const result = await r.json();
            if (!r.ok) throw new Error(result.detail || 'Server error');

            if (window.WebApp?.close) window.WebApp.close();

        } catch (err) {
            console.error(err);
            alert('Error: ' + err.message);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = orig;
            isSubmitting = false;
        }
    });
});
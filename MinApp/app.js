document.addEventListener('DOMContentLoaded', async () => {
    if (window.WebApp && window.WebApp.ready) window.WebApp.ready();

    const initData = window.WebApp?.initData || '';
    if (!initData) {
        showError('Нет данных авторизации. Откройте через бота MAX.');
        return;
    }

    let userData;
    try {
        const r = await fetch('/api/me', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: initData })
        });
        if (!r.ok) {
            const err = await r.json();
            throw new Error(err.detail || 'Ошибка загрузки профиля');
        }
        userData = await r.json();
    } catch (e) {
        showError('Ошибка: ' + e.message);
        return;
    }

    const role = userData.role || 'employee';
    if (role === 'manager' || role === 'superadmin') {
        initManager(initData);
    } else {
        initEmployee(initData, userData);
    }
});


function showError(text) {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('error-text').textContent = text;
    document.getElementById('error-screen').classList.remove('hidden');
}


// ================================================================
//  СОТРУДНИК
// ================================================================
function initEmployee(initData, userData) {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('employee-screen').classList.remove('hidden');

    const isClosing = !!userData.pending_closing;
    const slotSelect = document.getElementById('slot-select');
    const storeCode = userData.store_code;

    document.getElementById('emp-store-code').textContent =
        storeCode || 'нет активной смены';

    if (isClosing) {
        document.getElementById('emp-title').textContent = '📝 Последний отчёт за смену';
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
        submitBtn.textContent = 'Отправка...';

        try {
            if (!storeCode) throw new Error('Нет активной смены.');

            const fd = new FormData(form);
            const metrics = {};
            fd.forEach((v, k) => {
                if (k !== 'slot_time') {
                    metrics[k] = v === '' ? 0 : Math.round(Number(v));
                }
            });

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
            alert('Ошибка: ' + err.message);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = orig;
            isSubmitting = false;
        }
    });
}


// ================================================================
//  РУКОВОДИТЕЛЬ
// ================================================================
function initManager(initData) {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('manager-screen').classList.remove('hidden');

    const periodSelect = document.getElementById('period');
    const customDates = document.getElementById('custom-dates');
    const allStoresCheckbox = document.getElementById('all-stores');
    const storesList = document.getElementById('stores-list');
    const downloadBtn = document.getElementById('download-btn');
    const statusMsg = document.getElementById('status-msg');

    // настройки
    const openSettingsBtn = document.getElementById('open-settings');
    const closeSettingsBtn = document.getElementById('close-settings');
    const saveSettingsBtn = document.getElementById('save-settings-btn');
    const allMetricsCheckbox = document.getElementById('all-metrics');
    const metricsList = document.getElementById('metrics-list');
    const settingsStatus = document.getElementById('settings-status');

    function showStatus(el, text, type) {
        el.textContent = text;
        el.className = `status ${type}`;
        el.classList.remove('hidden');
    }

    // ================================================================
    //  ЗАГРУЗКА ТОЧЕК
    // ================================================================
    async function loadStores() {
        try {
            const r = await fetch('/api/manager/stores', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ init_data: initData })
            });
            if (!r.ok) {
                const err = await r.json();
                throw new Error(err.detail || 'Ошибка загрузки точек');
            }
            const data = await r.json();
            storesList.innerHTML = '';
            (data.stores || []).forEach(s => {
                const div = document.createElement('label');
                div.className = 'store-item';
                div.innerHTML = `<input type="checkbox" class="store-cb" value="${s.code}" checked>
                    <span><span class="code">${s.code}</span>${s.address}</span>`;
                storesList.appendChild(div);
            });
        } catch (e) {
            showStatus(statusMsg, 'Ошибка: ' + e.message, 'error');
        }
    }

    // ================================================================
    //  ЛОГИКА ЧЕКБОКСОВ ТОЧЕК (как у метрик)
    // ================================================================
    // Клик по "Все точки" — ставит/снимает все
    allStoresCheckbox.addEventListener('change', () => {
        storesList.querySelectorAll('.store-cb').forEach(cb => {
            cb.checked = allStoresCheckbox.checked;
        });
    });

    // Клик по конкретной точке — проверяем, все ли отмечены
    storesList.addEventListener('change', (e) => {
        if (e.target.classList.contains('store-cb')) {
            const cbs = storesList.querySelectorAll('.store-cb');
            const checked = storesList.querySelectorAll('.store-cb:checked');
            allStoresCheckbox.checked = (cbs.length > 0 && checked.length === cbs.length);
        }
    });

    // ================================================================
    //  ПЕРИОД
    // ================================================================
    periodSelect.addEventListener('change', () => {
        if (periodSelect.value === 'custom') customDates.classList.remove('hidden');
        else customDates.classList.add('hidden');
    });

    // ================================================================
    //  ЗАГРУЗКА МЕТРИК
    // ================================================================
    async function loadMetrics() {
        const r = await fetch('/api/manager/metrics', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: initData })
        });
        const data = await r.json();
        metricsList.innerHTML = '';
        (data.metrics || []).forEach(m => {
            const div = document.createElement('label');
            div.className = 'store-item';
            div.innerHTML = `<input type="checkbox" class="metric-cb" value="${m.key}" checked>
                <span>${m.label}</span>`;
            metricsList.appendChild(div);
        });
    }

    // ================================================================
    //  ЛОГИКА ЧЕКБОКСОВ МЕТРИК
    // ================================================================
    allMetricsCheckbox.addEventListener('change', () => {
        metricsList.querySelectorAll('.metric-cb').forEach(cb => {
            cb.checked = allMetricsCheckbox.checked;
        });
    });

    metricsList.addEventListener('change', (e) => {
        if (e.target.classList.contains('metric-cb')) {
            const cbs = metricsList.querySelectorAll('.metric-cb');
            const checked = metricsList.querySelectorAll('.metric-cb:checked');
            allMetricsCheckbox.checked = (cbs.length > 0 && checked.length === cbs.length);
        }
    });

    // ================================================================
    //  ЗАГРУЗКА НАСТРОЕК ИЗ БД
    // ================================================================
    async function loadSettings() {
        try {
            const r = await fetch('/api/manager/settings/get', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ init_data: initData })
            });
            const data = await r.json();

            // --- МЕТРИКИ ---
            const allMetricCbs = metricsList.querySelectorAll('.metric-cb');
            let metricKeys = data.metric_keys;
            if (!metricKeys || metricKeys.length === 0) {
                // null = все
                metricKeys = Array.from(allMetricCbs).map(cb => cb.value);
            }
            allMetricCbs.forEach(cb => {
                cb.checked = metricKeys.includes(cb.value);
            });
            const checkedMetricCbs = metricsList.querySelectorAll('.metric-cb:checked');
            allMetricsCheckbox.checked = (allMetricCbs.length > 0 && checkedMetricCbs.length === allMetricCbs.length);

            // --- ТОЧКИ ---
            const allStoreCbs = storesList.querySelectorAll('.store-cb');
            let storeCodes = data.store_codes;
            if (!storeCodes || storeCodes.length === 0) {
                // null = все
                allStoresCheckbox.checked = true;
                allStoreCbs.forEach(cb => cb.checked = true);
            } else {
                allStoresCheckbox.checked = false;
                allStoreCbs.forEach(cb => {
                    cb.checked = storeCodes.includes(cb.value);
                });
                // если вдруг все отмечены — включаем "Все"
                const checkedStoreCbs = storesList.querySelectorAll('.store-cb:checked');
                if (checkedStoreCbs.length === allStoreCbs.length && allStoreCbs.length > 0) {
                    allStoresCheckbox.checked = true;
                }
            }
        } catch (e) {
            console.error('settings load error', e);
        }
    }

    // ================================================================
    //  ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ
    // ================================================================
    openSettingsBtn.addEventListener('click', () => {
        document.getElementById('manager-screen').classList.add('hidden');
        document.getElementById('settings-screen').classList.remove('hidden');
        settingsStatus.classList.add('hidden');
    });

    closeSettingsBtn.addEventListener('click', () => {
        document.getElementById('settings-screen').classList.add('hidden');
        document.getElementById('manager-screen').classList.remove('hidden');
    });

    // ================================================================
    //  СОХРАНЕНИЕ НАСТРОЕК
    // ================================================================
    saveSettingsBtn.addEventListener('click', async () => {
        saveSettingsBtn.disabled = true;
        const orig = saveSettingsBtn.textContent;
        saveSettingsBtn.textContent = '⏳ Сохранение...';

        try {
            // --- МЕТРИКИ ---
            const metricCbs = metricsList.querySelectorAll('.metric-cb');
            const checkedMetricCbs = metricsList.querySelectorAll('.metric-cb:checked');
            let metric_keys = null;
            if (checkedMetricCbs.length === 0) {
                throw new Error('Выберите хотя бы одну метрику');
            }
            if (checkedMetricCbs.length < metricCbs.length) {
                metric_keys = Array.from(checkedMetricCbs).map(cb => cb.value);
            }
            // если все отмечены — metric_keys = null (значит "все")

            // --- ТОЧКИ ---
            const storeCbs = storesList.querySelectorAll('.store-cb');
            const checkedStoreCbs = storesList.querySelectorAll('.store-cb:checked');
            let store_codes = null;
            if (checkedStoreCbs.length === 0) {
                throw new Error('Выберите хотя бы одну точку');
            }
            if (checkedStoreCbs.length < storeCbs.length) {
                store_codes = Array.from(checkedStoreCbs).map(cb => cb.value);
            }
            // если все отмечены — store_codes = null (значит "все")

            const r = await fetch('/api/manager/settings/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    init_data: initData,
                    metric_keys: metric_keys,
                    store_codes: store_codes,
                })
            });
            const result = await r.json();
            if (!r.ok) throw new Error(result.detail || 'Ошибка сохранения');

            showStatus(settingsStatus, '✅ Настройки сохранены', 'success');

            setTimeout(() => {
                document.getElementById('settings-screen').classList.add('hidden');
                document.getElementById('manager-screen').classList.remove('hidden');
            }, 800);
        } catch (e) {
            showStatus(settingsStatus, '❌ ' + e.message, 'error');
        } finally {
            saveSettingsBtn.disabled = false;
            saveSettingsBtn.textContent = orig;
        }
    });

    // ================================================================
    //  СКАЧИВАНИЕ EXCEL
    // ================================================================
    downloadBtn.addEventListener('click', async () => {
        downloadBtn.disabled = true;
        const orig = downloadBtn.textContent;
        downloadBtn.textContent = '⏳ Генерация...';
        statusMsg.classList.add('hidden');

        try {
            const period = periodSelect.value;

            const payload = {
                init_data: initData,
                period: period,
            };

            if (period === 'custom') {
                const df = document.getElementById('date-from').value;
                const dt = document.getElementById('date-to').value;
                if (!df || !dt) throw new Error('Укажите обе даты');
                payload.date_from = df;
                payload.date_to = dt;
            }

            // --- ТОЧКИ ---
            const storeCbs = storesList.querySelectorAll('.store-cb');
            const checkedStoreCbs = storesList.querySelectorAll('.store-cb:checked');
            if (checkedStoreCbs.length === 0) {
                throw new Error('Выберите хотя бы одну точку');
            }
            // если выбраны не все — передаём список
            if (checkedStoreCbs.length < storeCbs.length) {
                payload.store_codes = Array.from(checkedStoreCbs).map(cb => cb.value);
            }
            // если все — не передаём (бэк возьмёт все)

            // --- МЕТРИКИ ---
            const metricCbs = metricsList.querySelectorAll('.metric-cb');
            const checkedMetricCbs = metricsList.querySelectorAll('.metric-cb:checked');
            if (checkedMetricCbs.length === 0) {
                throw new Error('Выберите хотя бы одну метрику в настройках');
            }
            if (checkedMetricCbs.length < metricCbs.length) {
                payload.metric_keys = Array.from(checkedMetricCbs).map(cb => cb.value);
            }

            const r = await fetch('/api/manager/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await r.json();
            if (!r.ok) throw new Error(result.detail || 'Ошибка генерации');

            showStatus(statusMsg, '✅ Файл готов. Скачиваем...', 'success');
            window.open(result.url, '_blank');

        } catch (e) {
            showStatus(statusMsg, '❌ ' + e.message, 'error');
        } finally {
            downloadBtn.disabled = false;
            downloadBtn.textContent = orig;
        }
    });

    // ================================================================
    //  СТАРТ
    // ================================================================
    (async () => {
        await loadStores();
        await loadMetrics();
        await loadSettings();
    })();
}
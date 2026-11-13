const tg = window.Telegram?.WebApp;
    const tgUser = tg?.initDataUnsafe?.user;
    const tgInitData = tg?.initData || '';
    const currentUserId = tgUser ? tgUser.id : null;
    // UI uchun taxminiy rol. Haqiqiy ruxsatni FAQAT server (initData imzosi orqali) beradi.
    let isAdmin = (String(currentUserId) === '6656667725');

    // Barcha API so'rovlari Telegram imzosi (initData) bilan yuboriladi
    function apiFetch(url, options = {}) {
      const headers = Object.assign({}, options.headers || {}, { 'X-Telegram-Init-Data': tgInitData });
      return fetch(url, Object.assign({}, options, { headers }));
    }

    let currentPeriod = '7days';
    // Admin uchun 'dashboard', mehmonlar uchun esa 'features' (Vitrina & Funksiyalar) ochiladi:
    let currentTab = isAdmin ? 'dashboard' : 'features';
    let salesChartInstance = null;
    let debtChartInstance = null;

    function formatNumber(num) {
      if (num === null || num === undefined || isNaN(num)) return '0';
      return Number(num).toLocaleString('uz-UZ').replace(/,/g, ' ');
    }

    function buySubscription() {
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
      const text = encodeURIComponent("men sotib olmoqchiman");
      const url = `https://t.me/fbr_a?text=${text}`;
      if (tg?.openTelegramLink) {
        tg.openTelegramLink(url);
      } else {
        window.open(url, "_blank");
      }
    }


const _loadedScripts = {};
function ensureScript(src) {
  if (_loadedScripts[src]) return _loadedScripts[src];
  _loadedScripts[src] = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Script load failed: ' + src));
    document.head.appendChild(s);
  });
  return _loadedScripts[src];
}

function switchTab(tab) {
  if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
  currentTab = tab;

  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  const activeEl = document.getElementById(`tab-${tab}`);
  if (activeEl) activeEl.classList.add('active');

  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  const activeNav = document.getElementById(`nav-${tab}`);
  if (activeNav) activeNav.classList.add('active');

  if (tab === 'customers') ensureScript('/static/js/customers.js').then(() => loadCustomers());
  if (tab === 'records') ensureScript('/static/js/records.js').then(() => loadRecords());
  if (tab === 'dashboard') loadDashboardStats();
}

function openSettingsModal() {
  ensureScript('/static/js/settings.js').then(() => if (typeof window._settingsReady === 'function') window._settingsReady());
}
function openCustomerDetail(partnerName) {
  ensureScript('/static/js/customers.js').then(() => if (typeof window._customerDetailReady === 'function') window._customerDetailReady(partnerName));
}
function filterAndSwitch(cat) {
  switchTab('records');
  ensureScript('/static/js/records.js').then(() => setRecordCategory(cat));
}


function changePeriod(period) {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
      currentPeriod = period;

      document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
      const btn = document.getElementById(`period-${period}`);
      if (btn) btn.classList.add('active');

      loadDashboardStats();
    }

    function applyDashboardData(data) {
      if (!data) return;
      const kpi = data.kpi || {};

      if (data.current_usd_rate) {
        const badge = document.getElementById('usd-rate-badge');
        if (badge) badge.innerText = `💵 1$ = ${formatNumber(data.current_usd_rate)} so'm`;
      }

      const elNaqdSum = document.getElementById('kpi-naqd-sum');
      const elNaqdCount = document.getElementById('kpi-naqd-count');
      const elNasiyaSum = document.getElementById('kpi-nasiya-sum');
      const elNasiyaCount = document.getElementById('kpi-nasiya-count');
      const elPaidSum = document.getElementById('kpi-paid-sum');
      const elPaidCount = document.getElementById('kpi-paid-count');
      const elDebtSum = document.getElementById('kpi-debt-sum');

      if (elNaqdSum && kpi.total_naqd_sum !== undefined) elNaqdSum.innerText = formatNumber(kpi.total_naqd_sum) + ' so\'m';
      const elNaqdUsd = document.getElementById('kpi-naqd-usd');
      if (elNaqdUsd) {
        if (kpi.total_naqd_usd && Number(kpi.total_naqd_usd) > 0) {
          elNaqdUsd.style.display = 'block';
          elNaqdUsd.innerText = `💵 $${formatNumber(kpi.total_naqd_usd)}`;
        } else {
          elNaqdUsd.style.display = 'none';
        }
      }
      if (elNaqdCount && kpi.count_naqd !== undefined) elNaqdCount.innerText = `${kpi.count_naqd} ta`;
      if (elNasiyaSum && kpi.total_nasiya_sum !== undefined) elNasiyaSum.innerText = formatNumber(kpi.total_nasiya_sum) + ' so\'m';
      if (elNasiyaCount && kpi.count_nasiya !== undefined) elNasiyaCount.innerText = `${kpi.count_nasiya} ta`;
      if (elPaidSum && kpi.total_paid_sum !== undefined) elPaidSum.innerText = formatNumber(kpi.total_paid_sum) + ' so\'m';
      if (elPaidCount && kpi.count_paid !== undefined) elPaidCount.innerText = `${kpi.count_paid} ta`;
      if (elDebtSum && kpi.total_debtors_balance !== undefined) elDebtSum.innerText = formatNumber(kpi.total_debtors_balance) + ' so\'m';

      // Kassa & Uyga Ketyapti mantiqi
      const rec = data.reconciliation || {};
      const elRecDate = document.getElementById('rec-date-badge');
      if (elRecDate && rec.date) elRecDate.innerText = rec.date;
      const setTxt = (id, val) => { const e = document.getElementById(id); if (e) e.innerText = val; };
      setTxt('rec-yesterday-uzs', `${formatNumber(rec.yesterday_net_uzs || 0)} so'm`);
      setTxt('rec-today-in-uzs', `${formatNumber(rec.today_in_uzs || 0)} so'm`);
      setTxt('rec-rasxod-uzs', `-${formatNumber(rec.today_rasxod_uzs || 0)} so'm`);
      setTxt('rec-expected-uzs', `${formatNumber(rec.expected_uzs || 0)} so'm`);
      setTxt('rec-uyga-uzs', `${formatNumber(rec.today_uyga_uzs || 0)} so'm`);
      const diffUzs = Number(rec.diff_uzs || 0);
      const diffEl = document.getElementById('rec-diff-uzs');
      if (diffEl) {
        if (diffUzs === 0) {
          diffEl.innerText = "✅ To'g'ri (0 so'm)";
          diffEl.style.color = "#00F5A0";
        } else if (diffUzs > 0) {
          diffEl.innerText = `+${formatNumber(diffUzs)} so'm (Ortiqcha)`;
          diffEl.style.color = "#00F2FE";
        } else {
          diffEl.innerText = `${formatNumber(diffUzs)} so'm (Kamomad)`;
          diffEl.style.color = "#FF3366";
        }
      }
      const usdLine = document.getElementById('rec-usd-line');
      if (usdLine) {
        if ((rec.expected_usd || 0) !== 0 || (rec.today_uyga_usd || 0) !== 0 || (rec.today_in_usd || 0) !== 0) {
          usdLine.style.display = 'block';
          usdLine.innerText = `💵 Dollar kassa: $${formatNumber(rec.expected_usd || 0)} | Uyga: $${formatNumber(rec.today_uyga_usd || 0)} | Farq: $${formatNumber(rec.diff_usd || 0)}`;
        } else {
          usdLine.style.display = 'none';
        }
      }

      if (data.chart || data.top_debtors) {
        ensureScript('https://cdn.jsdelivr.net/npm/chart.js').then(() => {
          if (data.chart && typeof Chart !== 'undefined') renderSalesChart(data.chart);
          if (data.top_debtors && typeof Chart !== 'undefined') renderDebtDoughnut(data.top_debtors);
        }).catch(() => {});
      }
      if (data.recent_records) renderRecentTransactions(data.recent_records);
    }

    async function loadDashboardStats() {
      try {
        const adminQ = '';
        const res = await apiFetch(`/api/stats?period=${currentPeriod}${adminQ}`);
        const data = await res.json();
        applyDashboardData(data);
      } catch (err) {
        console.error('Stat xato:', err);
      }
    }

    function renderSalesChart(chartData) {
      const canvas = document.getElementById('salesChart');
      if (!canvas || typeof Chart === 'undefined') return;
      const ctx = canvas.getContext('2d');
      if (salesChartInstance) salesChartInstance.destroy();

      salesChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: chartData.labels || [],
          datasets: [
            {
              label: 'Naqd',
              data: chartData.naqd || [],
              borderColor: '#00F5A0',
              borderWidth: 2,
              backgroundColor: 'rgba(0, 245, 160, 0.15)',
              fill: true,
              tension: 0.35,
              pointRadius: 2
            },
            {
              label: 'Nasiya',
              data: chartData.nasiya || [],
              borderColor: '#FF3366',
              borderWidth: 2,
              backgroundColor: 'rgba(255, 51, 102, 0.15)',
              fill: true,
              tension: 0.35,
              pointRadius: 2
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(255, 255, 255, 0.04)' }, ticks: { color: '#64748B', font: { size: 9 } } },
            y: {
              grid: { color: 'rgba(255, 255, 255, 0.04)' },
              ticks: {
                color: '#64748B',
                font: { size: 9 },
                callback: function(v) { return v >= 1000000 ? (v / 1000000).toFixed(1) + 'M' : (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v); }
              }
            }
          }
        }
      });
    }

    function renderDebtDoughnut(debtors) {
      const canvas = document.getElementById('debtDoughnutChart');
      if (!canvas || typeof Chart === 'undefined') return;
      const ctx = canvas.getContext('2d');
      if (debtChartInstance) debtChartInstance.destroy();

      const listContainer = document.getElementById('top-debtors-list');
      if (debtors && debtors.length > 0) {
        listContainer.innerHTML = '';
        debtors.forEach(d => {
          listContainer.innerHTML += `
            <div class="debtor-row">
              <span style="color:#FFF; font-weight:700; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${d.partner_name}</span>
              <span style="color:#FFB800; font-weight:900;">${formatNumber(d.balance)}</span>
            </div>
          `;
        });
      }

      debtChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: (debtors || []).map(d => d.partner_name),
          datasets: [{ data: (debtors || []).map(d => d.balance), backgroundColor: ['#FFB800', '#FF3366', '#A855F7', '#00F2FE', '#00F5A0'], borderWidth: 0 }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '72%',
          plugins: { legend: { display: false } }
        }
      });
    }

    function renderRecentTransactions(records) {
      const container = document.getElementById('recent-transactions-list');
      if (!container || !records) return;
      container.innerHTML = '';

      records.slice(0, 8).forEach(r => {
        let badgeColor = '#00F2FE';
        let badgeBg = 'rgba(0, 242, 254, 0.15)';
        let badgeText = 'To\'lov';

        if (r.category === 'naqd') { badgeColor = '#00F5A0'; badgeBg = 'rgba(0, 245, 160, 0.15)'; badgeText = 'Naqd'; }
        else if (r.category === 'nasiya') { badgeColor = '#FF3366'; badgeBg = 'rgba(255, 51, 102, 0.15)'; badgeText = 'Nasiya'; }

        const title = r.partner_name ? `${r.partner_name}: ${r.item_name || 'Savdo'}` : (r.item_name || 'Tovar');
        const timeBadge = r.time_str ? ` • ${r.time_str}` : '';

        container.innerHTML += `
          <div style="display:flex; align-items:center; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.03);">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:9px; font-weight:900; color:${badgeColor}; background:${badgeBg}; padding:2px 6px; border-radius:12px;">${badgeText}</span>
              <div>
                <div style="font-size:11px; font-weight:700; color:#FFF;">${title}</div>
                <div style="font-size:9px; color:#64748B;">${r.date_str}${timeBadge}</div>
              </div>
            </div>
            <div style="font-size:11px; font-weight:900; color:#FFF;">${formatNumber(r.total_amount)} so'm</div>
          </div>
        `;
      });
    }

function openSupportModal() {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      document.getElementById('support-modal')?.classList.add('active');
    }

    function closeSupportModal(e) {
      if (!e || e.target.id === 'support-modal' || e.target.classList.contains('modal-close-btn')) {
        document.getElementById('support-modal')?.classList.remove('active');
      }
    }

    function openSupportChat(e) {
      if (e) e.preventDefault();
      const url = "https://t.me/fbr_a";
      if (tg?.openTelegramLink) tg.openTelegramLink(url);
      else window.open(url, "_blank");
    }

let searchTimeout = null;
    function debounceSearch(type) {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        if (type === 'customers') loadCustomers();
        else if (type === 'records') loadRecords();
      }, 300);
    }

    function refreshData() {
      const icon = document.getElementById('refresh-icon');
      if (icon) icon.style.transform = 'rotate(360deg)';
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');

      if (currentTab === 'dashboard') loadDashboardStats();
      else if (currentTab === 'customers') loadCustomers();
      else if (currentTab === 'records') loadRecords();

      setTimeout(() => { if (icon) icon.style.transform = 'rotate(0deg)'; }, 400);
    }

    function exportExcel() {
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
      if (!isAdmin) {
        alert("🔒 Excel hisobot yuklab olish faqat biznes egasi (admin) uchun ochiq.\n\nO'z guruhingizga ushbu botni ulash narxi: oyiga 777 000 so'm.");
        switchTab('pricing');
        return;
      }
      apiFetch('/api/export-excel?via=telegram')
        .then(r => r.json())
        .then(d => {
          const msg = d.sent_to_chat
            ? "✅ Excel hisobot Telegram chatingizga yuborildi."
            : "❌ Excel yuborilmadi: " + (d.error || "noma'lum xatolik");
          if (tg?.showAlert) tg.showAlert(msg); else alert(msg);
        })
        .catch(() => { if (tg?.showAlert) tg.showAlert("❌ Tarmoq xatoligi. Qayta urinib ko'ring."); });
    }

    function initApp() {
      const roleBadge = document.getElementById('user-role-badge');
      const labelDash = document.getElementById('label-nav-dashboard');
      const demoBanner = document.getElementById('demo-banner');
      const guestCustLocked = document.getElementById('guest-customers-locked');
      const adminCustContent = document.getElementById('admin-customers-content');
      const guestRecLocked = document.getElementById('guest-records-locked');
      const adminRecContent = document.getElementById('admin-records-content');

      if (isAdmin) {
        if (roleBadge) roleBadge.innerText = '👑 Boshqaruvchi: Muslimjon';
        if (labelDash) labelDash.innerText = 'Dashboard';
        if (demoBanner) demoBanner.style.display = 'none';
        if (guestCustLocked) guestCustLocked.style.display = 'none';
        if (adminCustContent) adminCustContent.style.display = 'block';
        if (guestRecLocked) guestRecLocked.style.display = 'none';
        if (adminRecContent) adminRecContent.style.display = 'block';
        switchTab('dashboard');
      } else {
        if (roleBadge) roleBadge.innerText = '🚀 Vitrina & Taqdimot';
        if (labelDash) labelDash.innerText = 'Demo Panel';
        if (demoBanner) demoBanner.style.display = 'block';
        if (guestCustLocked) guestCustLocked.style.display = 'block';
        if (adminCustContent) adminCustContent.style.display = 'none';
        if (guestRecLocked) guestRecLocked.style.display = 'block';
        if (adminRecContent) adminRecContent.style.display = 'none';
        switchTab('features');
      }
      loadDashboardStats();

      // Serverdan kriptografik autentifikatsiyani tekshirib olish
      apiFetch('/api/me')
        .then(r => r.json())
        .then(d => {
          if (d && typeof d.is_admin === 'boolean') {
            isAdmin = d.is_admin;
            if (roleBadge) {
              roleBadge.innerText = isAdmin ? '👑 Boshqaruvchi: ' + (d.first_name || 'Muslimjon') : '🚀 Vitrina & Taqdimot';
            }
            if (demoBanner) demoBanner.style.display = isAdmin ? 'none' : 'block';
            if (guestCustLocked) guestCustLocked.style.display = isAdmin ? 'none' : 'block';
            if (adminCustContent) adminCustContent.style.display = isAdmin ? 'block' : 'none';
            if (guestRecLocked) guestRecLocked.style.display = isAdmin ? 'none' : 'block';
            if (adminRecContent) adminRecContent.style.display = isAdmin ? 'block' : 'none';
          }
        })
        .catch(() => {});
    }

    // Sahifa yuklanishi bilan ishga tushirish

window.addEventListener('load', () => {
  initApp();
});

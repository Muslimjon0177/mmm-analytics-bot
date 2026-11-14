// Mijozlar (CRM) bo'limi - faqat kerak bo'lganda yuklanadi

let currentSortOrder = 'alphabetical';

function setCustomerSort(order) {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
      currentSortOrder = order;
      document.getElementById('sort-alphabetical')?.classList.toggle('active', order === 'alphabetical');
      document.getElementById('sort-debt')?.classList.toggle('active', order === 'debt');
      loadCustomers();
    }

function sendDebtReminder() {
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
      const name = document.getElementById('cust-modal-name')?.innerText || 'Mijoz';
      const balText = document.getElementById('cust-modal-status')?.innerText || '';
      const credit = document.getElementById('cust-modal-credit')?.innerText || '0 so\'m';
      const paid = document.getElementById('cust-modal-paid')?.innerText || '0 so\'m';

      const text = `Assalomu alaykum, hurmatli ${name}!\n\n` +
        `📊 Savdo va hisob-kitoblar holati bo'yicha ma'lumot:\n` +
        `━━━━━━━━━━━━━━━━━━━━\n` +
        `📑 Jami olingan tovarlar: ${credit}\n` +
        `💰 To'langan summa: ${paid}\n` +
        `📌 ${balText}\n` +
        `━━━━━━━━━━━━━━━━━━━━\n` +
        `To'lovni plastik karta yoki naqd qabul qilamiz.\n` +
        `Hisob-kitob bo'yicha savollaringiz bo'lsa, bemalol bog'lanishingiz mumkin. Rahmat!`;

      const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(text)}`;
      if (tg?.openTelegramLink) {
        tg.openTelegramLink(shareUrl);
      } else {
        window.open(shareUrl, '_blank');
      }
    }

function closeCustomerModal(e) {
      if (!e || e.target.id === 'customer-modal' || e.target.classList.contains('modal-close-btn')) {
        document.getElementById('customer-modal')?.classList.remove('active');
      }
    }

    function renderCustomerModalData(data, name) {
      if (!data) return;
      const cust = data.customer || {};
      const records = data.records || [];

      document.getElementById('cust-modal-name').innerText = cust.display_name || name;
      const bal = cust.current_balance || 0;
      const balEl = document.getElementById('cust-modal-status');
      if (bal > 0) {
        balEl.innerText = `🔴 Qoldiq qarz: ${formatNumber(bal)} so'm`;
        balEl.style.color = '#FF3366';
      } else {
        balEl.innerText = '🟢 Hisob yopiq (Qarz yo\'q)';
        balEl.style.color = '#00F5A0';
      }

      document.getElementById('cust-modal-credit').innerText = formatNumber(cust.total_credit || 0) + ' so\'m';
      document.getElementById('cust-modal-paid').innerText = formatNumber(cust.total_paid || 0) + ' so\'m';
      document.getElementById('cust-modal-count').innerText = `${records.length} ta yozuv`;

      const listContainer = document.getElementById('cust-modal-records');
      if (records.length === 0) {
        listContainer.innerHTML = '<div style="font-size:11px; color:#64748B; text-align:center; padding:15px;">Ushbu mijozga oid operatsiyalar topilmadi.</div>';
        return;
      }

      listContainer.innerHTML = '';
      records.forEach(r => {
        let bColor = '#00F2FE';
        let bBg = 'rgba(0, 242, 254, 0.15)';
        let bText = 'Pul berdi';

        if (r.category === 'naqd') {
          bColor = '#00F5A0'; bBg = 'rgba(0, 245, 160, 0.15)'; bText = 'Naqd';
        } else if (r.category === 'nasiya') {
          bColor = '#FF3366'; bBg = 'rgba(255, 51, 102, 0.15)'; bText = 'Nasiya';
        }

        const itemDesc = r.item_name ? `${r.quantity || ''} ${r.unit || ''} ${r.item_name}`.trim() : (bText);
        const timeBadge = r.time_str ? ` • ${r.time_str}` : '';

        listContainer.innerHTML += `
          <div class="glass-card" style="padding:10px 12px; background:rgba(255,255,255,0.02); border-color:rgba(255,255,255,0.06);">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
              <span style="font-size:9px; font-weight:900; color:${bColor}; background:${bBg}; padding:2px 8px; border-radius:10px;">${bText}</span>
              <span style="font-size:12px; font-weight:900; color:#FFF;">${formatNumber(r.total_amount)} so'm</span>
            </div>
            <div style="font-size:11px; font-weight:700; color:#E2E8F0;">${itemDesc}</div>
            <div style="font-size:9px; color:#64748B; margin-top:2px; display:flex; justify-content:space-between;">
              <span>📅 ${r.date_str}${timeBadge}</span>
              ${r.price ? `<span>Narx: ${formatNumber(r.price)}</span>` : ''}
            </div>
            ${r.raw_message ? `<div style="font-size:9px; color:#475569; font-style:italic; margin-top:4px; border-top:1px dashed rgba(255,255,255,0.04); padding-top:2px;">"${r.raw_message}"</div>` : ''}
          </div>
        `;
      });
    }

    async function openCustomerDetail(partnerName) {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      const modal = document.getElementById('customer-modal');
      modal.classList.add('active');

      document.getElementById('cust-modal-name').innerText = partnerName;
      document.getElementById('cust-modal-records').innerHTML = '<div style="font-size:11px; color:#00F2FE; text-align:center; padding:20px;">Yuklanmoqda...</div>';

      // 1. Keshdan bir zumda ochish (0.001s instant display)
      const cacheKey = 'mmm_cust_' + partnerName.toLowerCase();
      try {
        const cached = localStorage.getItem(cacheKey);
        if (cached) renderCustomerModalData(JSON.parse(cached), partnerName);
      } catch (e) {}

      // 2. Serverdan yangilab olish
      try {
        const adminQ = '';
        const res = await apiFetch(`/api/customer-details?name=${encodeURIComponent(partnerName)}${adminQ}`);
        const data = await res.json();
        try { localStorage.setItem(cacheKey, JSON.stringify(data)); } catch (e) {}
        renderCustomerModalData(data, partnerName);
      } catch (err) {
        console.error('Mijoz tafsilotlari xatoligi:', err);
      }
    }

    async function loadCustomers() {
      if (!isAdmin) {
        document.getElementById('guest-customers-locked').style.display = 'block';
        document.getElementById('admin-customers-content').style.display = 'none';
        return;
      }

      const search = document.getElementById('search-customers')?.value || '';
      const container = document.getElementById('customers-list');
      if (!container) return;
      container.innerHTML = '<div style="text-align:center; color:#00F2FE; font-size:11px; padding:20px;">Yuklanmoqda...</div>';

      try {
        const adminQ = `&order=${currentSortOrder}`;
        const res = await apiFetch(`/api/customers?search=${encodeURIComponent(search)}${adminQ}`);
        const data = await res.json();
        const customers = data.customers || [];

        const countBadge = document.getElementById('customers-count');
        if (countBadge) countBadge.innerText = customers.length;

        container.innerHTML = '';
        if (customers.length === 0) {
          container.innerHTML = '<div style="text-align:center; color:#64748B; font-size:11px; padding:20px;">Mijozlar topilmadi</div>';
          return;
        }

        customers.forEach((c, idx) => {
          const isDebtor = (c.current_balance || 0) > 0;
          const dispName = escapeHtml(c.display_name || c.name || '');
          container.innerHTML += `
            <div data-cust="${dispName}" onclick="openCustomerDetail(this.dataset.cust)" class="glass-card customer-card-item" style="padding:12px 14px; border-color:${isDebtor ? 'rgba(255,51,102,0.3)' : 'rgba(0,245,160,0.2)'}">
              <div style="display:flex; align-items:center; justify-content:space-between;">
                <div>
                  <div style="font-size:12px; font-weight:900; color:#FFF; display:flex; align-items:center; gap:6px;">
                    <span style="color:#64748B; font-size:10px;">${idx+1}.</span> ${dispName}
                  </div>
                  <div style="font-size:9px; color:#64748B; margin-top:2px;">
                    Nasiya: ${formatNumber(c.total_credit || 0)} • To'lov: ${formatNumber(c.total_paid || 0)}
                  </div>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                  <div style="font-size:10px; font-weight:900; padding:3px 8px; border-radius:12px; ${isDebtor ? 'color:#FF3366; background:rgba(255,51,102,0.15);' : 'color:#00F5A0; background:rgba(0,245,160,0.15);'}">
                    ${isDebtor ? 'Qarz: ' + formatNumber(c.current_balance) : 'Yopiq'}
                  </div>
                  <span style="font-size:12px; color:#64748B;">→</span>
                </div>
              </div>
            </div>
          `;
        });
      } catch (err) {
        container.innerHTML = '<div style="text-align:center; color:#FF3366; font-size:11px; padding:10px;">Xatolik</div>';
      }
    }
window._customerDetailReady = openCustomerDetail;


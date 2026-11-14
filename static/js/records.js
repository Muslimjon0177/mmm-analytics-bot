// Yozuvlar tarixi bo'limi - faqat kerak bo'lganda yuklanadi

let currentRecordCategory = 'all';

function setRecordCategory(cat) {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
      currentRecordCategory = cat;
      document.querySelectorAll('.cat-pill').forEach(btn => btn.classList.remove('active'));
      document.getElementById(`cat-${cat}`)?.classList.add('active');
      loadRecords();
    }

    function filterAndSwitch(cat) {
      switchTab('records');
      setRecordCategory(cat);
    }

async function loadRecords() {
      if (!isAdmin) {
        document.getElementById('guest-records-locked').style.display = 'block';
        document.getElementById('admin-records-content').style.display = 'none';
        return;
      }

      const search = document.getElementById('search-records')?.value || '';
      const container = document.getElementById('records-list');
      if (!container) return;
      container.innerHTML = '<div style="text-align:center; color:#00F2FE; font-size:11px; padding:20px;">Yuklanmoqda...</div>';

      try {
        const catQ = currentRecordCategory !== 'all' ? `&category=${currentRecordCategory}` : '';
        const adminQ = `${catQ}`;
        const res = await apiFetch(`/api/records?search=${encodeURIComponent(search)}${adminQ}`);
        const data = await res.json();
        const records = data.records || [];

        container.innerHTML = '';
        if (records.length === 0) {
          container.innerHTML = '<div style="text-align:center; color:#64748B; font-size:11px; padding:20px;">Ushbu toifada yozuvlar topilmadi</div>';
          return;
        }

        records.slice(0, 50).forEach(r => {
          let bColor = '#00F2FE';
          let bBg = 'rgba(0, 242, 254, 0.15)';
          let bText = 'To\'lov';

          if (r.category === 'naqd') {
            bColor = '#00F5A0'; bBg = 'rgba(0, 245, 160, 0.15)'; bText = 'Naqd';
          } else if (r.category === 'nasiya') {
            bColor = '#FF3366'; bBg = 'rgba(255, 51, 102, 0.15)'; bText = 'Nasiya';
          } else if (r.category === 'rasxod') {
            bColor = '#F97316'; bBg = 'rgba(249, 115, 22, 0.15)'; bText = 'Rasxod';
          } else if (r.category === 'uyga') {
            bColor = '#A855F7'; bBg = 'rgba(168, 85, 247, 0.15)'; bText = 'Uyga';
          } else if (r.category === 'qaytarish') {
            bColor = '#FFB800'; bBg = 'rgba(255, 184, 0, 0.15)'; bText = 'Qaytarish';
          } else if (r.category === 'kelim') {
            bColor = '#38BDF8'; bBg = 'rgba(56, 189, 248, 0.15)'; bText = 'Kelim';
          }

          const timeBadge = r.time_str ? ` • ${escapeHtml(r.time_str)}` : '';
          const title = escapeHtml(r.partner_name ? `${r.partner_name}: ${r.item_name || 'Savdo'}` : (r.item_name || bText));
          const amtHtml = (r.currency === 'USD' && r.amount_usd) ? `$${formatNumber(r.amount_usd)}` : `${formatNumber(r.total_amount)} so'm`;

          container.innerHTML += `
            <div class="glass-card" style="padding:10px 14px; display:flex; justify-content:space-between; align-items:center;">
              <div>
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                  <span style="font-size:9px; font-weight:900; color:${bColor}; background:${bBg}; padding:1px 6px; border-radius:8px;">${bText}</span>
                  <div style="font-size:12px; font-weight:800; color:#FFF;">${title}</div>
                </div>
                <div style="font-size:9px; color:#64748B;">${escapeHtml(r.date_str)}${timeBadge} ${r.quantity ? '• ' + escapeHtml(r.quantity) + ' ' + escapeHtml(r.unit || '') : ''}</div>
              </div>
              <div style="font-size:12px; font-weight:900; color:${bColor};">${amtHtml}</div>
            </div>
          `;
        });
      } catch (err) {
        container.innerHTML = '<div style="text-align:center; color:#FF3366; font-size:11px; padding:10px;">Xatolik</div>';
      }
    }

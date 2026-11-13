// Modullar, Sozlamalar va Google Sheets sinxronizatsiyasi - faqat kerak bo'lganda yuklanadi

let globalSettings = {};

    const MODULE_DEFS = [
      { key: 'module_voice', title: '🎙 Ovozli Xabarlar (Audio AI)', desc: 'Guruhga tashlangan audio/golosovoyni avtomatik eshitib bazaga kiritish' },
      { key: 'module_nasiya', title: '📑 Nasiya Daftari (CRM)', desc: 'Mijozlar balansi, qarzlar tarixi va eng yirik qarzdorlar hisoboti' },
      { key: 'module_returns', title: '↩️ Tovar Qaytarish (Vozvrat)', desc: 'Qaytarilgan tovarlarni avtomatik hisoblab, qarzdan ayirish' },
      { key: 'module_kelim', title: '📦 Ombor Kirimi (Kelim)', desc: 'Fura va tovar kirimlarini alohida ombor hisobiga olish' },
      { key: 'module_usd', title: '💲 Valyuta (Dollar Kursi)', desc: 'Markaziy Bank kursini avtomatik ulab, dollar hisobini yuritish' },
      { key: 'module_backup', title: '📦 Har Kecha Avto-Backup', desc: 'Har kuni soat 23:00 da Telegramga to\'liq Excel zaxirasini yuborish' }
    ];

    function openSettingsModal() {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      if (!isAdmin) {
        alert("🔒 Modullar sozlamasi faqat tizim egasi (admin) uchun ochiq.");
        return;
      }
      document.getElementById('settings-modal')?.classList.add('active');
      loadSettings();
    }

    function closeSettingsModal(e) {
      if (!e || e.target.id === 'settings-modal' || e.target.classList.contains('modal-close-btn')) {
        document.getElementById('settings-modal')?.classList.remove('active');
      }
    }

    async function loadSettings() {
      const container = document.getElementById('settings-modules-list');
      if (!container) return;
      try {
        const res = await apiFetch('/api/settings');
        const data = await res.json();
        globalSettings = data.settings || {};
        const sheetsInput = document.getElementById('sheets-url-input');
        if (sheetsInput && globalSettings.google_sheets_url) {
          sheetsInput.value = globalSettings.google_sheets_url;
        }
        renderSettingsUI();
      } catch (e) {
        container.innerHTML = '<div style="color:#FF3366; font-size:11px; text-align:center;">Yuklashda xatolik</div>';
      }
    }

    async function importGoogleSheets() {
      const urlEl = document.getElementById('sheets-url-input');
      const statusEl = document.getElementById('sheets-import-status');
      const url = (urlEl?.value || '').trim();
      if (statusEl) {
        statusEl.style.color = '#00F2FE';
        statusEl.innerText = 'Yuklanmoqda...';
      }
      try {
        const res = await apiFetch('/api/import-sheets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data.success) {
          if (statusEl) {
            statusEl.style.color = '#00F5A0';
            statusEl.innerText = `✅ Yuklandi! Yangi: ${data.imported} ta, Yangilandi: ${data.updated} ta.`;
          }
          if (typeof loadCustomers === 'function') loadCustomers();
        } else {
          if (statusEl) {
            statusEl.style.color = '#FF3366';
            statusEl.innerText = `⚠️ ${data.error || 'Xatolik yuz berdi'}`;
          }
        }
      } catch (e) {
        if (statusEl) {
          statusEl.style.color = '#FF3366';
          statusEl.innerText = '⚠️ Serverga ulanishda xatolik';
        }
      }
    }

    function renderSettingsUI() {
      const container = document.getElementById('settings-modules-list');
      if (!container) return;
      container.innerHTML = '';
      MODULE_DEFS.forEach(m => {
        const isEnabled = String(globalSettings[m.key] || 'true') === 'true';
        container.innerHTML += `
          <div class="glass-card" style="padding:10px 12px; display:flex; justify-content:space-between; align-items:center;">
            <div style="flex:1; padding-right:10px;">
              <div style="font-size:12px; font-weight:800; color:#FFF;">${m.title}</div>
              <div style="font-size:9px; color:#64748B; margin-top:2px;">${m.desc}</div>
            </div>
            <button onclick="toggleSetting('${m.key}')" style="padding:6px 12px; border-radius:20px; font-size:10px; font-weight:800; cursor:pointer; border:1px solid; transition:all 0.2s; ${isEnabled ? 'background:rgba(0,245,160,0.15); color:#00F5A0; border-color:#00F5A0;' : 'background:rgba(255,255,255,0.05); color:#64748B; border-color:rgba(255,255,255,0.1);'}">
              ${isEnabled ? '🟢 Yoqilgan' : '⚪ O\'chiq'}
            </button>
          </div>
        `;
      });
    }

    async function toggleSetting(key) {
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
      const current = String(globalSettings[key] || 'true') === 'true';
      const newVal = !current;
      globalSettings[key] = String(newVal);
      renderSettingsUI();
      try {
        await apiFetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [key]: newVal })
        });
      } catch (e) {
        console.error("Sozlamani saqlashda xatolik:", e);
      }
    }
window._settingsReady = openSettingsModal;


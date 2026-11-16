// Ovozli va matnli AI Biznes Yordamchi - faqat kerak bo'lganda yuklanadi

let _aiMediaRecorder = null;
let _aiAudioChunks = [];
let _aiRecording = false;
let _aiRecognition = null;

function openAiModal() {
  if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
  if (!isAdmin) {
    alert("🤖 AI Biznes Yordamchi faqat tizim egasi (admin) uchun ochiq.");
    return;
  }
  document.getElementById('ai-modal')?.classList.add('active');
}

function closeAiModal(e) {
  if (!e || e.target.id === 'ai-modal' || e.target.classList.contains('modal-close-btn')) {
    document.getElementById('ai-modal')?.classList.remove('active');
  }
}

function _appendAiBubble(role, text) {
  const box = document.getElementById('ai-chat-box');
  if (!box) return;
  const isUser = role === 'user';
  const safe = escapeHtml(text).replace(/\n/g, '<br>');
  box.innerHTML += `
    <div style="align-self:${isUser ? 'flex-end' : 'flex-start'}; max-width:88%; padding:9px 12px; border-radius:12px; font-size:12px; line-height:1.45; background:${isUser ? 'linear-gradient(135deg,#00F2FE,#00F5A0)' : 'rgba(255,255,255,0.06)'}; color:${isUser ? '#06090F' : '#E2E8F0'}; font-weight:${isUser ? '700' : '500'}; border:${isUser ? 'none' : '1px solid rgba(255,255,255,0.08)'};">
      ${safe}
    </div>
  `;
  box.scrollTop = box.scrollHeight;
}

function _speakAiAnswer(text) {
  try {
    if (!('speechSynthesis' in window)) return;
    const toggle = document.getElementById('ai-tts-toggle');
    if (toggle && !toggle.checked) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'uz-UZ';
    u.rate = 1.05;
    window.speechSynthesis.speak(u);
  } catch (e) {}
}

async function sendAiQuestion(customText) {
  const input = document.getElementById('ai-question-input');
  const q = (customText !== undefined ? customText : (input?.value || '')).trim();
  if (!q) return;
  if (input && customText === undefined) input.value = '';

  _appendAiBubble('user', q);
  const statusEl = document.getElementById('ai-voice-status');
  if (statusEl) statusEl.innerText = '🤖 AI hisoblamoqda...';

  try {
    const res = await apiFetch('/api/ai-ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q })
    });
    const data = await res.json();
    const ans = data.answer || data.error || 'Javob olinmadi.';
    _appendAiBubble('ai', ans);
    _speakAiAnswer(ans);
    if (data.mutated && typeof refreshData === 'function') refreshData();
  } catch (e) {
    _appendAiBubble('ai', '⚠️ Server bilan aloqa xatoligi.');
  } finally {
    if (statusEl) statusEl.innerText = 'Tayyor — yozing yoki mikrofonni bosing';
  }
}

async function toggleAiVoice() {
  const btn = document.getElementById('ai-mic-btn');
  const statusEl = document.getElementById('ai-voice-status');

  // 1. Agar yozib olayotgan bo'lsa -> to'xtatish
  if (_aiRecording) {
    _aiRecording = false;
    if (btn) btn.style.background = 'linear-gradient(135deg,#A855F7,#00F2FE)';
    if (_aiRecognition) {
      try { _aiRecognition.stop(); } catch (e) {}
      _aiRecognition = null;
      return;
    }
    if (_aiMediaRecorder && _aiMediaRecorder.state !== 'inactive') {
      _aiMediaRecorder.stop();
      return;
    }
  }

  // 2. Brauzer SpeechRecognition sinab ko'rish (tezkor)
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRec) {
    try {
      const rec = new SpeechRec();
      rec.lang = 'uz-UZ';
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      _aiRecognition = rec;
      _aiRecording = true;
      if (btn) btn.style.background = '#FF3366';
      if (statusEl) statusEl.innerText = '🎙 Eshityapman... Gapiring (to‘xtatish uchun yana bosing)';

      rec.onresult = (ev) => {
        const transcript = ev.results?.[0]?.[0]?.transcript || '';
        _aiRecording = false;
        _aiRecognition = null;
        if (btn) btn.style.background = 'linear-gradient(135deg,#A855F7,#00F2FE)';
        if (transcript.trim()) {
          sendAiQuestion(transcript.trim());
        } else if (statusEl) {
          statusEl.innerText = 'Ovoz eshitilmadi, qayta urinib ko‘ring';
        }
      };
      rec.onerror = () => {
        _aiRecording = false;
        _aiRecognition = null;
        if (btn) btn.style.background = 'linear-gradient(135deg,#A855F7,#00F2FE)';
        _startMediaRecorderFallback();
      };
      rec.onend = () => {
        if (_aiRecording) {
          _aiRecording = false;
          _aiRecognition = null;
          if (btn) btn.style.background = 'linear-gradient(135deg,#A855F7,#00F2FE)';
          if (statusEl) statusEl.innerText = 'Tayyor — yozing yoki mikrofonni bosing';
        }
      };
      rec.start();
      return;
    } catch (e) {}
  }

  // 3. Fallback: MediaRecorder -> /api/ai-ask (Gemini Audio AI)
  _startMediaRecorderFallback();
}

async function _startMediaRecorderFallback() {
  const btn = document.getElementById('ai-mic-btn');
  const statusEl = document.getElementById('ai-voice-status');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (statusEl) statusEl.innerText = '⚠️ Bu qurilmada mikrofon ruxsati yo‘q. Savolni yozib yuboring.';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _aiAudioChunks = [];
    _aiMediaRecorder = new MediaRecorder(stream);
    _aiRecording = true;
    if (btn) btn.style.background = '#FF3366';
    if (statusEl) statusEl.innerText = '🎙 Ovoz yozilmoqda... Tugatish uchun yana bosing';

    _aiMediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) _aiAudioChunks.push(e.data);
    };
    _aiMediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_aiAudioChunks, { type: _aiMediaRecorder.mimeType || 'audio/webm' });
      if (statusEl) statusEl.innerText = '🤖 Ovoz tahlil qilinmoqda...';
      try {
        const fd = new FormData();
        fd.append('audio', blob, 'voice.webm');
        const res = await apiFetch('/api/ai-ask', { method: 'POST', body: fd });
        const data = await res.json();
        _appendAiBubble('user', data.question || '🎙 Ovozli savol');
        const ans = data.answer || data.error || 'Javob olinmadi.';
        _appendAiBubble('ai', ans);
        _speakAiAnswer(ans);
        if (data.mutated && typeof refreshData === 'function') refreshData();
      } catch (err) {
        _appendAiBubble('ai', '⚠️ Ovozni yuborishda xatolik.');
      } finally {
        if (statusEl) statusEl.innerText = 'Tayyor — yozing yoki mikrofonni bosing';
      }
    };
    _aiMediaRecorder.start();
  } catch (err) {
    _aiRecording = false;
    if (btn) btn.style.background = 'linear-gradient(135deg,#A855F7,#00F2FE)';
    if (statusEl) statusEl.innerText = '⚠️ Mikrofonga ruxsat berilmadi. Savolni yozing.';
  }
}

window._aiModalReady = openAiModal;

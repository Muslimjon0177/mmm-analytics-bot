// Gemini Live uslubidagi Jonli Ovozli + Admin AI Yordamchi

let _aiMediaRecorder = null;
let _aiAudioChunks = [];
let _aiRecording = false;
let _aiRecognition = null;
let _aiLiveMode = false;
let _aiCurrentAudio = null;
let _aiHistory = []; // [{role: 'user'|'ai', text: '...'}]

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
    stopAiLive();
    document.getElementById('ai-modal')?.classList.remove('active');
  }
}

function _setOrbState(state, label) {
  const orb = document.getElementById('ai-live-orb');
  const statusEl = document.getElementById('ai-voice-status');
  const liveBtn = document.getElementById('ai-live-btn');
  if (statusEl && label) statusEl.innerText = label;
  if (liveBtn) {
    liveBtn.innerText = _aiLiveMode ? '⏹ Suhbatni to‘xtatish' : '🎙 Jonli Suhbat (Gemini Live)';
    liveBtn.style.background = _aiLiveMode
      ? 'linear-gradient(135deg,#FF3366,#F97316)'
      : 'linear-gradient(135deg,#A855F7,#00F2FE)';
  }
  if (!orb) return;
  if (state === 'listening') {
    orb.style.background = 'radial-gradient(circle,#00F5A0,#00F2FE)';
    orb.style.boxShadow = '0 0 28px rgba(0,245,160,0.75), 0 0 60px rgba(0,242,254,0.45)';
    orb.style.transform = 'scale(1.12)';
  } else if (state === 'thinking') {
    orb.style.background = 'radial-gradient(circle,#A855F7,#38BDF8)';
    orb.style.boxShadow = '0 0 32px rgba(168,85,247,0.85)';
    orb.style.transform = 'scale(1.04)';
  } else if (state === 'speaking') {
    orb.style.background = 'radial-gradient(circle,#00F2FE,#A855F7)';
    orb.style.boxShadow = '0 0 34px rgba(0,242,254,0.85)';
    orb.style.transform = 'scale(1.16)';
  } else {
    orb.style.background = 'radial-gradient(circle,#A855F7,#0F172A)';
    orb.style.boxShadow = '0 0 14px rgba(168,85,247,0.35)';
    orb.style.transform = 'scale(1)';
  }
}

function _appendAiBubble(role, text) {
  const box = document.getElementById('ai-chat-box');
  if (!box) return;
  _aiHistory.push({ role: role === 'user' ? 'user' : 'ai', text });
  if (_aiHistory.length > 12) _aiHistory = _aiHistory.slice(-12);

  const isUser = role === 'user';
  const safe = escapeHtml(text).replace(/\n/g, '<br>');
  box.innerHTML += `
    <div style="align-self:${isUser ? 'flex-end' : 'flex-start'}; max-width:88%; padding:9px 12px; border-radius:12px; font-size:12px; line-height:1.45; background:${isUser ? 'linear-gradient(135deg,#00F2FE,#00F5A0)' : 'rgba(255,255,255,0.06)'}; color:${isUser ? '#06090F' : '#E2E8F0'}; font-weight:${isUser ? '700' : '500'}; border:${isUser ? 'none' : '1px solid rgba(255,255,255,0.08)'};">
      ${safe}
    </div>
  `;
  box.scrollTop = box.scrollHeight;
}

function _stopCurrentSpeech() {
  if (_aiCurrentAudio) {
    try { _aiCurrentAudio.pause(); _aiCurrentAudio.currentTime = 0; } catch (e) {}
    _aiCurrentAudio = null;
  }
  try { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); } catch (e) {}
}

function _playAiReply(text, audioB64) {
  const toggle = document.getElementById('ai-tts-toggle');
  const wantVoice = !toggle || toggle.checked;
  if (!wantVoice) {
    _setOrbState('idle', 'Tayyor — yozing yoki gapiring');
    if (_aiLiveMode) setTimeout(_listenOneTurn, 300);
    return;
  }

  _stopCurrentSpeech();
  _setOrbState('speaking', '🔊 Gapiryapman... (to‘xtatish uchun bosing)');

  const onDone = () => {
    _aiCurrentAudio = null;
    if (_aiLiveMode) {
      _setOrbState('listening', '🎙 Eshityapman...');
      setTimeout(_listenOneTurn, 250);
    } else {
      _setOrbState('idle', 'Tayyor — yozing yoki gapiring');
    }
  };

  if (audioB64) {
    try {
      const audio = new Audio('data:audio/mp3;base64,' + audioB64);
      _aiCurrentAudio = audio;
      audio.onended = onDone;
      audio.onerror = () => _fallbackBrowserTTS(text, onDone);
      audio.play().catch(() => _fallbackBrowserTTS(text, onDone));
      return;
    } catch (e) {}
  }
  _fallbackBrowserTTS(text, onDone);
}

function _fallbackBrowserTTS(text, onDone) {
  try {
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'uz-UZ';
      u.rate = 1.05;
      u.onend = onDone;
      u.onerror = onDone;
      window.speechSynthesis.speak(u);
      return;
    }
  } catch (e) {}
  onDone();
}

function stopAiLive() {
  _aiLiveMode = false;
  _aiRecording = false;
  _stopCurrentSpeech();
  if (_aiRecognition) {
    try { _aiRecognition.stop(); } catch (e) {}
    _aiRecognition = null;
  }
  if (_aiMediaRecorder && _aiMediaRecorder.state !== 'inactive') {
    try { _aiMediaRecorder.stop(); } catch (e) {}
  }
  _setOrbState('idle', 'Tayyor — yozing yoki «Jonli Suhbat» ni bosing');
}

function toggleAiLiveMode() {
  if (_aiLiveMode) {
    stopAiLive();
  } else {
    _aiLiveMode = true;
    _stopCurrentSpeech();
    _listenOneTurn();
  }
}

function onOrbTap() {
  if (_aiCurrentAudio || ('speechSynthesis' in window && window.speechSynthesis.speaking)) {
    // Gapirayotganda bosilsa — darhol to'xtatib, foydalanuvchini tinglashga o'tadi (Gemini Live kabi)
    _stopCurrentSpeech();
    if (_aiLiveMode) _listenOneTurn();
    else toggleAiVoice();
    return;
  }
  toggleAiVoice();
}

async function sendAiQuestion(customText) {
  const input = document.getElementById('ai-question-input');
  const q = (customText !== undefined ? customText : (input?.value || '')).trim();
  if (!q) return;
  if (input && customText === undefined) input.value = '';

  const historySnapshot = _aiHistory.slice(-8);
  _appendAiBubble('user', q);
  _setOrbState('thinking', '⚡ AI o‘ylamoqda...');

  try {
    const wantVoice = !document.getElementById('ai-tts-toggle') || document.getElementById('ai-tts-toggle').checked;
    const res = await apiFetch('/api/ai-ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history: historySnapshot, want_voice: wantVoice })
    });
    const data = await res.json();
    const ans = data.answer || data.error || 'Javob olinmadi.';
    _appendAiBubble('ai', ans);
    if (data.mutated && typeof refreshData === 'function') refreshData();
    _playAiReply(ans, data.audio_b64);
  } catch (e) {
    _appendAiBubble('ai', '⚠️ Server bilan aloqa xatoligi.');
    _setOrbState('idle', 'Tayyor — qayta urinib ko‘ring');
  }
}

function toggleAiVoice() {
  if (_aiRecording) {
    _aiRecording = false;
    if (_aiRecognition) {
      try { _aiRecognition.stop(); } catch (e) {}
      _aiRecognition = null;
      _setOrbState('idle', 'Tayyor');
      return;
    }
    if (_aiMediaRecorder && _aiMediaRecorder.state !== 'inactive') {
      _aiMediaRecorder.stop();
      return;
    }
  }
  _listenOneTurn();
}

function _listenOneTurn() {
  _stopCurrentSpeech();
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRec) {
    try {
      const rec = new SpeechRec();
      rec.lang = 'uz-UZ';
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      _aiRecognition = rec;
      _aiRecording = true;
      _setOrbState('listening', '🎙 Eshityapman... Gapiring');

      rec.onresult = (ev) => {
        const transcript = ev.results?.[0]?.[0]?.transcript || '';
        _aiRecording = false;
        _aiRecognition = null;
        if (transcript.trim()) {
          sendAiQuestion(transcript.trim());
        } else if (_aiLiveMode) {
          setTimeout(_listenOneTurn, 300);
        } else {
          _setOrbState('idle', 'Ovoz eshitilmadi, qayta urinib ko‘ring');
        }
      };
      rec.onerror = () => {
        _aiRecording = false;
        _aiRecognition = null;
        _startMediaRecorderFallback();
      };
      rec.onend = () => {
        if (_aiRecording) {
          _aiRecording = false;
          _aiRecognition = null;
          _setOrbState('idle', 'Tayyor — yozing yoki mikrofonni bosing');
        }
      };
      rec.start();
      return;
    } catch (e) {}
  }
  _startMediaRecorderFallback();
}

async function _startMediaRecorderFallback() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    _aiLiveMode = false;
    _setOrbState('idle', '⚠️ Mikrofon ruxsati yo‘q. Savolni yozing.');
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _aiAudioChunks = [];
    _aiMediaRecorder = new MediaRecorder(stream);
    _aiRecording = true;
    _setOrbState('listening', '🎙 Ovoz yozilmoqda... Tugatish uchun sharni bosing');

    _aiMediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) _aiAudioChunks.push(e.data);
    };
    _aiMediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_aiAudioChunks, { type: _aiMediaRecorder.mimeType || 'audio/webm' });
      _setOrbState('thinking', '⚡ Ovoz tahlil qilinmoqda...');
      try {
        const fd = new FormData();
        fd.append('audio', blob, 'voice.webm');
        fd.append('history', JSON.stringify(_aiHistory.slice(-8)));
        const wantVoice = !document.getElementById('ai-tts-toggle') || document.getElementById('ai-tts-toggle').checked;
        fd.append('want_voice', wantVoice ? 'true' : 'false');
        const res = await apiFetch('/api/ai-ask', { method: 'POST', body: fd });
        const data = await res.json();
        _appendAiBubble('user', data.question || '🎙 Ovozli savol');
        const ans = data.answer || data.error || 'Javob olinmadi.';
        _appendAiBubble('ai', ans);
        if (data.mutated && typeof refreshData === 'function') refreshData();
        _playAiReply(ans, data.audio_b64);
      } catch (err) {
        _appendAiBubble('ai', '⚠️ Ovozni yuborishda xatolik.');
        _setOrbState('idle', 'Tayyor');
      }
    };
    _aiMediaRecorder.start();
  } catch (err) {
    _aiRecording = false;
    _aiLiveMode = false;
    _setOrbState('idle', '⚠️ Mikrofonga ruxsat berilmadi. Savolni yozing.');
  }
}

window._aiModalReady = openAiModal;

/* ═══════════════════════════════════════════════════════════════════
   Wini Tutor Test UI — Client Logic
   ═══════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────
  const API = '';  // same origin
  const GAUGE_R = 22;
  const GAUGE_C = 2 * Math.PI * GAUGE_R;

  const COGNITIVE_KEYS = [
    { key: 'confusion',       label: 'Confuse',  color: 'hsl(0, 75%, 55%)' },
    { key: 'curiosity',       label: 'Curious',  color: 'hsl(270, 80%, 65%)' },
    { key: 'confidence',      label: 'Confid',   color: 'hsl(190, 95%, 55%)' },
    { key: 'cognitive_load',  label: 'CogLoad',  color: 'hsl(40, 95%, 60%)' },
    { key: 'engagement',      label: 'Engage',   color: 'hsl(155, 70%, 45%)' },
    { key: 'frustration_risk',label: 'Frustrat', color: 'hsl(340, 75%, 58%)' },
  ];

  const ACTION_COLORS = {
    'EXPLAIN':                 'action-explain',
    'QUIZ':                    'action-quiz',
    'MISCONCEPTION_PROBE':     'action-misconception',
    'SOCRATIC_Q':              'action-socratic',
    'ENCOURAGE':               'action-encourage',
    'TRANSFER_PROBLEM':        'action-transfer',
    'METACOGNITIVE_REFLECT':   'action-reflect',
    'REPRESENTATION_TRANSLATION': 'action-explain',
    'WORKED_EXAMPLE':          'action-explain',
    'ANALOGOUS_EXAMPLE':       'action-hint',
  };

  const HOPE_COLORS = {
    KI: 'hsl(270, 80%, 65%)',
    KT: 'hsl(190, 95%, 55%)',
    CT: 'hsl(155, 70%, 45%)',
  };

  // ── State ──────────────────────────────────────────────────────
  let busy = false;
  let firstTurn = true;
  let actionLog = [];
  let sessionStart = Date.now();
  let timerInterval = null;

  // ── DOM refs ───────────────────────────────────────────────────
  const $ = id => document.getElementById(id);
  const chatMessages  = $('chatMessages');
  const chatInput     = $('chatInput');
  const sendBtn       = $('sendBtn');
  const typing        = $('typingIndicator');
  const welcomeMsg    = $('welcomeMessage');
  const gaugeGrid     = $('gaugeGrid');
  const hopeGrid      = $('hopeGrid');
  const masteryList   = $('masteryList');
  const sessionInfo   = $('sessionInfo');
  const signalTags    = $('signalTags');
  const actionHistory = $('actionHistory');
  const healthDot     = $('healthDot');
  const healthText    = $('healthText');
  const loadingOvr    = $('loadingOverlay');
  const loadingTxt    = $('loadingText');
  const sessionTimer  = $('sessionTimer');
  const resetBtn      = $('resetBtn');

  // ── Init ───────────────────────────────────────────────────────
  function init() {
    buildGauges();
    buildHopeItems();
    loadState();
    checkHealth();
    setInterval(checkHealth, 12000);
    startTimer();

    chatInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    sendBtn.addEventListener('click', sendMessage);
    resetBtn.addEventListener('click', resetSession);
  }

  // ── Timer ──────────────────────────────────────────────────────
  function startTimer() {
    sessionStart = Date.now();
    timerInterval = setInterval(() => {
      const s = Math.floor((Date.now() - sessionStart) / 1000);
      const m = Math.floor(s / 60);
      const sec = s % 60;
      sessionTimer.textContent = `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
    }, 1000);
  }

  // ── Health Check ───────────────────────────────────────────────
  async function checkHealth() {
    try {
      const r = await fetch(`${API}/api/health`);
      const d = await r.json();
      healthDot.classList.toggle('online', d.qwen);
      healthText.textContent = d.qwen ? 'Qwen Online' : 'Qwen Offline';
    } catch {
      healthDot.classList.remove('online');
      healthText.textContent = 'Server Offline';
    }
  }

  // ── Load State ─────────────────────────────────────────────────
  async function loadState() {
    try {
      const r = await fetch(`${API}/api/state`);
      const state = await r.json();
      updateMasteryBars(state.concept_states || {});
      updateSessionCard(state.session || {});
      if (state.hope_rolling) updateHopeValues(state.hope_rolling);
      if (state.global) {
        updateCognitiveGauges({
          confusion: state.global.cognitive_load || 0,
          curiosity: state.global.curiosity || 0,
          confidence: state.global.confidence || 0,
          cognitive_load: state.global.cognitive_load || 0,
          engagement: state.global.engagement || 0,
          frustration_risk: 0,
        });
      }
    } catch { /* server not ready yet */ }
  }

  // ── Send Message ───────────────────────────────────────────────
  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || busy) return;
    busy = true;
    sendBtn.disabled = true;
    chatInput.value = '';

    // Hide welcome
    if (welcomeMsg) welcomeMsg.style.display = 'none';

    // Add student bubble
    addMessage('student', text);

    // Show typing
    typing.classList.add('active');
    scrollChat();

    // Show loading on first turn
    if (firstTurn) {
      loadingOvr.classList.add('active');
      loadingTxt.textContent = 'Loading MiniLM + store — first request takes ~10s…';
    }

    try {
      const r = await fetch(`${API}/api/turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const data = await r.json();

      if (data.error) {
        addMessage('wini', `⚠️ Error: ${data.error}`, { action: 'ERROR' });
      } else {
        // Add Wini response
        addMessage('wini', data.answer || '(No LLM answer — Qwen may be offline)', {
          action: data.action,
          concept: data.concept,
          nEvidence: data.n_evidence,
          signals: data.signals,
          cognitiveUpdate: data.cognitive_update,
          shadow: data.shadow,
          writeback: data.writeback,
          hopeUpdate: data.hope_update,
          actionReason: data.action_reason,
          bridgeIds: data.bridge_ids,
          pendingCheck: data.pending_check,
          pendingHope: data.pending_hope,
          display: data.display,
        });

        // Update dashboard
        if (data.cognitive_update) updateCognitiveGauges(data.cognitive_update);
        if (data.signals) updateSignals(data.signals);
        logAction(data.action);

        // Reload full state for mastery + HOPE
        loadState();
      }
    } catch (e) {
      addMessage('wini', `⚠️ Network error: ${e.message}`, { action: 'ERROR' });
    } finally {
      typing.classList.remove('active');
      loadingOvr.classList.remove('active');
      firstTurn = false;
      busy = false;
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }

  // ── Add Message Bubble ─────────────────────────────────────────
  function addMessage(role, text, meta = {}) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;        // set as text first (no HTML injection), then typeset math
    renderMath(bubble);
    msg.appendChild(bubble);

    // T9 multimodal display channel: show the textbook crop while Wini explains
    if (role === 'wini' && meta.display && meta.display.length) {
      for (const d of meta.display) {
        msg.appendChild(buildFigure(d));
      }
    }

    // Writeback banner
    if (meta.writeback) {
      const wb = meta.writeback;
      const banner = document.createElement('div');
      banner.className = `writeback-banner show ${wb.outcome}`;
      const icon = wb.outcome === 'correct' ? '✓' : wb.outcome === 'wrong' ? '✗' : '~';
      banner.innerHTML = `<strong>${icon}</strong> Diagnostic: ${wb.outcome}` +
        (wb.mastery != null ? ` · mastery → ${(wb.mastery * 100).toFixed(0)}%` : '') +
        (wb.misconception_status ? ` · ${wb.misconception_status}` : '');
      msg.appendChild(banner);
    }

    // Meta badges
    if (role === 'wini' && meta.action) {
      const metaRow = document.createElement('div');
      metaRow.className = 'message-meta';

      // Action badge
      const actionBadge = document.createElement('span');
      const actionClass = ACTION_COLORS[meta.action] || 'action';
      actionBadge.className = `meta-badge ${actionClass}`;
      actionBadge.textContent = meta.action.replace(/_/g, ' ');
      metaRow.appendChild(actionBadge);

      // Concept badge
      if (meta.concept && meta.concept.concept_id) {
        const conceptBadge = document.createElement('span');
        conceptBadge.className = 'meta-badge concept';
        conceptBadge.textContent = formatConceptId(meta.concept.concept_id);
        conceptBadge.title = meta.concept.concept_id;
        metaRow.appendChild(conceptBadge);
      }

      // Evidence badge
      if (meta.nEvidence > 0) {
        const evBadge = document.createElement('span');
        evBadge.className = 'meta-badge evidence';
        evBadge.textContent = `${meta.nEvidence} evidence`;
        metaRow.appendChild(evBadge);
      }

      msg.appendChild(metaRow);

      // HOPE update indicator
      if (meta.hopeUpdate) {
        const hBanner = document.createElement('div');
        hBanner.className = 'writeback-banner show';
        hBanner.style.background = 'hsla(270,80%,65%,0.08)';
        hBanner.style.color = 'var(--violet)';
        hBanner.style.border = '1px solid hsla(270,80%,65%,0.2)';
        const h = meta.hopeUpdate;
        hBanner.innerHTML = `<strong>HOPE</strong> ${h.signal}: ${h.label} (${h.score}/3) · rolling → ${(h.rolling * 100).toFixed(0)}%`;
        msg.appendChild(hBanner);
      }

      // Pipeline trace
      const trace = document.createElement('div');
      trace.className = 'pipeline-trace';

      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'trace-toggle';
      toggleBtn.textContent = '▸ Pipeline trace';
      trace.appendChild(toggleBtn);

      const content = document.createElement('div');
      content.className = 'trace-content';
      content.innerHTML = buildTraceHTML(meta);
      trace.appendChild(content);

      toggleBtn.addEventListener('click', () => {
        const open = content.classList.toggle('open');
        toggleBtn.textContent = open ? '▾ Pipeline trace' : '▸ Pipeline trace';
      });

      msg.appendChild(trace);
    }

    chatMessages.appendChild(msg);
    scrollChat();
  }

  function buildTraceHTML(meta) {
    let html = '';
    const ln = (label, value) => `<div><span class="trace-label">${label}:</span> <span class="trace-value">${escapeHtml(String(value ?? '—'))}</span></div>`;

    html += ln('Action', meta.action);
    html += ln('Reason', meta.actionReason);

    if (meta.concept) {
      html += ln('Concept', meta.concept.concept_id || '(abstained)');
      html += ln('Confidence', meta.concept.concept_confidence != null
        ? (meta.concept.concept_confidence * 100).toFixed(1) + '%' : '—');
      html += ln('Abstained', meta.concept.abstained);
      if (meta.concept.secondary_concepts?.length) {
        html += ln('Secondary', meta.concept.secondary_concepts.join(', '));
      }
    }

    if (meta.shadow) {
      html += ln('Shadow', typeof meta.shadow === 'object' ? meta.shadow.action : meta.shadow);
    }

    html += ln('Evidence', meta.nEvidence);
    if (meta.bridgeIds?.length) html += ln('Bridges', meta.bridgeIds.join(', '));
    if (meta.pendingCheck) html += ln('Pending check', meta.pendingCheck);
    if (meta.pendingHope) html += ln('Pending HOPE', meta.pendingHope);

    if (meta.cognitiveUpdate) {
      html += '<div style="margin-top:6px"><span class="trace-label">Cognitive Update:</span></div>';
      for (const [k, v] of Object.entries(meta.cognitiveUpdate)) {
        if (typeof v === 'number') html += ln(`  ${k}`, v.toFixed(3));
      }
    }

    if (meta.signals?.length) {
      html += ln('Signals', meta.signals.join(', '));
    }

    return html;
  }

  // ── LaTeX math rendering (KaTeX auto-render) ───────────────────
  function renderMath(el) {
    if (typeof renderMathInElement !== 'function') return;  // CDN not loaded / offline
    try {
      renderMathInElement(el, {
        delimiters: [
          { left: '\\[', right: '\\]', display: true },
          { left: '\\(', right: '\\)', display: false },
          { left: '$$', right: '$$', display: true },
        ],
        throwOnError: false,           // bad LaTeX -> leave it as text, never break the bubble
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      });
    } catch (e) { /* leave raw text on any KaTeX error */ }
  }

  // ── Display Figure (T9 multimodal channel) ─────────────────────
  function buildFigure(d) {
    const fig = document.createElement('figure');
    fig.className = 'message-figure';

    const img = document.createElement('img');
    img.className = 'figure-img';
    // image_path is store-relative; the server serves it under /store/
    img.src = `${API}/store/${d.image_path}`;
    img.alt = d.alt_text || 'figure';
    img.loading = 'lazy';
    img.title = d.why || '';
    img.addEventListener('error', () => { fig.style.display = 'none'; });
    fig.appendChild(img);

    const cap = document.createElement('figcaption');
    cap.className = 'figure-caption';
    const reps = (d.supports_representation || []).join(' · ');
    cap.innerHTML = `<span class="figure-eye">🖼</span> ${escapeHtml(d.alt_text || 'Figure on screen')}` +
      (reps ? ` <span class="figure-reps">${escapeHtml(reps)}</span>` : '');
    fig.appendChild(cap);

    return fig;
  }

  // ── Cognitive Gauges ───────────────────────────────────────────
  function buildGauges() {
    gaugeGrid.innerHTML = '';
    for (const g of COGNITIVE_KEYS) {
      const item = document.createElement('div');
      item.className = 'gauge-item';
      item.innerHTML = `
        <div class="gauge-ring">
          <svg viewBox="0 0 52 52">
            <circle class="track" cx="26" cy="26" r="${GAUGE_R}"/>
            <circle class="fill" id="gaugeFill_${g.key}" cx="26" cy="26" r="${GAUGE_R}"
              stroke="${g.color}" stroke-dasharray="${GAUGE_C}" stroke-dashoffset="${GAUGE_C}"/>
          </svg>
          <span class="gauge-value" id="gaugeVal_${g.key}">0</span>
        </div>
        <span class="gauge-label">${g.label}</span>`;
      gaugeGrid.appendChild(item);
    }
  }

  function updateCognitiveGauges(update) {
    for (const g of COGNITIVE_KEYS) {
      const v = Math.max(0, Math.min(1, update[g.key] || 0));
      const fill = $(`gaugeFill_${g.key}`);
      const val = $(`gaugeVal_${g.key}`);
      if (fill) fill.style.strokeDashoffset = GAUGE_C * (1 - v);
      if (val) val.textContent = (v * 100).toFixed(0);
    }
  }

  // ── HOPE Metrics ───────────────────────────────────────────────
  function buildHopeItems() {
    hopeGrid.innerHTML = '';
    for (const sig of ['KI', 'KT', 'CT']) {
      const item = document.createElement('div');
      item.className = 'hope-item';
      item.id = `hope_${sig}`;
      const label = sig === 'KI' ? 'Knowledge Integration' : sig === 'KT' ? 'Knowledge Transfer' : 'Critical Thinking';
      item.innerHTML = `
        <span class="hope-label" title="${label}">${sig}</span>
        <span class="hope-score" id="hopeScore_${sig}" style="color:${HOPE_COLORS[sig]}">50</span>
        <div class="hope-bar">
          <div class="hope-bar-fill" id="hopeBar_${sig}" style="width:50%;background:${HOPE_COLORS[sig]}"></div>
        </div>`;
      hopeGrid.appendChild(item);
    }
  }

  function updateHopeValues(hope) {
    for (const sig of ['KI', 'KT', 'CT']) {
      const v = hope[sig] != null ? hope[sig] : 0.5;
      const pct = (v * 100).toFixed(0);
      const score = $(`hopeScore_${sig}`);
      const bar = $(`hopeBar_${sig}`);
      if (score) score.textContent = pct;
      if (bar) bar.style.width = `${pct}%`;
    }
  }

  // ── Mastery Bars ───────────────────────────────────────────────
  function updateMasteryBars(conceptStates) {
    masteryList.innerHTML = '';
    const entries = Object.entries(conceptStates).sort((a, b) => {
      const ma = a[1].mastery ?? 0.3;
      const mb = b[1].mastery ?? 0.3;
      return ma - mb;
    });

    if (entries.length === 0) {
      masteryList.innerHTML = '<div style="color:var(--text-muted);font-size:0.75rem;">No concepts tracked yet</div>';
      return;
    }

    for (const [id, cs] of entries) {
      const m = cs.mastery ?? 0.3;
      const pct = (m * 100).toFixed(0);
      const colorClass = m < 0.35 ? 'mastery-low' : m < 0.65 ? 'mastery-mid' : 'mastery-high';
      const hasMisc = (cs.misconceptions || []).length > 0;

      const item = document.createElement('div');
      item.className = 'mastery-item';
      item.innerHTML = `
        <div class="mastery-header">
          <span class="mastery-name" title="${id}">${formatConceptId(id)}${hasMisc ? ' <span class="misconception-dot active" title="Active misconception"></span>' : ''}</span>
          <span class="mastery-value">${pct}%</span>
        </div>
        <div class="mastery-bar">
          <div class="mastery-bar-fill ${colorClass}" style="width:${pct}%"></div>
        </div>`;
      masteryList.appendChild(item);
    }
  }

  // ── Session Card ───────────────────────────────────────────────
  function updateSessionCard(session) {
    const rows = [];
    const row = (label, value, cls = '') =>
      `<div class="info-row"><span class="info-label">${label}</span><span class="info-value ${cls}">${escapeHtml(String(value || '—'))}</span></div>`;

    rows.push(row('Current Concept', formatConceptId(session.current_concept), 'active'));
    rows.push(row('Context Turns', (session.context || []).length));
    rows.push(row('Items Served', (session.served_items || []).length));
    rows.push(row('Bridges Served', (session.bridges_served || []).length));

    if (session.pending_check) {
      rows.push(row('Pending Check', session.pending_check.kind + ': ' +
        formatConceptId(session.pending_check.concept_id), 'pending'));
    }
    if (session.pending_hope) {
      rows.push(row('Pending HOPE', session.pending_hope.signal, 'pending'));
    }
    rows.push(row('Last Action', session.last_action));

    sessionInfo.innerHTML = rows.join('');
  }

  // ── Signals ────────────────────────────────────────────────────
  function updateSignals(signals) {
    signalTags.innerHTML = '';
    if (!signals || signals.length === 0) {
      signalTags.innerHTML = '<span style="color:var(--text-muted);font-size:0.72rem;">none</span>';
      return;
    }
    for (const s of signals) {
      const tag = document.createElement('span');
      tag.className = 'signal-tag';
      tag.textContent = s;
      signalTags.appendChild(tag);
    }
  }

  // ── Action History ─────────────────────────────────────────────
  function logAction(action) {
    actionLog.push(action);
    if (actionLog.length > 20) actionLog.shift();
    actionHistory.innerHTML = '';
    for (const a of actionLog) {
      const pill = document.createElement('span');
      pill.className = 'action-pill';
      const ac = ACTION_COLORS[a];
      if (ac) {
        const style = getComputedStyle(document.documentElement);
        pill.style.borderColor = `var(--${ac === 'action-explain' ? 'blue' : ac === 'action-quiz' ? 'emerald' : ac === 'action-misconception' ? 'coral' : ac === 'action-socratic' ? 'violet' : ac === 'action-encourage' ? 'amber' : ac === 'action-transfer' ? 'teal' : ac === 'action-reflect' ? 'rose' : 'text-muted'})`;
      }
      pill.textContent = a.replace(/_/g, ' ');
      actionHistory.appendChild(pill);
    }
  }

  // ── Reset Session ──────────────────────────────────────────────
  async function resetSession() {
    if (!confirm('Reset session? (Mastery scores are preserved.)')) return;
    try {
      await fetch(`${API}/api/reset-session`, { method: 'POST' });
      chatMessages.innerHTML = '';
      if (welcomeMsg) {
        const w = document.createElement('div');
        w.className = 'welcome-message';
        w.id = 'welcomeMessage';
        w.innerHTML = `
          <div class="welcome-icon">🧠</div>
          <div class="welcome-title">Session Reset</div>
          <div class="welcome-desc">Context cleared. Mastery scores preserved. Start a new conversation.</div>`;
        chatMessages.appendChild(w);
      }
      actionLog = [];
      actionHistory.innerHTML = '<span style="color:var(--text-muted);font-size:0.72rem;">—</span>';
      signalTags.innerHTML = '<span style="color:var(--text-muted);font-size:0.72rem;">No turns yet</span>';
      sessionStart = Date.now();
      loadState();
    } catch (e) {
      alert('Reset failed: ' + e.message);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────
  function scrollChat() {
    requestAnimationFrame(() => {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    });
  }

  function formatConceptId(id) {
    if (!id) return '—';
    // "jemh104__quadratic_equation_definition" → "Quadratic Equation Definition"
    const parts = id.replace(/^(jemh\d+|grade\d+)__?/i, '').replace(/::/g, ' › ').split('_');
    return parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Boot ───────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();

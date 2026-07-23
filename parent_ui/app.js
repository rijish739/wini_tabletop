/* Wini Parent Dashboard — fetch /api/progress and render it in parent language. */

const REFRESH_MS = 30000;
let lastGood = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function timeAgo(iso) {
  if (!iso) return "";
  const t = new Date(iso);
  if (isNaN(t)) return iso;
  const s = (Date.now() - t.getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} hours ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function niceDate(d) {
  const t = new Date(d + "T00:00:00");
  if (isNaN(t)) return d;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - t) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return t.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function ring(pct, color) {
  const r = 30, c = 2 * Math.PI * r, off = c * (1 - pct / 100);
  return `<div class="ring"><svg width="74" height="74" viewBox="0 0 74 74">
    <circle class="track" cx="37" cy="37" r="${r}" fill="none" stroke-width="8"/>
    <circle class="bar" cx="37" cy="37" r="${r}" fill="none" stroke-width="8"
      stroke="${color || "var(--teal)"}" stroke-dasharray="${c}" stroke-dashoffset="${off}"/>
    <text x="37" y="42" text-anchor="middle" font-size="16">${pct}%</text>
  </svg></div>`;
}

const statusChip = { strong: "good", growing: "neutral", started: "plain", learning: "warn", help: "bad" };
const barClass = (t) => t.status === "help" ? "bad" : (t.status === "learning" || t.struggling) ? "warn" : "";

/* ---------------- render sections ---------------- */

function renderAlerts(alerts) {
  const el = $("alerts");
  if (!alerts || !alerts.length) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  el.innerHTML = `<div class="alert-banner">
    <h3>&#9888; Wellbeing alert — please talk with your child</h3>
    <p style="margin:0 0 8px;font-size:.85rem">Wini flagged something your child said and responded with a caring, scripted message. This is shown to you because a caring adult should follow up.</p>
    ${alerts.slice(0, 5).map(a => `<div class="alert-row">&ldquo;${esc(a.message)}&rdquo;<span class="when">${esc(timeAgo(a.ts))}</span></div>`).join("")}
  </div>`;
}

function renderGlance(d) {
  const s = d.summary, m = s.mood, cur = d.learner.current_topic;
  $("glance").innerHTML = `
    <div class="gcard">${ring(s.overall_mastery_pct)}
      <div><div class="glabel">Overall progress</div>
      <div class="sub">across ${s.topics_total} topic${s.topics_total === 1 ? "" : "s"} started</div></div>
    </div>
    <div class="gcard">
      <div><div class="glabel">How they're doing</div>
      <div class="big"><span class="chip ${m.tone}">${esc(m.word)}</span></div>
      <div class="sub">${esc(m.note)}</div></div>
    </div>
    <div class="gcard">
      <div><div class="glabel">Now learning</div>
      <div class="big" style="font-size:1.05rem">${esc(cur.name || "—")}</div>
      <div class="sub">${esc(cur.chapter || "")}</div></div>
    </div>
    <div class="gcard">
      <div><div class="glabel">Keep an eye on</div>
      <div class="big" style="font-size:1.05rem">${s.topics_need_help} topic${s.topics_need_help === 1 ? "" : "s"}</div>
      <div class="sub">${s.foundations_to_revisit ? `+ ${s.foundations_to_revisit} Class 9 basics to revisit` : "foundations look okay"}</div></div>
    </div>`;
}

function topicCard(t) {
  const flags = (t.flags || []).map(f =>
    `<span class="chip ${f.tone}">${esc(f.label)}</span>`).join("");
  const struggle = t.struggling ? `<span class="chip bad">Finding this hard right now</span>` : "";
  // Part 12: a quiz-gate badge once a TEST has been taken on this topic.
  const tv = t.test || {};
  let gate = "";
  if (tv.tests_taken) {
    const tone = tv.mastery_gate === "passed" ? "good" : "warn";
    const lt = tv.last_test;
    const detail = lt ? ` &middot; ${lt.score_pct}%` : "";
    gate = `<span class="chip ${tone}">${esc(tv.label)}${detail}</span>`;
  }
  return `<div class="tcard">
    <div class="row1"><div><h3>${esc(t.name)}</h3>
      <div class="chapter">${esc(t.chapter)}</div></div>
      <span class="chip ${statusChip[t.status] || "plain"}">${esc(t.label)}</span></div>
    <div class="bar-track"><div class="bar-fill ${barClass(t)}" style="width:${t.mastery_pct}%"></div></div>
    <div class="pct">${t.measured
      ? `${t.mastery_pct}% solid &middot; practised ${esc(timeAgo(t.last_practiced) || "recently")}`
      : `<span class="est">just started — no check questions answered yet</span>`}</div>
    ${flags || struggle || gate ? `<div class="flags">${gate}${struggle}${flags}</div>` : ""}
  </div>`;
}

function renderTopics(d) {
  $("topics").innerHTML = d.topics.length
    ? d.topics.map(topicCard).join("")
    : `<div class="empty neutral">No topics started yet — progress will appear after the first session.</div>`;
  const weak = (d.foundations || []).filter(f => f.mastery_pct < 60);
  $("foundations").innerHTML = weak.length
    ? weak.map(topicCard).join("")
    : `<div class="empty">No Class 9 gaps found so far — the basics are holding up. &#10003;</div>`;
}

function renderQuizzes(d) {
  const panel = $("quizzes-panel"), box = $("quizzes");
  const qs = d.quizzes || [];
  if (!qs.length) {
    box.innerHTML = `<div class="empty neutral">No quizzes taken yet — Wini offers a quick check once a topic has been practised.</div>`;
    return;
  }
  const s = d.summary || {};
  const head = `<div class="quiz-summary"><span class="chip good">${s.quizzes_passed || 0} passed</span>
    <span class="muted">of ${s.quizzes_taken || 0} quiz${(s.quizzes_taken === 1) ? "" : "zes"} taken</span></div>`;
  box.innerHTML = head + qs.slice(0, 12).map(q => `
    <div class="quiz-row">
      <div><h3>${esc(q.concept_name)}</h3>
        <div class="concept">${esc(q.chapter)} &middot; ${esc(niceDate(q.date))}</div></div>
      <div class="quiz-score">
        <span class="chip ${q.passed ? "good" : "warn"}">${q.passed ? "Passed" : "Keep going"}</span>
        <span class="quiz-pct">${q.score_pct}%</span>
        <span class="muted">${esc(q.correct_of)}</span>
      </div>
    </div>`).join("");
}

function renderTrouble(d) {
  const items = [];
  for (const t of d.trouble_spots || []) {
    items.push(`<div class="mixup">
      <div class="row1"><div><h3>${esc(t.title)}</h3>
        ${t.concept_name ? `<div class="concept">in ${esc(t.concept_name)}</div>` : ""}</div>
        <span class="chip ${t.tone}">${esc(t.label)}</span></div>
      ${t.what_happened ? `<div class="detail"><b>The mix-up:</b> ${esc(t.what_happened)}</div>` : ""}
      ${t.correct_idea ? `<div class="detail"><b>The right idea:</b> ${esc(t.correct_idea)}</div>` : ""}
    </div>`);
  }
  for (const s of d.suspected_mixups || []) {
    items.push(`<div class="mixup">
      <div class="row1"><div><h3>Possible mix-up in ${esc(s.concept_name)}</h3>
        <div class="concept">${esc(s.chapter)}</div></div>
        <span class="chip neutral">Wini is checking</span></div>
      <div class="detail">Wini noticed signs of a misunderstanding here and will ask a gentle check question soon.</div>
    </div>`);
  }
  $("trouble").innerHTML = items.length ? items.join("")
    : `<div class="empty">No mix-ups spotted right now. &#10003;</div>`;
}

function renderSkills(d) {
  const chipTone = { strong: "good", ontrack: "neutral", developing: "warn", unmeasured: "plain" };
  $("skills").innerHTML = (d.thinking_skills || []).map(sk => `
    <div class="skill">
      <div class="row1"><h3>${esc(sk.label)}</h3>
        <span class="chip ${chipTone[sk.level] || "plain"}">${esc(sk.level_label)}</span>
      </div>
      <p>${esc(sk.help)}</p>
      <div class="bar-track"><div class="bar-fill ${sk.level === "developing" ? "warn" : ""}"
        style="width:${sk.measured ? sk.pct : 0}%"></div></div>
    </div>`).join("");
}

function renderActivity(d) {
  const days = d.recent_activity || [];
  $("activity").innerHTML = days.length ? days.map(day => {
    const checks = [];
    if (day.checks_passed) checks.push(`<span class="ok">${day.checks_passed} check${day.checks_passed > 1 ? "s" : ""} right</span>`);
    if (day.checks_partial) checks.push(`${day.checks_partial} partly right`);
    if (day.checks_missed) checks.push(`<span class="miss">${day.checks_missed} to retry</span>`);
    if (day.skill_checks) checks.push(`${day.skill_checks} thinking challenge${day.skill_checks > 1 ? "s" : ""}`);
    return `<div class="day">
      <div class="date">${esc(niceDate(day.date))}</div>
      <div class="facts">${day.interactions} interaction${day.interactions === 1 ? "" : "s"}${day.topics.length ? " &middot; " + esc(day.topics.slice(0, 3).join(", ")) : ""}</div>
      <div class="checks">${checks.join(" &middot; ") || "practice only"}</div>
    </div>`;
  }).join("") : `<div class="empty neutral">No sessions recorded yet.</div>`;
}

function render(d) {
  const who = d.learner || {};
  $("learner-line").textContent =
    `${who.name || "Student"} · last active ${timeAgo(who.last_active) || "—"}`;
  renderAlerts(d.alerts);
  renderGlance(d);
  renderTopics(d);
  renderQuizzes(d);
  renderTrouble(d);
  renderSkills(d);
  renderActivity(d);
  $("footer").textContent =
    `Updates every ${REFRESH_MS / 1000}s · report generated ${timeAgo(d.generated_at)} · Wini learns about your child only from their study sessions.`;
}

async function refresh() {
  try {
    const r = await fetch("/api/progress", { cache: "no-store" });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || r.statusText);
    lastGood = d;
    render(d);
    setConn(d);
  } catch (e) {
    setConn(null);
    if (lastGood) render(lastGood);
  }
}

function setConn(d) {
  const dot = $("conn-dot"), txt = $("conn-text");
  if (!d) {
    dot.className = "dot bad";
    txt.textContent = "Wini not reachable — no saved data yet";
  } else if (d.stale) {
    dot.className = "dot";
    txt.textContent = `Wini is off — showing data saved ${timeAgo(d.fetched_at) || "earlier"}`;
  } else {
    dot.className = "dot ok";
    txt.textContent = "up to date from Wini";
  }
}

refresh();
setInterval(refresh, REFRESH_MS);

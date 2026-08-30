const state = { prep:null, prepWeek:null, tasks: [], goals: [], commitments: [], memories: [], conversation: [], pendingProposal:null, voiceTarget:"report", socket: null, focus: null, history: [], timerHandle: null, recognition: null, recorder: null, mediaStream: null, listening: false, reportSource: "text", speaking: false, voiceStatus: {provider:"browser",transcription_enabled:false,synthesis_enabled:false}, speechAudio:null, speechUtterance:null, speechAbort:null, speechTimer:null, lastMiraResponse:null, portraitCue:"neutral", portraitRequest:0 };
const $ = (id) => document.getElementById(id);
const portraitAssets = {
  neutral: "/static/assets/avatar/mira-neutral.png",
  attentive: "/static/assets/avatar/mira-listening.png",
  focused: "/static/assets/avatar/mira-focused.png",
  raised_eyebrow: "/static/assets/avatar/mira-skeptical.png",
  soft_smile: "/static/assets/avatar/mira-warm-smile.png",
  pleased: "/static/assets/avatar/mira-pleased.png"
};

function preloadPortraits() {
  Object.values(portraitAssets).forEach(source => { const image = new Image(); image.src = source; });
}

function setPortrait(cue="neutral", stateLabel=null) {
  if (stateLabel) $("avatar").dataset.state = stateLabel;
  const normalizedCue = portraitAssets[cue] ? cue : "neutral";
  const source = portraitAssets[normalizedCue];
  if (normalizedCue === state.portraitCue) return;
  const request = ++state.portraitRequest;
  const layers = [...document.querySelectorAll(".portrait-layer")];
  const current = layers.find(layer => layer.classList.contains("active"));
  const next = layers.find(layer => layer !== current);
  const reveal = () => {
    if (request !== state.portraitRequest) return;
    current.classList.remove("active"); next.classList.add("active");
    state.portraitCue = normalizedCue;
  };
  next.src = source;
  if (next.complete) reveal(); else next.addEventListener("load", reveal, {once:true});
}

function portraitCueFor(response) {
  return {CHALLENGING:"raised_eyebrow",CELEBRATING:"pleased",FOCUSING:"focused",CURIOUS:"attentive"}[response.state]
    || response.expression.primary || "neutral";
}

function toast(message) {
  const el = $("toast"); el.textContent = message; el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

function renderPrep() {
  if (!state.prep) return;
  const selected = state.prep.weeks.find(w => w.number === state.prepWeek) || state.prep.weeks[0];
  state.prepWeek = selected.number;
  $("prep-week").innerHTML = state.prep.weeks.map(w => `<option value="${w.number}">Week ${w.number}</option>`).join("");
  $("prep-week").value = String(selected.number);
  $("prep-theme").textContent = selected.theme;
  $("prep-range").textContent = `${new Date(selected.starts_on+"T00:00:00").toLocaleDateString(undefined,{month:"short",day:"numeric"})} – ${new Date(selected.ends_on+"T00:00:00").toLocaleDateString(undefined,{month:"short",day:"numeric"})}`;
  const done = state.prep.completed_minutes / 60;
  $("prep-hours").textContent = `${done.toFixed(done % 1 ? 1 : 0)} / 240 HOURS`;
  $("prep-progress-bar").style.width = `${Math.min(100, done / 240 * 100)}%`;
  $("prep-items").innerHTML = selected.items.map(item => `
    <div class="prep-item ${item.status}">
      <span class="prep-track ${item.track}">${item.track}</span>
      <div><strong>${escapeHtml(item.title)}</strong><small>${Math.round(item.planned_minutes/60*10)/10}h · ${escapeHtml(item.description)}</small></div>
      <span class="prep-status">${item.status.replace("_"," ")}</span>
      <div class="prep-actions">
        ${item.task_id ? '<span class="queued">Queued</span>' : `<button class="quiet queue-prep" data-id="${item.id}">Queue</button>`}
        <button class="${item.status === "completed" ? "quiet" : "primary"} toggle-prep" data-id="${item.id}" data-status="${item.status === "completed" ? "planned" : "completed"}">${item.status === "completed" ? "Reopen" : "Complete"}</button>
      </div>
    </div>`).join("");
  $("prep-checkpoint").hidden = !selected.checkpoint;
  $("prep-checkpoint").textContent = selected.checkpoint ? `◆ ${selected.checkpoint}` : "";
  document.querySelectorAll(".toggle-prep").forEach(b => b.addEventListener("click", () => updatePrep(b.dataset.id,b.dataset.status)));
  document.querySelectorAll(".queue-prep").forEach(b => b.addEventListener("click", () => queuePrep(b.dataset.id)));
}
async function loadPrep() {
  const response = await fetch("/api/prep");
  if (!response.ok) return toast("Preparation plan could not be loaded.");
  state.prep = await response.json();
  state.prepWeek = state.prep.current_week;
  renderPrep();
}
async function updatePrep(id,status) {
  const response = await fetch(`/api/prep/items/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})});
  if (!response.ok) return toast("That preparation block could not be updated.");
  await loadPrep(); toast(status === "completed" ? "Block completed." : "Block reopened.");
}
async function queuePrep(id) {
  const response = await fetch(`/api/prep/items/${id}/queue`,{method:"POST"});
  if (!response.ok) return toast("That block could not be queued.");
  const result = await response.json();
  if (!state.tasks.some(t => t.id === result.task.id)) state.tasks.push(result.task);
  renderTasks(); await loadPrep(); toast("Added to today's execution queue.");
}

function renderTasks() {
  const sorted = [...state.tasks].sort((a,b) => a.priority - b.priority);
  const completed = sorted.filter(task => task.status === "completed").length;
  $("today-completed").textContent = completed;
  $("today-total").textContent = sorted.length;
  $("today-progress").style.width = `${sorted.length ? completed / sorted.length * 100 : 0}%`;
  $("task-count").textContent = `${sorted.length} TASK${sorted.length === 1 ? "" : "S"}`;
  $("task-list").innerHTML = sorted.map(task => `
    <div class="task ${task.status === "completed" ? "completed" : ""}">
      <span class="dot"></span>
      <div><div class="title">${escapeHtml(task.title)}</div><small>P${task.priority} � ${task.status.replace("_", " ")}</small></div>
      <span class="percent">${Math.round(task.progress * 100)}%</span>
      <span class="task-actions"><button type="button" class="quiet edit-task" data-id="${task.id}">Edit</button><button type="button" class="danger archive-task" data-id="${task.id}">Archive</button></span>
    </div>`).join("") || `<p class="muted">Your queue is empty. Add one concrete task.</p>`;
  const options = sorted.map(t => `<option value="${t.id}">${escapeHtml(t.title)}</option>`).join("");
  const selectedReport = $("report-task").value, selectedFocus = $("focus-task").value, selectedConversation = $("conversation-task").value;
  $("report-task").innerHTML = options; $("focus-task").innerHTML = options;
  $("conversation-task").innerHTML = `<option value="">No task context</option>${options}`;
  if (sorted.some(t => t.id === selectedReport)) $("report-task").value = selectedReport;
  if (sorted.some(t => t.id === selectedFocus)) $("focus-task").value = selectedFocus;
  if (sorted.some(t => t.id === selectedConversation)) $("conversation-task").value = selectedConversation;
  $("commitment-task").innerHTML = `<option value="">No linked task</option>${options}`;
  document.querySelectorAll(".edit-task").forEach(button => button.addEventListener("click", editTask));
  document.querySelectorAll(".archive-task").forEach(button => button.addEventListener("click", archiveTask));
}

function escapeHtml(value) {
  const node = document.createElement("div"); node.textContent = value; return node.innerHTML;
}

function applySnapshot(snapshot) {
  state.tasks = snapshot.tasks; state.goals = snapshot.goals || []; state.commitments = snapshot.commitments || []; state.memories = snapshot.memories || []; state.conversation = snapshot.conversation || []; state.pendingProposal = snapshot.pending_proposal || null; state.focus = snapshot.active_focus_session; state.history = snapshot.focus_history || []; applyRhythm(snapshot.daily_rhythm); renderTasks(); renderGoals(); renderCommitments(); renderMemories(); renderConversation(); renderHistory();
  if (state.focus) startTimer(state.focus); else resetTimer();
}

function applyRhythm(rhythm) {
  rhythm = rhythm || {enabled:false,morning_time:"08:30",midday_time:"13:00",evening_time:"20:30"};
  $("rhythm-enabled").checked = rhythm.enabled;
  $("rhythm-morning").value = rhythm.morning_time;
  $("rhythm-midday").value = rhythm.midday_time;
  $("rhythm-evening").value = rhythm.evening_time;
}

function renderConversation() {
  const list = $("conversation-list");
  const messages = state.conversation.map(message => `
    <div class="conversation-message ${message.role}">
      <span>${message.role === "mira" ? "Mira" : "You"}</span>
      <p>${escapeHtml(message.content)}</p>
    </div>`).join("");
  const proposal = state.pendingProposal?.status === "pending" ? `
    <div class="proposal-card">
      <strong>Choose what Mira should do</strong>
      <div>${state.pendingProposal.options.map(option => `<button type="button" class="proposal-option" data-proposal="${state.pendingProposal.id}" data-option="${option.id}"><b>${option.id.toUpperCase()}</b>${escapeHtml(option.label)}</button>`).join("")}</div>
      <small>You can also say "yes" or "option A".</small>
    </div>` : "";
  list.innerHTML = messages || proposal ? `${messages}${proposal}` : `<p class="muted">No follow-up yet. Ask Mira what to do next.</p>`;
  document.querySelectorAll(".proposal-option").forEach(button => button.addEventListener("click", () => {
    setThinking(true);
    sendClientEvent("conversation.proposal.selected", {proposal_id:button.dataset.proposal, option_id:button.dataset.option, source:"text"});
  }));
  list.scrollTop = list.scrollHeight;
}

function appendConversationMessage(message) {
  if (!state.conversation.some(existing => existing.id === message.id)) state.conversation.push(message);
}

function renderGoals() {
  const active = state.goals.filter(goal => goal.status === "active"); $("goal-count").textContent = `${active.length} ACTIVE`;
  $("goal-list").innerHTML = state.goals.map(goal => `<div class="goal ${goal.status}"><div><strong>${escapeHtml(goal.title)}</strong><br><small>${goal.status}</small></div><span class="goal-actions">${goal.status === "active" ? `<button class="quiet pause-goal" data-id="${goal.id}">Pause</button><button class="primary achieve-goal" data-id="${goal.id}">Achieved</button>` : `<button class="quiet activate-goal" data-id="${goal.id}">Activate</button>`}</span></div>`).join("") || `<p class="muted">No goals yet. Define the outcome behind the work.</p>`;
  [["pause-goal","paused"],["achieve-goal","achieved"],["activate-goal","active"]].forEach(([name,status]) => document.querySelectorAll(`.${name}`).forEach(button => button.addEventListener("click", () => setGoalStatus(button.dataset.id, status))));
}

function renderCommitments() {
  const open = state.commitments.filter(item => item.kept === null); $("commitment-count").textContent = `${open.length} OPEN`;
  $("commitment-list").innerHTML = state.commitments.map(item => { const task = state.tasks.find(t => t.id === item.task_id); const result = item.kept === null ? "open" : item.kept ? "kept" : "missed"; return `<div class="commitment ${item.kept === null ? "" : "resolved"}"><div><strong>${escapeHtml(item.statement)}</strong><br><small>${task ? escapeHtml(task.title) + " � " : ""}${item.due_at ? new Date(item.due_at).toLocaleString() + " � " : ""}${result}</small></div>${item.kept === null ? `<span class="commitment-actions"><button class="primary keep-commitment" data-id="${item.id}">Kept</button><button class="danger miss-commitment" data-id="${item.id}">Missed</button></span>` : ""}</div>`; }).join("") || `<p class="muted">No open promises. Commit only when you mean it.</p>`;
  document.querySelectorAll(".keep-commitment").forEach(button => button.addEventListener("click", () => resolveCommitment(button.dataset.id, "kept")));
  document.querySelectorAll(".miss-commitment").forEach(button => button.addEventListener("click", () => resolveCommitment(button.dataset.id, "missed")));
}

function renderMemories() {
  $("memory-count").textContent = `${state.memories.length} MEMORIES`;
  $("memory-list").innerHTML = state.memories.map(memory => `<div class="memory"><div><strong>${escapeHtml(memory.content)}</strong><br><small>${memory.kind} � source ${memory.source} � confidence ${Math.round(memory.confidence*100)}% � importance ${Math.round(memory.importance*100)}%${memory.expires_at ? ` � expires ${new Date(memory.expires_at).toLocaleDateString()}` : ""}</small></div><span class="memory-actions"><button class="quiet edit-memory" data-id="${memory.id}">Correct</button><button class="danger delete-memory" data-id="${memory.id}">Delete</button></span></div>`).join("") || `<p class="muted">Nothing stored. Mira will not invent durable memories.</p>`;
  document.querySelectorAll(".edit-memory").forEach(button => button.addEventListener("click", () => editMemory(button.dataset.id)));
  document.querySelectorAll(".delete-memory").forEach(button => button.addEventListener("click", () => deleteMemory(button.dataset.id)));
}

async function editMemory(id) { const memory = state.memories.find(item => item.id === id); const content = prompt("Correct this memory", memory.content); if (content === null) return; const response = await fetch(`/api/memories/${id}`, {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({content})}); if (!response.ok) return toast("Memory could not be corrected."); Object.assign(memory, await response.json()); renderMemories(); }
async function deleteMemory(id) { if (!confirm("Delete this memory permanently?")) return; const response = await fetch(`/api/memories/${id}`, {method:"DELETE"}); if (!response.ok) return toast("Memory could not be deleted."); state.memories = state.memories.filter(item => item.id !== id); renderMemories(); }

async function setGoalStatus(id, status) { const response = await fetch(`/api/goals/${id}/${status}`, {method:"POST"}); if (!response.ok) return toast("Goal could not be updated."); const goal = await response.json(); Object.assign(state.goals.find(item => item.id === id), goal); renderGoals(); }
async function resolveCommitment(id, result) { const response = await fetch(`/api/commitments/${id}/${result}`, {method:"POST"}); if (!response.ok) return toast("Commitment could not be updated."); const item = await response.json(); Object.assign(state.commitments.find(existing => existing.id === id), item); renderCommitments(); }

function renderHistory() {
  $("focus-history").innerHTML = state.history.slice(0, 5).map(item => {
    const task = state.tasks.find(t => t.id === item.task_id);
    return `<div class="history-item"><strong>${escapeHtml(task?.title || "Archived task")}</strong><span class="${item.status}">${item.status} � ${item.planned_minutes}m</span></div>`;
  }).join("") || `<p class="muted">No sessions yet.</p>`;
}

function applyMira(response) {
  state.lastMiraResponse = response;
  $("mira-speech").textContent = response.speech;
  $("mira-state").textContent = response.state;
  $("mira-tone").textContent = `${response.tone} � intensity ${Math.round(response.tone_intensity * 100)}% � ${response.expression.primary.replaceAll("_", " ")}`;
  $("avatar").dataset.state = response.state;
  setPortrait(portraitCueFor(response), response.state);
  setThinking(false);
  response.ui_actions.forEach(action => {
    if (action.type === "update_task") {
      const task = state.tasks.find(t => t.id === action.task_id);
      if (task) { task.status = action.status; task.progress = action.progress; }
    }
    if (action.type === "start_focus_mode") startTimer({ id: action.focus_session_id, task_id: action.task_id, planned_minutes: action.duration_minutes, started_at: new Date().toISOString(), status: "active" });
  });
  renderTasks();
  if ($("auto-speak").checked) speakMira(response);
}

function setThinking(thinking) {
  const button = $("report-submit");
  button.disabled = thinking;
  button.textContent = thinking ? "Mira is thinking." : "Report to Mira";
  const conversationButton = $("conversation-submit");
  conversationButton.disabled = thinking;
  conversationButton.textContent = thinking ? "Mira is thinking." : "Send";
  if (thinking) {
    $("mira-state").textContent = "THINKING";
    $("mira-tone").textContent = "considering the update";
    $("mira-speech").textContent = ".";
    $("avatar").dataset.state = "THINKING";
    setPortrait("focused", "THINKING");
  }
}

function startTimer(focus) {
  state.focus = focus; clearInterval(state.timerHandle);
  document.body.classList.toggle("focus-active", focus.status === "active");
  const task = state.tasks.find(t => t.id === focus.task_id);
  $("focus-title").textContent = task?.title || "Focused session"; $("focus-status").textContent = focus.status.toUpperCase();
  $("focus-controls").hidden = false; $("focus-toggle").textContent = focus.status === "paused" ? "Resume" : "Pause";
  const total = focus.planned_minutes * 60, started = new Date(focus.started_at).getTime();
  const tick = () => {
    const clock = focus.status === "paused" && focus.paused_at ? new Date(focus.paused_at).getTime() : Date.now();
    const elapsed = Math.max(0, Math.floor((clock - started) / 1000));
    const left = Math.max(0, total - elapsed), minutes = Math.floor(left / 60), seconds = left % 60;
    $("timer").textContent = `${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
    $("timer-progress").style.width = `${Math.min(100, elapsed / total * 100)}%`;
    $("focus-detail").textContent = `${focus.planned_minutes}-minute block � stay with the task`;
    if (!left) { clearInterval(state.timerHandle); $("focus-status").textContent = "DONE"; }
  }; tick(); if (focus.status === "active") state.timerHandle = setInterval(tick, 1000);
}

function resetTimer() {
  clearInterval(state.timerHandle); state.focus = null; document.body.classList.remove("focus-active"); $("focus-title").textContent = "No session active"; $("focus-status").textContent = "IDLE"; $("timer").textContent = "25:00"; $("timer-progress").style.width = "0"; $("focus-controls").hidden = true; $("focus-detail").textContent = "Complete a task and ask Mira to start the next focus block.";
}

async function editTask(event) {
  const task = state.tasks.find(item => item.id === event.currentTarget.dataset.id);
  const title = prompt("Task title", task.title); if (title === null) return;
  const priorityText = prompt("Priority (1-5)", String(task.priority)); if (priorityText === null) return;
  const response = await fetch(`/api/tasks/${task.id}`, { method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({title, priority:Number(priorityText)}) });
  if (!response.ok) return toast("That task could not be updated.");
  Object.assign(task, await response.json()); renderTasks(); toast("Task updated.");
}

async function archiveTask(event) {
  const task = state.tasks.find(item => item.id === event.currentTarget.dataset.id);
  if (!confirm(`Archive "${task.title}"?`)) return;
  const response = await fetch(`/api/tasks/${task.id}/archive`, {method:"POST"});
  if (!response.ok) return toast((await response.json()).detail || "That task could not be archived.");
  state.tasks = state.tasks.filter(item => item.id !== task.id); renderTasks(); toast("Task archived.");
}

async function transitionFocus(action) {
  if (!state.focus) return;
  const response = await fetch(`/api/focus/${state.focus.id}/${action}`, {method:"POST"});
  if (!response.ok) return toast((await response.json()).detail || "Focus Mode could not be updated.");
  const session = await response.json();
  state.history = [session, ...state.history.filter(item => item.id !== session.id)]; renderHistory();
  if (["completed","cancelled"].includes(session.status)) resetTimer(); else startTimer(session);
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws/session/dashboard`);
  state.socket.onopen = () => { $("connection-label").textContent = "Live"; document.querySelector(".connection").classList.add("online"); };
  state.socket.onclose = () => { $("connection-label").textContent = "Reconnecting"; document.querySelector(".connection").classList.remove("online"); setTimeout(connect, 1500); };
  state.socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    let acknowledgementStatus = "applied";
    try {
      if (message.type === "session.ready" || message.type === "session.snapshot") applySnapshot(message.payload);
      if (message.type === "mira.thinking") setThinking(true);
      if (message.type === "mira.response") applyMira(message.payload);
      if (message.type === "conversation.turn") {
        appendConversationMessage(message.payload.user_message);
        appendConversationMessage(message.payload.mira_message);
        state.pendingProposal = message.payload.proposal?.status === "pending" ? message.payload.proposal : null;
        renderConversation();
        applyMira(message.payload.response);
      }
      if (message.type === "error") { setThinking(false); toast(message.payload?.detail || "Mira could not process that update."); }
    } catch (error) {
      acknowledgementStatus = "failed";
      console.error("Could not apply Mira event", error);
    } finally {
      if (message.requires_ack) sendClientEvent("client.ack", {event_id:message.event_id, status:acknowledgementStatus}, message.event_id);
    }
  };
}

function clientEventId() {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `client-${id}`;
}

function sendClientEvent(type, payload={}, correlationId=null) {
  if (state.socket?.readyState !== WebSocket.OPEN) return false;
  state.socket.send(JSON.stringify({
    protocol_version:"0.1", event_id:clientEventId(), session_id:"dashboard",
    type, timestamp:new Date().toISOString(), correlation_id:correlationId, payload
  }));
  return true;
}

function sendVoiceEvent(type, transcript=null) {
  sendClientEvent(type, {transcript});
}

function clearSpeechTimer() {
  if (state.speechTimer) clearTimeout(state.speechTimer);
  state.speechTimer = null;
}

function restoreMiraPresentation(response=state.lastMiraResponse) {
  $("avatar").classList.remove("speaking", "voice-pending");
  if (!response) return;
  $("mira-state").textContent = response.state;
  setPortrait(portraitCueFor(response), response.state);
}

function beginSpeaking() {
  state.speaking = true;
  $("avatar").classList.remove("voice-pending");
  $("avatar").classList.add("speaking");
  $("stop-speaking").hidden = false;
  $("mira-state").textContent = "SPEAKING";
  sendVoiceEvent("mira.speech.started");
}

function finishSpeaking(response, completed=true) {
  state.speaking = false; state.speechAudio = null; state.speechUtterance = null; state.speechAbort = null;
  clearSpeechTimer(); $("stop-speaking").hidden = true;
  restoreMiraPresentation(response);
  if (completed) sendVoiceEvent("mira.speech.completed");
}

function interruptMira() {
  const browserSpeaking = "speechSynthesis" in window && speechSynthesis.speaking;
  if (!state.speaking && !browserSpeaking && !state.speechAbort && !state.speechTimer) return;
  clearSpeechTimer();
  state.speechAbort?.abort(); state.speechAbort = null;
  if (state.speechAudio) { const source = state.speechAudio.src; state.speechAudio.onplay = null; state.speechAudio.onended = null; state.speechAudio.onerror = null; state.speechAudio.pause(); state.speechAudio.currentTime = 0; state.speechAudio = null; if (source.startsWith("blob:")) URL.revokeObjectURL(source); }
  if (state.speechUtterance) { state.speechUtterance.onstart = null; state.speechUtterance.onend = null; state.speechUtterance.onerror = null; state.speechUtterance = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  state.speaking = false; $("stop-speaking").hidden = true; $("avatar").classList.remove("speaking", "voice-pending");
  sendVoiceEvent("mira.speech.interrupted"); $("mira-state").textContent = "INTERRUPTED"; setPortrait("attentive", "INTERRUPTED");
}

async function speakMira(response) {
  interruptMira();
  if (state.voiceStatus.synthesis_enabled) {
    const controller = new AbortController(); state.speechAbort = controller;
    $("avatar").classList.add("voice-pending"); $("stop-speaking").hidden = false; $("mira-state").textContent = "PREPARING VOICE";
    try {
      const result = await fetch("/api/voice/speak", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:response.speech}),signal:controller.signal});
      if (!result.ok) throw new Error("provider speech unavailable");
      const url = URL.createObjectURL(await result.blob()); const audio = new Audio(url); state.speechAudio = audio; state.speechAbort = null;
      audio.onplay = beginSpeaking;
      audio.onended = () => { finishSpeaking(response); URL.revokeObjectURL(url); };
      audio.onerror = () => { finishSpeaking(response, false); URL.revokeObjectURL(url); speakWithBrowser(response); };
      state.speechTimer = setTimeout(() => { state.speechTimer = null; audio.play().catch(() => audio.onerror()); }, response.pause_before_ms || 0); return;
    } catch (error) { state.speechAbort = null; $("avatar").classList.remove("voice-pending"); $("stop-speaking").hidden = true; if (error.name === "AbortError") return; }
  }
  speakWithBrowser(response);
}

function speakWithBrowser(response) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(response.speech);
  state.speechUtterance = utterance;
  const voices = speechSynthesis.getVoices();
  utterance.voice = voices.find(voice => voice.lang === "en-IN") || voices.find(voice => voice.lang.startsWith("en-GB")) || voices.find(voice => voice.lang.startsWith("en")) || null;
  utterance.rate = response.tone === "direct" ? .92 : .98; utterance.pitch = .96;
  utterance.onstart = beginSpeaking;
  utterance.onend = () => finishSpeaking(response);
  utterance.onerror = () => finishSpeaking(response, false);
  $("avatar").classList.add("voice-pending"); $("stop-speaking").hidden = false; $("mira-state").textContent = "PAUSING";
  state.speechTimer = setTimeout(() => { state.speechTimer = null; speechSynthesis.speak(utterance); }, response.pause_before_ms || 0);
}

function setupBrowserRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return false;
  const recognition = new Recognition(); state.recognition = recognition; recognition.continuous = false; recognition.interimResults = true; recognition.lang = "en-IN";
  let finalText = "";
  recognition.onstart = () => { interruptMira(); state.listening = true; finalText = ""; $("mic-button").classList.add("listening"); $("mic-label").textContent = "Listening. click to stop"; $("mira-state").textContent = "LISTENING"; setPortrait("attentive", "LISTENING"); sendVoiceEvent("user.speech.started"); };
  recognition.onresult = event => { let interim = ""; for (let i=event.resultIndex;i<event.results.length;i++) { const text=event.results[i][0].transcript; if (event.results[i].isFinal) finalText += text; else interim += text; } voiceField().value = `${finalText}${interim}`.trim(); state.reportSource = "voice"; };
  recognition.onerror = event => { if (event.error !== "no-speech" && event.error !== "aborted") toast(`Voice input: ${event.error}`); };
  recognition.onend = () => { const text = voiceField().value.trim(); setListening(false); if (text) { sendVoiceEvent("user.speech.completed", text); if (state.voiceTarget === "conversation") submitConversation("voice"); } };
  return true;
}

function voiceField() { return state.voiceTarget === "conversation" ? $("conversation-text") : $("report-text"); }

function setListening(active, label="Listening. click to stop") {
  state.listening = active; $("mic-button").classList.toggle("listening", active); $("mic-label").textContent = active ? label : "Start voice input";
  $("conversation-mic").classList.toggle("listening", active && state.voiceTarget === "conversation");
  $("conversation-mic").textContent = active && state.voiceTarget === "conversation" ? "�" : "?";
  if (active) { $("mira-state").textContent = "LISTENING"; setPortrait("attentive", "LISTENING"); sendVoiceEvent("user.speech.started"); }
}

async function startProviderRecording() {
  interruptMira();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio:true}); state.mediaStream = stream;
    const chunks = [];
    const preferredType = MediaRecorder.isTypeSupported?.("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    const recorder = preferredType ? new MediaRecorder(stream, {mimeType:preferredType}) : new MediaRecorder(stream); state.recorder = recorder;
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstart = () => setListening(true);
    recorder.onstop = async () => {
      setListening(false, "Transcribing."); $("mic-label").textContent = "Transcribing."; stream.getTracks().forEach(track => track.stop()); state.mediaStream = null;
      const blob = new Blob(chunks, {type:recorder.mimeType || "audio/webm"});
      try {
        const result = await fetch("/api/voice/transcribe", {method:"POST",headers:{"Content-Type":blob.type},body:blob});
        if (!result.ok) { const failure = await result.json().catch(() => ({})); throw new Error(failure.detail?.message || failure.detail || "Server transcription failed"); }
        const data = await result.json(); voiceField().value = data.text; state.reportSource = "voice"; sendVoiceEvent("user.speech.completed", data.text); if (state.voiceTarget === "conversation") submitConversation("voice");
      } catch (error) {
        state.voiceStatus.transcription_enabled = false;
        $("voice-support").textContent = "Browser voice � OpenAI transcription unavailable";
        toast(`${error.message}. Click again to use browser voice.`);
      }
      $("mic-label").textContent = "Start voice input"; state.recorder = null;
    };
    recorder.start(250);
  } catch { toast("Microphone permission is required for voice input."); setListening(false); }
}

function toggleVoiceInput(target="report") {
  if (state.listening) { if (state.recorder?.state === "recording") state.recorder.stop(); else state.recognition?.stop(); return; }
  state.voiceTarget = target;
  if (state.voiceStatus.transcription_enabled && navigator.mediaDevices && "MediaRecorder" in window) startProviderRecording();
  else if (state.recognition) state.recognition.start();
}

async function setupVoice() {
  try { const response = await fetch("/api/voice/status"); if (response.ok) state.voiceStatus = await response.json(); } catch {}
  const browserRecognition = setupBrowserRecognition();
  if (!state.voiceStatus.transcription_enabled && !browserRecognition) { $("mic-button").disabled = true; $("conversation-mic").disabled = true; $("mic-button").classList.add("unsupported"); $("voice-support").textContent = "Voice input is unavailable in this browser."; return; }
  $("voice-support").textContent = state.voiceStatus.provider === "openai" ? "OpenAI speech � browser fallback" : "Browser voice";
}

async function loadReasoningStatus() {
  const response = await fetch("/api/reasoning/status");
  if (!response.ok) return;
  const status = await response.json();
  $("reasoning-mode").textContent = `� ${status.configured_provider}`;
}

async function loadDesktopStatus() {
  try {
    const response = await fetch("/api/desktop/status");
    if (!response.ok) return;
    const status = await response.json();
    $("launch-startup").checked = status.startup_enabled;
    $("launch-startup").disabled = !status.windows;
    $("save-desktop-settings").disabled = !status.windows;
    $("tray-status").textContent = status.tray_available ? "TRAY READY" : "TRAY SETUP NEEDED";
  } catch {}
}

function updateClock() {
  const now = new Date();
  const hour = now.getHours();
  const salutation = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  $("greeting").textContent = `${salutation}, Piyush.`;
  $("today-date").textContent = now.toLocaleDateString(undefined, {weekday:"long", day:"numeric", month:"short"});
  $("today-time").textContent = now.toLocaleTimeString(undefined, {hour:"numeric", minute:"2-digit"});
}

$("progress-label").textContent = `${$("report-progress").value}%`;
$("report-progress").addEventListener("input", e => $("progress-label").textContent = `${e.target.value}%`);
$("task-form").addEventListener("submit", async e => {
  e.preventDefault();
  const response = await fetch("/api/tasks", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ title:$("task-title").value, priority:Number($("task-priority").value) }) });
  if (!response.ok) return toast("That task could not be added.");
  state.tasks.push(await response.json()); renderTasks(); e.target.reset(); toast("Task added.");
});
$("goal-form").addEventListener("submit", async e => { e.preventDefault(); const response = await fetch("/api/goals", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:$("goal-title").value})}); if (!response.ok) return toast("Goal could not be added."); state.goals.unshift(await response.json()); renderGoals(); e.target.reset(); });
$("commitment-form").addEventListener("submit", async e => { e.preventDefault(); const due = $("commitment-due").value; const response = await fetch("/api/commitments", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({statement:$("commitment-statement").value,task_id:$("commitment-task").value || null,due_at:due ? new Date(due).toISOString() : null})}); if (!response.ok) return toast("Commitment could not be added."); state.commitments.unshift(await response.json()); renderCommitments(); e.target.reset(); });
$("memory-form").addEventListener("submit", async e => { e.preventDefault(); const days = Number($("memory-expiry").value || 0); const expiresAt = days ? new Date(Date.now()+days*86400000).toISOString() : null; const response = await fetch("/api/memories", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:$("memory-kind").value,content:$("memory-content").value,importance:Number($("memory-importance").value)/100,confidence:1,expires_at:expiresAt})}); if (!response.ok) return toast("Memory could not be added."); state.memories.unshift(await response.json()); renderMemories(); e.target.reset(); });
$("report-form").addEventListener("submit", e => {
  e.preventDefault();
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return toast("Mira is reconnecting. Try again in a moment.");
  setThinking(true);
  const startFocus = $("start-focus").checked;
  sendClientEvent("progress.reported", {
    source:state.reportSource, task_id:$("report-task").value,
    transcript:$("report-text").value, progress:Number($("report-progress").value) / 100,
    start_focus:startFocus, focus_task_id:startFocus ? $("focus-task").value : null,
    focus_minutes:Number($("focus-minutes").value)
  });
  $("report-text").value = "";
  state.reportSource = "text";
});
function submitConversation(source="text") {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return toast("Mira is reconnecting. Try again in a moment.");
  const text = $("conversation-text").value.trim();
  if (!text) return;
  if ($("composer-mode").value === "report") {
    $("report-text").value = text;
    state.reportSource = source;
    document.querySelector(".report-panel").scrollIntoView({behavior:"smooth", block:"center"});
    $("report-text").focus();
    toast("Update ready-set the progress and report it.");
    return;
  }
  setThinking(true);
  sendClientEvent("conversation.message.sent", {
    source, text,
    task_id:$("conversation-task").value || null
  });
  $("conversation-text").value = "";
}
$("conversation-form").addEventListener("submit", e => {
  e.preventDefault();
  submitConversation("text");
});
$("focus-toggle").addEventListener("click", () => transitionFocus(state.focus?.status === "paused" ? "resume" : "pause"));
$("focus-complete").addEventListener("click", () => transitionFocus("complete"));
$("focus-cancel").addEventListener("click", () => transitionFocus("cancel"));
$("mic-button").addEventListener("click", () => toggleVoiceInput("report"));
$("conversation-mic").addEventListener("click", () => toggleVoiceInput("conversation"));
$("stop-speaking").addEventListener("click", interruptMira);
$("save-desktop-settings").addEventListener("click", async () => {
  const enabled = $("launch-startup").checked;
  const response = await fetch(`/api/desktop/startup/${enabled}`, {method:"POST"});
  if (!response.ok) return toast("Desktop settings could not be saved.");
  const status = await response.json();
  $("launch-startup").checked = status.startup_enabled;
  toast(status.startup_enabled ? "Mira will launch when you sign in." : "Windows startup disabled.");
});
$("save-rhythm").addEventListener("click", async () => {
  const response = await fetch("/api/daily-rhythm", {
    method:"PUT", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({enabled:$("rhythm-enabled").checked,morning_time:$("rhythm-morning").value,midday_time:$("rhythm-midday").value,evening_time:$("rhythm-evening").value})
  });
  if (!response.ok) return toast("Daily Rhythm could not be saved.");
  applyRhythm(await response.json());
  toast($("rhythm-enabled").checked ? "Daily Rhythm is on." : "Daily Rhythm is off.");
});
$("prep-week").addEventListener("change", e => { state.prepWeek=Number(e.target.value); renderPrep(); });
$("prep-current").addEventListener("click", () => { state.prepWeek=state.prep.current_week; renderPrep(); });

document.querySelectorAll("[data-rhythm-prompt]").forEach(button => button.addEventListener("click", () => {
  $("composer-mode").value = "talk";
  $("conversation-text").value = button.dataset.rhythmPrompt;
  document.querySelector(".mira-panel").scrollIntoView({behavior:"smooth", block:"center"});
  $("conversation-text").focus();
  toast("Check-in ready. Add anything you want, then send it.");
}));

preloadPortraits(); updateClock(); setInterval(updateClock, 30000); connect(); loadPrep(); loadReasoningStatus(); loadDesktopStatus(); setupVoice();


const state = { tasks: [], goals: [], commitments: [], socket: null, focus: null, history: [], timerHandle: null };
const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast"); el.textContent = message; el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

function renderTasks() {
  const sorted = [...state.tasks].sort((a,b) => a.priority - b.priority);
  $("task-count").textContent = `${sorted.length} TASK${sorted.length === 1 ? "" : "S"}`;
  $("task-list").innerHTML = sorted.map(task => `
    <div class="task ${task.status === "completed" ? "completed" : ""}">
      <span class="dot"></span>
      <div><div class="title">${escapeHtml(task.title)}</div><small>P${task.priority} · ${task.status.replace("_", " ")}</small></div>
      <span class="percent">${Math.round(task.progress * 100)}%</span>
      <span class="task-actions"><button type="button" class="quiet edit-task" data-id="${task.id}">Edit</button><button type="button" class="danger archive-task" data-id="${task.id}">Archive</button></span>
    </div>`).join("") || `<p class="muted">Your queue is empty. Add one concrete task.</p>`;
  const options = sorted.map(t => `<option value="${t.id}">${escapeHtml(t.title)}</option>`).join("");
  const selectedReport = $("report-task").value, selectedFocus = $("focus-task").value;
  $("report-task").innerHTML = options; $("focus-task").innerHTML = options;
  if (sorted.some(t => t.id === selectedReport)) $("report-task").value = selectedReport;
  if (sorted.some(t => t.id === selectedFocus)) $("focus-task").value = selectedFocus;
  $("commitment-task").innerHTML = `<option value="">No linked task</option>${options}`;
  document.querySelectorAll(".edit-task").forEach(button => button.addEventListener("click", editTask));
  document.querySelectorAll(".archive-task").forEach(button => button.addEventListener("click", archiveTask));
}

function escapeHtml(value) {
  const node = document.createElement("div"); node.textContent = value; return node.innerHTML;
}

function applySnapshot(snapshot) {
  state.tasks = snapshot.tasks; state.goals = snapshot.goals || []; state.commitments = snapshot.commitments || []; state.focus = snapshot.active_focus_session; state.history = snapshot.focus_history || []; renderTasks(); renderGoals(); renderCommitments(); renderHistory();
  if (state.focus) startTimer(state.focus); else resetTimer();
}

function renderGoals() {
  const active = state.goals.filter(goal => goal.status === "active"); $("goal-count").textContent = `${active.length} ACTIVE`;
  $("goal-list").innerHTML = state.goals.map(goal => `<div class="goal ${goal.status}"><div><strong>${escapeHtml(goal.title)}</strong><br><small>${goal.status}</small></div><span class="goal-actions">${goal.status === "active" ? `<button class="quiet pause-goal" data-id="${goal.id}">Pause</button><button class="primary achieve-goal" data-id="${goal.id}">Achieved</button>` : `<button class="quiet activate-goal" data-id="${goal.id}">Activate</button>`}</span></div>`).join("") || `<p class="muted">No goals yet. Define the outcome behind the work.</p>`;
  [["pause-goal","paused"],["achieve-goal","achieved"],["activate-goal","active"]].forEach(([name,status]) => document.querySelectorAll(`.${name}`).forEach(button => button.addEventListener("click", () => setGoalStatus(button.dataset.id, status))));
}

function renderCommitments() {
  const open = state.commitments.filter(item => item.kept === null); $("commitment-count").textContent = `${open.length} OPEN`;
  $("commitment-list").innerHTML = state.commitments.map(item => { const task = state.tasks.find(t => t.id === item.task_id); const result = item.kept === null ? "open" : item.kept ? "kept" : "missed"; return `<div class="commitment ${item.kept === null ? "" : "resolved"}"><div><strong>${escapeHtml(item.statement)}</strong><br><small>${task ? escapeHtml(task.title) + " · " : ""}${item.due_at ? new Date(item.due_at).toLocaleString() + " · " : ""}${result}</small></div>${item.kept === null ? `<span class="commitment-actions"><button class="primary keep-commitment" data-id="${item.id}">Kept</button><button class="danger miss-commitment" data-id="${item.id}">Missed</button></span>` : ""}</div>`; }).join("") || `<p class="muted">No open promises. Commit only when you mean it.</p>`;
  document.querySelectorAll(".keep-commitment").forEach(button => button.addEventListener("click", () => resolveCommitment(button.dataset.id, "kept")));
  document.querySelectorAll(".miss-commitment").forEach(button => button.addEventListener("click", () => resolveCommitment(button.dataset.id, "missed")));
}

async function setGoalStatus(id, status) { const response = await fetch(`/api/goals/${id}/${status}`, {method:"POST"}); if (!response.ok) return toast("Goal could not be updated."); const goal = await response.json(); Object.assign(state.goals.find(item => item.id === id), goal); renderGoals(); }
async function resolveCommitment(id, result) { const response = await fetch(`/api/commitments/${id}/${result}`, {method:"POST"}); if (!response.ok) return toast("Commitment could not be updated."); const item = await response.json(); Object.assign(state.commitments.find(existing => existing.id === id), item); renderCommitments(); }

function renderHistory() {
  $("focus-history").innerHTML = state.history.slice(0, 5).map(item => {
    const task = state.tasks.find(t => t.id === item.task_id);
    return `<div class="history-item"><strong>${escapeHtml(task?.title || "Archived task")}</strong><span class="${item.status}">${item.status} · ${item.planned_minutes}m</span></div>`;
  }).join("") || `<p class="muted">No sessions yet.</p>`;
}

function applyMira(response) {
  $("mira-speech").textContent = response.speech;
  $("mira-state").textContent = response.state;
  $("mira-tone").textContent = `${response.tone} · intensity ${Math.round(response.tone_intensity * 100)}% · ${response.expression.primary.replaceAll("_", " ")}`;
  $("avatar").dataset.state = response.state;
  response.ui_actions.forEach(action => {
    if (action.type === "update_task") {
      const task = state.tasks.find(t => t.id === action.task_id);
      if (task) { task.status = action.status; task.progress = action.progress; }
    }
    if (action.type === "start_focus_mode") startTimer({ id: action.focus_session_id, task_id: action.task_id, planned_minutes: action.duration_minutes, started_at: new Date().toISOString(), status: "active" });
  });
  renderTasks();
}

function startTimer(focus) {
  state.focus = focus; clearInterval(state.timerHandle);
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
    $("focus-detail").textContent = `${focus.planned_minutes}-minute block · stay with the task`;
    if (!left) { clearInterval(state.timerHandle); $("focus-status").textContent = "DONE"; }
  }; tick(); if (focus.status === "active") state.timerHandle = setInterval(tick, 1000);
}

function resetTimer() {
  clearInterval(state.timerHandle); state.focus = null; $("focus-title").textContent = "No session active"; $("focus-status").textContent = "IDLE"; $("timer").textContent = "25:00"; $("timer-progress").style.width = "0"; $("focus-controls").hidden = true; $("focus-detail").textContent = "Complete a task and ask Mira to start the next focus block.";
}

async function editTask(event) {
  const task = state.tasks.find(item => item.id === event.currentTarget.dataset.id);
  const title = prompt("Task title", task.title); if (title === null) return;
  const priorityText = prompt("Priority (1–5)", String(task.priority)); if (priorityText === null) return;
  const response = await fetch(`/api/tasks/${task.id}`, { method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({title, priority:Number(priorityText)}) });
  if (!response.ok) return toast("That task could not be updated.");
  Object.assign(task, await response.json()); renderTasks(); toast("Task updated.");
}

async function archiveTask(event) {
  const task = state.tasks.find(item => item.id === event.currentTarget.dataset.id);
  if (!confirm(`Archive “${task.title}”?`)) return;
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
    if (message.type === "session.ready" || message.type === "session.snapshot") applySnapshot(message.payload);
    if (message.type === "mira.response") applyMira(message.payload);
    if (message.type === "error") toast(message.detail || "Mira could not process that update.");
  };
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
$("report-form").addEventListener("submit", e => {
  e.preventDefault();
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return toast("Mira is reconnecting. Try again in a moment.");
  const startFocus = $("start-focus").checked;
  state.socket.send(JSON.stringify({
    type:"progress.reported", source:"text", task_id:$("report-task").value,
    transcript:$("report-text").value, progress:Number($("report-progress").value) / 100,
    start_focus:startFocus, focus_task_id:startFocus ? $("focus-task").value : null,
    focus_minutes:Number($("focus-minutes").value)
  }));
  $("report-text").value = "";
});
$("focus-toggle").addEventListener("click", () => transitionFocus(state.focus?.status === "paused" ? "resume" : "pause"));
$("focus-complete").addEventListener("click", () => transitionFocus("complete"));
$("focus-cancel").addEventListener("click", () => transitionFocus("cancel"));

connect();

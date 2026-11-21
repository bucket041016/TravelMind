const tripForm = document.querySelector("#tripForm");
const followupForm = document.querySelector("#followupForm");
const followupInput = document.querySelector("#followupInput");
const followupLog = document.querySelector("#followupLog");
const followupSendButton = document.querySelector("#followupForm .send-button");
const planButton = document.querySelector("#planButton");
const toolList = document.querySelector("#toolList");
const traceList = document.querySelector("#traceList");
const resetButton = document.querySelector("#resetButton");
const planningProgress = document.querySelector("#planningProgress");
const progressFill = document.querySelector("#progressFill");
const progressLabel = document.querySelector("#progressLabel");
const progressPercent = document.querySelector("#progressPercent");
const progressSteps = document.querySelector("#progressSteps");
const workspaceScroll = document.querySelector("#workspaceScroll");
const planResult = document.querySelector("#planResult");
const markdownResult = document.querySelector("#markdownResult");
const tabButtons = document.querySelectorAll("[data-tab]");
const appShell = document.querySelector(".app-shell");
const resultNavPanel = document.querySelector("#resultNavPanel");
const navCollapseButton = document.querySelector("#navCollapseButton");
const inputPanels = document.querySelector("#inputPanels");
const selectionSummary = document.querySelector("#selectionSummary");
const backHomeButton = document.querySelector("#backHomeButton");
const editPlanButton = document.querySelector("#editPlanButton");
const exportDropdown = document.querySelector(".export-dropdown");
const exportButton = document.querySelector("#exportButton");
const exportMenu = document.querySelector("#exportMenu");
const navLinks = document.querySelectorAll("[data-scroll-target]");
const modifyPanel = document.querySelector(".modify-panel");
const openRagModalButton = document.querySelector("#openRagModalButton");
const quotaBadge = document.querySelector("#quotaBadge");
const ragModal = document.querySelector("#ragModal");
const ragAdminNotice = document.querySelector("#ragAdminNotice");
const ragAdminTokenInput = document.querySelector("#ragAdminTokenInput");
const ragStatusLine = document.querySelector("#ragStatusLine");
const ragDocList = document.querySelector("#ragDocList");
const ragUploadForm = document.querySelector("#ragUploadForm");
const ragDocTitle = document.querySelector("#ragDocTitle");
const ragDocCity = document.querySelector("#ragDocCity");
const ragDocTags = document.querySelector("#ragDocTags");
const ragDocFile = document.querySelector("#ragDocFile");
const ragDocContent = document.querySelector("#ragDocContent");
const ragUploadMessage = document.querySelector("#ragUploadMessage");
const ragUploadSubmit = document.querySelector("#ragUploadSubmit");
const ragSearchForm = document.querySelector("#ragSearchForm");
const ragSearchCity = document.querySelector("#ragSearchCity");
const ragSearchQuery = document.querySelector("#ragSearchQuery");
const ragSearchResults = document.querySelector("#ragSearchResults");
const placePickerModal = document.querySelector("#placePickerModal");
const placePickerTitle = document.querySelector("#placePickerTitle");
const placePickerSub = document.querySelector("#placePickerSub");
const pickerTargetDay = document.querySelector("#pickerTargetDay");
const pickerTargetCategory = document.querySelector("#pickerTargetCategory");
const pickerTargetTime = document.querySelector("#pickerTargetTime");
const poiSearchForm = document.querySelector("#poiSearchForm");
const poiSearchCity = document.querySelector("#poiSearchCity");
const poiSearchKeyword = document.querySelector("#poiSearchKeyword");
const poiSearchSubmit = document.querySelector("#poiSearchSubmit");
const poiSearchStatus = document.querySelector("#poiSearchStatus");
const poiSearchResults = document.querySelector("#poiSearchResults");
const pickerExistingPool = document.querySelector("#pickerExistingPool");
const customItemForm = document.querySelector("#customItemForm");
const customItemTitle = document.querySelector("#customItemTitle");
const customItemLocation = document.querySelector("#customItemLocation");
const customItemAddress = document.querySelector("#customItemAddress");
const customItemCost = document.querySelector("#customItemCost");
const customItemTransport = document.querySelector("#customItemTransport");
const customItemDuration = document.querySelector("#customItemDuration");
const customItemDetail = document.querySelector("#customItemDetail");

const planningStages = [
  "理解旅行偏好",
  "比较跨城交通",
  "查询高德天气",
  "搜索景点美食",
  "匹配住宿酒店",
  "安排每日活动",
  "智能体检与路线评审",
  "估算旅行预算",
];

const timeSlots = ["上午", "中午", "下午", "晚上", "夜间"];
const maxUndoHistory = 40;
const sessionStorageKey = "travelmind:currentSession:v1";
const navCollapsedStorageKey = "travelmind:navCollapsed:v1";
const learnedHintsStorageKey = "travelmind:learnedHints:v1";
const sessionWindowNamePrefix = `${sessionStorageKey}:`;
const anonymousOwner = "anonymous";
const learnedHintRules = [
  { pattern: /少公交|少坐公交|不坐公交|公交太久|公交太累/, hint: "少公交" },
  { pattern: /别太赶|不要太赶|轻松|慢一点|松弛|休闲/, hint: "别太赶" },
  { pattern: /不去太远|别去太远|少跨区|不要跨区|跨区乱跳|太远景点/, hint: "不去太远景点" },
  { pattern: /少走路|别走太多|走路太多|腿累/, hint: "少走路" },
  { pattern: /少换乘|别换乘|换乘太多/, hint: "少换乘" },
];

let progressTimer = null;
let progressIndex = 0;
let currentPlanData = null;
let currentMarkdown = "";
let editMode = false;
let budgetAdjusted = false;
let activeTabName = "result";
let currentTrace = [];
let followupMessages = [];
let sessionId = createSessionId();
let undoStack = [];
let redoStack = [];
let editingCardKey = null;
let pickerContext = { mode: "add", dayIndex: 0, itemIndex: null };
let latestPoiSearchItems = [];
let dragSource = null;
let latestQuotaStatus = null;
const adminTokenStorageKey = "travelmind:adminToken:v1";

function getAdminToken() {
  const inputVal = String(ragAdminTokenInput?.value || "").trim();
  if (inputVal) return inputVal;
  try {
    return String(sessionStorage.getItem(adminTokenStorageKey) || "").trim();
  } catch (err) {
    return "";
  }
}

function getAdminTokenHeaders(baseHeaders = {}) {
  const token = getAdminToken();
  return token ? { ...baseHeaders, "X-Admin-Token": token } : { ...baseHeaders };
}

async function extractApiErrorMessage(response, fallbackText = "请求失败") {
  let rawText = "";
  try {
    rawText = await response.text();
  } catch (err) {
    return `${fallbackText}（HTTP ${response.status}）`;
  }
  if (!rawText) return `${fallbackText}（HTTP ${response.status}）`;
  try {
    const parsed = JSON.parse(rawText);
    const detail = parsed?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object" && detail.message) return String(detail.message);
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item?.msg || JSON.stringify(item)).join("；");
    }
    if (parsed?.message) return String(parsed.message);
  } catch (err) {
    // 非 JSON 文本原样返回
  }
  return rawText;
}

function renderQuotaBadge(status) {
  latestQuotaStatus = status || null;
  if (ragAdminNotice) {
    ragAdminNotice.hidden = !(status && status.public_mode && status.rag_write_protected);
  }
  if (!quotaBadge) return;
  if (!status || !status.rate_limit_enabled) {
    quotaBadge.hidden = true;
    return;
  }
  quotaBadge.hidden = false;
  const remaining = Number(status.remaining ?? 0);
  const limit = Number(status.daily_limit ?? 3);
  quotaBadge.classList.toggle("is-exhausted", remaining <= 0 || !status.global_available);
  if (!status.global_available) {
    quotaBadge.textContent = "今日全站额度已满 · 可体验精选示例";
    quotaBadge.title = "全站每日免费规划额度已用完，可点击精选示例秒开体验";
    return;
  }
  quotaBadge.textContent = `今日免费规划 ${remaining}/${limit}`;
  quotaBadge.title = `每 IP 每日免费规划 ${limit} 次（已用 ${status.used ?? 0} 次），追问剩余 ${status.refine_remaining ?? 0}/${status.refine_limit ?? 10} 次`;
}

async function refreshQuotaStatus() {
  try {
    const response = await fetch("/api/quota");
    if (!response.ok) return;
    const status = await response.json();
    renderQuotaBadge(status);
  } catch (err) {
    // 静默忽略，确保离线/E2E 零控制台错误
  }
}

async function loadPresetPlan(presetId) {
  try {
    const response = await fetch(`/api/presets/${encodeURIComponent(presetId)}`);
    if (!response.ok) {
      throw new Error(await extractApiErrorMessage(response, "加载精选示例失败"));
    }
    const payload = await response.json();
    const plan = payload?.plan;
    if (!plan) throw new Error("精选示例数据为空");
    currentPlanData = normalizePlanData(clonePlan(plan));
    currentMarkdown = plan.markdown || buildMarkdownFromPlan(currentPlanData);
    budgetAdjusted = false;
    editMode = false;
    clearEditHistory();
    if (editPlanButton) editPlanButton.textContent = "编辑行程";
    renderPlanResult(currentPlanData);
    renderMarkdownResult(currentMarkdown);
    setActiveTab("result", { skipSave: true });
    setTrace([], { skipSave: true });
    appendMessage(
      "assistant",
      `已为您免额度秒开精选示例「${payload.title || presetId}」。支持直接点击上方「编辑行程」拖拽调序、加减天数或导出 PDF。`,
      { skipSave: true },
    );
    saveSessionSnapshot();
    scrollWorkspaceToTop();
  } catch (error) {
    appendMessage("assistant", `请求失败：${error.message}`, { skipSave: true });
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInline(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function timeSlotForIndex(index) {
  return timeSlots[index] || `第 ${index + 1} 段`;
}

function isDefaultTimeSlot(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  return timeSlots.includes(text) || /^第\s*\d+\s*段$/.test(text);
}

function normalizeDayItemTimes(day, options = {}) {
  if (!day || !Array.isArray(day.items)) return;
  const force = Boolean(options.force);
  day.items.forEach((item, index) => {
    if (force || (!item.custom_time && isDefaultTimeSlot(item.time))) {
      item.time = timeSlotForIndex(index);
      if (force) item.custom_time = false;
    }
  });
}

function pushUndoSnapshot() {
  if (!currentPlanData) return;
  undoStack.push(clonePlan(currentPlanData));
  if (undoStack.length > maxUndoHistory) undoStack.shift();
  redoStack = [];
}

function clearEditHistory() {
  undoStack = [];
  redoStack = [];
  editingCardKey = null;
}

function undoPlanEdit() {
  if (!undoStack.length || !currentPlanData) return;
  redoStack.push(clonePlan(currentPlanData));
  currentPlanData = undoStack.pop();
  editingCardKey = null;
  finalizeManualPlanMutation({ skipRebuild: true });
}

function redoPlanEdit() {
  if (!redoStack.length || !currentPlanData) return;
  undoStack.push(clonePlan(currentPlanData));
  currentPlanData = redoStack.pop();
  editingCardKey = null;
  finalizeManualPlanMutation({ skipRebuild: true });
}

function renderTable(lines) {
  const rows = lines
    .filter((line) => {
      const cells = line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
      return !cells.every((cell) => /^:?-{3,}:?$/.test(cell));
    })
    .map((line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => renderInline(cell.trim())),
    );

  if (rows.length === 0) return "";
  const [head, ...body] = rows;
  const header = `<tr>${head.map((cell) => `<th>${cell}</th>`).join("")}</tr>`;
  const bodyRows = body
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${header}${bodyRows}</table>`;
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let listOpen = false;
  let tableBuffer = [];

  function flushList() {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  }

  function flushTable() {
    if (tableBuffer.length) {
      html.push(renderTable(tableBuffer));
      tableBuffer = [];
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.includes("|") && line.trim().startsWith("|")) {
      flushList();
      tableBuffer.push(line);
      continue;
    }

    flushTable();

    if (!line.trim()) {
      flushList();
      continue;
    }

    if (/^-{3,}$/.test(line.trim())) {
      flushList();
      html.push("<hr>");
    } else if (line.startsWith("### ")) {
      flushList();
      html.push(`<h3>${renderInline(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      flushList();
      html.push(`<h2>${renderInline(line.slice(3))}</h2>`);
    } else if (/^[-*]\s+/.test(line)) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${renderInline(line.replace(/^[-*]\s+/, ""))}</li>`);
    } else if (/^\d+\.\s+/.test(line)) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${renderInline(line.replace(/^\d+\.\s+/, ""))}</li>`);
    } else {
      flushList();
      html.push(`<p>${renderInline(line)}</p>`);
    }
  }

  flushTable();
  flushList();
  return html.join("");
}

function scrollWorkspaceToBottom() {
  const target = workspaceScroll;
  target.scrollTop = target.scrollHeight;
}

function scrollWorkspaceToTop() {
  const target = workspaceScroll;
  target.scrollTop = 0;
}

function scrollFollowupToBottom() {
  followupLog.scrollTop = followupLog.scrollHeight;
}

function clonePlan(data) {
  return JSON.parse(JSON.stringify(data || {}));
}

function createSessionId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getPersistentStorage() {
  try {
    return window.localStorage || null;
  } catch (error) {
    return null;
  }
}

function readNavCollapsed() {
  const storage = getPersistentStorage();
  return storage?.getItem(navCollapsedStorageKey) === "1";
}

function writeNavCollapsed(collapsed) {
  const storage = getPersistentStorage();
  if (!storage) return;
  storage.setItem(navCollapsedStorageKey, collapsed ? "1" : "0");
}

function setNavCollapsed(collapsed, options = {}) {
  const nextState = Boolean(collapsed);
  appShell.classList.toggle("nav-collapsed", nextState);
  resultNavPanel.classList.toggle("nav-collapsed", nextState);
  if (navCollapseButton) {
    navCollapseButton.setAttribute("aria-expanded", String(!nextState));
    navCollapseButton.setAttribute("aria-label", nextState ? "展开行程目录" : "收起行程目录");
    navCollapseButton.title = nextState ? "展开行程目录" : "收起行程目录";
    const icon = navCollapseButton.querySelector("span");
    if (icon) icon.textContent = nextState ? "›" : "‹";
  }
  if (options.persist !== false) writeNavCollapsed(nextState);
}

function readLearnedHints() {
  const storage = getPersistentStorage();
  if (!storage) return [];
  try {
    const parsed = JSON.parse(storage.getItem(learnedHintsStorageKey) || "[]");
    return Array.isArray(parsed)
      ? Array.from(new Set(parsed.map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 12)
      : [];
  } catch (error) {
    return [];
  }
}

function writeLearnedHints(hints) {
  const storage = getPersistentStorage();
  if (!storage) return;
  const normalized = Array.from(new Set((hints || []).map((item) => String(item || "").trim()).filter(Boolean))).slice(-12);
  storage.setItem(learnedHintsStorageKey, JSON.stringify(normalized));
}

function rememberLearnedHints(hints) {
  const incoming = (hints || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (!incoming.length) return;
  writeLearnedHints([...readLearnedHints(), ...incoming]);
}

function updateLearnedHintsFromText(text) {
  const content = String(text || "");
  const matched = learnedHintRules
    .filter((rule) => rule.pattern.test(content))
    .map((rule) => rule.hint);
  rememberLearnedHints(matched);
}

function readSessionSnapshotRaw() {
  const storage = getPersistentStorage();
  if (storage) return storage.getItem(sessionStorageKey);
  if (String(window.name || "").startsWith(sessionWindowNamePrefix)) {
    return String(window.name).slice(sessionWindowNamePrefix.length);
  }
  return null;
}

function writeSessionSnapshotRaw(value) {
  const storage = getPersistentStorage();
  if (storage) {
    storage.setItem(sessionStorageKey, value);
    return;
  }
  try {
    window.name = `${sessionWindowNamePrefix}${value}`;
  } catch (error) {
    // Some embedded browser sandboxes expose neither localStorage nor a writable window.name.
  }
}

function removeSessionSnapshotRaw() {
  const storage = getPersistentStorage();
  if (storage) {
    storage.removeItem(sessionStorageKey);
    return;
  }
  if (String(window.name || "").startsWith(sessionWindowNamePrefix)) {
    try {
      window.name = "";
    } catch (error) {
      // Ignore sandboxed window.name failures; clearing local memory still proceeds.
    }
  }
}

function hasSessionContent() {
  return Boolean(
    currentPlanData ||
      currentMarkdown ||
      followupMessages.length ||
      currentTrace.length,
  );
}

function buildSessionSnapshot() {
  return {
    sessionId,
    owner: anonymousOwner,
    updatedAt: new Date().toISOString(),
    activeTab: activeTabName,
    editMode,
    budgetAdjusted,
    currentPlanData: currentPlanData ? clonePlan(currentPlanData) : null,
    currentMarkdown,
    followupMessages: followupMessages.map((message) => ({ ...message })),
    trace: clonePlan(currentTrace),
  };
}

function saveSessionSnapshot() {
  try {
    if (!hasSessionContent()) {
      removeSessionSnapshotRaw();
      return;
    }
    writeSessionSnapshotRaw(JSON.stringify(buildSessionSnapshot()));
  } catch (error) {
    console.warn("TravelMind session snapshot save failed", error);
  }
}

function loadSessionSnapshot() {
  try {
    const raw = readSessionSnapshotRaw();
    if (!raw) return null;
    const snapshot = JSON.parse(raw);
    if (!snapshot || snapshot.owner !== anonymousOwner) return null;
    return snapshot;
  } catch (error) {
    console.warn("TravelMind session snapshot restore failed", error);
    removeSessionSnapshotRaw();
    return null;
  }
}

function clearSessionSnapshot() {
  try {
    removeSessionSnapshotRaw();
  } catch (error) {
    console.warn("TravelMind session snapshot clear failed", error);
  }
  sessionId = createSessionId();
}

function recordFollowupMessage(role, content, options = {}) {
  followupMessages.push({
    role,
    content: String(content || ""),
    createdAt: options.createdAt || new Date().toISOString(),
  });
  if (role === "user" && options.learn !== false) updateLearnedHintsFromText(content);
  if (!options.skipSave) saveSessionSnapshot();
}

function renderEmptyFollowupState() {
  followupLog.innerHTML = `<div class="empty-state">生成行程后，可以在这里继续追问或调整偏好。</div>`;
}

function restoreFollowupMessages(messages) {
  followupMessages = Array.isArray(messages)
    ? messages
        .filter((message) => message && ["user", "assistant"].includes(message.role))
        .map((message) => ({
          role: message.role,
          content: String(message.content || ""),
          createdAt: message.createdAt || new Date().toISOString(),
        }))
    : [];
  followupLog.innerHTML = "";
  if (!followupMessages.length) {
    renderEmptyFollowupState();
    return;
  }
  followupMessages.forEach((message) => {
    appendMessage(message.role, message.content, { persist: false });
  });
}

function setPlannedMode(enabled) {
  appShell.classList.toggle("has-plan", enabled);
  resultNavPanel.hidden = !enabled;
  setNavCollapsed(enabled ? readNavCollapsed() : false, { persist: false });
  if (inputPanels) inputPanels.hidden = enabled;
  if (backHomeButton) backHomeButton.hidden = !enabled;
  if (editPlanButton) editPlanButton.hidden = !enabled;
  if (exportDropdown) exportDropdown.hidden = !enabled;
  if (!enabled) {
    editMode = false;
    budgetAdjusted = false;
    appShell.classList.remove("show-inputs");
    if (modifyPanel) modifyPanel.open = false;
    if (inputPanels) inputPanels.hidden = false;
    if (editPlanButton) editPlanButton.textContent = "编辑行程";
    if (exportMenu) exportMenu.hidden = true;
  }
}

function sanitizeFilename(value) {
  return String(value || "travelmind-plan")
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "")
    .slice(0, 60);
}

function getPlanTitle(data = currentPlanData) {
  const prefs = data?.preferences || {};
  return `${prefs.originCity || "出发地"}-${prefs.destinationCity || "目的地"}-${prefs.days || ""}days`;
}

function toDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setupDefaultDate() {
  const input = document.querySelector("#travelDate");
  if (!input || input.value) return;
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  input.value = toDateInputValue(tomorrow);
}

function formatDateLabel(dateValue) {
  if (!dateValue) return "明天";
  const today = toDateInputValue(new Date());
  const tomorrowDate = new Date();
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrow = toDateInputValue(tomorrowDate);
  const afterTomorrowDate = new Date();
  afterTomorrowDate.setDate(afterTomorrowDate.getDate() + 2);
  const afterTomorrow = toDateInputValue(afterTomorrowDate);

  if (dateValue === today) return `今天（${dateValue}）`;
  if (dateValue === tomorrow) return `明天（${dateValue}）`;
  if (dateValue === afterTomorrow) return `后天（${dateValue}）`;
  return dateValue;
}

function getCheckedValues(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(
    (input) => input.value,
  );
}

function buildTripPrompt() {
  const payload = buildPlanPayload();
  const intercityText = payload.intercityModes.length
    ? payload.intercityModes.join("、")
    : "高铁/动车/城际、自驾";
  const localText = payload.localModes.length ? payload.localModes.join("、") : "公共交通、打车、步行";
  const profile = payload.preferenceProfile || {};
  const learnedText = profile.learnedHints?.length ? `；已记住：${profile.learnedHints.join("、")}` : "";
  const constraintSummary = {
    rawText: payload.freeText || "",
    hard: Array.isArray(payload.hardConstraints) ? payload.hardConstraints : [],
    soft: Array.isArray(payload.softPreferences) ? payload.softPreferences : [],
    unknown: [],
  };
  const hardText = constraintSummary.hard.length ? constraintSummary.hard.join("、") : "暂无显式硬约束";
  const softText = constraintSummary.soft.length ? constraintSummary.soft.join("、") : "暂无显式软偏好";

  return [
    `我计划从${payload.originCity}去${payload.destinationCity}，${formatDateLabel(payload.startDate)}出发，玩${payload.days}天，${payload.travelers}人，预算${payload.budget || "未指定"}元。`,
    `旅行偏好：${payload.interests.join("、") || "经典景点"}。`,
    `跨城交通请考虑：${intercityText}。目的地内交通请考虑：${localText}。住宿选择${payload.hotelLevel}档。`,
    `节奏：${profile.pace || "标准"}；单段交通尽量控制在 ${profile.maxTransferMinutes || 45} 分钟内；住宿策略：${profile.hotelStrategy || "近地铁枢纽"}${learnedText}。`,
    `补充要求：${constraintSummary.rawText || "未填写"}。硬约束：${hardText}。软偏好：${softText}。`,
    "请生成跨城主交通对比、酒店匹配、每日活动安排、行程详情、天气与出行建议、预算评估和推荐方案。",
  ].join("\n");
}

function buildPlanPayload() {
  const formData = new FormData(tripForm);
  const origin = formData.get("originCity");
  const destination = formData.get("destinationCity");
  const startDate = formData.get("travelDate");
  const days = formData.get("days");
  const travelers = formData.get("travelers");
  const budget = formData.get("budget");
  const hotelLevel = formData.get("hotelLevel") || "舒适";
  const pace = formData.get("pace") || "标准";
  const maxTransferMinutes = Number.parseInt(formData.get("maxTransferMinutes"), 10) || 45;
  const hotelStrategy = formData.get("hotelStrategy") || "近地铁枢纽";
  const freeText = String(formData.get("freeText") || "").trim();
  const interests = getCheckedValues("interests");
  const intercityModes = getCheckedValues("intercityModes");
  const localModes = getCheckedValues("localModes");

  return {
    originCity: String(origin || "").trim(),
    destinationCity: String(destination || "").trim(),
    startDate,
    days: Number.parseInt(days, 10) || 2,
    travelers: Number.parseInt(travelers, 10) || 1,
    budget: budget ? Number.parseInt(budget, 10) : null,
    intercityModes: intercityModes.length ? intercityModes : ["高铁/动车/城际", "自驾"],
    localModes: localModes.length ? localModes : ["公共交通", "打车", "步行"],
    hotelLevel,
    interests: interests.length ? interests : ["经典景点"],
    freeText,
    hardConstraints: [],
    softPreferences: [
      pace ? `旅行节奏：${pace}` : "",
      hotelStrategy ? `住宿策略：${hotelStrategy}` : "",
    ].filter(Boolean),
    preferenceProfile: {
      pace,
      maxTransferMinutes,
      hotelStrategy,
      learnedHints: readLearnedHints(),
    },
  };
}

function updateSelectionSummary() {
  if (!selectionSummary) return;
  const origin = document.querySelector("#originCity")?.value?.trim() || "出发地";
  const destination = document.querySelector("#destinationCity")?.value?.trim() || "目的地";
  const days = document.querySelector("#days")?.value || "2";
  const travelers = document.querySelector("#travelers")?.value || "1";
  const budget = document.querySelector("#budget")?.value;
  const pace = document.querySelector('input[name="pace"]:checked')?.value || "标准节奏";
  const hotelLevel = document.querySelector('input[name="hotelLevel"]:checked')?.value || "舒适住宿";
  const interests = getCheckedValues("interests").slice(0, 2);
  const chips = [
    `${origin} → ${destination}`,
    `${days} 天 · ${travelers} 人`,
    budget ? `预算 ¥${Number(budget).toLocaleString("zh-CN")}` : "预算待定",
    `${hotelLevel} · ${pace}`,
    ...(interests.length ? [interests.join(" / ")] : []),
  ];
  const chipRoot = selectionSummary.querySelector(".selection-chips");
  if (chipRoot) {
    chipRoot.innerHTML = chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("");
  }
}

function renderProgressSteps(activeIndex = 0, failed = false) {
  progressSteps.innerHTML = planningStages
    .map((stage, index) => {
      let className = "progress-step";
      if (failed && index === activeIndex) className += " error";
      else if (index < activeIndex) className += " done";
      else if (index === activeIndex) className += " running";
      return `<div class="${className}">${escapeHtml(stage)}</div>`;
    })
    .join("");
}

function setProgress(percent, label) {
  progressFill.style.width = `${percent}%`;
  progressPercent.textContent = `${percent}%`;
  progressLabel.textContent = label;
}

function startPlanningProgress() {
  clearInterval(progressTimer);
  planningProgress.hidden = false;
  progressIndex = 0;
  renderProgressSteps(progressIndex);
  setProgress(8, planningStages[0]);

  progressTimer = setInterval(() => {
    progressIndex = Math.min(progressIndex + 1, planningStages.length - 1);
    const cappedPercent = Math.min(88, 8 + progressIndex * 15);
    renderProgressSteps(progressIndex);
    setProgress(cappedPercent, planningStages[progressIndex]);
    if (progressIndex >= planningStages.length - 1) {
      clearInterval(progressTimer);
    }
  }, 900);
}

function completePlanningProgress() {
  clearInterval(progressTimer);
  renderProgressSteps(planningStages.length);
  setProgress(100, "规划完成");
}

function failPlanningProgress() {
  clearInterval(progressTimer);
  renderProgressSteps(Math.min(progressIndex, planningStages.length - 1), true);
  setProgress(Math.max(12, Number.parseInt(progressPercent.textContent, 10) || 12), "规划失败");
}

function clearEmptyFollowupState() {
  const empty = followupLog.querySelector(".empty-state");
  if (empty) empty.remove();
}

function appendMessage(role, content, options = {}) {
  clearEmptyFollowupState();
  const article = document.createElement("article");
  article.className = `message ${role}`;
  if (options.id) article.id = options.id;
  const avatarText = role === "user" ? "U" : "A";
  const avatarClass = role === "user" ? "user" : "bot";
  article.innerHTML = `
    <div class="avatar ${avatarClass}">${avatarText}</div>
    <div class="bubble ${options.typing ? "typing" : ""}">${options.html ? content : renderMarkdown(content)}</div>
  `;
  followupLog.appendChild(article);
  scrollFollowupToBottom();
  if (options.persist !== false && !options.typing) {
    recordFollowupMessage(role, content, { skipSave: options.skipSave });
  }
  return article;
}

function renderEmptyResult() {
  currentPlanData = null;
  currentMarkdown = "";
  setPlannedMode(false);
  planResult.hidden = false;
  markdownResult.hidden = true;
  planResult.innerHTML = `
    <div class="empty-result empty-result--hero">
      <div class="empty-orbit" aria-hidden="true"><span>TM</span></div>
      <div class="empty-kicker">TRAVEL WORKSPACE · READY</div>
      <strong>把下一段旅程，变成一张清晰的行动地图</strong>
      <p>填写出发地、目的地和偏好，TravelMind 会把路线、酒店、天气、景点与预算组织成可执行的旅行桌面。</p>
      <div class="empty-feature-grid" aria-label="规划能力">
        <span><b>01</b>多路线对比</span>
        <span><b>02</b>每日节奏编排</span>
        <span><b>03</b>天气与预算联动</span>
      </div>
      <div class="preset-demo-row" aria-label="免额度精选示例">
        <button class="preset-chip" type="button" data-preset-id="gz-sz-2d">免额度体验：广州 → 深圳 2 天</button>
        <button class="preset-chip" type="button" data-preset-id="cd-3d">免额度体验：成都 3 天慢生活</button>
      </div>
    </div>
  `;
  markdownResult.innerHTML = `<div class="empty-result"><strong>暂无方案原文</strong><p>生成行程后，这里会显示 Markdown 版本，便于复制或归档。</p></div>`;
}

function setActiveTab(tabName, options = {}) {
  activeTabName = tabName || "result";
  tabButtons.forEach((button) => {
    const active = button.dataset.tab === activeTabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  planResult.hidden = activeTabName !== "result";
  markdownResult.hidden = activeTabName !== "markdown";
  scrollWorkspaceToTop();
  if (!options.skipSave) saveSessionSnapshot();
}

function renderMarkdownResult(markdown) {
  markdownResult.innerHTML = `
    <article class="markdown-card">
      ${renderMarkdown(markdown || "暂无方案原文。")}
    </article>
  `;
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "待校准";
  return `¥${Number(value).toLocaleString("zh-CN")}`;
}

function modeLabel(mode) {
  return {
    rail: "高铁/动车/城际",
    flight: "飞机航班",
    driving: "自驾",
    transit: "公共交通",
    walking: "步行",
    bicycling: "骑行",
    taxi: "打车",
  }[mode] || mode;
}

function renderInfoList(items) {
  if (!items || !items.length) return `<div class="empty-state">暂无数据</div>`;
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderNamedItems(items, limit = 6, options = {}) {
  if (!items || !items.length) return `<div class="empty-state">暂无候选</div>`;
  const selectedHotelId = options.kind === "hotel" ? currentPlanData?.hotels?.selected_id : "";
  return items
    .slice(0, limit)
    .map((item, index) => {
      const compactHotel = options.kind === "hotel" && options.compact;
      const note =
        options.kind === "hotel" && !compactHotel
          ? [hotelMatchReason(item, options), item.cost_note].filter(Boolean).join(" ")
          : item.cost_note;
      const isSelectedHotel =
        options.kind === "hotel" &&
        ((selectedHotelId && item.id === selectedHotelId) || (!selectedHotelId && index === 0));
      let actionHtml = "";
      if (options.kind === "hotel") {
        actionHtml = isSelectedHotel
          ? `<span class="mini-badge selected">当前入住</span>`
          : `<button type="button" class="mini-action-btn" data-select-hotel-index="${index}">设为入住</button>`;
      } else if (options.group) {
        actionHtml = `<button type="button" class="mini-action-btn" data-add-candidate-group="${escapeHtml(options.group)}" data-add-candidate-index="${index}">+ 加入行程</button>`;
      }
      return `
        <div class="mini-item${compactHotel ? " mini-item--hotel" : ""}${isSelectedHotel ? " selected-card" : ""}">
          <div class="mini-item-head">
            <strong>${escapeHtml(item.name || "未命名")}</strong>
            ${actionHtml}
          </div>
          <span>${escapeHtml(item.address || (compactHotel ? "地址待核实" : item.description || "暂无补充信息"))}</span>
          <small>${compactHotel ? renderHotelMeta(item, options) : renderPoiMeta(item, options)}</small>
          ${!compactHotel && note ? `<em>${escapeHtml(note)}</em>` : ""}
        </div>
      `;
    })
    .join("");
}

function cleanHotelNearbyLabel(value) {
  return String(value || "")
    .trim()
    .replace(/^[近靠近毗邻位于距离]+/, "")
    .replace(/(酒店|宾馆|公寓)?店$/, "")
    .replace(/^[，,；;。()（）\s]+|[，,；;。()（）\s]+$/g, "");
}

function looksLikeHotelNearbyLabel(value) {
  if (!value || ["高端酒店", "舒适酒店", "经济酒店", "酒店", "宾馆", "公寓"].includes(value)) return false;
  return /地铁|站|会展|机场|口岸|码头|公园|广场|景区|美术馆|博物馆|购物中心|商业中心|花园|旁|附近|对面|步行/.test(value);
}

function hotelNearbyLandmarks(item = {}) {
  const labels = [];
  const add = (value) => {
    const label = cleanHotelNearbyLabel(value);
    if (label && looksLikeHotelNearbyLabel(label) && !labels.includes(label)) labels.push(label);
  };
  const address = String(item.address || "");
  const parenPattern = /[（(]([^（）()]+)[）)]/g;
  let parenMatch;
  while ((parenMatch = parenPattern.exec(address))) add(parenMatch[1]);

  const landmarkPattern =
    /([\u4e00-\u9fffA-Za-z0-9]+?(?:国际会展中心|会展中心|地铁站|火车站|高铁站|北站|东站|西站|南站|机场|口岸|码头|公园|广场|景区|美术馆|博物馆|购物中心|商业中心))/g;
  [item.type, item.name].forEach((source) => {
    const text = cleanHotelNearbyLabel(source);
    let match;
    while ((match = landmarkPattern.exec(text))) add(match[1]);
  });

  if (/旁|附近|对面/.test(address)) {
    let piece = address.split(/[，,；;]/).pop() || "";
    const markerIndex = piece.lastIndexOf("号");
    if (markerIndex >= 0) piece = piece.slice(markerIndex + 1);
    add(piece);
  }
  return labels.slice(0, 3);
}

function hotelNearbyLabel(item = {}) {
  const labels = hotelNearbyLandmarks(item);
  if (labels.length) return `近${labels.slice(0, 2).join("/")}`;
  if (item.address) return `位于${item.address}`;
  return "位于候选酒店所在片区";
}

function isGenericHotelArea(value) {
  return /核心商圈|地铁枢纽|第一天重点景点|交通枢纽/.test(String(value || ""));
}

function hotelAreaRecommendation(hotels = {}, prefs = {}) {
  const existing = String(hotels.area_recommendation || "");
  if (existing && !isGenericHotelArea(existing)) return existing;
  const labels = [];
  (hotels.candidates || []).slice(0, 4).forEach((item) => {
    hotelNearbyLandmarks(item).forEach((label) => {
      if (!labels.includes(label) && labels.length < 3) labels.push(label);
    });
  });
  if (labels.length) return `建议优先住在${labels.join("、")}周边，减少换乘和搬运行李。`;
  return existing || `建议选择${prefs.destinationCity || "目的地"}交通便利区域。`;
}

function hotelMatchReason(item = {}, options = {}) {
  const existing = String(item.match_reason || "");
  if (existing && !isGenericHotelArea(existing)) return existing;
  const level = options.hotelLevel ? `${options.hotelLevel}档住宿` : "住宿";
  return `${hotelNearbyLabel(item)}，${level}，便于换乘、晚间返程和寄存行李。`;
}

function positiveAmount(value) {
  const amount = Number(value);
  return Number.isFinite(amount) && amount > 0 ? amount : null;
}

function hotelReferencePrice(hotelLevel) {
  return { 经济: 220, 舒适: 380, 高端: 680 }[hotelLevel] || 380;
}

function renderPoiMeta(item = {}, options = {}) {
  const meta = [];
  if (item.rating) meta.push(`评分 ${item.rating}`);
  meta.push(formatPriceDisplay(item, options));
  if (item.price_confidence) meta.push(`可信度 ${priceConfidenceLabel(item.price_confidence)}`);
  if (item.type) meta.push(item.type);
  return escapeHtml(meta.join(" · ") || "高德 POI 参考");
}

function renderHotelMeta(item = {}, options = {}) {
  const meta = [];
  if (item.rating) meta.push(`评分 ${item.rating}`);
  meta.push(hotelPriceSummary(item, options));
  return escapeHtml(meta.filter(Boolean).join(" · ") || "价格待核实");
}

function hotelPriceSummary(item = {}, options = {}) {
  const rangeText = formatPriceRange(item.price_range, { ...options, kind: "hotel" });
  if (rangeText) return rangeText;
  const cost = positiveAmount(item.cost) || positiveAmount(item.cost_estimate);
  if (cost) return `约 ${formatMoney(cost)}/晚`;
  if (["category_rule", "rule_fallback"].includes(item.cost_source)) {
    return `约 ${formatMoney(hotelReferencePrice(options.hotelLevel))}/晚`;
  }
  return "价格待核实";
}

function priceConfidenceLabel(value) {
  return {
    high: "高",
    medium: "中",
    low: "低",
    unknown: "待核实",
  }[value] || "待核实";
}

function formatPriceRange(range, options = {}) {
  if (!range || range.min === undefined || range.max === undefined) return "";
  const min = Number(range.min);
  const max = Number(range.max);
  if (!Number.isFinite(min) || !Number.isFinite(max)) return "";
  const unit = options.kind === "hotel" || range.unit === "night" ? "/晚" : "/人";
  if (min === max) return `${formatMoney(min)}${unit}`;
  return `约 ${formatMoney(min)}-${formatMoney(max)}${unit}`;
}

function formatPriceDisplay(item = {}, options = {}) {
  const source = item.cost_source || (positiveAmount(item.cost) ? "amap_cost" : "unknown_price");
  const cost = positiveAmount(item.cost) || positiveAmount(item.cost_estimate);
  const rangeText = formatPriceRange(item.price_range, options);
  const unit = options.kind === "hotel" ? "/晚" : "";

  if (source === "manual_edit") {
    return `${formatMoney(cost ?? 0)}${unit} · 手动编辑预算`;
  }
  if (source === "amap_cost" && cost) {
    return `${formatMoney(cost)}${unit} · ${options.kind === "hotel" ? "高德酒店参考消费" : "高德参考消费"}`;
  }
  if (source === "ai_price_range") {
    return `${rangeText || (cost ? `约 ${formatMoney(cost)}${unit}` : "约价待核实")} · AI 常识估算，需核实`;
  }
  if (source === "free_or_no_ticket_default") {
    return `${formatMoney(0)} · 无门票/免费默认，需核实`;
  }
  if (source === "category_rule" || source === "rule_fallback") {
    const fallbackCost = cost || (options.kind === "hotel" ? hotelReferencePrice(options.hotelLevel) : null);
    if (fallbackCost) {
      return `${formatMoney(fallbackCost)}${unit} · ${options.kind === "hotel" ? "档位规则估算" : "类型规则估算"}`;
    }
    return "价格待核实 · 暂无可靠参考";
  }
  return "价格待核实 · 暂无可靠参考";
}

function extractRailEndpointsFromSummary(summary = "") {
  const headingMatch = String(summary || "").match(/(?:高铁\/城际铁路|高铁\/城际铁路建议)：\s*(.+?)(?:，|。|$)/);
  const routeText = headingMatch ? headingMatch[1] : String(summary || "");
  const routeMatch = routeText.match(/(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:，|。|$)/);
  if (!routeMatch) return null;
  return {
    origin: routeMatch[1].trim(),
    destination: routeMatch[2].trim(),
  };
}

function inferDurationFromSummary(summary = "") {
  const text = String(summary || "");
  const railMatch = text.match(/车程\s*(约?\s*[^。；，]+?分钟)/);
  if (railMatch) return railMatch[1].replace(/\s+/g, " ").trim();
  const genericMatch = text.match(/约?\s*\d+(?:\.\d+)?\s*(?:小时|分钟)(?:\s*\d+\s*分钟)?/);
  return genericMatch ? genericMatch[0].trim() : "";
}

function inferPriceFromSummary(summary = "") {
  const text = String(summary || "");
  const railMatch = text.match(/(?:二等座通常)?约\s*([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元/);
  if (railMatch) return `二等座约 ${railMatch[1]}-${railMatch[2]} 元/人，需以 12306 为准`;
  const tollMatch = text.match(/过路费约\s*([0-9.]+)\s*元/);
  if (tollMatch) return `过路费约 ${tollMatch[1]} 元，油电费另计`;
  return "";
}

function normalizeTransportOption(option = {}, prefs = {}) {
  const normalized = option;
  const originCity = normalized.origin_city || normalized.origin || prefs.originCity || "";
  const destinationCity = normalized.destination_city || normalized.destination || prefs.destinationCity || "";
  normalized.origin_city = originCity;
  normalized.destination_city = destinationCity;
  normalized.origin = normalized.origin || originCity;
  normalized.destination = normalized.destination || destinationCity;

  const railEndpoints = extractRailEndpointsFromSummary(normalized.summary);
  if (!normalized.origin_detail) {
    normalized.origin_detail =
      railEndpoints?.origin ||
      (normalized.mode === "flight" && originCity ? `${originCity}机场待确认` : "") ||
      (originCity ? `${originCity}市中心` : "出发地待确认");
  }
  if (!normalized.destination_detail) {
    normalized.destination_detail =
      railEndpoints?.destination ||
      (normalized.mode === "flight" && destinationCity ? `${destinationCity}机场待确认` : "") ||
      (destinationCity ? `${destinationCity}市中心` : "目的地待确认");
  }
  normalized.duration = normalized.duration || inferDurationFromSummary(normalized.summary) || "待校准";
  normalized.price = normalized.price || inferPriceFromSummary(normalized.summary) || "待校准";
  return normalized;
}

function normalizePlanData(data) {
  if (!data || typeof data !== "object") return data;
  const prefs = data.preferences || {};
  const intercity = data.intercity_transport || {};
  if (Array.isArray(intercity.options)) {
    intercity.options.forEach((option) => normalizeTransportOption(option, prefs));
  }
  if (!data.local_transport || typeof data.local_transport !== "object") {
    data.local_transport = { recommended_modes: [], notes: [], segments: [] };
  }
  if (!Array.isArray(data.local_transport.segments)) data.local_transport.segments = [];
  return data;
}

function renderTransportCards(intercity, prefs = {}, renderOptions = {}) {
  const routeOptions = intercity?.options || [];
  if (!routeOptions.length) return `<div class="empty-state">暂无跨城交通候选</div>`;
  const compact = Boolean(renderOptions.compact);
  return routeOptions
    .map((option) => {
      const normalized = normalizeTransportOption({ ...option }, prefs);
      const isSelected = option.mode === intercity.recommended;
      const selected = isSelected ? " selected" : "";
      return `
        <article class="route-card${selected}${compact ? " route-card--compact" : ""}">
          <div class="route-card-head">
            <div class="card-kicker">${isSelected ? "推荐主交通" : "备选方案"}</div>
            ${
              isSelected
                ? `<span class="mini-badge selected">已选用</span>`
                : `<button type="button" class="mini-action-btn" data-select-intercity-mode="${escapeHtml(option.mode)}">选为主交通</button>`
            }
          </div>
          <h4>${escapeHtml(option.title || modeLabel(option.mode))}</h4>
          <div class="route-endpoints">
            <strong>${escapeHtml(normalized.origin_detail)}</strong>
            <span>→</span>
            <strong>${escapeHtml(normalized.destination_detail)}</strong>
          </div>
          <div class="route-city-hint">
            ${escapeHtml(normalized.origin_city || normalized.origin || "出发城市待确认")} → ${escapeHtml(normalized.destination_city || normalized.destination || "目的城市待确认")}
          </div>
          <div class="route-facts">
            <span>耗时：${escapeHtml(normalized.duration || "待校准")}</span>
            <span>费用：${escapeHtml(normalized.price || "待校准")}</span>
            ${normalized.distance_km ? `<span>距离：约 ${escapeHtml(normalized.distance_km)} km</span>` : ""}
          </div>
          ${compact ? "" : `
            <p>${escapeHtml(normalized.summary || "暂无路线摘要")}</p>
            <span>${escapeHtml(normalized.warning || normalized.provider_status || "")}</span>
          `}
        </article>
      `;
    })
    .join("");
}

function getBudgetRows(budget) {
  const breakdown = budget?.breakdown || {};
  return [
    ["跨城交通", "intercity_transport", breakdown.intercity_transport],
    ["住宿", "hotel", breakdown.hotel],
    ["餐饮", "food", breakdown.food],
    ["门票/体验", "tickets", breakdown.tickets],
    ["市内交通", "local_transport", breakdown.local_transport],
  ];
}

function budgetRowPercent(value, total) {
  const amount = Number(value);
  const totalAmount = Number(total);
  if (!Number.isFinite(amount) || !Number.isFinite(totalAmount) || totalAmount <= 0 || amount <= 0) return 0;
  return Math.round(Math.min(100, (amount / totalAmount) * 100));
}

function expectedSpendLabel(budget = {}) {
  return budget?.total !== null && budget?.total !== undefined
    ? `预计花费 ${formatMoney(budget.total)}`
    : "预计花费待校准";
}

function budgetBreakdownSummary(budget = {}) {
  const labels = getBudgetRows(budget)
    .filter(([, , value]) => Number.isFinite(Number(value)) && Number(value) > 0)
    .map(([label]) => label);
  return labels.length ? `费用构成：${labels.join("、")}` : "费用构成待补充";
}

function budgetStatusLabel(budget = {}) {
  if (budget.verdict === "within_budget") return `预算内 · ${formatMoney(budget.total)}`;
  if (budget.verdict === "over_budget") return `超预算 · ${formatMoney(budget.total)}`;
  if (budget.total) return `预算待校准 · ${formatMoney(budget.total)}`;
  return "预算待校准";
}

function planningModeLabel(data = {}) {
  if (data.planning_mode === "deepseek_hybrid" && data.llm_status === "used") {
    return "DeepSeek 智能规划 + 高德事实校验";
  }
  if (data.llm_status && data.llm_status !== "used") {
    return "规则降级规划 + 高德事实校验";
  }
  return "结构化规划 + 高德事实校验";
}

function qualitySourceLabel(source) {
  return {
    deepseek: "DeepSeek 自检",
    rule_fallback: "规则兜底体检",
  }[source] || "体检结果";
}

function issueSeverityLabel(severity) {
  return {
    high: "高风险",
    medium: "需留意",
    low: "提示",
  }[severity] || "需留意";
}

function renderQualityReview(review = null) {
  if (!review || typeof review !== "object") {
    return `
      <div class="quality-review pending">
        <div class="quality-head">
          <strong>智能体检</strong>
          <span>旧会话缺少体检结果</span>
        </div>
        <p>路线、片区和返程逻辑需要重新规划后才能展示体检分数。</p>
      </div>
    `;
  }
  const scores = [
    ["总分", review.overall_score],
    ["路线", review.route_score],
    ["节奏", review.pace_score],
    ["片区", review.cluster_score],
    ["逻辑", review.logic_score],
  ];
  const issues = Array.isArray(review.issues) ? review.issues.filter((item) => item?.message).slice(0, 3) : [];
  const fixes = Array.isArray(review.fixes) ? review.fixes.filter(Boolean).slice(0, 3) : [];
  const constraints = Array.isArray(review.constraints) ? review.constraints.filter((item) => item?.text).slice(0, 8) : [];
  const gateViolations = Array.isArray(review.gate_violations) ? review.gate_violations.filter((item) => item?.message) : [];
  return `
    <div class="quality-review">
      <div class="quality-head">
        <strong>智能体检</strong>
        <span>${escapeHtml(qualitySourceLabel(review.source))}${review.repaired ? " · 已返工" : ""}</span>
      </div>
      <div class="quality-scores">
        ${scores
          .map(([label, value]) => `<span><em>${escapeHtml(label)}</em>${escapeHtml(value ?? "-")}</span>`)
          .join("")}
      </div>
      ${
        gateViolations.length
          ? `<div class="quality-gate-violations">
              <h4>硬门槛提醒</h4>
              ${gateViolations
                .map(
                  (violation) =>
                    `<p class="quality-issue ${escapeHtml(violation.severity || "high")}">${escapeHtml(violation.day ? `第 ${violation.day} 天 · ` : "")}${escapeHtml(issueSeverityLabel(violation.severity))}：${escapeHtml(violation.message)}</p>`,
                )
                .join("")}
            </div>`
          : ""
      }
      <div class="quality-columns">
        <div>
          <h4>关键问题</h4>
          ${
            issues.length
              ? issues
                  .map(
                    (issue) =>
                      `<p class="quality-issue ${escapeHtml(issue.severity || "medium")}">${escapeHtml(issue.day ? `第 ${issue.day} 天 · ` : "")}${escapeHtml(issueSeverityLabel(issue.severity))}：${escapeHtml(issue.message)}</p>`,
                  )
                  .join("")
              : `<p>未发现高风险问题。</p>`
          }
        </div>
        <div>
          <h4>已修复/处理</h4>
          ${
            fixes.length
              ? fixes.map((fix) => `<p>${escapeHtml(fix)}</p>`).join("")
              : `<p>${review.repaired ? "已按体检结果完成一次受控返工。" : "未触发返工，继续使用当前行程。"}</p>`
          }
        </div>
      </div>
      <div class="quality-constraints">
        <h4>约束检查</h4>
        ${
          constraints.length
            ? constraints
                .map(
                  (constraint) =>
                    `<p class="quality-issue ${escapeHtml(constraint.status || "unknown")}">${escapeHtml(constraintStatusLabel(constraint.status))}：${escapeHtml(constraint.text)}${constraint.evidence ? ` · ${escapeHtml(constraint.evidence)}` : ""}</p>`,
                )
                .join("")
            : `<p>暂无逐条约束记录。</p>`
        }
      </div>
    </div>
  `;
}

function constraintStatusLabel(status) {
  return {
    satisfied: "满足",
    violated: "未满足",
    unknown: "待核实",
  }[status] || "待核实";
}

const BUDGET_LEVER_LABELS = {
  replace: "同片区替换",
  hotel_strategy: "住宿策略",
  trim: "删减活动",
};

function renderBudgetAdjustments(adjustments) {
  if (!adjustments || typeof adjustments !== "object" || adjustments.enabled === false) {
    return "";
  }
  const applied = Array.isArray(adjustments.applied) ? adjustments.applied : [];
  const skipped = Array.isArray(adjustments.skipped) ? adjustments.skipped : [];
  if (!applied.length && !skipped.length) {
    return "";
  }
  const gapLine =
    adjustments.gap_before == null
      ? ""
      : `<p class="budget-adjust-gap">缺口（调整期估算）：¥${formatMoney(adjustments.gap_before)} → ¥${formatMoney(adjustments.gap_after ?? 0)}${adjustments.rounds_used ? ` · 共 ${adjustments.rounds_used} 轮` : ""}</p>`;
  const actionLines = applied
    .map(
      (action) =>
        `<p class="budget-adjust-action"><strong>${escapeHtml(BUDGET_LEVER_LABELS[action.lever] || action.lever || "调整")}</strong>${action.day ? ` · 第 ${escapeHtml(action.day)} 天` : ""}：${escapeHtml(action.before?.title || "")}${action.before?.cost != null ? `（¥${formatMoney(action.before.cost)}）` : ""} → ${action.after?.title ? `${escapeHtml(action.after.title)}` : "移除"}${action.after?.cost != null ? `（¥${formatMoney(action.after.cost)}）` : ""}，节省 ¥${formatMoney(action.saved)}。${escapeHtml(action.reason || "")}</p>`,
    )
    .join("");
  const skipLines = skipped
    .slice(0, 4)
    .map(
      (skip) =>
        `<p class="budget-adjust-skip">${escapeHtml(BUDGET_LEVER_LABELS[skip.lever] || skip.lever || "调整")}${skip.day ? ` · 第 ${escapeHtml(skip.day)} 天` : ""}：${escapeHtml(skip.title || "") ? `${escapeHtml(skip.title)} — ` : ""}${escapeHtml(skip.reason || "")}</p>`,
    )
    .join("");
  return `
    <details class="inline-details budget-adjust-details">
      <summary>预算自动调整（${applied.length} 项动作${adjustments.total_saved ? ` · 共省 ¥${formatMoney(adjustments.total_saved)}` : ""}）</summary>
      <div class="budget-adjust-body">
        ${gapLine}
        ${actionLines || "<p>本轮未执行调整动作。</p>"}
        ${skipLines ? `<h5>已跳过</h5>${skipLines}` : ""}
        ${adjustments.note ? `<p class="budget-adjust-note">${escapeHtml(adjustments.note)}</p>` : ""}
      </div>
    </details>
  `;
}

function renderBudget(budget, options = {}) {
  const sources = budget?.sources || {};
  const rows = getBudgetRows(budget);
  return `
    ${options.showTotal === false ? "" : `
      <div class="budget-total">
        <span>${options.compact ? "预算小结" : "预计总计"}</span>
        <strong>${formatMoney(budget?.total)}</strong>
      </div>
    `}
    <div class="budget-rows ${options.compact ? "compact" : ""}">
      ${rows
        .map(
          ([label, key, value]) => `
            <div class="budget-breakdown-row">
              <div class="budget-row-head">
                <span>${escapeHtml(label)}</span>
                <strong>${formatMoney(value)}</strong>
              </div>
              <div class="budget-row-track" aria-hidden="true"><span style="width: ${budgetRowPercent(value, budget?.total)}%"></span></div>
              ${options.showSources === false ? "" : `<em>${escapeHtml(sourceLabel(sources[key]))}</em>`}
            </div>
          `,
        )
        .join("")}
    </div>
    ${options.showAdvice === false ? "" : `<p class="budget-advice">${escapeHtml(budget?.advice || "预算待校准")}</p>`}
    ${budgetAdjusted ? `<div class="status-line">已按手动调整重新估算活动项。</div>` : ""}
    ${options.compact || options.showBasis === false ? "" : `
      <div class="basis-list">
        ${(budget?.basis || [])
          .map((item) => `<span>${escapeHtml(item)}</span>`)
          .join("")}
      </div>
    `}
  `;
}

function sourceLabel(source) {
  return {
    amap_cost: "高德参考消费",
    amap_route: "高德路线费用",
    ai_price_range: "AI 常识区间",
    free_or_no_ticket_default: "无门票/免费默认",
    category_rule: "类型规则估算",
    unknown_price: "价格待核实",
    rule_fallback: "规则估算",
    manual_edit: "手动编辑预算",
    knowledge_base: "攻略知识库",
  }[source] || "待校准";
}

function placeSourceLabel(source, isRealPlace) {
  return {
    amap_poi: "高德 POI",
    hotel_poi: "酒店 POI",
    transport_hub: "交通枢纽",
    planning_note: "说明项",
    transport_note: "交通说明",
    llm_suggestion: "待确认建议",
    user_custom: "自定义节点",
  }[source] || (isRealPlace ? "真实地点" : "说明项");
}

function renderWeather(weather, advice = {}) {
  const entries = Object.entries(weather || {});
  const weatherRows = entries.length
    ? entries
    .map(
      ([city, text]) => `
        <div class="weather-row">
          <strong>${escapeHtml(city)}</strong>
          <span>${escapeHtml(text)}</span>
        </div>
      `,
    )
    .join("")
    : `<div class="empty-state">暂无天气数据</div>`;
  const adviceRows = [
    ["防晒", advice.sun_protection],
    ["穿衣", advice.clothing],
    ["雨具", advice.umbrella],
  ]
    .filter(([, text]) => text)
    .map(
      ([label, text]) => `
        <div class="advice-row">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(text)}</span>
        </div>
      `,
    )
    .join("");
  return `${weatherRows}${adviceRows ? `<div class="advice-list">${adviceRows}</div>` : ""}`;
}

function renderMap(mapData) {
  const markers = mapData?.markers || [];
  const fallbackPoints = mapData?.fallback_points || [];
  const staticLimit = mapData?.static_marker_limit || 10;
  const pointTone = (category = "") =>
    ({
      activity: "activity",
      attraction: "activity",
      food: "food",
      dining: "food",
      hotel: "hotel",
      lodging: "hotel",
      transfer: "transport",
      transport: "transport",
    }[String(category).toLowerCase()] || "activity");
  const sourceLabels = {
    amap_poi: "高德 POI",
    hotel_poi: "酒店 POI",
    transport_hub: "交通枢纽",
    city_center: "城市中心",
    hotel_area: "住宿区域",
    derived: "邻近点位",
    missing: "未定位",
  };
  const pointRows = markers.length
    ? markers.map((marker) => ({
        label: marker.label,
        title: marker.title,
        tone: pointTone(marker.category || marker.place_source),
        meta: `第 ${marker.day || "-"} 天 · ${marker.time || ""} · ${sourceLabels[marker.location_source] || "位置参考"}`,
      }))
    : fallbackPoints.map((title, index) => ({
        label: String(index + 1),
        title,
        tone: "activity",
        meta: "暂无坐标，按候选点展示",
      }));
  const markerRows = pointRows
    .map(
      (point) => `
        <div class="map-point map-point--${point.tone}">
          <span aria-hidden="true">${escapeHtml(point.label)}</span>
          <strong>${escapeHtml(point.title)}</strong>
          <em>${escapeHtml(point.meta)}</em>
        </div>
      `,
    )
    .join("");
  const previewRows = pointRows
    .map(
      (point) => `
        <span class="map-chip map-chip--${point.tone}" title="${escapeHtml(point.meta)}">
          <b>${escapeHtml(point.label)}</b>${escapeHtml(point.title)}
        </span>
      `,
    )
    .join("");

  return `
    <div class="map-frame">
      ${
        mapData?.image_url
          ? `<img src="${escapeHtml(mapData.image_url)}" alt="高德景点地图" loading="lazy" />`
          : `<div class="map-placeholder">地图暂不可用</div>`
        }
    </div>
    <div class="map-chip-list">${previewRows || `<div class="empty-state">暂无地图点位</div>`}</div>
    <details class="map-points-drawer">
      <summary>查看全部点位</summary>
      <div class="map-point-list">${markerRows || `<div class="empty-state">暂无地图点位</div>`}</div>
    </details>
    <p class="map-note">${escapeHtml((mapData?.notes || [])[0] || "地图点位来自高德 POI 参考坐标。")}${markers.length > staticLimit ? ` 静态图显示前 ${escapeHtml(staticLimit)} 个点，完整点位见下方列表。` : ""}</p>
  `;
}

function renderItineraryDays(days) {
  if (!days || !days.length) return `<div class="empty-state">暂无每日行程</div>`;
  const totalDays = days.length;
  return days
    .map(
      (day, dayIndex) => `
        <details class="day-card story-day" data-day-card="${dayIndex}" open>
          <summary>
            <span>第 ${escapeHtml(day.day)} 天</span>
            ${
              editMode
                ? `<div class="day-theme-editor">
                    <input type="text" class="day-theme-input" data-day-theme-index="${dayIndex}" value="${escapeHtml(day.theme || "")}" placeholder="输入当天主题" aria-label="第 ${escapeHtml(day.day)} 天主题" />
                    <button type="button" class="mini-action-btn" data-day-action="add-item" data-day-index="${dayIndex}">+ 添加节点</button>
                    <button type="button" class="mini-action-btn danger" data-day-action="delete-day" data-day-index="${dayIndex}" ${totalDays <= 1 ? "disabled" : ""}>删除该天</button>
                  </div>`
                : `<strong>${escapeHtml(day.theme || "")}</strong>`
            }
            <em>${escapeHtml(day.date || "")}</em>
          </summary>
          <div class="timeline" data-day-dropzone="${dayIndex}">
            ${
              (day.items || []).length
                ? (day.items || [])
                    .map((item, itemIndex) => renderTimelineItem(item, dayIndex, itemIndex, day.items.length, totalDays))
                    .join("")
                : `<div class="empty-day-dropzone" data-day-dropzone="${dayIndex}">
                    <span>这一天暂时还没有安排，可将其他天的活动拖到这里，或点击“+ 添加节点”。</span>
                    ${editMode ? `<button type="button" class="mini-action-btn" data-day-action="add-item" data-day-index="${dayIndex}">+ 添加节点</button>` : ""}
                  </div>`
            }
          </div>
        </details>
      `,
    )
    .join("");
}

function renderArrivalSegment(segment) {
  if (!segment) return "";
  const normalized = normalizeArrivalSegment(segment);
  const riskClass = normalized.risk_level ? `risk-${normalized.risk_level}` : "";
  const reason = normalized.judge_reason || normalized.warning || normalized.summary || "";
  return `
    <div class="arrival-segment ${escapeHtml(riskClass)}">
      <strong>上一站到本站${normalized.status === "impractical" ? " · 路线待重新规划" : ""}</strong>
      <span>${escapeHtml(normalized.mode_label || modeLabel(normalized.mode))} · ${escapeHtml(normalized.duration || "耗时待核实")} · ${escapeHtml(normalized.distance || "距离待核实")} · ${escapeHtml(normalized.price || "价格待核实")}</span>
      <em>${escapeHtml(reason)}</em>
    </div>
  `;
}

function parseDurationMinutes(text = "") {
  const clean = String(text || "").replace(/\s+/g, "");
  const match = clean.match(/(?:(\d+)小时)?(?:(\d+)分钟)?/);
  if (!match || (!match[1] && !match[2])) return 0;
  return Number(match[1] || 0) * 60 + Number(match[2] || 0);
}

function segmentDistanceKm(segment = {}) {
  const direct = Number(segment.distance_km);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const text = String(segment.distance || segment.summary || "");
  const kmMatch = text.match(/([0-9.]+)\s*km/i);
  if (kmMatch) return Number(kmMatch[1]);
  const meterMatch = text.match(/([0-9.]+)\s*m\b/i);
  if (meterMatch) return Number(meterMatch[1]) / 1000;
  return 0;
}

function isImpracticalTransitSegment(segment = {}) {
  const distanceKm = segmentDistanceKm(segment);
  const minutes = parseDurationMinutes(segment.duration || segment.summary);
  return segment.mode === "transit" && (minutes > 90 || distanceKm > 35);
}

function normalizeArrivalSegment(segment = {}) {
  if (segment.status === "impractical" || segment.judge_decision === "mark_impractical") {
    return { risk_level: "high", ...segment };
  }
  if (isImpracticalTransitSegment(segment) || segmentDistanceKm(segment) > 60) {
    return {
      ...segment,
      status: "impractical",
      judge_source: segment.judge_source || "rule_fallback",
      judge_decision: "mark_impractical",
      risk_level: "high",
      judge_reason: "路线待重新规划：该段距离或公交耗时过长，不建议作为同一天相邻行程。",
      price: "建议重排，不估算",
    };
  }
  return { risk_level: segment.risk_level || "low", ...segment };
}

function isReturnTransferItem(item = {}) {
  const prefs = currentPlanData?.preferences || {};
  const text = `${item.title || ""} ${item.location || ""} ${item.detail || ""} ${item.transport || ""}`;
  if (item.category !== "transfer") return false;
  if (prefs.originCity && text.includes(prefs.originCity)) return true;
  return /返程|返回|回程|回到|返家|回家/.test(text);
}

function looksLikeLodgingText(value = "") {
  return /建议优先住在|住宿区域|住宿参考|酒店|周边，减少换乘|寄存行李/.test(String(value || ""));
}

function returnTransferLocation(item = {}) {
  const title = String(item.title || "");
  const location = String(item.location || "");
  const source = looksLikeLodgingText(location) ? title : location || title;
  const match = source.match(/(.+?)\s*(?:->|→|到|至)\s*(.+?)(?:（|\(|，|,|。|$)/);
  if (match) return `${match[1].trim()} → ${match[2].trim()}`;
  const prefs = currentPlanData?.preferences || {};
  return `${prefs.destinationCity || "目的地"} → ${prefs.originCity || "出发城市"}`;
}

function timelineItemLocation(item = {}) {
  if (isReturnTransferItem(item)) return returnTransferLocation(item);
  return item.location || "";
}

function timelineItemDetail(item = {}) {
  if (isReturnTransferItem(item) && looksLikeLodgingText(item.detail)) {
    const prefs = currentPlanData?.preferences || {};
    return `按推荐跨城交通返回${prefs.originCity || "出发城市"}，这是返程交通安排，不需要再安排目的地住宿。`;
  }
  return item.detail || "";
}

// 知识库详情（TRAVELMIND_KNOWLEDGE 开启时后端附带）：事实性描述优先于模型自由文字。
function renderKnowledgeDetail(item = {}) {
  const text = String(item.knowledge_detail || "").trim();
  if (!text) return "";
  return `<p class="activity-knowledge"><span class="knowledge-badge">知识库</span>${escapeHtml(text)}</p>`;
}

function timelineItemTransport(item = {}) {
  const raw = String(item.transport || "");
  if (["rail", "flight", "driving", "transit", "walking", "bicycling", "taxi"].includes(raw)) return modeLabel(raw);
  return raw;
}

function renderInlineCardEditor(item, dayIndex, itemIndex) {
  const category = item.category || "activity";
  const costValue = Number.isFinite(Number(item.cost_estimate)) ? Number(item.cost_estimate) : 0;
  return `
    <form class="inline-item-editor" data-inline-edit-form="${dayIndex}:${itemIndex}">
      <div class="inline-editor-grid">
        <label>
          <span>时间段 / 具体时间</span>
          <input type="text" name="time" value="${escapeHtml(item.time || timeSlotForIndex(itemIndex))}" placeholder="如 上午 或 09:30-11:30" />
        </label>
        <label>
          <span>类别</span>
          <select name="category">
            <option value="activity" ${category === "activity" ? "selected" : ""}>景点 / 体验</option>
            <option value="food" ${category === "food" ? "selected" : ""}>美食 / 餐厅</option>
            <option value="hotel" ${category === "hotel" ? "selected" : ""}>住宿 / 休整</option>
            <option value="transfer" ${category === "transfer" ? "selected" : ""}>交通 / 接驳</option>
            <option value="note" ${category === "note" ? "selected" : ""}>自由备注</option>
          </select>
        </label>
        <label class="span-2">
          <span>活动标题</span>
          <input type="text" name="title" value="${escapeHtml(item.title || "")}" required />
        </label>
        <label>
          <span>地点名称</span>
          <input type="text" name="location" value="${escapeHtml(item.location || "")}" />
        </label>
        <label>
          <span>地址</span>
          <input type="text" name="address" value="${escapeHtml(item.address || "")}" />
        </label>
        <label>
          <span>交通方式</span>
          <input type="text" name="transport" value="${escapeHtml(timelineItemTransport(item))}" />
        </label>
        <label>
          <span>预计耗时</span>
          <input type="text" name="duration" value="${escapeHtml(item.duration || "")}" />
        </label>
        <label>
          <span>单人预算（元）</span>
          <input type="number" name="cost_estimate" min="0" step="5" value="${escapeHtml(costValue)}" />
        </label>
        <label class="span-2">
          <span>详细说明 / 个人备注</span>
          <textarea name="detail" rows="2">${escapeHtml(item.detail || "")}</textarea>
        </label>
      </div>
      <div class="inline-editor-actions">
        <button type="button" class="ghost-button" data-action="cancel-inline-edit">取消</button>
        <button type="submit" class="primary-button">保存修改</button>
      </div>
    </form>
  `;
}

function renderTimelineItem(item, dayIndex, itemIndex, count, totalDays = 1) {
  const hasImage = item.photo_url;
  const displayTime = item.time || timeSlotForIndex(itemIndex);
  const displayLocation = timelineItemLocation(item);
  const displayTransport = timelineItemTransport(item);
  const displayDetail = timelineItemDetail(item);
  const cardKey = `${dayIndex}:${itemIndex}`;
  const isInlineEditing = editMode && editingCardKey === cardKey;
  const moveDayOptions =
    totalDays > 1
      ? `<select class="move-day-select" data-move-day-select="1" aria-label="移动到其他天">
          <option value="">移到第...天</option>
          ${Array.from({ length: totalDays }, (_, idx) =>
            idx === dayIndex
              ? ""
              : `<option value="${idx}">移到第 ${idx + 1} 天</option>`,
          ).join("")}
        </select>`
      : "";
  return `
    <article class="activity-card feed-card${editMode ? " editable" : ""}${isInlineEditing ? " inline-editing" : ""}" data-day-index="${dayIndex}" data-item-index="${itemIndex}" ${editMode && !isInlineEditing ? 'draggable="true"' : ""}>
      <div class="activity-time-col">
        ${editMode ? `<div class="drag-handle" title="按住拖拽排序或跨天移动">⋮⋮</div>` : ""}
        <div class="activity-time">${escapeHtml(displayTime)}</div>
      </div>
      <div class="activity-media ${hasImage ? "" : "empty"}">
        ${
          hasImage
            ? `<img src="${escapeHtml(item.photo_url)}" alt="${escapeHtml(item.title || item.location || "活动图片")}" loading="lazy" />`
            : `<span>${escapeHtml((item.location || item.title || "行程").slice(0, 2))}</span>`
        }
      </div>
      <div class="activity-body">
        <div class="activity-head">
          <div>
            <strong>${escapeHtml(item.title || "")}</strong>
            <span>${escapeHtml(displayLocation)}${item.address && !isReturnTransferItem(item) ? ` · ${escapeHtml(item.address)}` : ""}</span>
          </div>
          ${
            editMode
              ? `<div class="activity-actions">
                  <button type="button" data-action="edit-inline">${isInlineEditing ? "收起" : "编辑"}</button>
                  <button type="button" data-action="replace">替换</button>
                  ${moveDayOptions}
                  <button type="button" data-action="move-up" ${itemIndex === 0 ? "disabled" : ""}>上移</button>
                  <button type="button" data-action="move-down" ${itemIndex === count - 1 ? "disabled" : ""}>下移</button>
                  <button type="button" class="danger" data-action="delete">删除</button>
                </div>`
              : ""
          }
        </div>
        ${isInlineEditing ? renderInlineCardEditor(item, dayIndex, itemIndex) : ""}
        ${renderArrivalSegment(item.arrival_transport_segment)}
        ${renderKnowledgeDetail(item)}
        <p class="activity-detail ${item.knowledge_detail ? "secondary" : ""}">${escapeHtml(displayDetail)}</p>
        <div class="activity-meta">
          <span>交通：${escapeHtml(displayTransport)}</span>
          <span>耗时：${escapeHtml(item.duration || "")}</span>
          <span>${item.rating ? `评分 ${escapeHtml(item.rating)}` : "评分待补充"}</span>
          <span>${escapeHtml(placeSourceLabel(item.place_source, item.is_real_place))}</span>
          <span>${escapeHtml(formatPriceDisplay(item))}</span>
          ${item.cost_note ? `<span>${escapeHtml(item.cost_note)}</span>` : ""}
          ${item.validation_note ? `<span>${escapeHtml(item.validation_note)}</span>` : ""}
        </div>
      </div>
    </article>
  `;
}

function renderSpotlightCards(items, kind = "activity", limit = 2, options = {}) {
  const list = (items || []).slice(0, limit);
  if (!list.length) return `<div class="empty-state">暂无推荐</div>`;
  const kindLabel = kind === "food" ? "美食推荐" : "精选景点";
  const group = kind === "food" ? "foods" : "attractions";
  return list
    .map((item, index) => {
      const hasImage = item.photo_url;
      const title = item.name || item.title || "未命名";
      const swatch = (title || kindLabel).slice(0, 2);
      return `
        <article class="spotlight-card ${escapeHtml(kind)}">
          <div class="spotlight-top-row">
            <div class="spotlight-kicker">${escapeHtml(kindLabel)}</div>
            <button type="button" class="mini-action-btn" data-add-candidate-group="${escapeHtml(group)}" data-add-candidate-index="${index}">+ 加入行程</button>
          </div>
          <div class="spotlight-media ${hasImage ? "" : "empty"}">
            ${
              hasImage
                ? `<img src="${escapeHtml(item.photo_url)}" alt="${escapeHtml(title)}" loading="lazy" />`
                : `<span>${escapeHtml(swatch)}</span>`
            }
          </div>
          <strong>${escapeHtml(title)}</strong>
          <p>${escapeHtml(item.address || item.description || "候选地点，需以现场和平台信息为准。")}</p>
          <small>${renderPoiMeta(item, options)}</small>
          <div class="social-proof">
            <span>${index + 1}</span>
            <em>高德参考</em>
          </div>
        </article>
      `;
    })
    .join("");
}

function ragModeLabel(mode) {
  return {
    hybrid_bm25_vector: "BM25 + 向量混合检索 (RRF)",
    bm25_metadata: "BM25 + 元数据加权检索",
    fallback: "知识库降级",
  }[mode] || "知识库检索";
}

function renderRagReferences(refs = [], meta = {}) {
  const list = Array.isArray(refs) ? refs : [];
  const header = `
    <div class="rag-meta-bar">
      <span>${escapeHtml(ragModeLabel(meta?.retrieval_mode))}${list.length ? ` · 命中 ${list.length} 条` : ""}</span>
      <button type="button" class="mini-action-btn" data-open-rag-modal="1">管理/上传攻略</button>
    </div>
  `;
  if (!list.length) {
    return `${header}<div class="empty-state">当前行程未命中特定攻略片段，可点击上方按钮上传自定义攻略笔记。</div>`;
  }
  const cards = list
    .map(
      (item) => `
        <article class="rag-ref-card">
          <div class="rag-ref-head">
            <strong>${escapeHtml(item.title || "攻略片段")}${item.section ? ` · ${escapeHtml(item.section)}` : ""}</strong>
            <span class="rag-origin-tag ${item.origin_type === "custom" ? "custom" : "builtin"}">${item.origin_type === "custom" ? "自定义" : "内置"}</span>
          </div>
          <p>${escapeHtml(item.content || "")}</p>
          <div class="rag-ref-foot">
            <span>城市：${escapeHtml(item.city || "通用")}</span>
            <span>匹配：${escapeHtml((item.match_reasons || []).join(" · ") || "关键词匹配")}</span>
            <span>相关度 ${escapeHtml(item.score ?? "-")}</span>
          </div>
        </article>
      `,
    )
    .join("");
  return `${header}<div class="rag-ref-list">${cards}</div>`;
}

function renderEditToolbar() {
  if (!editMode) return "";
  return `
    <div class="edit-toolbar">
      <div class="edit-toolbar-group">
        <button type="button" class="toolbar-btn primary" data-toolbar-action="add-item">+ 搜索/添加地点</button>
        <button type="button" class="toolbar-btn" data-toolbar-action="add-day">+ 新增一天</button>
        <button type="button" class="toolbar-btn" data-toolbar-action="reset-times">重排默认时段</button>
      </div>
      <div class="edit-toolbar-group">
        <button type="button" class="toolbar-btn" data-toolbar-action="undo" ${undoStack.length ? "" : "disabled"}>撤销 (${undoStack.length})</button>
        <button type="button" class="toolbar-btn" data-toolbar-action="redo" ${redoStack.length ? "" : "disabled"}>重做 (${redoStack.length})</button>
      </div>
      <div class="edit-toolbar-tip">支持按住左侧 ⋮⋮ 拖拽排序或跨天移动；点“编辑”可直接修改时间、标题、备注与单价预算；不会自动重跑 Agent。</div>
    </div>
  `;
}

function renderSupportPanel({ id = "", className = "", title, summary = "", body = "", open = false }) {
  const idAttr = id ? ` id="${escapeHtml(id)}"` : "";
  return `
    <details${idAttr} class="result-card support-panel ${escapeHtml(className)}" ${open ? "open" : ""}>
      <summary>
        <span>${escapeHtml(title)}</span>
        <em>${escapeHtml(summary)}</em>
      </summary>
      <div class="support-panel-body">${body}</div>
    </details>
  `;
}

function qualityReviewSummary(review = null) {
  if (!review || typeof review !== "object") return "旧会话缺少体检结果";
  const source = qualitySourceLabel(review.source);
  return `总分 ${review.overall_score ?? "-"} · ${source}${review.repaired ? " · 已返工" : ""}`;
}

function weatherSummary(weather = {}) {
  const entries = Object.entries(weather || {});
  if (!entries.length) return "暂无天气数据";
  const [city, text] = entries[0];
  return `${city} · ${String(text || "").slice(0, 24)}`;
}

function renderWeatherSignal(weather = {}, advice = {}) {
  const entries = Object.entries(weather || {});
  const [city, text] = entries[0] || ["目的地", "天气待查询"];
  const adviceItems = [
    ["穿衣", advice.clothing],
    ["雨具", advice.umbrella],
    ["防晒", advice.sun_protection],
  ]
    .filter(([, value]) => value)
    .slice(0, 3);
  return `
    <div class="weather-signal-value" title="${escapeHtml(String(text || "天气待查询"))}">${escapeHtml(String(text || "天气待查询"))}</div>
    <div class="weather-signal-city">${escapeHtml(city)} · 行程期间天气参考</div>
    <div class="signal-tags">
      ${adviceItems.length ? adviceItems.map(([label, value]) => `<span title="${escapeHtml(value)}">${escapeHtml(label)}</span>`).join("") : `<span>建议出发前复核</span>`}
    </div>
    <details class="inline-details weather-details">
      <summary>查看详细天气与穿衣</summary>
      <div class="weather-detail-list">${renderWeather(weather, advice)}</div>
    </details>
    <p class="card-footnote">天气为行程参考，出发前请再次确认。</p>
  `;
}

function renderFeaturedHotel(hotels = {}, hotelArea = "") {
  const candidates = Array.isArray(hotels.candidates) ? hotels.candidates : [];
  const featured =
    (hotels.selected_id && candidates.find((item) => item.id === hotels.selected_id)) ||
    candidates[0] ||
    null;
  if (!featured) {
    return `
      <div class="hotel-featured">
        <strong>按片区筛选合适酒店</strong>
        <span>${escapeHtml(hotelArea || "暂无酒店候选")}</span>
      </div>
    `;
  }
  const title = featured.name || featured.title || "酒店候选";
  return `
    <div class="hotel-featured">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(featured.address || hotelArea || "高德酒店 POI 参考")}</span>
      <small>${renderHotelMeta(featured, { kind: "hotel", compact: true })}</small>
    </div>
  `;
}

function renderPlanResult(data, options = {}) {
  const prefs = data.preferences || {};
  const hotels = data.hotels || {};
  const pois = data.pois || {};
  const recommendedMode = modeLabel(data.intercity_transport?.recommended || "");
  const planningMode = planningModeLabel(data);
  const hotelArea = hotelAreaRecommendation(hotels, prefs);
  const activitySpotlights = renderSpotlightCards(pois.attractions, "activity", 4);
  const foodSpotlights = renderSpotlightCards(pois.foods, "food", 4);
  const qualityScore = data.quality_review?.overall_score ?? "-";
  const routeSource = qualitySourceLabel(data.quality_review?.source);
  const routeSupport = `
    ${renderQualityReview(data.quality_review)}
  `;
  const poiSupport = `
    <div class="spotlight-grid">
      ${activitySpotlights}
      ${foodSpotlights}
    </div>
    <details class="candidate-drawer">
      <summary>查看全部候选（可直接一键加入行程）</summary>
      <div class="poi-columns">
        <div>
          <h4>景点/活动</h4>
          <div class="mini-list">${renderNamedItems(pois.attractions, 8, { group: "attractions" })}</div>
        </div>
        <div>
          <h4>地方美食</h4>
          <div class="mini-list">${renderNamedItems(pois.foods, 8, { group: "foods" })}</div>
        </div>
      </div>
    </details>
  `;
  planResult.hidden = false;
  setPlannedMode(true);
  planResult.innerHTML = `
    <div class="workbench-page travel-board">
      <section id="overviewSection" class="overview-hero">
        <div class="hero-main">
          <div class="hero-kicker"><span class="hero-status-dot"></span>规划完成 · ${escapeHtml(planningMode)}</div>
          <h3>${escapeHtml(prefs.destinationCity || "")}旅行计划</h3>
          <p class="hero-description">路线、地点、天气与预算已经整理好，接下来只需要按你的节奏出发。</p>
          <div class="hero-meta">
            <span>${escapeHtml(prefs.startDate || "日期待定")} 出发</span>
            <span>${escapeHtml(prefs.days || "-")} 天 · ${escapeHtml(prefs.travelers || "-")} 人</span>
            <span>${escapeHtml(recommendedMode || "主交通待定")}</span>
          </div>
        </div>
        <div class="hero-side">
          <div class="hero-route-label">本次路线</div>
          <strong class="hero-route">${escapeHtml(prefs.originCity || "出发地")} <span>→</span> ${escapeHtml(prefs.destinationCity || "目的地")}</strong>
          <div class="hero-tags">
            <strong>${escapeHtml(prefs.hotelLevel || "舒适")}档住宿</strong>
            <strong>${escapeHtml((prefs.interests || []).join("、") || "经典景点")}</strong>
            <strong>${escapeHtml(budgetStatusLabel(data.budget || {}))}</strong>
          </div>
        </div>
      </section>

      <section id="routeOptionsSection" class="route-options-panel" aria-labelledby="routeComparisonTitle">
        <div class="route-options-head">
          <div>
            <span class="route-options-kicker">ROUTE OPTIONS</span>
            <strong id="routeComparisonTitle">路线对比</strong>
          </div>
          <small>选择本次行程的主交通方式</small>
        </div>
        <div class="route-grid route-grid--hero">${renderTransportCards(data.intercity_transport, prefs, { compact: true })}</div>
      </section>

      <section class="signal-grid" aria-label="旅行摘要">
        <article id="hotelSection" class="signal-card signal-card--stay">
          <div class="signal-card-head"><span class="signal-eyebrow">住宿策略</span><span class="signal-icon" aria-hidden="true">⌂</span></div>
          <strong class="signal-card-title">${escapeHtml(hotelArea || "按片区筛选酒店")}</strong>
          ${renderFeaturedHotel(hotels, hotelArea)}
          <details class="inline-details">
            <summary>查看匹配候选</summary>
            <div class="mini-list">${renderNamedItems(hotels.candidates, 4, { kind: "hotel", hotelLevel: prefs.hotelLevel, compact: true })}</div>
          </details>
          <p class="card-footnote">酒店位置为高德 POI 参考；价格为参考区间，实际房价和房态以酒店平台实时信息为准。</p>
        </article>

        <article id="budgetSection" class="signal-card signal-card--budget">
          <div class="signal-card-head"><span class="signal-eyebrow">预算大盘</span><span class="signal-icon" aria-hidden="true">¥</span></div>
          <div class="signal-money">${formatMoney(data.budget?.total)}</div>
          <div class="signal-status">${escapeHtml(expectedSpendLabel(data.budget || {}))}</div>
          <div class="budget-spark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
          <details class="inline-details budget-details">
            <summary>查看费用构成</summary>
            <div class="budget-breakdown">${renderBudget(data.budget || {}, { compact: true, showTotal: false, showAdvice: false, showSources: false })}</div>
          </details>
          ${renderBudgetAdjustments(data.budget_adjustments)}
          <p class="signal-note">${escapeHtml(budgetBreakdownSummary(data.budget || {}))}</p>
          <p class="card-footnote">预计金额会随购票、订房和现场消费变化。</p>
        </article>

        <article id="weatherSection" class="signal-card signal-card--weather">
          <div class="signal-card-head"><span class="signal-eyebrow">天气与穿衣</span><span class="signal-icon" aria-hidden="true">☼</span></div>
          ${renderWeatherSignal(data.weather, data.weather_advice)}
        </article>

        <article class="signal-card signal-card--route">
          <div class="signal-card-head"><span class="signal-eyebrow">路线体检</span><span class="signal-icon" aria-hidden="true">↗</span></div>
          <div class="route-score-line"><strong>${escapeHtml(qualityScore)}</strong><span>/ 100</span><small>${escapeHtml(routeSource)}</small></div>
          <p class="signal-card-title">${escapeHtml(qualityReviewSummary(data.quality_review))}</p>
          <div class="signal-tags"><span>推荐：${escapeHtml(recommendedMode || "主交通待定")}</span><span>低摩擦衔接</span></div>
          <details class="inline-details route-health-details">
            <summary>查看路线体检详情</summary>
            <div class="route-health-details-body">${routeSupport}</div>
          </details>
        </article>
      </section>

      <section id="mapSection" class="result-card map-card map-card--wide">
        <div class="section-heading-row compact-heading"><div><div class="section-kicker">MAP VIEW</div><div class="section-title">地图视图</div></div><span class="section-caption">按行程顺序</span></div>
        ${renderMap(data.map || {})}
      </section>

      <div class="content-grid">
        <section id="daysSection" class="result-card day-section">
          <div class="section-heading-row">
            <div>
              <div class="section-kicker">DAY BY DAY</div>
              <div class="section-title">每日行程</div>
            </div>
            ${
              !editMode
                ? `<button type="button" class="mini-action-btn" data-quick-enter-edit="1">自由编辑行程</button>`
                : `<span class="section-caption">编辑中 · 拖拽或点击卡片调整</span>`
            }
          </div>
          ${renderEditToolbar()}
          ${renderItineraryDays(data.itinerary_days)}
        </section>

        <aside class="support-dock" aria-label="支持信息">
          <section id="poiSection" class="result-card recommendation-card">
            <div class="section-heading-row compact-heading"><div><div class="section-kicker">LOCAL PICKS</div><div class="section-title">精选推荐</div></div><span class="section-caption">景点与餐饮</span></div>
            ${poiSupport}
          </section>
          <section id="ragSection" class="result-card rag-card">
            <div class="section-heading-row compact-heading"><div><div class="section-kicker">RAG KNOWLEDGE</div><div class="section-title">攻略知识参考</div></div><span class="section-caption">动线与避坑</span></div>
            ${renderRagReferences(data.rag_references, data.rag_meta)}
          </section>
        </aside>
      </div>
    </div>
  `;
  if (!options.preserveScroll) scrollWorkspaceToTop();
}

function renderCurrentPlanFromState(options = {}) {
  if (!currentPlanData) {
    renderEmptyResult();
    setActiveTab("result", { skipSave: true });
    return false;
  }
  currentMarkdown = currentMarkdown || buildMarkdownFromPlan(currentPlanData);
  if (editPlanButton) editPlanButton.textContent = editMode ? "完成编辑" : "编辑行程";
  renderPlanResult(currentPlanData, { preserveScroll: options.preserveScroll });
  renderMarkdownResult(currentMarkdown);
  setTrace(currentTrace, { skipSave: true });
  setActiveTab(activeTabName || "result", { skipSave: true });
  if (!options.skipSave) saveSessionSnapshot();
  return true;
}

function renderSavedHomeState() {
  appShell.classList.remove("has-plan", "show-inputs");
  resultNavPanel.hidden = true;
  if (inputPanels) inputPanels.hidden = false;
  if (backHomeButton) backHomeButton.hidden = true;
  if (editPlanButton) editPlanButton.hidden = true;
  if (exportDropdown) exportDropdown.hidden = true;
  if (exportMenu) exportMenu.hidden = true;
  if (modifyPanel) modifyPanel.open = false;
  activeTabName = "result";
  planResult.hidden = false;
  markdownResult.hidden = true;
  planResult.innerHTML = `
    <div class="empty-result">
      <strong>上次行程已保存</strong>
      <p>当前规划结果、方案原文、追问记录和手动编辑已经保存在本机浏览器。返回首页不会清空记录，继续查看即可回到完成页。</p>
      <div>
        <button class="ghost-button" type="button" data-session-action="restore-plan">继续查看行程</button>
      </div>
    </div>
  `;
  markdownResult.innerHTML = `<div class="empty-result"><strong>方案原文已保存</strong><p>继续查看行程后，可以切换到“方案原文”标签查看 Markdown 版本。</p></div>`;
  setActiveTab("result", { skipSave: true });
  saveSessionSnapshot();
}

function restoreSessionSnapshot() {
  const snapshot = loadSessionSnapshot();
  if (!snapshot) return false;
  sessionId = snapshot.sessionId || createSessionId();
  currentPlanData = snapshot.currentPlanData ? normalizePlanData(clonePlan(snapshot.currentPlanData)) : null;
  currentMarkdown = snapshot.currentMarkdown || "";
  editMode = Boolean(snapshot.editMode);
  budgetAdjusted = Boolean(snapshot.budgetAdjusted);
  activeTabName = ["result", "markdown"].includes(snapshot.activeTab) ? snapshot.activeTab : "result";
  currentTrace = Array.isArray(snapshot.trace) ? clonePlan(snapshot.trace) : [];
  restoreFollowupMessages(snapshot.followupMessages);
  if (currentPlanData) {
    renderCurrentPlanFromState({ skipSave: true, preserveScroll: true });
  } else {
    renderEmptyResult();
    setTrace(currentTrace, { skipSave: true });
    setActiveTab("result", { skipSave: true });
  }
  return true;
}

function rebuildClientMap(data) {
  const markers = [];
  const staticMarkerLimit = data.map?.static_marker_limit || 10;
  const center = data.map?.center || findFirstClientPoint(data);
  let lastPoint = center;
  (data.itinerary_days || []).forEach((day) => {
    (day.items || []).forEach((item) => {
      const resolved = resolveClientMapPoint(item, center, lastPoint);
      if (!resolved.point) {
        item.location_source = "missing";
        item.map_label = "";
        item.map_included = false;
        return;
      }
      const point = resolved.point;
      const label = String(markers.length + 1);
      item.location_point = point;
      item.location_source = resolved.source;
      item.map_label = label;
      item.map_included = true;
      lastPoint = point;
      markers.push({
        id: item.id,
        label,
        title: item.location || item.title,
        day: day.day,
        time: item.time,
        lng: Number(point.lng.toFixed(6)),
        lat: Number(point.lat.toFixed(6)),
        category: item.category || "activity",
        location_source: resolved.source,
      });
    });
  });

  if (!markers.length) {
    data.map = {
      provider_status: "fallback",
      image_url: "",
      center: null,
      markers: [],
      path: [],
      fallback_points: (data.itinerary_days || [])
        .flatMap((day) => day.items || [])
        .map((item) => item.location || item.title)
        .filter(Boolean),
      static_marker_limit: staticMarkerLimit,
      notes: ["当前编辑后的行程暂无可用坐标，暂以点位顺序列表展示。"],
    };
    return;
  }

  const staticMarkers = markers.slice(0, staticMarkerLimit);
  const markerParam = staticMarkers.map((marker) => `${marker.lng},${marker.lat},${marker.label}`).join(";");
  const pathParam = staticMarkers.map((marker) => `${marker.lng},${marker.lat}`).join(";");
  data.map = {
    provider_status: "amap_static",
    image_url: `/api/map-static?plan_id=${encodeURIComponent(data.plan_id || "edited")}&markers=${encodeURIComponent(markerParam)}&path=${encodeURIComponent(pathParam)}&title=${encodeURIComponent(data.preferences?.destinationCity || "")}`,
    center: {
      lng: markers.reduce((sum, marker) => sum + marker.lng, 0) / markers.length,
      lat: markers.reduce((sum, marker) => sum + marker.lat, 0) / markers.length,
    },
    markers,
    path: markers.map((marker) => ({ lng: marker.lng, lat: marker.lat })),
    static_marker_limit: staticMarkerLimit,
    notes: ["地图点位已按当前手动调整后的每日行程同步更新。"],
  };
}

function findFirstClientPoint(data) {
  const items = (data.itinerary_days || []).flatMap((day) => day.items || []);
  for (const item of items) {
    const point = normalizeClientPoint(item.location_point);
    if (point) return point;
  }
  return data.map?.center || null;
}

function normalizeClientPoint(point) {
  if (!point || typeof point.lng !== "number" || typeof point.lat !== "number") return null;
  if (point.lng < -180 || point.lng > 180 || point.lat < -90 || point.lat > 90) return null;
  return { lng: point.lng, lat: point.lat };
}

function resolveClientMapPoint(item, center, lastPoint) {
  const direct = normalizeClientPoint(item.location_point);
  if (direct) {
    let source = item.location_source || item.place_source || "amap_poi";
    if (source === "missing") source = item.place_source || "amap_poi";
    return { point: direct, source };
  }
  const text = `${item.title || ""}${item.location || ""}`;
  if (["planning_note", "transport_note"].includes(item.place_source) || item.is_real_place === false) {
    return { point: null, source: "missing" };
  }
  if (item.category === "transfer" && center && item.place_source === "transport_hub") return { point: center, source: "city_center" };
  if ((text.includes("酒店") || text.includes("休整") || item.category === "hotel") && center) {
    return { point: center, source: "hotel_area" };
  }
  if (item.is_real_place && lastPoint) return { point: lastPoint, source: "derived" };
  if (item.is_real_place && center) return { point: center, source: "city_center" };
  return { point: null, source: "missing" };
}

function clientDistanceKm(start, end) {
  const toRad = (value) => (Number(value) * Math.PI) / 180;
  const lat1 = toRad(start.lat);
  const lat2 = toRad(end.lat);
  const deltaLat = lat2 - lat1;
  const deltaLng = toRad(end.lng - start.lng);
  const haversine =
    Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2;
  return Math.max(0.05, 6371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine)));
}

function formatClientDistance(distanceKm) {
  if (distanceKm < 1) return `${Math.round(distanceKm * 1000)} m`;
  return `${distanceKm.toFixed(1)} km`;
}

function fallbackClientDuration(mode, distanceKm) {
  const speed = { walking: 4.5, bicycling: 12, transit: 18, driving: 25, taxi: 25 }[mode] || 18;
  const buffer = { transit: 8, driving: 8, taxi: 5 }[mode] || 0;
  const minutes = Math.max(3, Math.round((distanceKm / speed) * 60 + buffer));
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
}

function selectClientLocalMode(modes = [], distanceKm) {
  const available = Array.from(new Set(modes));
  if (available.includes("walking") && distanceKm <= 1.2) return "walking";
  if (available.includes("bicycling") && distanceKm <= 5) return "bicycling";
  if (distanceKm > 25) {
    if (available.includes("taxi")) return "taxi";
    if (available.includes("driving")) return "driving";
  }
  return ["transit", "driving", "taxi", "walking", "bicycling"].find((mode) => available.includes(mode)) || "taxi";
}

function clientSegmentPrice(mode, distanceKm) {
  if (mode === "taxi") {
    const amount = Math.round(Math.max(12, 8 + distanceKm * 2.8));
    return { amount, text: `约 ¥${amount}/车，距离规则估算`, unit: "party" };
  }
  if (mode === "transit") {
    const amount = Math.round(Math.max(2, Math.min(12, distanceKm * 1.2 + 2)));
    return { amount, text: `约 ¥${amount}/人，规则估算`, unit: "person" };
  }
  if (mode === "driving") {
    const amount = Math.round(Math.max(3, distanceKm * 0.9));
    return { amount, text: `约 ¥${amount}/车，油电规则估算，停车另计`, unit: "party" };
  }
  return { amount: 0, text: "¥0，慢行接驳", unit: "person" };
}

function applyClientRouteJudgement(segment, modes = []) {
  const distanceKm = segmentDistanceKm(segment);
  const minutes = parseDurationMinutes(segment.duration || segment.summary);
  const available = Array.from(new Set(modes));
  const tooLongTransit = segment.mode === "transit" && (minutes > 90 || distanceKm > 35);
  const veryFar = distanceKm > 60;
  if (veryFar || tooLongTransit) {
    if (!veryFar && (available.includes("taxi") || available.includes("driving"))) {
      const mode = available.includes("taxi") ? "taxi" : "driving";
      const price = clientSegmentPrice(mode, distanceKm);
      return {
        ...segment,
        mode,
        mode_label: modeLabel(mode),
        duration: fallbackClientDuration(mode, distanceKm),
        price: price.text,
        cost_estimate: price.amount,
        cost_unit: price.unit,
        source: "rule_fallback",
        status: "mode_switched",
        judge_source: "rule_fallback",
        judge_decision: "switch_mode",
        risk_level: "medium",
        judge_reason: "手动编辑后规则兜底：公共交通距离或耗时过长，已改用更省时方式估算。",
        warning: "打车/自驾费用为距离规则估算，不代表实时价格。",
      };
    }
    return {
      ...segment,
      status: "impractical",
      price: "建议重排，不估算",
      cost_estimate: 0,
      judge_source: "rule_fallback",
      judge_decision: "mark_impractical",
      risk_level: "high",
      judge_reason: "手动编辑后规则兜底：该段距离或公交耗时过长，建议替换或重排景点。",
      warning: "路线待重新规划，不建议作为同一天相邻移动。",
    };
  }
  return {
    ...segment,
    judge_source: segment.judge_source || "rule_fallback",
    judge_decision: segment.judge_decision || "accept",
    risk_level: segment.risk_level || "low",
    judge_reason: segment.judge_reason || "手动编辑后路线距离和耗时在可接受范围内。",
  };
}

function clientSegmentPlace(item) {
  if (item.is_real_place === false) return null;
  if (["planning_note", "transport_note", "llm_suggestion"].includes(item.place_source)) return null;
  const point = normalizeClientPoint(item.location_point);
  const detail = String(item.address || item.location || item.title || "").trim();
  if (!point || !detail) return null;
  return { item, point, detail };
}

function rebuildClientLocalTransport(data) {
  if (!data.local_transport) data.local_transport = { recommended_modes: [], notes: [], segments: [] };
  const modes = data.local_transport.recommended_modes || [];
  const segments = [];
  (data.itinerary_days || []).forEach((day) => {
    (day.items || []).forEach((item) => {
      delete item.arrival_transport_segment;
    });
    const places = (day.items || []).map(clientSegmentPlace).filter(Boolean);
    places.slice(1).forEach((place, index) => {
      const previous = places[index];
      const distanceKm = clientDistanceKm(previous.point, place.point);
      const mode = selectClientLocalMode(modes, distanceKm);
      const price = clientSegmentPrice(mode, distanceKm);
      const segment = applyClientRouteJudgement({
        day: day.day,
        from_detail: previous.detail,
        to_detail: place.detail,
        from_item_id: previous.item.id || "",
        to_item_id: place.item.id || "",
        mode,
        mode_label: modeLabel(mode),
        duration: fallbackClientDuration(mode, distanceKm),
        distance: formatClientDistance(distanceKm),
        distance_km: Number(distanceKm.toFixed(2)),
        price: price.text,
        cost_estimate: price.amount,
        cost_unit: price.unit,
        summary: `${modeLabel(mode)}：${previous.detail} → ${place.detail}，约 ${formatClientDistance(distanceKm)}。`,
        source: "rule_fallback",
        status: "edited",
        warning: "手动编辑后按距离规则估算，未重新调用高德路线。",
      }, modes);
      segments.push(segment);
      place.item.arrival_transport_segment = {
        from_detail: segment.from_detail,
        to_detail: segment.to_detail,
        mode: segment.mode,
        mode_label: segment.mode_label,
        duration: segment.duration,
        distance: segment.distance,
        price: segment.price,
        summary: segment.summary,
        source: segment.source,
        status: segment.status,
        warning: segment.warning,
        judge_source: segment.judge_source,
        judge_decision: segment.judge_decision,
        risk_level: segment.risk_level,
        judge_reason: segment.judge_reason,
        replacement_candidate_id: segment.replacement_candidate_id,
      };
    });
  });
  const notes = (data.local_transport.notes || []).filter((note) => !String(note).includes("手动编辑后"));
  if (segments.length) notes.push("手动编辑后，目的地内路线已按当前行程顺序用距离规则重算。");
  data.local_transport = { ...data.local_transport, notes, segments };
}

function combinedClientSource(items) {
  if (items.some((item) => item.cost_source === "manual_edit")) return "manual_edit";
  if (items.some((item) => item.cost_source === "amap_cost")) return "amap_cost";
  if (items.some((item) => item.cost_source === "amap_route")) return "amap_route";
  if (items.some((item) => item.cost_source === "ai_price_range")) return "ai_price_range";
  if (items.some((item) => ["category_rule", "rule_fallback"].includes(item.cost_source))) return "category_rule";
  if (items.some((item) => item.cost_source === "free_or_no_ticket_default")) return "free_or_no_ticket_default";
  return "unknown_price";
}

function combinedClientSegmentSource(segments) {
  if (segments.some((segment) => segment.source === "amap_route")) return "amap_route";
  if (segments.some((segment) => ["category_rule", "rule_fallback"].includes(segment.source))) return "category_rule";
  return "unknown_price";
}

function estimateClientIntercityCost(data, mode) {
  const travelers = Math.max(1, Number(data.preferences?.travelers || 1));
  const distance = Number(data.preferences?.estimatedDistanceKm || 180);
  const option = (data.intercity_transport?.options || []).find((item) => item.mode === mode);
  const text = `${option?.price || ""} ${option?.summary || ""}`;
  if (mode === "driving") {
    const tollMatch = text.match(/过路费约\s*([0-9.]+)\s*元/);
    if (tollMatch) return { total: Math.round(Number(tollMatch[1]) * 2), source: "amap_route" };
    return { total: Math.round(distance * 1.2), source: "rule_fallback" };
  }
  if (mode === "rail") {
    const rangeMatch = text.match(/([0-9.]+)\s*[~\-～]\s*([0-9.]+)\s*元/);
    if (rangeMatch) {
      const avg = (Number(rangeMatch[1]) + Number(rangeMatch[2])) / 2;
      return { total: Math.round(avg * 2 * travelers), source: "rule_fallback" };
    }
    return { total: Math.round(distance * 0.6 * 2 * travelers), source: "rule_fallback" };
  }
  if (mode === "flight") {
    const oneWay = Math.max(450, Math.min(1800, distance * 0.45));
    return { total: Math.round(oneWay * 2 * travelers), source: "rule_fallback" };
  }
  return { total: Number(data.budget?.breakdown?.intercity_transport || 160 * travelers), source: "rule_fallback" };
}

function getSelectedHotelCandidate(data) {
  const candidates = data?.hotels?.candidates || [];
  if (!candidates.length) return null;
  const selectedId = data?.hotels?.selected_id;
  if (selectedId) {
    const found = candidates.find((item) => item.id === selectedId);
    if (found) return found;
  }
  return candidates[0];
}

function recalculateBudgetAfterEdit(data, options = {}) {
  const budget = data.budget || {};
  const breakdown = { ...(budget.breakdown || {}) };
  const sources = { ...(budget.sources || {}) };
  const travelers = Math.max(1, Number(data.preferences?.travelers || 1));
  const days = data.itinerary_days || [];
  const dayCount = Math.max(1, days.length);
  const nights = Math.max(dayCount - 1, 1);
  const rooms = Math.max(1, Math.floor((travelers + 1) / 2));

  if (options.recalcHotel || data.hotels?.selected_id) {
    const selectedHotel = getSelectedHotelCandidate(data);
    const hotelUnit =
      positiveAmount(selectedHotel?.cost) ||
      positiveAmount(selectedHotel?.cost_estimate) ||
      hotelReferencePrice(data.preferences?.hotelLevel);
    breakdown.hotel = Math.round(hotelUnit * nights * rooms);
    sources.hotel = selectedHotel?.cost_source || "category_rule";
  }

  if (options.recalcIntercity) {
    const intercity = estimateClientIntercityCost(data, data.intercity_transport?.recommended);
    breakdown.intercity_transport = intercity.total;
    sources.intercity_transport = intercity.source;
  }

  const allItems = days.flatMap((day) => day.items || []);
  const foodItems = allItems.filter((item) => item.category === "food");
  const activityItems = allItems.filter((item) => item.category === "activity");
  const foodTotal = foodItems.reduce((sum, item) => sum + (Number(item.cost_estimate) || 0) * travelers, 0);
  const activityTotal = activityItems.reduce((sum, item) => sum + (Number(item.cost_estimate) || 0) * travelers, 0);
  const segments = data.local_transport?.segments || [];
  let movementCount = segments.length;
  let localTotal = 0;
  if (segments.length) {
    localTotal = segments.reduce((sum, segment) => {
      const amount = Number(segment.cost_estimate) || 0;
      return sum + (segment.cost_unit === "party" ? amount : amount * travelers);
    }, 0);
  } else {
    movementCount = days.reduce((sum, day) => {
      const movableItems = (day.items || []).filter(
        (item) => ["activity", "food", "hotel"].includes(item.category) && !["planning_note", "transport_note"].includes(item.place_source),
      );
      return sum + Math.max(0, movableItems.length - 1);
    }, 0);
    const modes = new Set(data.local_transport?.recommended_modes || []);
    let unit = 0;
    if (modes.has("taxi") && modes.has("transit")) unit = 22;
    else if (modes.has("taxi")) unit = 45;
    else if (modes.has("transit")) unit = 7;
    else if (modes.has("driving")) unit = 28;
    else if (modes.has("bicycling")) unit = 5;
    const dailyBuffer = modes.has("taxi") || modes.has("transit") ? 12 : 0;
    localTotal = (movementCount * unit + days.length * dailyBuffer) * travelers;
  }
  breakdown.food = Math.round(foodTotal);
  breakdown.tickets = Math.round(activityTotal);
  breakdown.local_transport = Math.round(localTotal);
  sources.food = combinedClientSource(foodItems);
  sources.tickets = combinedClientSource(activityItems);
  sources.local_transport = segments.length ? combinedClientSegmentSource(segments) : "category_rule";
  const total = Object.values(breakdown).reduce(
    (sum, value) => sum + (Number.isFinite(Number(value)) ? Number(value) : 0),
    0,
  );
  const target = budget.target ?? data.preferences?.budget ?? null;
  data.budget = {
    ...budget,
    total,
    target,
    breakdown,
    sources,
    verdict: target ? (total <= target ? "within_budget" : "over_budget") : "unknown",
    advice: target
      ? `预计总花费约 ${total} 元，${total <= target ? "低于" : "高于"}预算 ${target} 元。`
      : "已按当前手动调整后的每日活动重新估算活动项。",
    basis: [
      ...(budget.basis || []).filter((item) => !String(item).includes("手动调整")),
      `手动调整后，按 ${dayCount} 天（${nights} 晚住宿）、${foodItems.length} 个餐饮项目、${activityItems.length} 个活动项目、约 ${movementCount} 次市内移动重新估算；活动缺少可靠门票价时按无门票/免费项目默认 0 元，仍需核实。`,
    ],
  };
  budgetAdjusted = true;
}

function renumberItineraryDays(data) {
  const days = data?.itinerary_days || [];
  const startDateRaw = String(data?.preferences?.startDate || "").trim();
  const baseDate = /^\d{4}-\d{2}-\d{2}$/.test(startDateRaw) ? new Date(`${startDateRaw}T00:00:00`) : null;
  days.forEach((day, index) => {
    day.day = index + 1;
    if (baseDate && !Number.isNaN(baseDate.getTime())) {
      const nextDate = new Date(baseDate.getTime());
      nextDate.setDate(baseDate.getDate() + index);
      day.date = toDateInputValue(nextDate);
    }
  });
  if (data?.preferences) {
    data.preferences.days = days.length;
  }
}

function finalizeManualPlanMutation(options = {}) {
  if (!currentPlanData) return;
  if (!options.skipRebuild) {
    renumberItineraryDays(currentPlanData);
    (currentPlanData.itinerary_days || []).forEach((day) => {
      normalizeDayItemTimes(day, { force: Boolean(options.forceTimes) });
    });
    rebuildClientMap(currentPlanData);
    rebuildClientLocalTransport(currentPlanData);
    recalculateBudgetAfterEdit(currentPlanData, {
      recalcHotel: Boolean(options.recalcHotel),
      recalcIntercity: Boolean(options.recalcIntercity),
    });
  }
  currentMarkdown = buildMarkdownFromPlan(currentPlanData);
  renderMarkdownResult(currentMarkdown);
  renderPlanResult(currentPlanData, { preserveScroll: true });
  saveSessionSnapshot();
}

function buildItemFromPoiCandidate(poi, dayNumber, slotText, categoryOverride = "") {
  const category =
    categoryOverride ||
    (poi._candidate_category === "food" || /餐|美食|菜|火锅|早茶|面|小吃/.test(String(poi.type || ""))
      ? "food"
      : "activity");
  const isFood = category === "food";
  const cost = positiveAmount(poi.cost) || positiveAmount(poi.cost_estimate) || (isFood ? 80 : 0);
  const costSource =
    poi.cost_source ||
    (positiveAmount(poi.cost)
      ? "amap_cost"
      : isFood
        ? "category_rule"
        : "free_or_no_ticket_default");
  const isCustomSlot = Boolean(slotText && !isDefaultTimeSlot(slotText));
  return {
    id: `manual-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
    poi_id: poi.id || "",
    time: slotText || "下午",
    custom_time: isCustomSlot,
    title: `${poi.name || "自选地点"}${isFood ? "用餐" : "游览"}`,
    location: poi.name || "",
    address: poi.address || "",
    transport: "打车/公共交通/步行",
    duration: isFood ? "1-1.5 小时" : "1.5-2.5 小时",
    detail: poi.description || "用户自由添加到行程的高德真实 POI。",
    category,
    rating: poi.rating || null,
    cost: positiveAmount(poi.cost),
    cost_estimate: cost,
    cost_source: costSource,
    price_range: poi.price_range || (cost ? { min: cost, max: cost, currency: "CNY", unit: "person" } : { min: 0, max: 0, currency: "CNY", unit: "person" }),
    price_confidence: poi.price_confidence || (costSource === "amap_cost" ? "high" : "low"),
    cost_note: poi.cost_note || (isFood ? "按餐厅参考估算，以现场为准。" : "未获取门票价，默认 0 元，出行前请核实。"),
    type: poi.type || "",
    location_point: normalizeClientPoint(poi.location || poi.location_point),
    location_source: normalizeClientPoint(poi.location || poi.location_point) ? "amap_poi" : "missing",
    map_label: "",
    map_included: false,
    photo_url: poi.photo_url || "",
    is_real_place: Boolean(poi.name && (poi.location || poi.location_point || poi.address)),
    place_source: poi.place_source || "amap_poi",
    validation_note: "用户手动加入的高德候选地点。",
    knowledge_detail: poi.knowledge_detail || "",
  };
}

function addNewItineraryDay() {
  if (!currentPlanData) return;
  pushUndoSnapshot();
  if (!Array.isArray(currentPlanData.itinerary_days)) currentPlanData.itinerary_days = [];
  const nextNumber = currentPlanData.itinerary_days.length + 1;
  currentPlanData.itinerary_days.push({
    day: nextNumber,
    date: "",
    theme: `${currentPlanData.preferences?.destinationCity || "目的地"}自由探索日`,
    weather_note: "",
    items: [],
  });
  editingCardKey = null;
  finalizeManualPlanMutation({ recalcHotel: true });
}

function deleteItineraryDay(dayIndex) {
  if (!currentPlanData) return;
  const days = currentPlanData.itinerary_days || [];
  if (days.length <= 1 || dayIndex < 0 || dayIndex >= days.length) return;
  pushUndoSnapshot();
  days.splice(dayIndex, 1);
  editingCardKey = null;
  finalizeManualPlanMutation({ recalcHotel: true });
}

function moveItemBetweenDays(fromDayIndex, fromItemIndex, toDayIndex, toItemIndex = null) {
  if (!currentPlanData) return;
  const days = currentPlanData.itinerary_days || [];
  const sourceDay = days[fromDayIndex];
  const targetDay = days[toDayIndex];
  if (!sourceDay || !targetDay || !Array.isArray(sourceDay.items) || !Array.isArray(targetDay.items)) return;
  if (fromItemIndex < 0 || fromItemIndex >= sourceDay.items.length) return;
  if (fromDayIndex === toDayIndex && (toItemIndex === fromItemIndex || toItemIndex === null)) return;

  pushUndoSnapshot();
  const [moved] = sourceDay.items.splice(fromItemIndex, 1);
  let insertAt = toItemIndex === null ? targetDay.items.length : Number(toItemIndex);
  if (fromDayIndex === toDayIndex && fromItemIndex < insertAt) {
    insertAt = Math.max(0, insertAt - 1);
  }
  insertAt = Math.max(0, Math.min(insertAt, targetDay.items.length));
  targetDay.items.splice(insertAt, 0, moved);
  rememberLearnedHints(["不去太远景点"]);
  editingCardKey = null;
  finalizeManualPlanMutation();
}

function saveInlineItemEdit(form) {
  if (!currentPlanData) return;
  const [dayIdxStr, itemIdxStr] = String(form.dataset.inlineEditForm || "").split(":");
  const dayIndex = Number(dayIdxStr);
  const itemIndex = Number(itemIdxStr);
  const item = currentPlanData.itinerary_days?.[dayIndex]?.items?.[itemIndex];
  if (!item) return;

  const formData = new FormData(form);
  const nextTitle = String(formData.get("title") || "").trim();
  if (!nextTitle) return;

  pushUndoSnapshot();
  const nextTime = String(formData.get("time") || "").trim() || timeSlotForIndex(itemIndex);
  const nextCategory = String(formData.get("category") || item.category || "activity");
  const nextLocation = String(formData.get("location") || "").trim();
  const nextAddress = String(formData.get("address") || "").trim();
  const nextTransport = String(formData.get("transport") || "").trim();
  const nextDuration = String(formData.get("duration") || "").trim();
  const nextDetail = String(formData.get("detail") || "").trim();
  const rawCost = Number(formData.get("cost_estimate"));
  const nextCost = Number.isFinite(rawCost) && rawCost >= 0 ? Math.round(rawCost) : 0;

  item.time = nextTime;
  item.custom_time = !isDefaultTimeSlot(nextTime);
  item.category = nextCategory;
  item.title = nextTitle;
  item.location = nextLocation;
  item.address = nextAddress;
  item.transport = nextTransport;
  item.duration = nextDuration;
  item.detail = nextDetail;

  if (nextCost !== Number(item.cost_estimate || 0)) {
    item.cost_estimate = nextCost;
    item.cost = nextCost;
    item.cost_source = "manual_edit";
    item.price_range = { min: nextCost, max: nextCost, currency: "CNY", unit: "person" };
    item.cost_note = "用户手动编辑的预算单价。";
  }

  editingCardKey = null;
  finalizeManualPlanMutation();
}

function selectHotelCandidate(index) {
  if (!currentPlanData) return;
  const candidates = currentPlanData.hotels?.candidates || [];
  const chosen = candidates[index];
  if (!chosen) return;
  pushUndoSnapshot();
  currentPlanData.hotels.selected_id = chosen.id || `hotel-${index}`;
  const nearby = hotelNearbyLabel(chosen);
  currentPlanData.hotels.area_recommendation = `已选入住：${chosen.name}（${nearby}），便于行程衔接与返程。`;

  const firstDayItems = currentPlanData.itinerary_days?.[0]?.items || [];
  const hotelItem = firstDayItems.find((item) => item.place_source === "hotel_poi" || item.category === "hotel");
  if (hotelItem) {
    hotelItem.title = `抵达后前往住宿：${chosen.name}`;
    hotelItem.location = chosen.name;
    hotelItem.address = chosen.address || "";
    hotelItem.poi_id = chosen.id || "";
    hotelItem.location_point = normalizeClientPoint(chosen.location) || hotelItem.location_point;
    hotelItem.validation_note = "已按用户选定的入住酒店同步更新。";
  }
  finalizeManualPlanMutation({ recalcHotel: true });
}

function selectIntercityMode(mode) {
  if (!currentPlanData || !mode) return;
  if (currentPlanData.intercity_transport?.recommended === mode) return;
  pushUndoSnapshot();
  if (!currentPlanData.intercity_transport) currentPlanData.intercity_transport = { recommended: mode, options: [] };
  currentPlanData.intercity_transport.recommended = mode;
  finalizeManualPlanMutation({ recalcIntercity: true });
}

function addCandidateFromRightPanel(group, index) {
  if (!currentPlanData) return;
  const pool = currentPlanData.pois?.[group] || [];
  const candidate = pool[index];
  if (!candidate) return;
  const days = currentPlanData.itinerary_days || [];
  if (!days.length) return;

  const targetDayIndex = days.length - 1;
  const targetDay = days[targetDayIndex];
  pushUndoSnapshot();
  const category = group === "foods" ? "food" : "activity";
  const slot = timeSlotForIndex((targetDay.items || []).length);
  const newItem = buildItemFromPoiCandidate(candidate, targetDay.day, slot, category);
  targetDay.items = targetDay.items || [];
  targetDay.items.push(newItem);
  editMode = true;
  if (editPlanButton) editPlanButton.textContent = "完成编辑";
  finalizeManualPlanMutation();
}

function applyActivityEdit(card, action) {
  if (!currentPlanData) return;
  const dayIndex = Number(card.dataset.dayIndex);
  const itemIndex = Number(card.dataset.itemIndex);
  const day = currentPlanData.itinerary_days?.[dayIndex];
  if (!day || !Array.isArray(day.items)) return;

  if (action === "edit-inline") {
    const key = `${dayIndex}:${itemIndex}`;
    editingCardKey = editingCardKey === key ? null : key;
    renderPlanResult(currentPlanData, { preserveScroll: true });
    return;
  }
  if (action === "cancel-inline-edit") {
    editingCardKey = null;
    renderPlanResult(currentPlanData, { preserveScroll: true });
    return;
  }
  if (action === "replace") {
    openPlacePickerModal({ mode: "replace", dayIndex, itemIndex });
    return;
  }

  pushUndoSnapshot();
  if (action === "delete") {
    day.items.splice(itemIndex, 1);
    rememberLearnedHints(["别太赶"]);
    editingCardKey = null;
  } else if (action === "move-up" && itemIndex > 0) {
    [day.items[itemIndex - 1], day.items[itemIndex]] = [day.items[itemIndex], day.items[itemIndex - 1]];
    rememberLearnedHints(["不去太远景点"]);
    editingCardKey = null;
  } else if (action === "move-down" && itemIndex < day.items.length - 1) {
    [day.items[itemIndex + 1], day.items[itemIndex]] = [day.items[itemIndex], day.items[itemIndex + 1]];
    rememberLearnedHints(["不去太远景点"]);
    editingCardKey = null;
  }

  normalizeDayItemTimes(day);
  finalizeManualPlanMutation();
}

function buildMarkdownFromPlan(data) {
  const prefs = data.preferences || {};
  const lines = [
    `## ${prefs.originCity || ""} 到 ${prefs.destinationCity || ""} ${prefs.days || ""} 天行程方案`,
    "",
    "### 每日行程",
  ];
  (data.itinerary_days || []).forEach((day) => {
    lines.push(`- 第 ${day.day} 天 ${day.date || ""}：${day.theme || ""}`);
    (day.items || []).forEach((item) => {
      lines.push(`  - ${item.time}｜${item.title}｜${item.location || ""}｜交通：${item.transport || ""}｜${item.detail || ""}`);
      if (item.knowledge_detail) {
        lines.push(`    - 知识库详情：${item.knowledge_detail}`);
      }
      if (item.arrival_transport_segment) {
        const segment = item.arrival_transport_segment;
        lines.push(
          `    - 上一站到本站：${segment.mode_label || modeLabel(segment.mode)}｜${segment.duration || "耗时待核实"}｜${segment.distance || "距离待核实"}｜${segment.price || "价格待核实"}｜${segment.summary || ""}`,
        );
      }
    });
  });
  if (Array.isArray(data.rag_references) && data.rag_references.length) {
    lines.push("", "### 攻略知识参考（RAG）");
    data.rag_references.slice(0, 5).forEach((ref) => {
      const heading = ref.section ? `${ref.title} · ${ref.section}` : ref.title || "攻略片段";
      lines.push(`- ${heading}：${String(ref.content || "").replace(/\s+/g, " ").slice(0, 140)}`);
    });
  }
  if (data.quality_review) {
    const review = data.quality_review;
    lines.push("", "### 智能体检");
    lines.push(`- 总分：${review.overall_score ?? "待评估"}；路线：${review.route_score ?? "-"}；节奏：${review.pace_score ?? "-"}；片区：${review.cluster_score ?? "-"}；逻辑：${review.logic_score ?? "-"}。`);
    (review.issues || []).slice(0, 5).forEach((issue) => lines.push(`- 问题：${issue.day ? `第 ${issue.day} 天，` : ""}${issue.message || ""}`));
    (review.fixes || []).slice(0, 5).forEach((fix) => lines.push(`- 处理：${fix}`));
    (review.constraints || []).slice(0, 8).forEach((constraint) => {
      lines.push(`- 约束${constraintStatusLabel(constraint.status)}：${constraint.text || ""}${constraint.evidence ? `；证据：${constraint.evidence}` : ""}`);
    });
    (review.gate_violations || []).slice(0, 5).forEach((violation) => {
      lines.push(`- 硬门槛提醒：${violation.day ? `第 ${violation.day} 天，` : ""}${violation.message || ""}`);
    });
  }
  lines.push("", "### 预算评估");
  lines.push(`- 预计总计：${data.budget?.total ?? "待校准"} 元；目标预算：${data.budget?.target ?? "未指定"} 元。`);
  lines.push(`- 建议：${data.budget?.advice || ""}`);
  const adjustments = data.budget_adjustments || data.budget?.adjustments;
  if (adjustments?.enabled !== false && Array.isArray(adjustments?.applied) && adjustments.applied.length) {
    lines.push("", "### 预算自动调整");
    if (adjustments.gap_before != null) {
      lines.push(`- 缺口（调整期估算）：${adjustments.gap_before} 元 → ${adjustments.gap_after ?? 0} 元，共 ${adjustments.rounds_used || 0} 轮。`);
    }
    adjustments.applied.slice(0, 8).forEach((action) => {
      lines.push(
        `- ${BUDGET_LEVER_LABELS[action.lever] || action.lever || "调整"}${action.day ? `（第 ${action.day} 天）` : ""}：${action.before?.title || ""}${action.before?.cost != null ? `（${action.before.cost} 元）` : ""} → ${action.after?.title || "移除"}${action.after?.cost != null ? `（${action.after.cost} 元）` : ""}，节省 ${action.saved || 0} 元。${action.reason || ""}`,
      );
    });
    if (adjustments.note) lines.push(`- 说明：${adjustments.note}`);
  }
  lines.push("", "### 天气与出行建议");
  Object.entries(data.weather || {}).forEach(([city, text]) => lines.push(`- ${city}：${text}`));
  ["sun_protection", "clothing", "umbrella", "schedule_note"].forEach((key) => {
    if (data.weather_advice?.[key]) lines.push(`- ${data.weather_advice[key]}`);
  });
  lines.push("", "### 说明");
  lines.push("- 高德 POI 的 cost 是参考消费，不等于实时库存价、实时门票价或可预订价；活动 0 元默认值需出行前核实。");
  return lines.join("\n");
}

function exportMarkdown() {
  const markdown = currentMarkdown || buildMarkdownFromPlan(currentPlanData || {});
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${sanitizeFilename(getPlanTitle())}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function printPlanAsPdf() {
  window.print();
}

function setTrace(trace, options = {}) {
  currentTrace = Array.isArray(trace) ? clonePlan(trace) : [];
  if (!trace || trace.length === 0) {
    traceList.innerHTML = `<div class="empty-state">本次回答未调用工具</div>`;
    if (!options.skipSave) saveSessionSnapshot();
    return;
  }

  traceList.innerHTML = trace
    .map(
      (item, index) => `
        <div class="trace-item">
          <strong>${index + 1}. ${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.status || "success")} · ${escapeHtml(item.duration_ms || "-")} ms</span>
          <code>args: ${escapeHtml(item.args)}</code>
          <code>result: ${escapeHtml(item.output)}</code>
        </div>
      `,
    )
    .join("");
  if (!options.skipSave) saveSessionSnapshot();
}

async function loadTools() {
  try {
    const response = await fetch("/api/tools");
    if (!response.ok) throw new Error(await response.text());
    const tools = await response.json();
    toolList.innerHTML = tools
      .map(
        (tool) => `
          <div class="tool-item">
            <strong>${escapeHtml(tool.name)}</strong>
            <span>${escapeHtml(tool.description || "暂无描述")}</span>
          </div>
        `,
      )
      .join("");
  } catch (error) {
    toolList.innerHTML = `<div class="empty-state">工具加载失败：${escapeHtml(error.message)}</div>`;
  }
}

async function sendMessage(message, options = {}) {
  appendMessage("user", message);
  const pending = appendMessage(
    "assistant",
    currentPlanData ? "正在解析追问并增量修改当前计划..." : "多 Agent 团队正在拆解需求、并行调用 MCP 工具...",
    {
      typing: true,
    },
  );
  followupSendButton.disabled = true;
  if (planButton) {
    planButton.disabled = true;
    planButton.textContent = "处理中...";
  }
  if (options.showProgress) startPlanningProgress();
  const setBubble = (html) => {
    pending.querySelector(".bubble").classList.remove("typing");
    pending.querySelector(".bubble").innerHTML = html;
  };

  try {
    // 结构化追问（Phase 4）：有当前计划时优先尝试 /api/refine-plan；
    // status=ok+changed 更新计划，ok+无变更只回答，失败/不可用自动回退旧链路。
    let handled = false;
    if (currentPlanData) {
      try {
        const refineResponse = await fetch("/api/refine-plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan: currentPlanData, message }),
        });
        if (refineResponse.status === 429 || refineResponse.status === 403) {
          throw new Error(await extractApiErrorMessage(refineResponse, "追问请求被限制"));
        }
        if (refineResponse.ok) {
          const data = await refineResponse.json();
          if (data.status === "ok" && data.changed) {
            currentPlanData = normalizePlanData(clonePlan(data.plan));
            currentMarkdown = data.markdown || buildMarkdownFromPlan(currentPlanData);
            budgetAdjusted = false;
            editMode = false;
            renderPlanResult(currentPlanData);
            renderMarkdownResult(currentMarkdown);
            const badge = currentPlanData.version ? `计划已更新到 v${currentPlanData.version}。` : "计划已更新。";
            const text = `${badge}\n\n${data.explanation || ""}`;
            setBubble(renderMarkdown(text));
            recordFollowupMessage("assistant", text, { skipSave: true });
            setTrace([], { skipSave: true });
            if (options.showProgress) completePlanningProgress();
            handled = true;
          } else if (data.status === "ok") {
            const text = data.explanation || "本次未对计划做修改。";
            setBubble(renderMarkdown(text));
            recordFollowupMessage("assistant", text, { skipSave: true });
            setTrace([], { skipSave: true });
            handled = true;
          }
          // status === "failed"：保持未处理，回退旧链路
        }
      } catch (refineError) {
        if (/限|额度|次数|用完|频繁|禁用/.test(String(refineError?.message || ""))) {
          throw refineError;
        }
        // refine 不可用（网络/503），回退旧链路
      }
    }

    if (!handled) {
      const legacyResponse = await fetch("/api/multi-agent-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });

      if (!legacyResponse.ok) {
        throw new Error(await extractApiErrorMessage(legacyResponse, "请求失败"));
      }

      const data = await legacyResponse.json();
      const answer = data.answer || "没有生成回答。";
      const labeled = currentPlanData ? `（旧链路文本回答，未修改当前计划）\n\n${answer}` : answer;
      setBubble(renderMarkdown(labeled));
      recordFollowupMessage("assistant", labeled, { skipSave: true });
      setTrace(data.trace, { skipSave: true });
      if (options.showProgress) completePlanningProgress();
    }
  } catch (error) {
    const failureMessage = `请求失败：${error.message}`;
    setBubble(renderMarkdown(failureMessage));
    recordFollowupMessage("assistant", failureMessage, { skipSave: true });
    setTrace([], { skipSave: true });
    if (options.showProgress) failPlanningProgress();
  } finally {
    followupSendButton.disabled = false;
    if (planButton) {
      planButton.disabled = false;
      planButton.textContent = "开始规划";
    }
    saveSessionSnapshot();
    scrollFollowupToBottom();
    refreshQuotaStatus();
  }
}

// 后端 _record 步骤名 → 前端 8 阶段进度（Phase 5：真实事件驱动进度）。
const BACKEND_STEP_TO_STAGE = {
  WeatherAgent: 2,
  WeatherAdviceAgent: 2,
  IntercityTransportAgent: 1,
  POIAgent: 3,
  KnowledgeAgent: 3,
  RAGKnowledgeAgent: 4,
  HotelAgent: 4,
  LocalMobilityAgent: 5,
  DeepSeekPlanningBrainAgent: 5,
  DayPlannerAgent: 5,
  ItineraryReviewAgent: 6,
  BudgetOptimizerAgent: 6,
  MapAgent: 6,
  BudgetAgent: 7,
  QualityGateAgent: 7,
  WriterAgent: 7,
};

function stageForStep(stepName) {
  const text = String(stepName || "");
  if (text.indexOf("LocalMobilityAgent 目的地内路线") === 0) return 6;
  return BACKEND_STEP_TO_STAGE[text.split(" ")[0]] ?? 5;
}

const activeTaskStorageKey = "travelmind:activeTask:v1";
let activeEventSource = null;

function saveActiveTask(value) {
  try {
    sessionStorage.setItem(activeTaskStorageKey, JSON.stringify(value));
  } catch (storageError) {
    /* sessionStorage 不可用时跳过（刷新恢复降级为无） */
  }
}

function readActiveTask() {
  try {
    const raw = sessionStorage.getItem(activeTaskStorageKey);
    return raw ? JSON.parse(raw) : null;
  } catch (storageError) {
    return null;
  }
}

function clearActiveTask() {
  try {
    sessionStorage.removeItem(activeTaskStorageKey);
  } catch (storageError) {
    /* ignore */
  }
}

function consumePlanEvents(taskId) {
  // SSE 消费真实进度；断线由浏览器自动重连（服务端按 Last-Event-ID 重放），
  // done/error 后显式 close 防止重连风暴。120s 无事件触发看门狗报错。
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/plan-events/${encodeURIComponent(taskId)}`);
    activeEventSource = es;
    let watchdog = null;
    const armWatchdog = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => {
        es.close();
        activeEventSource = null;
        reject(new Error("事件流 120 秒无响应，请稍后重试或刷新页面恢复"));
      }, 120000);
    };
    armWatchdog();
    const finish = (settle, value) => {
      clearTimeout(watchdog);
      es.close();
      activeEventSource = null;
      settle(value);
    };
    ["step_start", "step_end"].forEach((type) => {
      es.addEventListener(type, (evt) => {
        armWatchdog();
        try {
          const data = JSON.parse(evt.data || "{}");
          if (type === "step_start") {
            const stage = stageForStep(data.step);
            progressIndex = stage;
            renderProgressSteps(stage);
            setProgress(Math.min(92, 8 + stage * 12), planningStages[stage]);
          }
        } catch (parseError) {
          /* 忽略坏事件，等待下一个 */
        }
      });
    });
    es.addEventListener("done", () => {
      armWatchdog();
      finish(resolve, true);
    });
    es.addEventListener("error", (evt) => {
      if (evt && evt.data) {
        let data = {};
        try {
          data = JSON.parse(evt.data);
        } catch (parseError) {
          data = {};
        }
        finish(reject, new Error(data.message || "任务失败"));
        return;
      }
      if (es.readyState === EventSource.CLOSED) {
        clearTimeout(watchdog);
        activeEventSource = null;
        reject(new Error("事件流已断开"));
      }
      // readyState=CONNECTING：浏览器自动重连，继续等待。
    });
  });
}

async function fetchTaskPlan(taskId) {
  // done 事件后取计划快照；服务端已保证「快照先落库、done 最后写」，
  // 此处短重试仅为磁盘/调度抖动的纵深防御。
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const response = await fetch(`/api/task/${encodeURIComponent(taskId)}`);
    if (response.ok) {
      const data = await response.json();
      if (data.plan) return data.plan;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error("任务已完成但计划快照不可用");
}

async function sendPlanAsync(payload) {
  // 返回 "fallback" 表示任务未启动、可安全回退同步端点；否则返回计划 JSON。
  const requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  let submit;
  try {
    submit = await fetch("/api/plan-async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, clientRequestId: requestId }),
    });
  } catch (networkError) {
    return "fallback";
  }
  if (!submit.ok) {
    if ([404, 405, 501, 503].includes(submit.status)) return "fallback";
    throw new Error(await extractApiErrorMessage(submit, "提交规划失败"));
  }
  const submitData = await submit.json();
  saveActiveTask({ taskId: submitData.task_id, requestId });
  progressIndex = 0;
  renderProgressSteps(0);
  setProgress(8, planningStages[0]);
  await consumePlanEvents(submitData.task_id);
  const plan = await fetchTaskPlan(submitData.task_id);
  clearActiveTask();
  return plan;
}

async function sendPlanSync(payload) {
  // 同步回退路径（Phase 4 之前的唯一路径）：AbortController 120s 超时（D7 最小修复）。
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await extractApiErrorMessage(response, "规划请求失败"));
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function sendPlan(payload) {
  const message = buildTripPrompt();
  appendMessage("user", message);
  const pending = appendMessage("assistant", "正在生成结构化行程，完成后会显示在主结果页。", {
    typing: true,
  });
  followupSendButton.disabled = true;
  if (planButton) {
    planButton.disabled = true;
    planButton.textContent = "规划中...";
  }
  startPlanningProgress();

  try {
    let data;
    if (window.EventSource) {
      const outcome = await sendPlanAsync(payload);
      data = outcome === "fallback" ? await sendPlanSync(payload) : outcome;
    } else {
      data = await sendPlanSync(payload);
    }
    currentPlanData = normalizePlanData(clonePlan(data));
    currentMarkdown = data.markdown || buildMarkdownFromPlan(currentPlanData);
    budgetAdjusted = false;
    editMode = false;
    clearEditHistory();
    if (editPlanButton) editPlanButton.textContent = "编辑行程";
    renderPlanResult(currentPlanData);
    renderMarkdownResult(currentMarkdown);
    setActiveTab("result", { skipSave: true });
    const doneMessage =
      "已生成结构化行程，可在右侧继续追问或调整。需要查看完整文本时，切换左侧“方案原文”标签。";
    pending.querySelector(".bubble").classList.remove("typing");
    pending.querySelector(".bubble").innerHTML = renderMarkdown(doneMessage);
    recordFollowupMessage("assistant", doneMessage, { skipSave: true });
    setTrace(data.trace, { skipSave: true });
    completePlanningProgress();
    planningProgress.hidden = true;
    saveSessionSnapshot();
    scrollWorkspaceToTop();
  } catch (error) {
    const failureMessage = `请求失败：${error.message}`;
    pending.querySelector(".bubble").classList.remove("typing");
    pending.querySelector(".bubble").innerHTML = renderMarkdown(failureMessage);
    recordFollowupMessage("assistant", failureMessage, { skipSave: true });
    setTrace([], { skipSave: true });
    failPlanningProgress();
    saveSessionSnapshot();
  } finally {
    followupSendButton.disabled = false;
    if (planButton) {
      planButton.disabled = false;
      planButton.textContent = "开始规划";
    }
    refreshQuotaStatus();
  }
}

async function restoreActiveTask() {
  // 刷新恢复：页面加载时若存在未完成的任务，重连 SSE 续传真实进度。
  const active = readActiveTask();
  if (!active || !active.taskId || !window.EventSource) return;
  planningProgress.hidden = false;
  followupSendButton.disabled = true;
  if (planButton) {
    planButton.disabled = true;
    planButton.textContent = "规划中...";
  }
  startPlanningProgress();
  try {
    await consumePlanEvents(active.taskId);
    const plan = await fetchTaskPlan(active.taskId);
    clearActiveTask();
    currentPlanData = normalizePlanData(clonePlan(plan));
    currentMarkdown = plan.markdown || buildMarkdownFromPlan(currentPlanData);
    budgetAdjusted = false;
    editMode = false;
    renderPlanResult(currentPlanData);
    renderMarkdownResult(currentMarkdown);
    setActiveTab("result", { skipSave: true });
    setTrace(plan.trace || [], { skipSave: true });
    completePlanningProgress();
    planningProgress.hidden = true;
    saveSessionSnapshot();
  } catch (error) {
    clearActiveTask();
    failPlanningProgress();
    appendMessage("assistant", `恢复进行中的规划失败：${error.message}`, { skipSave: true });
  } finally {
    followupSendButton.disabled = false;
    if (planButton) {
      planButton.disabled = false;
      planButton.textContent = "开始规划";
    }
    refreshQuotaStatus();
  }
}

followupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = followupInput.value.trim();
  if (!message) return;
  followupInput.value = "";
  sendMessage(message);
});

tripForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendPlan(buildPlanPayload());
});

followupInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    followupForm.requestSubmit();
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    followupInput.value = button.dataset.prompt;
    const followupPanel = document.querySelector(".followup-panel");
    if (followupPanel) followupPanel.open = true;
    followupInput.focus();
  });
});

tripForm.addEventListener("input", updateSelectionSummary);
tripForm.addEventListener("change", updateSelectionSummary);

resetButton.addEventListener("click", async () => {
  await fetch("/api/reset", { method: "POST" });
  clearInterval(progressTimer);
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
  clearActiveTask();
  planningProgress.hidden = true;
  currentPlanData = null;
  currentMarkdown = "";
  followupMessages = [];
  currentTrace = [];
  activeTabName = "result";
  editMode = false;
  budgetAdjusted = false;
  clearEditHistory();
  clearSessionSnapshot();
  renderEmptyResult();
  setActiveTab("result", { skipSave: true });
  setProgress(0, "准备开始");
  followupLog.innerHTML = "";
  appendMessage(
    "assistant",
    "会话已清空。可以重新填写左侧表单生成行程，或在这里继续追问。",
    { persist: false },
  );
  setTrace([], { skipSave: true });
});

if (backHomeButton) {
  backHomeButton.addEventListener("click", () => {
    clearInterval(progressTimer);
    planningProgress.hidden = true;
    renderSavedHomeState();
  });
}

/* ===========================
 * RAG 知识库弹窗 & 地点选择器弹窗
 * =========================== */

function setRagModalTab(tabName) {
  document.querySelectorAll("[data-rag-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.ragTab === tabName);
  });
  const panels = {
    docs: document.querySelector("#ragTabDocs"),
    upload: document.querySelector("#ragTabUpload"),
    search: document.querySelector("#ragTabSearch"),
  };
  Object.entries(panels).forEach(([key, panel]) => {
    if (panel) panel.hidden = key !== tabName;
  });
}

async function refreshRagDocs() {
  if (!ragDocList) return;
  try {
    const response = await fetch("/api/rag/docs");
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    const modeText = ragModeLabel(data.retrieval_mode);
    if (ragStatusLine) {
      ragStatusLine.textContent = `当前模式：${modeText} · 共 ${data.total_docs || 0} 篇攻略 / ${data.total_chunks || 0} 个语义分块`;
    }
    const docs = Array.isArray(data.documents) ? data.documents : [];
    if (!docs.length) {
      ragDocList.innerHTML = `<div class="empty-state">知识库暂无攻略，切换到“上传/新建攻略”即可添加。</div>`;
      return;
    }
    ragDocList.innerHTML = docs
      .map(
        (doc) => `
          <article class="rag-doc-item">
            <div class="rag-doc-head">
              <div>
                <strong>${escapeHtml(doc.title)}</strong>
                <span class="rag-origin-tag ${doc.origin_type === "custom" ? "custom" : "builtin"}">${doc.origin_type === "custom" ? "自定义" : "内置"}</span>
                <span class="rag-city-tag">${escapeHtml(doc.city || "通用")}</span>
              </div>
              ${
                doc.origin_type === "custom"
                  ? `<button type="button" class="mini-action-btn danger" data-delete-rag-doc="${escapeHtml(doc.doc_id)}">删除</button>`
                  : `<span class="rag-meta-muted">${escapeHtml(doc.chunk_count)} 块</span>`
              }
            </div>
            <p>${escapeHtml(doc.preview || "")}</p>
            <div class="rag-ref-foot">
              <span>分类：${escapeHtml(doc.category || "攻略")}</span>
              <span>标签：${escapeHtml((doc.tags || []).join(" / ") || "无")}</span>
              <span>更新：${escapeHtml(doc.updated_at || "-")}</span>
            </div>
          </article>
        `,
      )
      .join("");
  } catch (error) {
    if (ragStatusLine) ragStatusLine.textContent = "加载知识库失败";
    ragDocList.innerHTML = `<div class="empty-state">加载失败：${escapeHtml(error.message)}</div>`;
  }
}

function openRagModal(defaultTab = "docs") {
  if (!ragModal) return;
  ragModal.hidden = false;
  setRagModalTab(defaultTab);
  const currentCity = currentPlanData?.preferences?.destinationCity || document.querySelector("#destinationCity")?.value || "";
  if (ragSearchCity && !ragSearchCity.value && currentCity) ragSearchCity.value = currentCity;
  if (ragDocCity && ragDocCity.value === "通用" && currentCity) ragDocCity.value = currentCity;
  if (ragUploadMessage) ragUploadMessage.textContent = "";
  refreshRagDocs();
}

function closeModalById(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.hidden = true;
}

function setPickerTab(tabName) {
  document.querySelectorAll("[data-picker-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.pickerTab === tabName);
  });
  const amapPanel = document.querySelector("#pickerTabAmap");
  const customPanel = document.querySelector("#pickerTabCustom");
  if (amapPanel) amapPanel.hidden = tabName !== "amap";
  if (customPanel) customPanel.hidden = tabName !== "custom";
}

function renderPickerExistingPool() {
  if (!pickerExistingPool || !currentPlanData) return;
  const usedIds = new Set(
    (currentPlanData.itinerary_days || [])
      .flatMap((day) => day.items || [])
      .map((item) => item.poi_id)
      .filter(Boolean),
  );
  const attractions = (currentPlanData.pois?.attractions || []).map((item, idx) => ({
    ...item,
    _poolGroup: "attractions",
    _poolIdx: idx,
    _poolCat: "activity",
  }));
  const foods = (currentPlanData.pois?.foods || []).map((item, idx) => ({
    ...item,
    _poolGroup: "foods",
    _poolIdx: idx,
    _poolCat: "food",
  }));
  const all = [...attractions, ...foods];
  if (!all.length) {
    pickerExistingPool.innerHTML = `<div class="empty-state">当前规划暂无内置候选池，请在上方搜索高德地点或切换到“自由自定义节点”。</div>`;
    return;
  }
  const btnText = pickerContext.mode === "replace" ? "替换为此地点" : "+ 加入行程";
  pickerExistingPool.innerHTML = all
    .slice(0, 16)
    .map(
      (item) => `
        <div class="picker-poi-row">
          <div>
            <strong>${escapeHtml(item.name)}${usedIds.has(item.id) ? ` <em class="used-flag">已在行程中</em>` : ""}</strong>
            <span>${escapeHtml(item.address || item.description || "")}</span>
            <small>${escapeHtml(item._poolCat === "food" ? "美食" : "景点")} · ${renderPoiMeta(item)}</small>
          </div>
          <button type="button" class="mini-action-btn" data-pick-pool-group="${escapeHtml(item._poolGroup)}" data-pick-pool-index="${item._poolIdx}">${btnText}</button>
        </div>
      `,
    )
    .join("");
}

function renderPoiSearchResults(items) {
  latestPoiSearchItems = Array.isArray(items) ? items : [];
  if (!poiSearchResults) return;
  if (!latestPoiSearchItems.length) {
    poiSearchResults.innerHTML = `<div class="empty-state">没有检索到匹配的高德地点，可换个关键词或切换到“自由自定义节点”。</div>`;
    return;
  }
  const btnText = pickerContext.mode === "replace" ? "替换为此地点" : "+ 加入行程";
  poiSearchResults.innerHTML = latestPoiSearchItems
    .map(
      (item, index) => `
        <div class="picker-poi-row">
          <div>
            <strong>${escapeHtml(item.name || "未命名")}</strong>
            <span>${escapeHtml(item.address || item.description || "")}</span>
            <small>${renderPoiMeta(item)}</small>
          </div>
          <button type="button" class="mini-action-btn" data-pick-search-index="${index}">${btnText}</button>
        </div>
      `,
    )
    .join("");
}

function openPlacePickerModal(options = {}) {
  if (!placePickerModal || !currentPlanData) return;
  const days = currentPlanData.itinerary_days || [];
  pickerContext = {
    mode: options.mode === "replace" ? "replace" : "add",
    dayIndex: Math.max(0, Math.min(Number(options.dayIndex || 0), Math.max(days.length - 1, 0))),
    itemIndex: options.itemIndex ?? null,
  };
  if (placePickerTitle) {
    placePickerTitle.textContent =
      pickerContext.mode === "replace" ? "替换当前行程节点" : "添加新地点或自定义活动";
  }
  if (placePickerSub) {
    placePickerSub.textContent =
      pickerContext.mode === "replace"
        ? "从高德实时搜索、候选池或自定义内容中选一项，原地替换当前节点。"
        : "支持实时搜索高德 POI 景点/餐厅并附带坐标，也支持完全自由填写自定义日程。";
  }
  if (pickerTargetDay) {
    pickerTargetDay.innerHTML = days
      .map((day, idx) => `<option value="${idx}" ${idx === pickerContext.dayIndex ? "selected" : ""}>第 ${day.day} 天（${escapeHtml(day.theme || "")}）</option>`)
      .join("");
    pickerTargetDay.disabled = pickerContext.mode === "replace";
  }

  const existingItem =
    pickerContext.mode === "replace" && pickerContext.itemIndex !== null
      ? days[pickerContext.dayIndex]?.items?.[pickerContext.itemIndex]
      : null;

  if (pickerTargetCategory) pickerTargetCategory.value = existingItem?.category || "activity";
  if (pickerTargetTime) pickerTargetTime.value = existingItem?.time || "";
  if (poiSearchCity) poiSearchCity.value = currentPlanData.preferences?.destinationCity || "";
  if (poiSearchKeyword) poiSearchKeyword.value = "";
  if (poiSearchStatus) poiSearchStatus.textContent = "";
  if (poiSearchResults) poiSearchResults.innerHTML = "";
  if (customItemForm) customItemForm.reset();

  setPickerTab("amap");
  renderPickerExistingPool();
  placePickerModal.hidden = false;
}

function commitPickedItem(newItem) {
  if (!currentPlanData) return;
  const targetDayIndex = Number(pickerTargetDay?.value ?? pickerContext.dayIndex ?? 0);
  const day = currentPlanData.itinerary_days?.[targetDayIndex];
  if (!day) return;
  day.items = day.items || [];

  pushUndoSnapshot();
  if (pickerContext.mode === "replace" && pickerContext.itemIndex !== null && day.items[pickerContext.itemIndex]) {
    const oldItem = day.items[pickerContext.itemIndex];
    const customTime = String(pickerTargetTime?.value || "").trim();
    newItem.time = customTime || oldItem.time || timeSlotForIndex(pickerContext.itemIndex);
    newItem.custom_time = !isDefaultTimeSlot(newItem.time);
    day.items.splice(pickerContext.itemIndex, 1, newItem);
  } else {
    const customTime = String(pickerTargetTime?.value || "").trim();
    newItem.time = customTime || timeSlotForIndex(day.items.length);
    newItem.custom_time = Boolean(customTime && !isDefaultTimeSlot(customTime));
    day.items.push(newItem);
  }

  editingCardKey = null;
  closeModalById("placePickerModal");
  finalizeManualPlanMutation();
}

if (editPlanButton) {
  editPlanButton.addEventListener("click", () => {
    if (!currentPlanData) return;
    editMode = !editMode;
    if (!editMode) editingCardKey = null;
    editPlanButton.textContent = editMode ? "完成编辑" : "编辑行程";
    renderPlanResult(currentPlanData, { preserveScroll: true });
    saveSessionSnapshot();
  });
}

if (openRagModalButton) {
  openRagModalButton.addEventListener("click", () => openRagModal("docs"));
}

if (exportButton) {
  exportButton.addEventListener("click", () => {
    exportMenu.hidden = !exportMenu.hidden;
  });
}

if (exportMenu) {
  exportMenu.addEventListener("click", (event) => {
    const button = event.target.closest("[data-export]");
    if (!button) return;
    exportMenu.hidden = true;
    if (button.dataset.export === "markdown") exportMarkdown();
    if (button.dataset.export === "pdf") printPlanAsPdf();
  });
}

planResult.addEventListener("click", (event) => {
  if (event.target.closest(".day-theme-input")) {
    event.stopPropagation();
    return;
  }

  const quickEdit = event.target.closest("[data-quick-enter-edit]");
  if (quickEdit && currentPlanData) {
    editMode = true;
    if (editPlanButton) editPlanButton.textContent = "完成编辑";
    renderPlanResult(currentPlanData, { preserveScroll: true });
    saveSessionSnapshot();
    return;
  }

  const openRagBtn = event.target.closest("[data-open-rag-modal]");
  if (openRagBtn) {
    openRagModal("upload");
    return;
  }

  const sessionButton = event.target.closest("[data-session-action]");
  if (sessionButton?.dataset.sessionAction === "restore-plan") {
    renderCurrentPlanFromState();
    return;
  }

  const selectHotelBtn = event.target.closest("[data-select-hotel-index]");
  if (selectHotelBtn) {
    selectHotelCandidate(Number(selectHotelBtn.dataset.selectHotelIndex));
    return;
  }

  const selectIntercityBtn = event.target.closest("[data-select-intercity-mode]");
  if (selectIntercityBtn) {
    selectIntercityMode(selectIntercityBtn.dataset.selectIntercityMode);
    return;
  }

  const addCandBtn = event.target.closest("[data-add-candidate-group]");
  if (addCandBtn) {
    addCandidateFromRightPanel(
      addCandBtn.dataset.addCandidateGroup,
      Number(addCandBtn.dataset.addCandidateIndex),
    );
    return;
  }

  const toolbarBtn = event.target.closest("[data-toolbar-action]");
  if (toolbarBtn && editMode) {
    const action = toolbarBtn.dataset.toolbarAction;
    if (action === "add-day") addNewItineraryDay();
    else if (action === "add-item") openPlacePickerModal({ mode: "add", dayIndex: 0 });
    else if (action === "undo") undoPlanEdit();
    else if (action === "redo") redoPlanEdit();
    else if (action === "reset-times") {
      pushUndoSnapshot();
      finalizeManualPlanMutation({ forceTimes: true });
    }
    return;
  }

  const dayActionBtn = event.target.closest("[data-day-action]");
  if (dayActionBtn) {
    event.preventDefault();
    event.stopPropagation();
    const dayIndex = Number(dayActionBtn.dataset.dayIndex);
    if (dayActionBtn.dataset.dayAction === "add-item") {
      openPlacePickerModal({ mode: "add", dayIndex });
    } else if (dayActionBtn.dataset.dayAction === "delete-day") {
      deleteItineraryDay(dayIndex);
    }
    return;
  }

  const actionButton = event.target.closest("[data-action]");
  if (!actionButton || !editMode) return;
  const card = actionButton.closest(".activity-card");
  if (!card) return;
  applyActivityEdit(card, actionButton.dataset.action);
});

planResult.addEventListener("change", (event) => {
  const moveSelect = event.target.closest("[data-move-day-select]");
  if (moveSelect && editMode) {
    const targetDayIndex = Number(moveSelect.value);
    const card = moveSelect.closest(".activity-card");
    if (card && Number.isInteger(targetDayIndex)) {
      moveItemBetweenDays(Number(card.dataset.dayIndex), Number(card.dataset.itemIndex), targetDayIndex, null);
    }
    return;
  }

  const themeInput = event.target.closest("[data-day-theme-index]");
  if (themeInput && currentPlanData) {
    const dayIndex = Number(themeInput.dataset.dayThemeIndex);
    const day = currentPlanData.itinerary_days?.[dayIndex];
    if (day && day.theme !== themeInput.value.trim()) {
      pushUndoSnapshot();
      day.theme = themeInput.value.trim() || `第 ${day.day} 天行程`;
      currentMarkdown = buildMarkdownFromPlan(currentPlanData);
      renderMarkdownResult(currentMarkdown);
      saveSessionSnapshot();
    }
  }
});

planResult.addEventListener("submit", (event) => {
  const inlineForm = event.target.closest("[data-inline-edit-form]");
  if (!inlineForm) return;
  event.preventDefault();
  saveInlineItemEdit(inlineForm);
});

planResult.addEventListener("dragstart", (event) => {
  if (!editMode) return;
  const card = event.target.closest(".activity-card[draggable='true']");
  if (!card) return;
  dragSource = {
    dayIndex: Number(card.dataset.dayIndex),
    itemIndex: Number(card.dataset.itemIndex),
  };
  card.classList.add("dragging");
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", JSON.stringify(dragSource));
  }
});

planResult.addEventListener("dragend", () => {
  dragSource = null;
  planResult.querySelectorAll(".dragging, .drag-over").forEach((el) => {
    el.classList.remove("dragging", "drag-over");
  });
});

planResult.addEventListener("dragover", (event) => {
  if (!editMode || !dragSource) return;
  const targetCard = event.target.closest(".activity-card");
  const targetDropzone = event.target.closest("[data-day-dropzone]");
  if (!targetCard && !targetDropzone) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  planResult.querySelectorAll(".drag-over").forEach((el) => el.classList.remove("drag-over"));
  if (targetCard) targetCard.classList.add("drag-over");
  else if (targetDropzone) targetDropzone.classList.add("drag-over");
});

planResult.addEventListener("drop", (event) => {
  if (!editMode || !dragSource) return;
  const targetCard = event.target.closest(".activity-card");
  const targetDropzone = event.target.closest("[data-day-dropzone]");
  if (!targetCard && !targetDropzone) return;
  event.preventDefault();
  const source = dragSource;
  dragSource = null;
  planResult.querySelectorAll(".dragging, .drag-over").forEach((el) => {
    el.classList.remove("dragging", "drag-over");
  });

  if (targetCard) {
    moveItemBetweenDays(
      source.dayIndex,
      source.itemIndex,
      Number(targetCard.dataset.dayIndex),
      Number(targetCard.dataset.itemIndex),
    );
  } else if (targetDropzone) {
    moveItemBetweenDays(
      source.dayIndex,
      source.itemIndex,
      Number(targetDropzone.dataset.dayDropzone),
      null,
    );
  }
});

document.addEventListener("click", (event) => {
  const closeBtn = event.target.closest("[data-close-modal]");
  if (closeBtn) {
    closeModalById(closeBtn.dataset.closeModal);
    return;
  }
  if (event.target.classList?.contains("modal-backdrop")) {
    event.target.hidden = true;
    return;
  }
  const ragTabBtn = event.target.closest("[data-rag-tab]");
  if (ragTabBtn) {
    setRagModalTab(ragTabBtn.dataset.ragTab);
    return;
  }
  const pickerTabBtn = event.target.closest("[data-picker-tab]");
  if (pickerTabBtn) {
    setPickerTab(pickerTabBtn.dataset.pickerTab);
    return;
  }
  const presetBtn = event.target.closest("[data-preset-id]");
  if (presetBtn) {
    loadPresetPlan(presetBtn.dataset.presetId);
    return;
  }
  const delRagBtn = event.target.closest("[data-delete-rag-doc]");
  if (delRagBtn) {
    const docId = delRagBtn.dataset.deleteRagDoc;
    fetch(`/api/rag/docs/${encodeURIComponent(docId)}`, {
      method: "DELETE",
      headers: getAdminTokenHeaders(),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(await extractApiErrorMessage(res, "删除失败"));
        return refreshRagDocs();
      })
      .catch((err) => {
        if (ragStatusLine) ragStatusLine.textContent = `删除失败：${err.message}`;
      });
    return;
  }
  const pickSearchBtn = event.target.closest("[data-pick-search-index]");
  if (pickSearchBtn) {
    const poi = latestPoiSearchItems[Number(pickSearchBtn.dataset.pickSearchIndex)];
    if (poi) {
      const targetDayIndex = Number(pickerTargetDay?.value ?? pickerContext.dayIndex ?? 0);
      const dayNum = currentPlanData?.itinerary_days?.[targetDayIndex]?.day || targetDayIndex + 1;
      const item = buildItemFromPoiCandidate(
        poi,
        dayNum,
        String(pickerTargetTime?.value || "").trim(),
        pickerTargetCategory?.value || "",
      );
      commitPickedItem(item);
    }
    return;
  }
  const pickPoolBtn = event.target.closest("[data-pick-pool-group]");
  if (pickPoolBtn && currentPlanData) {
    const group = pickPoolBtn.dataset.pickPoolGroup;
    const idx = Number(pickPoolBtn.dataset.pickPoolIndex);
    const poi = currentPlanData.pois?.[group]?.[idx];
    if (poi) {
      const targetDayIndex = Number(pickerTargetDay?.value ?? pickerContext.dayIndex ?? 0);
      const dayNum = currentPlanData.itinerary_days?.[targetDayIndex]?.day || targetDayIndex + 1;
      const item = buildItemFromPoiCandidate(
        poi,
        dayNum,
        String(pickerTargetTime?.value || "").trim(),
        group === "foods" ? "food" : pickerTargetCategory?.value || "activity",
      );
      commitPickedItem(item);
    }
  }
});

if (ragDocFile) {
  ragDocFile.addEventListener("change", async () => {
    const file = ragDocFile.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      if (ragDocContent) ragDocContent.value = text;
      if (ragDocTitle && !ragDocTitle.value.trim()) {
        ragDocTitle.value = file.name.replace(/\.(md|markdown|txt)$/i, "");
      }
      if (ragUploadMessage) ragUploadMessage.textContent = `已读入文件：${file.name}（${text.length} 字）`;
    } catch (error) {
      if (ragUploadMessage) ragUploadMessage.textContent = `读取文件失败：${error.message}`;
    }
  });
}

if (ragAdminTokenInput) {
  try {
    ragAdminTokenInput.value = sessionStorage.getItem(adminTokenStorageKey) || "";
  } catch (err) {
    /* ignore */
  }
  ragAdminTokenInput.addEventListener("input", () => {
    try {
      sessionStorage.setItem(adminTokenStorageKey, ragAdminTokenInput.value.trim());
    } catch (err) {
      /* ignore */
    }
  });
}

if (ragUploadForm) {
  ragUploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (ragUploadSubmit) ragUploadSubmit.disabled = true;
    if (ragUploadMessage) ragUploadMessage.textContent = "正在入库并更新索引...";
    try {
      const response = await fetch("/api/rag/docs", {
        method: "POST",
        headers: getAdminTokenHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          title: ragDocTitle.value.trim(),
          city: ragDocCity.value.trim() || "通用",
          tags: ragDocTags.value.trim(),
          content: ragDocContent.value.trim(),
        }),
      });
      if (!response.ok) throw new Error(await extractApiErrorMessage(response, "保存失败"));
      ragUploadForm.reset();
      if (ragDocCity) ragDocCity.value = currentPlanData?.preferences?.destinationCity || "通用";
      if (ragUploadMessage) ragUploadMessage.textContent = "攻略已成功入库！后续规划与检索将自动生效。";
      await refreshRagDocs();
      setRagModalTab("docs");
    } catch (error) {
      if (ragUploadMessage) ragUploadMessage.textContent = `保存失败：${error.message}`;
    } finally {
      if (ragUploadSubmit) ragUploadSubmit.disabled = false;
    }
  });
}

if (ragSearchForm) {
  ragSearchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = ragSearchQuery.value.trim();
    if (!query) return;
    ragSearchResults.innerHTML = `<div class="empty-state">检索中...</div>`;
    try {
      const response = await fetch("/api/rag/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          city: ragSearchCity.value.trim(),
          top_k: 5,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      const hits = Array.isArray(data.hits) ? data.hits : [];
      if (!hits.length) {
        ragSearchResults.innerHTML = `<div class="empty-state">未召回相关片段，可尝试放宽城市过滤或上传自定义攻略。</div>`;
        return;
      }
      ragSearchResults.innerHTML = hits
        .map(
          (hit) => `
            <article class="rag-ref-card">
              <div class="rag-ref-head">
                <strong>${escapeHtml(hit.title)}${hit.section ? ` · ${escapeHtml(hit.section)}` : ""}</strong>
                <span class="rag-origin-tag ${hit.origin_type === "custom" ? "custom" : "builtin"}">${hit.origin_type === "custom" ? "自定义" : "内置"}</span>
              </div>
              <p>${escapeHtml(hit.content)}</p>
              <div class="rag-ref-foot">
                <span>城市：${escapeHtml(hit.city || "通用")}</span>
                <span>匹配：${escapeHtml((hit.match_reasons || []).join(" · "))}</span>
                <span>模式：${escapeHtml(ragModeLabel(hit.retrieval_mode))} · 分值 ${escapeHtml(hit.score)}</span>
              </div>
            </article>
          `,
        )
        .join("");
    } catch (error) {
      ragSearchResults.innerHTML = `<div class="empty-state">检索失败：${escapeHtml(error.message)}</div>`;
    }
  });
}

if (poiSearchForm) {
  poiSearchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const keyword = poiSearchKeyword.value.trim();
    const city = poiSearchCity.value.trim() || currentPlanData?.preferences?.destinationCity || "深圳";
    if (!keyword) return;
    if (poiSearchSubmit) poiSearchSubmit.disabled = true;
    if (poiSearchStatus) poiSearchStatus.textContent = `正在高德地图中搜索「${city} · ${keyword}」...`;
    try {
      const response = await fetch("/api/poi/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city, keyword, limit: 8 }),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      if (poiSearchStatus) {
        poiSearchStatus.textContent = items.length
          ? `找到 ${items.length} 个真实高德 POI（来源：${data.source || "amap"}），点击即可加入行程。`
          : "未找到高德 POI，可更换关键词或切到“自由自定义节点”。";
      }
      renderPoiSearchResults(items);
    } catch (error) {
      if (poiSearchStatus) poiSearchStatus.textContent = `搜索失败：${error.message}`;
      renderPoiSearchResults([]);
    } finally {
      if (poiSearchSubmit) poiSearchSubmit.disabled = false;
    }
  });
}

if (customItemForm) {
  customItemForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const title = customItemTitle.value.trim();
    if (!title) return;
    const category = pickerTargetCategory?.value || "activity";
    const costVal = Math.max(0, Math.round(Number(customItemCost.value) || 0));
    const slotText = String(pickerTargetTime?.value || "").trim();
    const customItem = {
      id: `custom-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
      poi_id: "",
      time: slotText || "下午",
      custom_time: Boolean(slotText && !isDefaultTimeSlot(slotText)),
      title,
      location: customItemLocation.value.trim() || title,
      address: customItemAddress.value.trim(),
      transport: customItemTransport.value.trim() || "打车/步行",
      duration: customItemDuration.value.trim() || "1.5 小时",
      detail: customItemDetail.value.trim() || "用户自由添加的自定义日程节点。",
      category,
      rating: null,
      cost: costVal > 0 ? costVal : null,
      cost_estimate: costVal,
      cost_source: costVal > 0 ? "manual_edit" : "free_or_no_ticket_default",
      price_range: { min: costVal, max: costVal, currency: "CNY", unit: "person" },
      price_confidence: "medium",
      cost_note: costVal > 0 ? "用户自定义单人预算。" : "自定义安排，默认 0 元。",
      type: "自定义日程",
      location_point: null,
      location_source: "missing",
      map_label: "",
      map_included: false,
      photo_url: "",
      is_real_place: false,
      place_source: "user_custom",
      validation_note: "用户手动添加的自由安排。",
    };
    commitPickedItem(customItem);
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModalById("ragModal");
    closeModalById("placePickerModal");
    return;
  }
  const tag = String(event.target?.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return;
  if (!editMode) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redoPlanEdit();
    else undoPlanEdit();
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redoPlanEdit();
  }
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.tab));
});

navLinks.forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.querySelector(`#${button.dataset.scrollTarget}`);
    if (!target) return;
    navLinks.forEach((item) => item.classList.toggle("active", item === button));
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

if (navCollapseButton) {
  navCollapseButton.addEventListener("click", () => {
    setNavCollapsed(!appShell.classList.contains("nav-collapsed"));
  });
}

if (modifyPanel) {
  modifyPanel.addEventListener("toggle", () => {
    appShell.classList.toggle("show-inputs", modifyPanel.open);
    if (inputPanels && appShell.classList.contains("has-plan")) {
      inputPanels.hidden = !modifyPanel.open;
    }
  });
}

setupDefaultDate();
updateSelectionSummary();
if (!restoreSessionSnapshot()) {
  renderEmptyResult();
}
if (toolList && !toolList.closest("[hidden]")) loadTools();
refreshQuotaStatus();
restoreActiveTask();

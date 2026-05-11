import { fetchJson } from "/assets/scripts/api.js";
import {
  clearStoredToken,
  escapeHtml,
  formatTimestamp,
  getStoredToken,
  initialsFromEmail,
} from "/assets/scripts/session.js";

const appState = {
  user: null,
  prompts: [],
  documents: [],
  histories: [],
  activeHistoryId: null,
  messages: [],
  isTyping: false,
};

const elements = {
  logoutButton: document.querySelector("#logout-button"),
  newChatButton: document.querySelector("#new-chat-button"),
  userName: document.querySelector("#user-name"),
  userEmail: document.querySelector("#user-email"),
  roleBadge: document.querySelector("#role-badge"),
  historyCount: document.querySelector("#history-count"),
  historyList: document.querySelector("#history-list"),
  documentList: document.querySelector("#document-list"),
  documentsPanel: document.querySelector("#documents-panel"),
  docCount: document.querySelector("#doc-count"),
  promptList: document.querySelector("#prompt-list"),
  chatLog: document.querySelector("#chat-log"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#message-input"),
  sendButton: document.querySelector("#send-button"),
  fileInput: document.querySelector("#file-input"),
  adminUploadPanel: document.querySelector("#admin-upload-panel"),
  appNotice: document.querySelector("#app-notice"),
  currentChatTitle: document.querySelector("#current-chat-title"),
};

bootstrap();

async function bootstrap() {
  if (!getStoredToken()) {
    window.location.replace("/login");
    return;
  }

  bindEvents();
  autoResizeTextarea();
  renderPrompts();
  renderDocuments();
  renderHistories();
  renderMessages();

  try {
    await loadBootstrapData();
    setNotice("");
  } catch {
    clearStoredToken();
    window.location.replace("/login");
  }
}

function bindEvents() {
  elements.logoutButton.addEventListener("click", handleLogout);
  elements.newChatButton.addEventListener("click", handleNewChat);
  elements.composer.addEventListener("submit", handleComposerSubmit);
  elements.messageInput.addEventListener("input", autoResizeTextarea);
  elements.fileInput.addEventListener("change", handleFileUpload);
}

async function handleLogout() {
  try {
    await fetchJson("/api/logout", { method: "POST", redirectOnAuthFailure: false });
  } catch {
    // Ignore logout failures.
  }

  clearStoredToken();
  window.location.replace("/login");
}

function handleNewChat() {
  appState.activeHistoryId = null;
  appState.messages = [];
  renderHistories();
  renderMessages();
  updateCurrentTitle();
  setNotice("");
}

async function handleComposerSubmit(event) {
  event.preventDefault();
  if (appState.isTyping) {
    return;
  }

  const message = elements.messageInput.value.trim();
  if (!message) {
    return;
  }

  appState.isTyping = true;
  elements.sendButton.disabled = true;
  setNotice("Хариулт боловсруулж байна...");

  try {
    const response = await fetchJson("/api/chat", {
      method: "POST",
      body: {
        message,
        historyId: appState.activeHistoryId,
      },
    });

    elements.messageInput.value = "";
    autoResizeTextarea();
    applyHistoryResponse(response.history);
    appState.documents = response.documents;
    renderDocuments();
    setNotice("");
  } catch (error) {
    setNotice(error.message || "Chat илгээх үед алдаа гарлаа.", "error");
  } finally {
    appState.isTyping = false;
    elements.sendButton.disabled = false;
  }
}

async function handleHistorySelect(historyId) {
  try {
    const response = await fetchJson(`/api/history?id=${encodeURIComponent(historyId)}`);
    applyHistoryResponse(response.history);
    setNotice("");
  } catch (error) {
    setNotice(error.message || "Chat history ачаалж чадсангүй.", "error");
  }
}

async function handleFileUpload(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    return;
  }

  try {
    const payloadFiles = await Promise.all(
      files.map(async (file) => {
        const extension = getExtension(file.name);

        if (extension === ".pdf") {
          const bytes = new Uint8Array(await file.arrayBuffer());
          return {
            name: file.name,
            encoding: "base64",
            content: bytesToBase64(bytes),
          };
        }

        return {
          name: file.name,
          encoding: "utf8",
          content: await file.text(),
        };
      }),
    );

    const response = await fetchJson("/api/upload", {
      method: "POST",
      body: { files: payloadFiles },
    });

    appState.documents = [...response.documents, ...appState.documents];
    renderDocuments();
    const warnings = Array.isArray(response.warnings) ? response.warnings.filter(Boolean) : [];
    const uploadMessage = warnings.length
      ? `${response.documents.length} файл knowledge base-д нэмэгдлээ. ${warnings.join(" ")}`
      : `${response.documents.length} файл knowledge base-д нэмэгдлээ.`;
    setNotice(uploadMessage, warnings.length ? "warning" : "success");
  } catch (error) {
    setNotice(error.message || "Файл upload хийх үед алдаа гарлаа.", "error");
  } finally {
    event.target.value = "";
  }
}

async function loadBootstrapData() {
  const response = await fetchJson("/api/bootstrap");
  appState.user = response.user;
  appState.prompts = response.prompts;
  appState.documents = response.documents;
  appState.histories = response.histories;
  renderUser();
  renderPrompts();
  renderDocuments();
  renderHistories();

  if (appState.histories.length) {
    const responseHistory = await fetchJson(`/api/history?id=${encodeURIComponent(appState.histories[0].id)}`);
    applyHistoryResponse(responseHistory.history);
    return;
  }

  appState.activeHistoryId = null;
  appState.messages = [];
  renderMessages();
  updateCurrentTitle();
}

function applyHistoryResponse(history) {
  appState.activeHistoryId = history.id;
  appState.messages = history.messages || [];
  upsertHistorySummary(history);
  renderHistories();
  renderMessages();
  updateCurrentTitle();
}

function upsertHistorySummary(history) {
  const summary = {
    id: history.id,
    title: history.title,
    createdAt: history.createdAt,
    updatedAt: history.updatedAt,
    messageCount: history.messageCount ?? (history.messages || []).length,
  };

  const existingIndex = appState.histories.findIndex((entry) => entry.id === summary.id);
  if (existingIndex >= 0) {
    appState.histories.splice(existingIndex, 1);
  }

  appState.histories.unshift(summary);
  appState.histories.sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt));
}

function renderUser() {
  elements.userName.textContent = appState.user?.name || "Хэрэглэгч";
  elements.userEmail.textContent = appState.user?.email || "";
  elements.roleBadge.textContent = appState.user?.role || "";
  elements.adminUploadPanel.classList.toggle("hidden", appState.user?.role !== "admin");
  elements.documentsPanel.classList.toggle("hidden", appState.user?.role !== "admin");
}

function renderHistories() {
  elements.historyCount.textContent = `${appState.histories.length} чат`;
  elements.historyList.innerHTML = "";

  if (!appState.histories.length) {
    elements.historyList.innerHTML = `<p class="panel-caption">Хадгалсан чат алга.</p>`;
    return;
  }

  appState.histories.forEach((history) => {
    const button = document.createElement("button");
    button.className = `history-item${history.id === appState.activeHistoryId ? " active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <strong>${escapeHtml(history.title)}</strong>
      <p class="history-meta">${escapeHtml(formatHistoryMeta(history))}</p>
    `;
    button.addEventListener("click", () => handleHistorySelect(history.id));
    elements.historyList.appendChild(button);
  });
}

function renderDocuments() {
  elements.docCount.textContent = `${appState.documents.length} файл`;
  elements.documentList.innerHTML = "";

  if (!appState.documents.length) {
    elements.documentList.innerHTML = `<p class="panel-caption">Индексэлсэн файл алга.</p>`;
    return;
  }

  appState.documents.forEach((documentItem) => {
    const item = document.createElement("article");
    item.className = "document-item";
    item.innerHTML = `
      <strong>${escapeHtml(documentItem.title)}</strong>
      <p class="document-meta">${escapeHtml(documentItem.summary || "No preview available.")}</p>
    `;
    elements.documentList.appendChild(item);
  });
}

function renderPrompts() {
  elements.promptList.innerHTML = "";

  appState.prompts.forEach((prompt) => {
    const button = document.createElement("button");
    button.className = "prompt-chip";
    button.type = "button";
    button.textContent = prompt;
    button.addEventListener("click", () => {
      elements.messageInput.value = prompt;
      autoResizeTextarea();
      elements.messageInput.focus();
    });
    elements.promptList.appendChild(button);
  });
}

function renderMessages() {
  if (!appState.messages.length) {
    elements.chatLog.innerHTML = `
      <div class="empty-state">
        <div class="empty-card">
          <p class="eyebrow">Saved History</p>
          <h2>Backend-тэй chatbot бэлэн байна</h2>
          <p>Асуултаа бичээд шууд эхлүүлж болно.</p>
        </div>
      </div>
    `;
    return;
  }

  elements.chatLog.innerHTML = "";

  appState.messages.forEach((message) => {
    const row = document.createElement("div");
    row.className = `message-row ${message.role}`;
    const avatarLabel = message.role === "bot" ? "AI" : initialsFromEmail(appState.user?.email);
    const citationsMarkup =
      message.role === "bot" && Array.isArray(message.citations) && message.citations.length
        ? `<div class="citations">${message.citations
            .map((citation) => `<span class="citation">${escapeHtml(citation.title)}</span>`)
            .join("")}</div>`
        : "";

    row.innerHTML = `
      ${message.role === "bot" ? `<div class="avatar bot">${avatarLabel}</div>` : ""}
      <div class="bubble-wrap">
        <div class="bubble">${escapeHtml(message.text)}</div>
        ${citationsMarkup}
        <div class="message-meta">${formatTimestamp(message.timestamp)}</div>
      </div>
      ${message.role === "user" ? `<div class="avatar user">${avatarLabel}</div>` : ""}
    `;
    elements.chatLog.appendChild(row);
  });

  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function updateCurrentTitle() {
  const activeHistory = appState.histories.find((history) => history.id === appState.activeHistoryId);
  elements.currentChatTitle.textContent = activeHistory?.title || "Шинэ чат";
}

function setNotice(message, tone = "") {
  elements.appNotice.textContent = message || "";
  elements.appNotice.className = `app-notice${tone ? ` ${tone}` : ""}`;
}

function formatHistoryMeta(history) {
  const updated = formatTimestamp(history.updatedAt);
  const messageCount = history.messageCount || 0;
  return `${messageCount} message • ${updated}`;
}

function autoResizeTextarea() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 176)}px`;
}

function getExtension(filename) {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

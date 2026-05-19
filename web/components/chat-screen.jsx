"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import LogoMark from "@/components/logo-mark";
import { fetchJson } from "@/lib/api";
import {
  bytesToBase64,
  clearStoredToken,
  formatTimestamp,
  getExtension,
  getStoredToken,
  initialsFromEmail,
  optimizeImageForUpload,
} from "@/lib/session";

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"];
const BINARY_UPLOAD_EXTENSIONS = [".pdf", ".doc", ".docx", ".xls", ".xlsx"];

const EMPTY_STATE = {
  user: null,
  prompts: [],
  documents: [],
  chatDocuments: [],
  submissions: [],
  histories: [],
  activeHistoryId: null,
  messages: [],
};

function renderInlineMarkup(text, keyPrefix) {
  const nodes = [];
  const pattern = /(\*\*[^*]+\*\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let lastIndex = 0;
  let match;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-strong-${index}`}>{token.slice(2, -2)}</strong>,
      );
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a
            key={`${keyPrefix}-link-${index}`}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer"
          >
            {linkMatch[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }

    lastIndex = pattern.lastIndex;
    index += 1;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function renderStructuredMessage(text) {
  const lines = String(text || "").split("\n");
  const elements = [];
  let paragraph = [];
  let bulletItems = [];
  let numberedItems = [];
  let key = 0;

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    const joined = paragraph.join(" ").trim();
    if (joined) {
      elements.push(
        <p key={`p-${key}`} className="rich-text-paragraph">
          {renderInlineMarkup(joined, `p-${key}`)}
        </p>,
      );
      key += 1;
    }
    paragraph = [];
  }

  function flushBullets() {
    if (!bulletItems.length) {
      return;
    }
    elements.push(
      <ul key={`ul-${key}`} className="rich-text-list">
        {bulletItems.map((item, itemIndex) => (
          <li key={`ul-${key}-${itemIndex}`}>{renderInlineMarkup(item, `ul-${key}-${itemIndex}`)}</li>
        ))}
      </ul>,
    );
    key += 1;
    bulletItems = [];
  }

  function flushNumbered() {
    if (!numberedItems.length) {
      return;
    }
    elements.push(
      <ol key={`ol-${key}`} className="rich-text-list rich-text-ordered">
        {numberedItems.map((item, itemIndex) => (
          <li key={`ol-${key}-${itemIndex}`}>{renderInlineMarkup(item, `ol-${key}-${itemIndex}`)}</li>
        ))}
      </ol>,
    );
    key += 1;
    numberedItems = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushBullets();
      flushNumbered();
      continue;
    }

    if (/^[-*•]\s+/.test(line)) {
      flushParagraph();
      flushNumbered();
      bulletItems.push(line.replace(/^[-*•]\s+/, "").trim());
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      flushParagraph();
      flushBullets();
      numberedItems.push(line.replace(/^\d+\.\s+/, "").trim());
      continue;
    }

    flushBullets();
    flushNumbered();

    if (/^\*\*.+\*\*$/.test(line)) {
      flushParagraph();
      elements.push(
        <p key={`heading-${key}`} className="rich-text-heading">
          {renderInlineMarkup(line, `heading-${key}`)}
        </p>,
      );
      key += 1;
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  flushBullets();
  flushNumbered();

  return elements;
}

export default function ChatScreen() {
  const router = useRouter();
  const [appState, setAppState] = useState(EMPTY_STATE);
  const [isTyping, setIsTyping] = useState(false);
  const [pendingMessage, setPendingMessage] = useState(null);
  const [notice, setNotice] = useState({ text: "", tone: "" });
  const [message, setMessage] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeHistoryMenuId, setActiveHistoryMenuId] = useState("");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmittingDocument, setIsSubmittingDocument] = useState(false);
  const textareaRef = useRef(null);
  const chatLogRef = useRef(null);
  const fileInputRef = useRef(null);
  const submissionInputRef = useRef(null);

  useEffect(() => {
    if (!getStoredToken()) {
      router.replace("/login");
      return;
    }

    void loadBootstrapData();
  }, [router]);

  useEffect(() => {
    autoResizeTextarea();
  }, [message]);

  useEffect(() => {
    if (chatLogRef.current) {
      chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
    }
  }, [appState.messages, isTyping]);

  useEffect(() => {
    function handleWindowClick(event) {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      if (!target.closest("[data-chat-menu-root]")) {
        setActiveHistoryMenuId("");
        setUserMenuOpen(false);
      }
    }

    window.addEventListener("click", handleWindowClick);
    return () => window.removeEventListener("click", handleWindowClick);
  }, []);

  const activeHistory = useMemo(
    () => appState.histories.find((history) => history.id === appState.activeHistoryId) || null,
    [appState.activeHistoryId, appState.histories],
  );
  const renderedMessages = useMemo(() => {
    if (!pendingMessage) {
      return appState.messages;
    }
    return [
      ...appState.messages,
      {
        role: "user",
        text: pendingMessage.text,
        timestamp: pendingMessage.timestamp,
        citations: [],
        pending: true,
      },
    ];
  }, [appState.messages, pendingMessage]);

  async function loadBootstrapData() {
    try {
      const response = await fetchJson("/api/bootstrap?scope=chat");
      setAppState((current) => ({
        ...current,
        user: response.user,
        prompts: response.prompts,
        documents: response.documents || [],
        chatDocuments: response.chatDocuments || [],
        submissions: response.submissions || [],
        histories: response.histories,
      }));

      if (response.histories.length) {
        const historyResponse = await fetchJson(
          `/api/history?id=${encodeURIComponent(response.histories[0].id)}`,
        );
        applyHistoryResponse(
          historyResponse.history,
          response.documents || [],
          response.prompts,
          response.user,
        );
      } else {
        setAppState((current) => ({
          ...current,
          user: response.user,
          prompts: response.prompts,
          documents: response.documents || [],
          chatDocuments: response.chatDocuments || [],
          submissions: response.submissions || [],
          histories: response.histories,
          activeHistoryId: null,
          messages: [],
        }));
      }

      setNotice({ text: "", tone: "" });
    } catch {
      clearStoredToken();
      router.replace("/login");
    }
  }

  function applyHistoryResponse(history, documentsOverride, promptsOverride, userOverride) {
    setAppState((current) => {
      const summary = {
        id: history.id,
        title: history.title,
        createdAt: history.createdAt,
        updatedAt: history.updatedAt,
        messageCount: history.messageCount ?? (history.messages || []).length,
      };

      const nextHistories = current.histories.filter((entry) => entry.id !== summary.id);
      nextHistories.unshift(summary);
      nextHistories.sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt));

      return {
        user: userOverride ?? current.user,
        prompts: promptsOverride ?? current.prompts,
        documents: documentsOverride ?? current.documents,
        chatDocuments: current.chatDocuments,
        submissions: current.submissions,
        histories: nextHistories,
        activeHistoryId: history.id,
        messages: history.messages || [],
      };
    });
  }

  async function handleLogout() {
    try {
      await fetchJson("/api/logout", { method: "POST", redirectOnAuthFailure: false });
    } catch {
      // ignore
    }

    clearStoredToken();
    router.replace("/login");
  }

  function handleNewChat() {
    setAppState((current) => ({
      ...current,
      activeHistoryId: null,
      messages: [],
    }));
    setPendingMessage(null);
    setMessage("");
    setActiveHistoryMenuId("");
    setNotice({ text: "", tone: "" });
  }

  async function handleComposerSubmit(event) {
    event.preventDefault();
    if (isTyping || !message.trim()) {
      return;
    }

    const trimmedMessage = message.trim();
    const optimisticMessage = {
      text: trimmedMessage,
      timestamp: new Date().toISOString(),
    };

    setMessage("");
    setPendingMessage(optimisticMessage);
    setIsTyping(true);
    setNotice({ text: "", tone: "" });

    try {
      const response = await fetchJson("/api/chat", {
        method: "POST",
        body: {
          message: trimmedMessage,
          historyId: appState.activeHistoryId,
        },
      });

      setPendingMessage(null);
      applyHistoryResponse(response.history, response.documents);
      setNotice({ text: "", tone: "" });
    } catch (submitError) {
      setPendingMessage(null);
      setMessage(trimmedMessage);
      setNotice({
        text: submitError.message || "Chat илгээх үед алдаа гарлаа.",
        tone: "error",
      });
    } finally {
      setIsTyping(false);
    }
  }

  async function handleHistorySelect(historyId) {
    try {
      const response = await fetchJson(`/api/history?id=${encodeURIComponent(historyId)}`);
      applyHistoryResponse(response.history);
      setActiveHistoryMenuId("");
      setNotice({ text: "", tone: "" });
    } catch (historyError) {
      setNotice({
        text: historyError.message || "Chat history ачаалж чадсангүй.",
        tone: "error",
      });
    }
  }

  async function handleHistoryRename(history) {
    setRenameTarget(history);
    setRenameDraft(history.title || "Шинэ чат");
    setActiveHistoryMenuId("");
  }

  async function submitHistoryRename() {
    if (!renameTarget || !renameDraft.trim()) {
      return;
    }
    try {
      const response = await fetchJson("/api/history/rename", {
        method: "POST",
        body: {
          historyId: renameTarget.id,
          title: renameDraft.trim(),
        },
      });

      setAppState((current) => {
        const nextHistories = response.histories || current.histories;
        const nextMessages = current.messages;
        return {
          ...current,
          histories: nextHistories,
          messages: nextMessages,
        };
      });
      setRenameTarget(null);
      setRenameDraft("");
    } catch (renameError) {
      setNotice({
        text: renameError.message || "Чатын нэр солих үед алдаа гарлаа.",
        tone: "error",
      });
    }
  }

  async function handleHistoryDelete(history) {
    const shouldDelete = window.confirm("Энэ chat history-г устгах уу?");
    if (!shouldDelete) {
      setActiveHistoryMenuId("");
      return;
    }

    const previousHistories = appState.histories;
    const previousActiveHistoryId = appState.activeHistoryId;
    const previousMessages = appState.messages;
    const wasActive = previousActiveHistoryId === history.id;
    const optimisticHistories = previousHistories.filter((entry) => entry.id !== history.id);

    setAppState((current) => ({
      ...current,
      histories: current.histories.filter((entry) => entry.id !== history.id),
      activeHistoryId: current.activeHistoryId === history.id ? null : current.activeHistoryId,
      messages: current.activeHistoryId === history.id ? [] : current.messages,
    }));
    setActiveHistoryMenuId("");

    try {
      const response = await fetchJson("/api/history/delete", {
        method: "POST",
        body: {
          historyId: history.id,
        },
      });

      const remainingHistories = response.histories || optimisticHistories;
      setAppState((current) => ({
        ...current,
        histories: remainingHistories,
        activeHistoryId: wasActive ? null : current.activeHistoryId,
        messages: wasActive ? [] : current.messages,
      }));

      if (wasActive && remainingHistories.length) {
        await handleHistorySelect(remainingHistories[0].id);
      }
    } catch (deleteError) {
      setAppState((current) => ({
        ...current,
        histories: previousHistories,
        activeHistoryId: previousActiveHistoryId,
        messages: previousMessages,
      }));
      setNotice({
        text: deleteError.message || "Chat устгах үед алдаа гарлаа.",
        tone: "error",
      });
    }
  }

  async function handleComposerUpload(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      return;
    }

    setIsUploading(true);
    setNotice({ text: "", tone: "" });

    try {
      const payloadFiles = await Promise.all(
        files.map(async (file) => {
          const extension = getExtension(file.name);
          if (
            BINARY_UPLOAD_EXTENSIONS.includes(extension) ||
            file.type.startsWith("image/") ||
            IMAGE_EXTENSIONS.includes(extension)
          ) {
            const optimized =
              file.type.startsWith("image/")
                ? await optimizeImageForUpload(file)
                : {
                    fileName: file.name,
                    mimeType: file.type,
                    bytes: new Uint8Array(await file.arrayBuffer()),
                  };
            return {
              name: optimized.fileName,
              encoding: "base64",
              content: bytesToBase64(optimized.bytes),
              mimeType: optimized.mimeType,
            };
          }

          return {
            name: file.name,
            encoding: "utf8",
            content: await file.text(),
            mimeType: file.type,
          };
        }),
      );

      const response = await fetchJson("/api/chat/upload", {
        method: "POST",
        body: { files: payloadFiles },
      });

      setAppState((current) => ({
        ...current,
        documents: [...response.documents, ...current.documents],
        chatDocuments: [...response.documents, ...current.chatDocuments],
      }));

      const warnings = Array.isArray(response.warnings)
        ? response.warnings.filter(Boolean)
        : [];
      if (warnings.length) {
        setNotice({ text: warnings.join(" "), tone: "warning" });
      }
    } catch (uploadError) {
      setNotice({
        text: uploadError.message || "Файл upload хийх үед алдаа гарлаа.",
        tone: "error",
      });
    } finally {
      setIsUploading(false);
      event.target.value = "";
    }
  }

  async function handleSubmissionUpload(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      return;
    }

    setIsSubmittingDocument(true);
    setNotice({ text: "", tone: "" });

    try {
      const payloadFiles = await Promise.all(
        files.map(async (file) => {
          const extension = getExtension(file.name);
          if (
            file.type.startsWith("image/") ||
            BINARY_UPLOAD_EXTENSIONS.includes(extension) ||
            IMAGE_EXTENSIONS.includes(extension)
          ) {
            const optimized =
              file.type.startsWith("image/")
                ? await optimizeImageForUpload(file)
                : {
                    fileName: file.name,
                    mimeType: file.type,
                    bytes: new Uint8Array(await file.arrayBuffer()),
                  };
            return {
              name: optimized.fileName,
              encoding: "base64",
              content: bytesToBase64(optimized.bytes),
              mimeType: optimized.mimeType,
            };
          }

          return {
            name: file.name,
            encoding: "utf8",
            content: await file.text(),
            mimeType: file.type,
          };
        }),
      );

      const response = await fetchJson("/api/submission/upload", {
        method: "POST",
        body: { files: payloadFiles },
      });

      setAppState((current) => ({
        ...current,
        submissions: [...(response.submissions || []), ...(current.submissions || [])],
      }));
      setNotice({
        text: response.message || "Баримтыг илгээлээ.",
        tone: response.tone || "success",
      });
    } catch (uploadError) {
      setNotice({
        text: uploadError.message || "Баримт илгээх үед алдаа гарлаа.",
        tone: "error",
      });
    } finally {
      setIsSubmittingDocument(false);
      event.target.value = "";
    }
  }

  async function handleRemoveChatUpload(documentId) {
    try {
      const response = await fetchJson("/api/chat/upload/delete", {
        method: "POST",
        body: { documentId },
      });
      setAppState((current) => ({
        ...current,
        chatDocuments: response.documents || [],
      }));
    } catch (removeError) {
      setNotice({
        text: removeError.message || "Файл салгах үед алдаа гарлаа.",
        tone: "error",
      });
    }
  }

  function autoResizeTextarea() {
    const node = textareaRef.current;
    if (!node) {
      return;
    }
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 176)}px`;
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }

    if (event.nativeEvent?.isComposing) {
      return;
    }

    event.preventDefault();
    if (isTyping || !message.trim()) {
      return;
    }
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <main className="chat-body">
      <div className="background-orb orb-left" />
      <div className="background-orb orb-right" />

      <div className="chat-shell">
        <section className={`app-layout chat-app-shell${sidebarOpen ? "" : " sidebar-collapsed"}`}>
          <aside className="sidebar user-chat-sidebar">
            <div className="chat-brand-lockup">
              <LogoMark className="mini-badge chat-brand-badge" />
              <div>
                <p className="chat-brand-overline">Сос Медика Монгол</p>
                <h2>Ухаалаг туслах</h2>
              </div>
            </div>

            <div className="chat-sidebar-actions">
              <button className="new-chat-rail-button new-chat-rail-button-secondary" type="button" onClick={handleNewChat}>
                <span className="new-chat-rail-icon">
                  <EditIcon />
                </span>
                <span>Шинэ чат үүсгэх</span>
              </button>

              <input
                ref={submissionInputRef}
                id="submission-file-input"
                type="file"
                accept=".pdf,.doc,.docx,.xls,.xlsx,image/*,.txt,.md,.json,.csv"
                multiple
                hidden
                onChange={handleSubmissionUpload}
              />
              <button
                className="new-chat-rail-button new-chat-rail-button-secondary"
                type="button"
                onClick={() => submissionInputRef.current?.click()}
                disabled={isSubmittingDocument}
              >
                <span className="new-chat-rail-icon">
                  <UploadIcon />
                </span>
                <span>{isSubmittingDocument ? "Баримт илгээж байна..." : "Баримт илгээх"}</span>
              </button>
            </div>

            <div className="chat-history-block">
              <p className="chat-history-label">Chat History</p>
              <div className="chat-history-scroll">
                {appState.histories.length ? (
                  appState.histories.map((history) => {
                    const isActive = history.id === appState.activeHistoryId;
                    return (
                      <div
                        className={`chat-history-row${isActive ? " active" : ""}`}
                        key={history.id}
                      >
                        <button
                          className="chat-history-main"
                          type="button"
                          onClick={() => handleHistorySelect(history.id)}
                        >
                          <span className="chat-history-icon" aria-hidden="true">
                            <ChatBubbleIcon />
                          </span>
                          <span className="chat-history-title">
                            {formatCompactHistoryTitle(history.title)}
                          </span>
                        </button>

                        <div className="menu-anchor" data-chat-menu-root>
                          <button
                            className="history-menu-button"
                            type="button"
                            aria-label="History menu"
                            onClick={(event) => {
                              event.stopPropagation();
                              setUserMenuOpen(false);
                              setActiveHistoryMenuId((current) =>
                                current === history.id ? "" : history.id,
                              );
                            }}
                          >
                            <EllipsisIcon />
                          </button>

                          {activeHistoryMenuId === history.id ? (
                            <div className="popup-menu history-popup-menu">
                              <button
                                className="popup-menu-item"
                                type="button"
                                onClick={() => handleHistoryRename(history)}
                              >
                                <EditIcon />
                                <span>Rename</span>
                              </button>
                              <button
                                className="popup-menu-item danger"
                                type="button"
                                onClick={() => handleHistoryDelete(history)}
                              >
                                <TrashIcon />
                                <span>Delete</span>
                              </button>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="chat-history-empty">Chat history хоосон байна.</p>
                )}
              </div>
            </div>

            <div className="chat-user-footer" data-chat-menu-root>
              <button
                className="chat-user-trigger"
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setActiveHistoryMenuId("");
                  setUserMenuOpen((current) => !current);
                }}
              >
                <span className="chat-user-avatar">
                  {initialsFromEmail(appState.user?.email)}
                </span>
                <span className="chat-user-name">{appState.user?.name || "Хэрэглэгч"}</span>
                <ChevronUpDownIcon />
              </button>

              {userMenuOpen ? (
                <div className="popup-menu chat-user-menu">
                  {appState.user?.role === "admin" ? (
                    <button
                      className="popup-menu-item"
                      type="button"
                      onClick={() => {
                        setUserMenuOpen(false);
                        router.push("/admin");
                      }}
                    >
                      <GridIcon />
                      <span>Admin panel</span>
                    </button>
                  ) : null}
                  <button className="popup-menu-item danger" type="button" onClick={handleLogout}>
                    <LogoutIcon />
                    <span>Logout</span>
                  </button>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="chat-stage user-chat-stage">
            <header className="user-chat-header">
              <button
                className="header-icon-button"
                type="button"
                aria-label={sidebarOpen ? "Sidebar нуух" : "Sidebar нээх"}
                onClick={() => setSidebarOpen((current) => !current)}
              >
                <SidebarToggleIcon collapsed={!sidebarOpen} />
              </button>

              <div className="user-chat-header-center">
                <h1>{activeHistory?.title || "Шинэ чат"}</h1>
              </div>

              <div className="user-chat-header-spacer" />
            </header>

            {notice.text ? (
              <p className={`app-notice${notice.tone ? ` ${notice.tone}` : ""}`} aria-live="polite">
                {notice.text}
              </p>
            ) : (
              <div className="app-notice app-notice-placeholder" aria-hidden="true" />
            )}

            <div className="chat-log user-chat-log" ref={chatLogRef} aria-live="polite">
              {renderedMessages.length ? (
                renderedMessages.map((entry, index) => (
                  <div className={`message-row user-chat-row ${entry.role}`} key={`${entry.timestamp}-${index}`}>
                    <div className="bubble-wrap user-bubble-wrap">
                      <div className="bubble user-chat-bubble">
                        {renderStructuredMessage(entry.text)}
                      </div>
                      {entry.role === "bot" && Array.isArray(entry.citations) && entry.citations.length ? (
                        <div className="citations user-chat-citations">
                          {entry.citations.map((citation, citationIndex) => (
                            <span className="citation" key={`${citation.title}-${citationIndex}`}>
                              {citation.title}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <div className="message-meta">{formatTimestamp(entry.timestamp)}</div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="chat-empty-state">
                  <p>Сос Медика Чат бот таньд хариулхад бэлэн</p>
                </div>
              )}

              {isTyping ? (
                <div className="message-row user-chat-row bot message-loader-row" aria-live="polite">
                  <div className="bubble-wrap user-bubble-wrap">
                    <div className="user-chat-loader" aria-label="Хариулт ачаалж байна">
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <form className="composer user-composer" onSubmit={handleComposerSubmit}>
              <div className="composer-shell user-composer-shell">
                <input
                  ref={fileInputRef}
                  id="chat-file-input"
                  type="file"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.json,.csv"
                  multiple
                  hidden
                  onChange={handleComposerUpload}
                />
                {appState.chatDocuments.length ? (
                  <div className="composer-attachments" aria-live="polite">
                    {appState.chatDocuments.map((documentItem) => (
                      <div className="attachment-chip" key={documentItem.id}>
                        <span className="attachment-chip-icon">
                          <FileIcon />
                        </span>
                        <span className="attachment-chip-copy">
                          <strong>{documentItem.title}</strong>
                          <span>{fileTypeLabel(documentItem.title)}</span>
                        </span>
                        <button
                          className="attachment-chip-remove"
                          type="button"
                          aria-label={`${documentItem.title} хасах`}
                          onClick={() => void handleRemoveChatUpload(documentItem.id)}
                        >
                          <CloseIcon />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
                <textarea
                  ref={textareaRef}
                  rows={1}
                  placeholder="Message..."
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                />

                <div className="composer-toolbar">
                  <div className="composer-tools">
                    <button
                      className="composer-tool-icon"
                      type="button"
                      aria-label="Файл нэмэх"
                      title={isUploading ? "Upload хийж байна..." : "Файл нэмэх"}
                      disabled={isUploading}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <PlusIcon />
                    </button>
                    <button className="composer-tool" type="button" aria-label="Translate">
                      <TranslateIcon />
                      <span>Translate</span>
                    </button>
                  </div>

                  <button
                    className="composer-send-button"
                    type="submit"
                    disabled={isTyping || !message.trim()}
                    aria-label="Илгээх"
                  >
                    <SendIcon />
                  </button>
                </div>
              </div>
            </form>
          </section>
        </section>

        {renameTarget ? (
          <div className="rename-modal-backdrop" role="presentation" onClick={() => setRenameTarget(null)}>
            <div className="rename-modal" role="dialog" aria-modal="true" aria-labelledby="rename-history-title" onClick={(event) => event.stopPropagation()}>
              <div className="rename-modal-head">
                <h3 id="rename-history-title">Chat нэр солих</h3>
                <p>Шинэ нэрээ оруулна уу.</p>
              </div>
              <input
                className="rename-modal-input"
                type="text"
                value={renameDraft}
                onChange={(event) => setRenameDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void submitHistoryRename();
                  }
                }}
                autoFocus
              />
              <div className="rename-modal-actions">
                <button className="ghost-button" type="button" onClick={() => setRenameTarget(null)}>
                  Болих
                </button>
                <button className="primary-button" type="button" onClick={() => void submitHistoryRename()}>
                  Хадгалах
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}

function formatCompactHistoryTitle(title) {
  const words = String(title || "Шинэ чат")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (words.length <= 2) {
    return words.join(" ") || "Шинэ чат";
  }

  return `${words.slice(0, 2).join(" ")}...`;
}

function SidebarToggleIcon({ collapsed }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M9 4v16" />
      {collapsed ? <path d="M13 12h4" /> : <path d="M14.5 9.5 12 12l2.5 2.5" />}
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="m16.5 3.5 4 4L8 20l-5 1 1-5Z" />
    </svg>
  );
}

function EllipsisIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <circle cx="5" cy="12" r="1.8" />
      <circle cx="12" cy="12" r="1.8" />
      <circle cx="19" cy="12" r="1.8" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="m19 6-1 14H6L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}

function ChevronUpDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m8 10 4-4 4 4" />
      <path d="m16 14-4 4-4-4" />
    </svg>
  );
}

function TranslateIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 7h10" />
      <path d="M10 4v3c0 4-2 8-5 10" />
      <path d="M6 15c1.4-1.1 2.8-2.8 4-5 1.2 2.1 2.6 3.8 4 5" />
      <path d="M14 20 19 8l5 12" />
      <path d="M16 16h6" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 2 11 13" />
      <path d="m22 2-7 20-4-9-9-4Z" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  );
}

function fileTypeLabel(filename) {
  const extension = getExtension(filename).replace(".", "").toUpperCase();
  return extension || "FILE";
}

function ChatBubbleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 15a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3Z" />
    </svg>
  );
}

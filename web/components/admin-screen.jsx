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
} from "@/lib/session";

export default function AdminScreen() {
  const router = useRouter();
  const menuRef = useRef(null);
  const [user, setUser] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState("Өвчтөний мэдээлэл");
  const [newFolderName, setNewFolderName] = useState("");
  const [copyTargets, setCopyTargets] = useState({});
  const [notice, setNotice] = useState({ text: "", tone: "" });
  const [isUploading, setIsUploading] = useState(false);
  const [openFolderMenu, setOpenFolderMenu] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [fileFilter, setFileFilter] = useState("all");
  const [sortMode, setSortMode] = useState("newest");

  useEffect(() => {
    if (!getStoredToken()) {
      router.replace("/login");
      return;
    }

    void loadBootstrapData();
  }, [router]);

  useEffect(() => {
    if (folders.length && !folders.includes(selectedFolder)) {
      setSelectedFolder(folders[0]);
    }
  }, [folders, selectedFolder]);

  useEffect(() => {
    function handlePointerDown(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setOpenFolderMenu("");
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  const folderSummaries = useMemo(
    () =>
      folders.map((folder) => ({
        name: folder,
        count: documents.filter((documentItem) => (documentItem.folder || "Ерөнхий") === folder).length,
      })),
    [documents, folders],
  );

  const selectedDocuments = useMemo(
    () => documents.filter((documentItem) => (documentItem.folder || "Ерөнхий") === selectedFolder),
    [documents, selectedFolder],
  );

  const visibleDocuments = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filtered = selectedDocuments.filter((documentItem) => {
      const searchable = [
        documentItem.title,
        documentItem.summary,
        documentItem.source,
        ...(documentItem.tags || []),
      ]
        .join(" ")
        .toLowerCase();

      if (normalizedQuery && !searchable.includes(normalizedQuery)) {
        return false;
      }

      const kind = getDocumentKind(documentItem);
      if (fileFilter !== "all" && kind !== fileFilter) {
        return false;
      }

      return true;
    });

    return filtered.sort((left, right) => compareDocuments(left, right, sortMode));
  }, [fileFilter, searchQuery, selectedDocuments, sortMode]);

  async function loadBootstrapData() {
    try {
      const response = await fetchJson("/api/bootstrap");
      if (response.user?.role !== "admin") {
        router.replace("/chat");
        return;
      }

      setUser(response.user);
      setDocuments(response.documents);
      setFolders(response.folders || []);
      setSelectedFolder((current) => current || response.folders?.[0] || "Ерөнхий");
      setNotice({ text: "", tone: "" });
    } catch {
      clearStoredToken();
      router.replace("/login");
    }
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

  async function handleFileUpload(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      return;
    }

    setIsUploading(true);
    try {
      const payloadFiles = await Promise.all(
        files.map(async (file) => {
          const extension = getExtension(file.name);
          if (extension === ".pdf") {
            const bytes = new Uint8Array(await file.arrayBuffer());
            return {
              name: file.name,
              folder: selectedFolder,
              encoding: "base64",
              content: bytesToBase64(bytes),
            };
          }

          return {
            name: file.name,
            folder: selectedFolder,
            encoding: "utf8",
            content: await file.text(),
          };
        }),
      );

      const response = await fetchJson("/api/upload", {
        method: "POST",
        body: { files: payloadFiles },
      });

      setDocuments((current) => [...response.documents, ...current]);
      setFolders(response.folders || []);
      const warnings = Array.isArray(response.warnings)
        ? response.warnings.filter(Boolean)
        : [];
      const text = warnings.length
        ? `${response.documents.length} файл нэмэгдлээ. ${warnings.join(" ")}`
        : `${response.documents.length} файл нэмэгдлээ.`;
      setNotice({ text, tone: warnings.length ? "warning" : "success" });
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

  async function handleCreateFolder() {
    const trimmed = newFolderName.trim();
    if (!trimmed) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/folder/create", {
        method: "POST",
        body: { name: trimmed },
      });
      setFolders(response.folders || []);
      setSelectedFolder(response.selectedFolder || trimmed);
      setNewFolderName("");
      setNotice({ text: `"${trimmed}" folder үүслээ.`, tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Folder үүсгэх үед алдаа гарлаа.", tone: "error" });
    }
  }

  async function handleRenameFolder(folderName) {
    const nextName = window.prompt("Шинэ folder нэр оруулна уу", folderName)?.trim();
    if (!nextName || nextName === folderName) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/folder/rename", {
        method: "POST",
        body: { oldName: folderName, newName: nextName },
      });
      setFolders(response.folders || []);
      setDocuments(response.documents || []);
      if (selectedFolder === folderName) {
        setSelectedFolder(nextName);
      }
      setOpenFolderMenu("");
      setNotice({ text: `"${folderName}" нэр шинэчлэгдлээ.`, tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Folder rename хийх үед алдаа гарлаа.", tone: "error" });
    }
  }

  async function handleDeleteFolder(folderName) {
    if (!window.confirm(`"${folderName}" folder-ийг устгах уу?`)) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/folder/delete", {
        method: "POST",
        body: { name: folderName },
      });
      setFolders(response.folders || []);
      if (selectedFolder === folderName) {
        setSelectedFolder("Ерөнхий");
      }
      setOpenFolderMenu("");
      setNotice({ text: response.message || "Folder устгалаа.", tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Folder устгах үед алдаа гарлаа.", tone: "error" });
    }
  }

  async function handleDeleteDocument(documentId, title) {
    if (!window.confirm(`"${title}" файлыг устгах уу?`)) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/document/delete", {
        method: "POST",
        body: { documentId },
      });
      setDocuments(response.documents || []);
      setFolders(response.folders || []);
      setNotice({ text: `"${title}" файлыг устгалаа.`, tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Файл устгах үед алдаа гарлаа.", tone: "error" });
    }
  }

  async function handleCopyDocument(documentItem) {
    const targetFolder =
      copyTargets[documentItem.id] ||
      folders.find((folder) => folder !== documentItem.folder) ||
      documentItem.folder;
    if (!targetFolder) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/document/copy", {
        method: "POST",
        body: { documentId: documentItem.id, targetFolder },
      });
      setDocuments(response.documents || []);
      setFolders(response.folders || []);
      setNotice({
        text: `"${documentItem.title}" файлыг "${targetFolder}" руу хууллаа.`,
        tone: "success",
      });
    } catch (error) {
      setNotice({ text: error.message || "Файл хуулах үед алдаа гарлаа.", tone: "error" });
    }
  }

  return (
    <main className="chat-body">
      <div className="background-orb orb-left" />
      <div className="background-orb orb-right" />

      <div className="chat-shell">
        <section className="app-layout admin-layout">
          <aside className="sidebar admin-sidebar">
            <div className="sidebar-brand admin-brand">
              <LogoMark className="mini-badge" />
              <div>
                <p className="eyebrow">SOS Medica</p>
                <h2>Admin</h2>
              </div>
            </div>

            <div className="panel admin-identity-panel">
              <div>
                <h3>{user?.name || "Admin"}</h3>
                <p className="panel-caption">{user?.email || ""}</p>
              </div>
              <div className="admin-top-actions">
                <span className="role-badge">{user?.role || "admin"}</span>
                <button
                  className="icon-button icon-button-soft"
                  type="button"
                  onClick={() => router.push("/chat")}
                  aria-label="Chat руу буцах"
                  title="Chat руу буцах"
                >
                  <ArrowLeftIcon />
                </button>
                <button
                  className="icon-button icon-button-soft"
                  type="button"
                  onClick={handleLogout}
                  aria-label="Logout"
                  title="Logout"
                >
                  <LogoutIcon />
                </button>
              </div>
            </div>

            <div className="panel admin-upload-panel">
              <div className="admin-section-head">
                <div>
                  <p className="eyebrow">Upload</p>
                  <h3>Файл нэмэх</h3>
                </div>
                <span className="pill-muted">{isUploading ? "Uploading" : "Ready"}</span>
              </div>

              <div className="field">
                <span>Folder</span>
                <select
                  className="field-select field-select-compact"
                  value={selectedFolder}
                  onChange={(event) => setSelectedFolder(event.target.value)}
                >
                  {folders.map((folder) => (
                    <option key={folder} value={folder}>
                      {folder}
                    </option>
                  ))}
                </select>
              </div>

              <div className="folder-create-row admin-create-row">
                <input
                  className="folder-input"
                  type="text"
                  placeholder="Шинэ folder нэр..."
                  value={newFolderName}
                  onChange={(event) => setNewFolderName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void handleCreateFolder();
                    }
                  }}
                />
                <button
                  className="icon-button icon-button-soft"
                  type="button"
                  onClick={handleCreateFolder}
                  aria-label="Folder үүсгэх"
                  title="Folder үүсгэх"
                >
                  <PlusIcon />
                </button>
              </div>

              <label className="upload-card upload-card-minimal" htmlFor="admin-file-input">
                <input
                  id="admin-file-input"
                  type="file"
                  accept=".txt,.md,.json,.csv,.pdf"
                  multiple
                  hidden
                  onChange={handleFileUpload}
                />
                <div className="upload-card-icon">
                  <UploadIcon />
                </div>
                <div>
                  <strong>{isUploading ? "Файл оруулж байна..." : "Upload files"}</strong>
                  <span>PDF, CSV, TXT файлуудыг сонгосон folder руу хадгална.</span>
                </div>
              </label>
            </div>

            <div className="panel admin-folders-panel">
              <div className="admin-section-head">
                <div>
                  <p className="eyebrow">Folders</p>
                  <h3>Ангиллууд</h3>
                </div>
                <span className="pill-muted">{folders.length}</span>
              </div>

              <div className="folder-stack">
                {folderSummaries.map((folderItem) => (
                  <div
                    className={`folder-row${selectedFolder === folderItem.name ? " active" : ""}`}
                    key={folderItem.name}
                  >
                    <button
                      type="button"
                      className="folder-row-main"
                      onClick={() => setSelectedFolder(folderItem.name)}
                    >
                      <span className="folder-row-icon">
                        <FolderIcon />
                      </span>
                      <span className="folder-row-text">
                        <strong>{folderItem.name}</strong>
                        <span>{folderItem.count} файл</span>
                      </span>
                    </button>

                    <div
                      className="menu-anchor"
                      ref={openFolderMenu === folderItem.name ? menuRef : null}
                    >
                      <button
                        type="button"
                        className="icon-button icon-button-quiet"
                        aria-label={`${folderItem.name} үйлдэл`}
                        title="Folder үйлдэл"
                        onClick={() =>
                          setOpenFolderMenu((current) => (current === folderItem.name ? "" : folderItem.name))
                        }
                      >
                        <MoreIcon />
                      </button>

                      {openFolderMenu === folderItem.name ? (
                        <div className="popup-menu">
                          <button
                            type="button"
                            className="popup-menu-item"
                            onClick={() => void handleRenameFolder(folderItem.name)}
                          >
                            <EditIcon />
                            <span>Нэр солих</span>
                          </button>
                          <button
                            type="button"
                            className="popup-menu-item danger"
                            onClick={() => void handleDeleteFolder(folderItem.name)}
                          >
                            <TrashIcon />
                            <span>Устгах</span>
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </aside>

          <section className="chat-stage admin-stage admin-stage-minimal">
            <header className="chat-header admin-stage-header">
              <div>
                <p className="eyebrow">Knowledge Base</p>
                <h2>{selectedFolder || "Folder сонгоно уу"}</h2>
                <p className="panel-caption">
                  {visibleDocuments.length} файл харагдаж байна. Нийт {selectedDocuments.length} файл энэ folder дотор, {documents.length} файл индексэлэгдсэн.
                </p>
              </div>
              <span className="pill-muted">{visibleDocuments.length}</span>
            </header>

            <p className={`app-notice${notice.tone ? ` ${notice.tone}` : ""}`} aria-live="polite">
              {notice.text}
            </p>

            <div className="admin-table-toolbar">
              <div className="field admin-search-field">
                <span>Хайх</span>
                <input
                  type="text"
                  placeholder="Файлын нэр, summary..."
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              </div>

              <div className="field">
                <span>Filter</span>
                <select
                  className="field-select field-select-compact"
                  value={fileFilter}
                  onChange={(event) => setFileFilter(event.target.value)}
                >
                  <option value="all">Бүгд</option>
                  <option value="pdf">PDF</option>
                  <option value="text">Text / CSV / MD</option>
                  <option value="scan">Scan PDF</option>
                </select>
              </div>

              <div className="field">
                <span>Эрэмбэ</span>
                <select
                  className="field-select field-select-compact"
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value)}
                >
                  <option value="newest">Шинээс</option>
                  <option value="oldest">Хуучнаас</option>
                  <option value="name">Нэрээр</option>
                </select>
              </div>
            </div>

            <div className="folder-groups admin-documents-view">
              {visibleDocuments.length ? (
                <div className="document-list-table">
                  <div className="document-table-head">
                    <span>Файл</span>
                    <span>Товч</span>
                    <span>Оруулсан</span>
                    <span>Хуулах folder</span>
                    <span>Үйлдэл</span>
                  </div>
                  <div className="document-table-body">
                    {visibleDocuments.map((documentItem) => (
                      <article className="document-row" key={documentItem.id}>
                        <div className="document-row-main">
                          <strong>{documentItem.title}</strong>
                          <span className="document-folder-badge">{documentItem.folder || "Ерөнхий"}</span>
                        </div>

                        <p className="document-meta document-row-summary">
                          {documentItem.summary || "No preview available."}
                        </p>

                        <div className="document-row-date">
                          <strong>{formatTimestamp(documentItem.createdAt)}</strong>
                          <span>{documentItem.source || "Uploaded"}</span>
                        </div>

                        <div className="document-row-move">
                          <select
                            className="field-select compact-select"
                            value={
                              copyTargets[documentItem.id] ||
                              folders.find((folder) => folder !== documentItem.folder) ||
                              documentItem.folder
                            }
                            onChange={(event) =>
                              setCopyTargets((current) => ({
                                ...current,
                                [documentItem.id]: event.target.value,
                              }))
                            }
                          >
                            {folders.map((folder) => (
                              <option key={`${documentItem.id}-${folder}`} value={folder}>
                                {folder}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="document-row-actions">
                          <button
                            className="icon-button icon-button-soft"
                            type="button"
                            onClick={() => void handleCopyDocument(documentItem)}
                            aria-label={`${documentItem.title} хуулах`}
                            title="Файл хуулах"
                          >
                            <CopyIcon />
                          </button>
                          <button
                            className="icon-button icon-button-danger"
                            type="button"
                            onClick={() => void handleDeleteDocument(documentItem.id, documentItem.title)}
                            aria-label={`${documentItem.title} устгах`}
                            title="Файл устгах"
                          >
                            <TrashIcon />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-card">
                    <p className="eyebrow">Folder</p>
                    <h2>{selectedFolder ? `"${selectedFolder}" дээр тохирох файл алга` : "Folder сонгоно уу"}</h2>
                    <p>Search, filter-ээ цэвэрлэх эсвэл зүүн талын upload хэсгээс файл нэмээд үзээрэй.</p>
                  </div>
                </div>
              )}
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}

function ArrowLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 18l-6-6 6-6" />
      <path d="M21 12H9" />
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

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3" />
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

function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <circle cx="5" cy="12" r="1.8" />
      <circle cx="12" cy="12" r="1.8" />
      <circle cx="19" cy="12" r="1.8" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
    </svg>
  );
}

function getDocumentKind(documentItem) {
  const title = String(documentItem?.title || "").toLowerCase();
  const summary = String(documentItem?.summary || "").toLowerCase();
  if (summary.includes("scan pdf") || summary.includes("ocr")) {
    return "scan";
  }
  if (title.endsWith(".pdf")) {
    return "pdf";
  }
  return "text";
}

function compareDocuments(left, right, sortMode) {
  if (sortMode === "name") {
    return String(left.title || "").localeCompare(String(right.title || ""));
  }

  const leftTime = new Date(left.createdAt || 0).getTime();
  const rightTime = new Date(right.createdAt || 0).getTime();
  if (sortMode === "oldest") {
    return leftTime - rightTime;
  }
  return rightTime - leftTime;
}

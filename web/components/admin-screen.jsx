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
} from "@/lib/session";

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"];

export default function AdminScreen() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [submissions, setSubmissions] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState("Өвчтөний мэдээлэл");
  const [copyTargets, setCopyTargets] = useState({});
  const [notice, setNotice] = useState({ text: "", tone: "" });
  const [isUploading, setIsUploading] = useState(false);
  const [openFolderMenu, setOpenFolderMenu] = useState("");
  const [openCopyMenu, setOpenCopyMenu] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [fileFilter, setFileFilter] = useState("all");
  const [sortMode, setSortMode] = useState("newest");
  const [page, setPage] = useState(1);
  const [submissionsPage, setSubmissionsPage] = useState(1);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [viewMode, setViewMode] = useState("documents");
  const [previewSubmission, setPreviewSubmission] = useState(null);
  const fileInputRef = useRef(null);
  const pageSize = 10;

  useEffect(() => {
    if (!getStoredToken()) {
      router.replace("/login");
      return;
    }

    void loadBootstrapData();
  }, [router]);

  const visibleFolders = useMemo(
    () => folders.filter((folder) => !/^Temp Folder/i.test(folder)),
    [folders],
  );

  useEffect(() => {
    if (visibleFolders.length && !visibleFolders.includes(selectedFolder)) {
      setSelectedFolder(visibleFolders[0]);
    }
  }, [visibleFolders, selectedFolder]);

  useEffect(() => {
    function handlePointerDown(event) {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      if (!target.closest("[data-admin-menu-root]")) {
        setOpenFolderMenu("");
        setOpenCopyMenu("");
        setUserMenuOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  const folderSummaries = useMemo(
    () =>
      visibleFolders.map((folder) => ({
        name: folder,
        count: documents.filter((documentItem) => (documentItem.folder || "Ерөнхий") === folder).length,
      })),
    [documents, visibleFolders],
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

  const visibleSubmissions = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filtered = submissions.filter((submission) => {
      const searchable = [
        submission.title,
        submission.userEmail,
        submission.summary,
        submission.patientFields?.patientName,
        submission.patientFields?.registerNumber,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      if (normalizedQuery && !searchable.includes(normalizedQuery)) {
        return false;
      }

      if (fileFilter === "pdf" && !String(submission.title || "").toLowerCase().endsWith(".pdf")) {
        return false;
      }

      if (
        fileFilter === "text" &&
        [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"].some((ext) =>
          String(submission.title || "").toLowerCase().endsWith(ext),
        )
      ) {
        return false;
      }

      if (fileFilter === "scan" && submission.status !== "needs_resubmit") {
        return false;
      }

      return true;
    });

    return filtered.sort((left, right) => compareDocuments(left, right, sortMode));
  }, [fileFilter, searchQuery, sortMode, submissions]);

  const totalPages = Math.max(1, Math.ceil(visibleDocuments.length / pageSize));
  const totalSubmissionPages = Math.max(1, Math.ceil(visibleSubmissions.length / pageSize));

  const pagedDocuments = useMemo(() => {
    const startIndex = (page - 1) * pageSize;
    return visibleDocuments.slice(startIndex, startIndex + pageSize);
  }, [page, visibleDocuments]);

  const pagedSubmissions = useMemo(() => {
    const startIndex = (submissionsPage - 1) * pageSize;
    return visibleSubmissions.slice(startIndex, startIndex + pageSize);
  }, [submissionsPage, visibleSubmissions]);

  useEffect(() => {
    setPage(1);
  }, [selectedFolder, searchQuery, fileFilter, sortMode]);

  useEffect(() => {
    setSubmissionsPage(1);
  }, [searchQuery, fileFilter, sortMode, viewMode]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    if (submissionsPage > totalSubmissionPages) {
      setSubmissionsPage(totalSubmissionPages);
    }
  }, [submissionsPage, totalSubmissionPages]);

  async function loadBootstrapData() {
    try {
      const response = await fetchJson("/api/bootstrap?scope=admin");
      if (response.user?.role !== "admin") {
        router.replace("/chat");
        return;
      }

      setUser(response.user);
      setDocuments(response.documents);
      setSubmissions(response.submissions || []);
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
          if (
            extension === ".pdf" ||
            extension === ".docx" ||
            file.type.startsWith("image/") ||
            IMAGE_EXTENSIONS.includes(extension)
          ) {
            const bytes = new Uint8Array(await file.arrayBuffer());
            return {
              name: file.name,
              folder: selectedFolder,
              encoding: "base64",
              content: bytesToBase64(bytes),
              mimeType: file.type,
            };
          }

          return {
            name: file.name,
            folder: selectedFolder,
            encoding: "utf8",
            content: await file.text(),
            mimeType: file.type,
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
    const nextName = window.prompt("Шинэ folder нэр оруулна уу")?.trim();
    const trimmed = nextName || "";
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
      setOpenCopyMenu("");
    } catch (error) {
      setNotice({ text: error.message || "Файл хуулах үед алдаа гарлаа.", tone: "error" });
    }
  }

  function handleViewDocument(documentItem) {
    if (!documentItem.storagePath) {
      setNotice({ text: "Энэ файлд preview байхгүй байна.", tone: "warning" });
      return;
    }
    const query = new URLSearchParams({ id: String(documentItem.id) });
    window.open(`/api/admin/document/file?${query.toString()}`, "_blank", "noopener,noreferrer");
  }

  function handleViewSubmission(submissionItem) {
    if (!submissionItem.storagePath) {
      setNotice({ text: "Энэ баримтад preview байхгүй байна.", tone: "warning" });
      return;
    }
    setPreviewSubmission(submissionItem);
  }

  async function handleDeleteSubmission(submissionItem) {
    if (!window.confirm(`"${submissionItem.title}" баримтыг бүр мөсөн устгах уу?`)) {
      return;
    }

    try {
      const response = await fetchJson("/api/admin/submission/delete", {
        method: "POST",
        body: { submissionId: submissionItem.id },
      });
      setSubmissions(response.submissions || []);
      if (previewSubmission?.id === submissionItem.id) {
        setPreviewSubmission(null);
      }
      setNotice({ text: `"${submissionItem.title}" баримтыг устгалаа.`, tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Баримт устгах үед алдаа гарлаа.", tone: "error" });
    }
  }

  return (
    <main className="chat-body">
      <div className="background-orb orb-left" />
      <div className="background-orb orb-right" />

      <div className="chat-shell">
        <section className={`app-layout chat-app-shell admin-app-shell${sidebarOpen ? "" : " sidebar-collapsed"}`}>
          <aside className="sidebar user-chat-sidebar admin-sidebar-clean">
            <div className="chat-brand-lockup">
              <LogoMark className="mini-badge chat-brand-badge" />
              <div>
                <p className="chat-brand-overline">Сос Медика Монгол</p>
                <h2>Админ самбар</h2>
              </div>
            </div>

            <button
              className="new-chat-rail-button"
              type="button"
              onClick={() => {
                setViewMode((current) => (current === "documents" ? "submissions" : "documents"));
                setNotice({ text: "", tone: "" });
              }}
            >
              <span className="new-chat-rail-icon">
                <GridIcon />
              </span>
              <span>{viewMode === "documents" ? "Баримтын мэдээллүүд" : "Файлууд руу буцах"}</span>
            </button>

            <div className="panel admin-folders-panel admin-clean-panel">
              <div className="admin-section-head">
                <div>
                  <h3>Ангиллууд ({visibleFolders.length})</h3>
                  {/* <span className="pill-muted"></span> */}
                </div>
                <div className="admin-section-actions">
                  <button
                    className="icon-button icon-button-soft"
                    type="button"
                    aria-label="Folder үүсгэх"
                    title="Folder үүсгэх"
                    onClick={handleCreateFolder}
                  >
                    <PlusIcon />
                  </button>
                </div>
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
                      data-admin-menu-root
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

            <div className="chat-user-footer" data-admin-menu-root>
              <button
                className="chat-user-trigger"
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setOpenFolderMenu("");
                  setUserMenuOpen((current) => !current);
                }}
              >
                <span className="chat-user-avatar">{initialsFromEmail(user?.email)}</span>
                <span className="chat-user-name">{user?.name || "Admin"}</span>
                <ChevronUpDownIcon />
              </button>

              {userMenuOpen ? (
                <div className="popup-menu chat-user-menu">
                  <button className="popup-menu-item" type="button" onClick={() => router.push("/chat")}>
                    <ArrowLeftIcon />
                    <span>Чат руу буцах</span>
                  </button>
                  <button className="popup-menu-item danger" type="button" onClick={handleLogout}>
                    <LogoutIcon />
                    <span>Logout</span>
                  </button>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="chat-stage user-chat-stage admin-stage-clean">
            <header className="user-chat-header">
              <button
                className="header-icon-button"
                type="button"
                aria-label={sidebarOpen ? "Sidebar нуух" : "Sidebar нээх"}
                onClick={() => setSidebarOpen((current) => !current)}
              >
                <SidebarToggleIcon collapsed={!sidebarOpen} />
              </button>

              <div className="admin-header-title">
                <h1>{viewMode === "submissions" ? "Баримтын мэдээллүүд" : selectedFolder || "Admin panel"}</h1>
              </div>

              <div className="admin-header-upload">
                {viewMode === "documents" ? (
                  <>
                    <input
                      ref={fileInputRef}
                      id="admin-file-input"
                      type="file"
                      accept=".txt,.md,.json,.csv,.pdf,image/*,.heic,.heif"
                      multiple
                      hidden
                      onChange={handleFileUpload}
                    />
                    <button
                      className="new-chat-rail-button admin-upload-trigger"
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploading}
                    >
                      <span className="new-chat-rail-icon">
                        <UploadIcon />
                      </span>
                      <span>{isUploading ? "Файл оруулж байна..." : "Файл оруулах"}</span>
                    </button>
                  </>
                ) : null}
              </div>
            </header>

            {notice.text ? (
              <p className={`app-notice${notice.tone ? ` ${notice.tone}` : ""}`} aria-live="polite">
                {notice.text}
              </p>
            ) : (
              <div className="app-notice app-notice-placeholder" aria-hidden="true" />
            )}

            <div className="admin-stage-scroll">
              <div className="admin-table-toolbar">
                <div className="field admin-search-field">
                  <span>Хайх</span>
                  <input
                    type="text"
                    placeholder={viewMode === "submissions" ? "Файл, и-мэйл, өвчтөний нэр..." : "Файлын нэр, summary..."}
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
                {viewMode === "documents" ? (
                  visibleDocuments.length ? (
                  <div className="document-list-table">
                    <div className="document-table-head">
                      <span>Файл</span>
                      <span>Товч</span>
                      <span>Оруулсан</span>
                      <span>Үйлдэл</span>
                    </div>
                    <div className="document-table-body">
                      {pagedDocuments.map((documentItem) => (
                        <article className="document-row" key={documentItem.id}>
                          <div className="document-row-main">
                            <strong>{documentItem.title}</strong>
                          </div>

                          <p className="document-meta document-row-summary">
                            {documentItem.summary || "No preview available."}
                          </p>

                          <div className="document-row-date">
                            <strong>{formatTimestamp(documentItem.createdAt)}</strong>
                            <span>{documentItem.source || "Uploaded"}</span>
                          </div>

                          <div className="document-row-actions">
                            <button
                              className="icon-button icon-button-soft"
                              type="button"
                              onClick={() => handleViewDocument(documentItem)}
                              aria-label={`${documentItem.title} харах`}
                              title="Файл харах"
                            >
                              <ViewIcon />
                            </button>
                            <div className="menu-anchor" data-admin-menu-root>
                              <button
                                className="icon-button icon-button-soft"
                                type="button"
                                onClick={() =>
                                  setOpenCopyMenu((current) =>
                                    current === documentItem.id ? "" : documentItem.id,
                                  )
                                }
                                aria-label={`${documentItem.title} хуулах`}
                                title="Файл хуулах"
                              >
                                <CopyIcon />
                              </button>

                              {openCopyMenu === documentItem.id ? (
                                <div className="popup-menu copy-popup-menu">
                                  <div className="copy-popup-body">
                                    <label className="field copy-popup-field">
                                      <span>Folder сонгох</span>
                                      <select
                                        className="field-select compact-select"
                                        value={
                                          copyTargets[documentItem.id] ||
                                          visibleFolders.find((folder) => folder !== documentItem.folder) ||
                                          documentItem.folder
                                        }
                                        onChange={(event) =>
                                          setCopyTargets((current) => ({
                                            ...current,
                                            [documentItem.id]: event.target.value,
                                          }))
                                        }
                                      >
                                        {visibleFolders.map((folder) => (
                                          <option key={`${documentItem.id}-${folder}`} value={folder}>
                                            {folder}
                                          </option>
                                        ))}
                                      </select>
                                    </label>
                                    <button
                                      className="new-chat-rail-button copy-popup-submit"
                                      type="button"
                                      onClick={() => void handleCopyDocument(documentItem)}
                                    >
                                      <span className="new-chat-rail-icon">
                                        <CopyIcon />
                                      </span>
                                      <span>Хуулах</span>
                                    </button>
                                  </div>
                                </div>
                              ) : null}
                            </div>
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
                      <p>Search, filter-ээ цэвэрлэх эсвэл дээрх `Файл оруулах` товчоор баримт нэмээд үзээрэй.</p>
                    </div>
                  </div>
                  )
                ) : visibleSubmissions.length ? (
                  <div className="document-list-table">
                    <div className="document-table-head document-table-head-submissions">
                      <span>Хэрэглэгч</span>
                      <span>Бараануудын мэдээлэл</span>
                      <span>Нийт дүн</span>
                      <span>Илгээсэн</span>
                      <span>Үйлдэл</span>
                    </div>
                    <div className="document-table-body">
                      {pagedSubmissions.map((submissionItem) => (
                        <article className="document-row submission-row" key={submissionItem.id}>
                          <div className="document-row-main">
                            <strong>{submissionItem.userEmail}</strong>
                            <p className="document-meta">
                              {submissionItem.patientFields?.patientName || submissionItem.patientFields?.registerNumber || "Баримт илгээсэн хэрэглэгч"}
                            </p>
                          </div>

                          <div className="document-row-main">
                            <strong>{submissionItem.patientFields?.itemInfo || submissionItem.title}</strong>
                            <p className="document-meta document-row-summary">
                              {submissionItem.summary || submissionItem.content || "No preview available."}
                            </p>
                          </div>

                          <div className="document-row-status">
                            <strong className="submission-amount">
                              {submissionItem.patientFields?.totalAmount
                                || (submissionItem.status === "needs_resubmit" ? "Дахин илгээх" : "-")}
                            </strong>
                          </div>

                          <div className="document-row-date">
                            <strong>{formatTimestamp(submissionItem.createdAt)}</strong>
                            <span>{submissionItem.patientFields?.visitDate || "Илгээсэн огноо"}</span>
                          </div>

                          <div className="document-row-actions">
                            <button
                              className="icon-button icon-button-soft"
                              type="button"
                              onClick={() => handleViewSubmission(submissionItem)}
                              aria-label={`${submissionItem.title} харах`}
                              title="Баримт харах"
                            >
                              <ViewIcon />
                            </button>
                            <button
                              className="icon-button icon-button-danger"
                              type="button"
                              onClick={() => void handleDeleteSubmission(submissionItem)}
                              aria-label={`${submissionItem.title} устгах`}
                              title="Баримт устгах"
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
                      <p className="eyebrow">Баримт</p>
                      <h2>Илгээсэн баримт алга</h2>
                      <p>Хэрэглэгчийн илгээсэн баримтууд энд нэг дор харагдана.</p>
                    </div>
                  </div>
                )}

                {(viewMode === "documents" ? visibleDocuments.length : visibleSubmissions.length) > pageSize ? (
                  <div className="admin-pagination">
                    <button
                      className="icon-button icon-button-soft"
                      type="button"
                      onClick={() =>
                        viewMode === "documents"
                          ? setPage((current) => Math.max(1, current - 1))
                          : setSubmissionsPage((current) => Math.max(1, current - 1))
                      }
                      disabled={viewMode === "documents" ? page === 1 : submissionsPage === 1}
                      aria-label="Өмнөх хуудас"
                    >
                      <ArrowLeftIcon />
                    </button>
                    <span className="admin-pagination-label">
                      {viewMode === "documents" ? page : submissionsPage} / {viewMode === "documents" ? totalPages : totalSubmissionPages}
                    </span>
                    <button
                      className="icon-button icon-button-soft"
                      type="button"
                      onClick={() =>
                        viewMode === "documents"
                          ? setPage((current) => Math.min(totalPages, current + 1))
                          : setSubmissionsPage((current) => Math.min(totalSubmissionPages, current + 1))
                      }
                      disabled={viewMode === "documents" ? page === totalPages : submissionsPage === totalSubmissionPages}
                      aria-label="Дараагийн хуудас"
                    >
                      <ArrowRightIcon />
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        </section>
      </div>

      {previewSubmission ? (
        <div
          className="preview-modal-overlay"
          role="presentation"
          onClick={() => setPreviewSubmission(null)}
        >
          <div
            className="preview-modal"
            role="dialog"
            aria-modal="true"
            aria-label={previewSubmission.title}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="preview-modal-header">
              <div className="preview-modal-title">
                <h3>{previewSubmission.title}</h3>
                <p>{previewSubmission.userEmail}</p>
              </div>
              <button
                className="icon-button icon-button-soft"
                type="button"
                aria-label="Modal хаах"
                onClick={() => setPreviewSubmission(null)}
              >
                <CloseIcon />
              </button>
            </div>
            <div className="preview-modal-body">
              {String(previewSubmission.title || "").toLowerCase().endsWith(".pdf") ? (
                <iframe
                  className="preview-frame"
                  src={`/api/admin/submission/file?id=${encodeURIComponent(previewSubmission.id)}`}
                  title={previewSubmission.title}
                />
              ) : (
                <img
                  className="preview-image"
                  src={`/api/admin/submission/file?id=${encodeURIComponent(previewSubmission.id)}`}
                  alt={previewSubmission.title}
                />
              )}
            </div>
          </div>
        </div>
      ) : null}
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

function ArrowRightIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18l6-6-6-6" />
      <path d="M3 12h12" />
    </svg>
  );
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

function ViewIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
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

function ChevronUpDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m8 9 4-4 4 4" />
      <path d="m16 15-4 4-4-4" />
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

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
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

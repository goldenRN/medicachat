"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchBlob, fetchJson } from "@/lib/api";
import { bytesToBase64 } from "@/lib/session";

const CATEGORY_OPTIONS = [
  { key: "clinic_management_admin", label: "Clinic удирдлага, захиргаа" },
  { key: "clinic_medical", label: "Clinic эмнэлгийн чиг үүрэг" },
  { key: "ot_staff", label: "OT Staff" },
  { key: "clinic_other", label: "Clinic бусад чиг үүрэг" },
];

const EMPTY_DRAFT = {
  categoryKey: CATEGORY_OPTIONS[0].key,
  lastNameEn: "",
  firstNameEn: "",
  lastNameMn: "",
  firstNameMn: "",
  positionEn: "",
  positionMn: "",
  registerNumber: "",
  emailPrimary: "",
  emailSecondary: "",
  phonePrimary: "",
  phoneSecondary: "",
  dutyPhone: "",
  dateOfBirth: "",
  hireDate: "",
  homeAddress: "",
  notes: "",
  extraInfo: "",
  photoContent: "",
  photoMimeType: "",
  removePhoto: false,
};

export default function AdminEmployeesPanel({ employees, setEmployees, setNotice }) {
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [sortMode, setSortMode] = useState("category");
  const [page, setPage] = useState(1);
  const [editingEmployee, setEditingEmployee] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [isSaving, setIsSaving] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [photoPreviewUrl, setPhotoPreviewUrl] = useState("");
  const [employeePhotoUrls, setEmployeePhotoUrls] = useState({});
  const [editingEmployeePhotoUrl, setEditingEmployeePhotoUrl] = useState("");
  const pageSize = 12;

  useEffect(() => {
    setPage(1);
  }, [searchQuery, categoryFilter, sortMode]);

  useEffect(() => () => {
    if (photoPreviewUrl) {
      URL.revokeObjectURL(photoPreviewUrl);
    }
  }, [photoPreviewUrl]);

  useEffect(() => () => {
    Object.values(employeePhotoUrls).forEach((url) => {
      if (url) {
        URL.revokeObjectURL(url);
      }
    });
  }, [employeePhotoUrls]);

  useEffect(() => () => {
    if (editingEmployeePhotoUrl) {
      URL.revokeObjectURL(editingEmployeePhotoUrl);
    }
  }, [editingEmployeePhotoUrl]);

  const visibleEmployees = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filtered = employees.filter((employee) => {
      if (categoryFilter !== "all" && employee.categoryKey !== categoryFilter) {
        return false;
      }

      const searchable = [
        employee.fullNameEn,
        employee.fullNameMn,
        employee.lastNameEn,
        employee.firstNameEn,
        employee.lastNameMn,
        employee.firstNameMn,
        employee.positionEn,
        employee.positionMn,
        employee.categoryNameMn,
        employee.categoryNameEn,
        employee.emailPrimary,
        employee.emailSecondary,
        employee.phonePrimary,
        employee.phoneSecondary,
        employee.registerNumber,
        employee.notes,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return !normalizedQuery || searchable.includes(normalizedQuery);
    });

    return filtered.sort((left, right) => {
      if (sortMode === "name") {
        return `${left.fullNameMn || left.fullNameEn}`.localeCompare(
          `${right.fullNameMn || right.fullNameEn}`,
          "mn",
          { sensitivity: "base" },
        );
      }
      if (sortMode === "updated") {
        return String(right.updatedAt || "").localeCompare(String(left.updatedAt || ""));
      }
      if (left.categoryKey !== right.categoryKey) {
        return String(left.categoryNameMn || left.categoryKey).localeCompare(
          String(right.categoryNameMn || right.categoryKey),
          "mn",
          { sensitivity: "base" },
        );
      }
      return Number(left.sortOrder || 0) - Number(right.sortOrder || 0);
    });
  }, [categoryFilter, employees, searchQuery, sortMode]);

  const totalPages = Math.max(1, Math.ceil(visibleEmployees.length / pageSize));
  const pagedEmployees = useMemo(() => {
    const startIndex = (page - 1) * pageSize;
    return visibleEmployees.slice(startIndex, startIndex + pageSize);
  }, [page, visibleEmployees]);

  useEffect(() => {
    let isActive = true;

    async function loadEmployeePhotos() {
      const photoEmployees = pagedEmployees.filter((employee) => employee.hasPhoto);
      if (!photoEmployees.length) {
        setEmployeePhotoUrls((current) => {
          Object.values(current).forEach((url) => {
            if (url) {
              URL.revokeObjectURL(url);
            }
          });
          return {};
        });
        return;
      }

      const nextUrls = await Promise.all(
        photoEmployees.map(async (employee) => {
          try {
            const { blob } = await fetchBlob(`/api/admin/employee/photo?id=${encodeURIComponent(employee.id)}`);
            return [employee.id, URL.createObjectURL(blob)];
          } catch {
            return [employee.id, ""];
          }
        }),
      );

      if (!isActive) {
        nextUrls.forEach(([, url]) => {
          if (url) {
            URL.revokeObjectURL(url);
          }
        });
        return;
      }

      setEmployeePhotoUrls((current) => {
        Object.values(current).forEach((url) => {
          if (url) {
            URL.revokeObjectURL(url);
          }
        });
        return Object.fromEntries(nextUrls.filter(([, url]) => url));
      });
    }

    void loadEmployeePhotos();
    return () => {
      isActive = false;
    };
  }, [pagedEmployees]);

  useEffect(() => {
    let isActive = true;

    async function loadEditingEmployeePhoto() {
      if (!editingEmployee?.hasPhoto) {
        setEditingEmployeePhotoUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return "";
        });
        return;
      }

      try {
        const { blob } = await fetchBlob(`/api/admin/employee/photo?id=${encodeURIComponent(editingEmployee.id)}`);
        const nextUrl = URL.createObjectURL(blob);
        if (!isActive) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        setEditingEmployeePhotoUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return nextUrl;
        });
      } catch {
        if (isActive) {
          setEditingEmployeePhotoUrl((current) => {
            if (current) {
              URL.revokeObjectURL(current);
            }
            return "";
          });
        }
      }
    }

    void loadEditingEmployeePhoto();
    return () => {
      isActive = false;
    };
  }, [editingEmployee]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  function openCreateModal() {
    if (photoPreviewUrl) {
      URL.revokeObjectURL(photoPreviewUrl);
      setPhotoPreviewUrl("");
    }
    setEditingEmployee(null);
    setDraft(EMPTY_DRAFT);
    setIsModalOpen(true);
  }

  function openEditModal(employee) {
    if (photoPreviewUrl) {
      URL.revokeObjectURL(photoPreviewUrl);
      setPhotoPreviewUrl("");
    }
    setEditingEmployee(employee);
    setIsModalOpen(true);
    setDraft({
      categoryKey: employee.categoryKey || CATEGORY_OPTIONS[0].key,
      lastNameEn: employee.lastNameEn || "",
      firstNameEn: employee.firstNameEn || "",
      lastNameMn: employee.lastNameMn || "",
      firstNameMn: employee.firstNameMn || "",
      positionEn: employee.positionEn || "",
      positionMn: employee.positionMn || "",
      registerNumber: employee.registerNumber || "",
      emailPrimary: employee.emailPrimary || "",
      emailSecondary: employee.emailSecondary || "",
      phonePrimary: employee.phonePrimary || "",
      phoneSecondary: employee.phoneSecondary || "",
      dutyPhone: employee.dutyPhone || "",
      dateOfBirth: employee.dateOfBirth || "",
      hireDate: employee.hireDate || "",
      homeAddress: employee.homeAddress || "",
      notes: employee.notes || "",
      extraInfo: employee.extraInfo || "",
      photoContent: "",
      photoMimeType: "",
      removePhoto: false,
    });
  }

  function closeModal() {
    setIsModalOpen(false);
    setEditingEmployee(null);
    setDraft(EMPTY_DRAFT);
    if (photoPreviewUrl) {
      URL.revokeObjectURL(photoPreviewUrl);
      setPhotoPreviewUrl("");
    }
  }

  async function handlePhotoChange(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    if (photoPreviewUrl) {
      URL.revokeObjectURL(photoPreviewUrl);
    }

    const bytes = new Uint8Array(await file.arrayBuffer());
    setPhotoPreviewUrl(URL.createObjectURL(file));
    setDraft((current) => ({
      ...current,
      photoContent: bytesToBase64(bytes),
      photoMimeType: file.type,
      removePhoto: false,
    }));
  }

  async function handleSaveEmployee() {
    setIsSaving(true);
    try {
      const endpoint = editingEmployee ? "/api/admin/employee/update" : "/api/admin/employee/create";
      const response = await fetchJson(endpoint, {
        method: "POST",
        body: editingEmployee
          ? { employeeId: editingEmployee.id, employee: draft }
          : { employee: draft },
      });
      setEmployees(response.employees || []);
      setNotice({
        text: editingEmployee ? "Ажилтны мэдээлэл шинэчлэгдлээ." : "Ажилтан амжилттай нэмэгдлээ.",
        tone: "success",
      });
      closeModal();
    } catch (error) {
      setNotice({
        text: error.message || "Ажилтны мэдээлэл хадгалах үед алдаа гарлаа.",
        tone: "error",
      });
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeleteEmployee(employee) {
    if (!window.confirm(`${employee.fullNameMn || employee.fullNameEn || "Энэ ажилтан"}-ы мэдээллийг устгах уу?`)) {
      return;
    }
    try {
      const response = await fetchJson("/api/admin/employee/delete", {
        method: "POST",
        body: { employeeId: employee.id },
      });
      setEmployees(response.employees || []);
      setNotice({ text: "Ажилтны мэдээллийг устгалаа.", tone: "success" });
    } catch (error) {
      setNotice({ text: error.message || "Ажилтан устгах үед алдаа гарлаа.", tone: "error" });
    }
  }

  async function handleSyncEmployees() {
    setIsSyncing(true);
    try {
      const response = await fetchJson("/api/admin/employee/sync", {
        method: "POST",
        body: {},
      });
      setEmployees(response.employees || []);
      setNotice({
        text: response.message || "Employee data Excel-ээс дахин sync хийгдлээ.",
        tone: "success",
      });
    } catch (error) {
      setNotice({
        text: error.message || "Excel sync хийх үед алдаа гарлаа.",
        tone: "error",
      });
    } finally {
      setIsSyncing(false);
    }
  }

  const currentPhotoUrl = photoPreviewUrl || editingEmployeePhotoUrl;

  return (
    <>
      <div className="employee-panel-head">
        <div className="admin-table-toolbar employee-table-toolbar">
          <div className="field admin-search-field">
            <span>Хайх</span>
            <input
              type="text"
              placeholder="Нэр, албан тушаал, и-мэйл..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          <div className="field">
            <span>Ангилал</span>
            <select
              className="field-select field-select-compact"
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
            >
              <option value="all">Бүгд</option>
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span>Эрэмбэ</span>
            <select
              className="field-select field-select-compact"
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value)}
            >
              <option value="category">Ангиллаар</option>
              <option value="name">Нэрээр</option>
              <option value="updated">Сүүлд шинэчилснээр</option>
            </select>
          </div>
        </div>

        <div className="employee-panel-actions">
          <button
            className="new-chat-rail-button employee-sync-button"
            type="button"
            onClick={() => void handleSyncEmployees()}
            disabled={isSyncing}
          >
            <span className="new-chat-rail-icon">{isSyncing ? "…" : "↻"}</span>
            <span>{isSyncing ? "Sync хийж байна..." : "Excel-ээс sync хийх"}</span>
          </button>

          <button className="new-chat-rail-button employee-add-button" type="button" onClick={openCreateModal}>
            <span className="new-chat-rail-icon">+</span>
            <span>Ажилтан нэмэх</span>
          </button>
        </div>
      </div>

      {pagedEmployees.length ? (
        <div className="document-list-table employee-table-shell">
          <div className="document-table-head employee-table-head">
            <span>Зураг</span>
            <span>Нэр</span>
            <span>Албан тушаал</span>
            <span>Холбоо барих</span>
            <span>Үйлдэл</span>
          </div>
          <div className="document-table-body">
            {pagedEmployees.map((employee) => {
              const employeePhotoUrl = employeePhotoUrls[employee.id] || "";
              return (
                <article className="document-row employee-row" key={employee.id}>
                  <div className="employee-photo-cell">
                    {employeePhotoUrl ? (
                      <img
                        className="employee-photo-thumb"
                        src={employeePhotoUrl}
                        alt={employee.fullNameMn || employee.fullNameEn || "Employee photo"}
                      />
                    ) : (
                      <div className="employee-photo-fallback">
                        {(employee.firstNameMn || employee.firstNameEn || "NA").slice(0, 1)}
                      </div>
                    )}
                  </div>

                  <div className="document-row-main">
                    <strong>{employee.fullNameMn || employee.fullNameEn || "Нэр оруулаагүй"}</strong>
                    <p className="document-meta">{employee.fullNameEn || employee.fullNameMn || "-"}</p>
                    <span className="document-folder-badge">{employee.categoryNameMn || employee.categoryKey}</span>
                  </div>

                  <div className="document-row-main">
                    <strong>{employee.positionMn || employee.positionEn || "-"}</strong>
                    <p className="document-meta">{employee.positionEn || employee.positionMn || "-"}</p>
                    <p className="document-meta">Регистр: {employee.registerNumber || "-"}</p>
                  </div>

                  <div className="document-row-main">
                    <strong>{employee.emailPrimary || "-"}</strong>
                    <p className="document-meta">{employee.emailSecondary || employee.phonePrimary || "-"}</p>
                    <p className="document-meta">
                      {[employee.phonePrimary, employee.phoneSecondary, employee.dutyPhone].filter(Boolean).join(" · ") || "-"}
                    </p>
                  </div>

                  <div className="document-row-actions">
                    <button className="employee-action-button" type="button" onClick={() => openEditModal(employee)}>
                      Засах
                    </button>
                    <button
                      className="employee-action-button danger"
                      type="button"
                      onClick={() => void handleDeleteEmployee(employee)}
                    >
                      Устгах
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-card">
            <p className="eyebrow">Ажилчид</p>
            <h2>Ажилтны мэдээлэл олдсонгүй</h2>
            <p>Search эсвэл filter-ээ цэвэрлэх эсвэл `Ажилтан нэмэх` товчоор шинэ мөр үүсгэнэ үү.</p>
          </div>
        </div>
      )}

      {visibleEmployees.length > pageSize ? (
        <div className="admin-pagination">
          <button
            className="icon-button icon-button-soft"
            type="button"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={page === 1}
            aria-label="Өмнөх хуудас"
          >
            {"<"}
          </button>
          <span className="admin-pagination-label">{page} / {totalPages}</span>
          <button
            className="icon-button icon-button-soft"
            type="button"
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            disabled={page === totalPages}
            aria-label="Дараагийн хуудас"
          >
            {">"}
          </button>
        </div>
      ) : null}

      {isModalOpen ? (
        <div className="preview-modal-overlay" role="presentation" onClick={closeModal}>
          <div className="preview-modal employee-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="preview-modal-header">
              <div className="preview-modal-title">
                <h3>{editingEmployee ? "Ажилтны мэдээлэл засах" : "Шинэ ажилтан нэмэх"}</h3>
                <p>Англи болон монгол нэр, албан тушаал, зураг, холбоо барих мэдээллийг хадгална.</p>
              </div>
              <button className="icon-button icon-button-soft" type="button" onClick={closeModal} aria-label="Modal хаах">
                ✕
              </button>
            </div>

            <div className="preview-modal-body employee-modal-body">
              <div className="employee-form-grid">
                <label className="field">
                  <span>Ангилал</span>
                  <select
                    className="field-select"
                    value={draft.categoryKey}
                    onChange={(event) => setDraft((current) => ({ ...current, categoryKey: event.target.value }))}
                  >
                    {CATEGORY_OPTIONS.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>Овог (EN)</span>
                  <input value={draft.lastNameEn} onChange={(event) => setDraft((current) => ({ ...current, lastNameEn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Нэр (EN)</span>
                  <input value={draft.firstNameEn} onChange={(event) => setDraft((current) => ({ ...current, firstNameEn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Овог (MN)</span>
                  <input value={draft.lastNameMn} onChange={(event) => setDraft((current) => ({ ...current, lastNameMn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Нэр (MN)</span>
                  <input value={draft.firstNameMn} onChange={(event) => setDraft((current) => ({ ...current, firstNameMn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Албан тушаал (EN)</span>
                  <input value={draft.positionEn} onChange={(event) => setDraft((current) => ({ ...current, positionEn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Албан тушаал (MN)</span>
                  <input value={draft.positionMn} onChange={(event) => setDraft((current) => ({ ...current, positionMn: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Регистр</span>
                  <input value={draft.registerNumber} onChange={(event) => setDraft((current) => ({ ...current, registerNumber: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Email 1</span>
                  <input value={draft.emailPrimary} onChange={(event) => setDraft((current) => ({ ...current, emailPrimary: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Email 2</span>
                  <input value={draft.emailSecondary} onChange={(event) => setDraft((current) => ({ ...current, emailSecondary: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Утас 1</span>
                  <input value={draft.phonePrimary} onChange={(event) => setDraft((current) => ({ ...current, phonePrimary: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Утас 2</span>
                  <input value={draft.phoneSecondary} onChange={(event) => setDraft((current) => ({ ...current, phoneSecondary: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Duty phone</span>
                  <input value={draft.dutyPhone} onChange={(event) => setDraft((current) => ({ ...current, dutyPhone: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Төрсөн огноо</span>
                  <input value={draft.dateOfBirth} onChange={(event) => setDraft((current) => ({ ...current, dateOfBirth: event.target.value }))} />
                </label>
                <label className="field">
                  <span>Ажилд орсон огноо</span>
                  <input value={draft.hireDate} onChange={(event) => setDraft((current) => ({ ...current, hireDate: event.target.value }))} />
                </label>
                <label className="field field-span-2">
                  <span>Гэрийн хаяг</span>
                  <textarea value={draft.homeAddress} onChange={(event) => setDraft((current) => ({ ...current, homeAddress: event.target.value }))} rows={3} />
                </label>
                <label className="field field-span-2">
                  <span>Тэмдэглэл</span>
                  <textarea value={draft.notes} onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} rows={3} />
                </label>
                <label className="field field-span-2">
                  <span>Нэмэлт мэдээлэл</span>
                  <textarea value={draft.extraInfo} onChange={(event) => setDraft((current) => ({ ...current, extraInfo: event.target.value }))} rows={2} />
                </label>

                <div className="employee-photo-editor field-span-2">
                  <div className="employee-photo-preview-wrap">
                    {currentPhotoUrl && !draft.removePhoto ? (
                      <img className="employee-photo-preview" src={currentPhotoUrl} alt="Employee preview" />
                    ) : (
                      <div className="employee-photo-empty">Зураггүй</div>
                    )}
                  </div>
                  <div className="employee-photo-editor-actions">
                    <label className="new-chat-rail-button employee-upload-button">
                      <span>Зураг сонгох</span>
                      <input type="file" accept="image/*" hidden onChange={(event) => void handlePhotoChange(event)} />
                    </label>
                    {editingEmployee?.hasPhoto || photoPreviewUrl ? (
                      <button
                        className="employee-action-button danger"
                        type="button"
                        onClick={() => {
                          if (photoPreviewUrl) {
                            URL.revokeObjectURL(photoPreviewUrl);
                            setPhotoPreviewUrl("");
                          }
                          setDraft((current) => ({
                            ...current,
                            photoContent: "",
                            photoMimeType: "",
                            removePhoto: true,
                          }));
                        }}
                      >
                        Зураг арилгах
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>

            <div className="employee-modal-footer">
              <button className="employee-action-button" type="button" onClick={closeModal}>
                Болих
              </button>
              <button className="new-chat-rail-button employee-save-button" type="button" onClick={() => void handleSaveEmployee()} disabled={isSaving}>
                <span>{isSaving ? "Хадгалж байна..." : "Хадгалах"}</span>
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

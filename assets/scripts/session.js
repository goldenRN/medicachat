export const STORAGE_KEY = "sosmedica_chatbot_token";

export function getStoredToken() {
  return localStorage.getItem(STORAGE_KEY) || "";
}

export function setStoredToken(token) {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearStoredToken() {
  localStorage.removeItem(STORAGE_KEY);
}

export function initialsFromEmail(email) {
  return String(email || "ME").slice(0, 2).toUpperCase();
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export const timeFormatter = new Intl.DateTimeFormat("mn-MN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatTimestamp(value) {
  return timeFormatter.format(new Date(value));
}

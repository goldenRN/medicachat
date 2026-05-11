"use client";

export const STORAGE_KEY = "sosmedica_chatbot_token";

export function getStoredToken() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(STORAGE_KEY) || "";
}

export function setStoredToken(token) {
  window.localStorage.setItem(STORAGE_KEY, token);
}

export function clearStoredToken() {
  window.localStorage.removeItem(STORAGE_KEY);
}

export function initialsFromEmail(email) {
  return String(email || "ME").slice(0, 2).toUpperCase();
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

export function getExtension(filename) {
  const lastDot = String(filename || "").lastIndexOf(".");
  return lastDot >= 0 ? filename.slice(lastDot).toLowerCase() : "";
}

export function bytesToBase64(bytes) {
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary);
}

import { clearStoredToken, getStoredToken } from "/assets/scripts/session.js";

export async function fetchJson(url, options = {}) {
  const requestOptions = {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };

  const token = getStoredToken();
  if (token) {
    requestOptions.headers.Authorization = `Bearer ${token}`;
  }

  if (options.body) {
    requestOptions.body = JSON.stringify(options.body);
  }

  const response = await fetch(url, requestOptions);
  let payload = {};

  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (response.status === 401) {
    clearStoredToken();
    if (options.redirectOnAuthFailure !== false) {
      window.location.replace("/login");
    }
  }

  if (!response.ok) {
    throw new Error(payload.error || "Алдаа гарлаа.");
  }

  return payload;
}

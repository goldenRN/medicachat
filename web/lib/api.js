"use client";

import { clearStoredToken, getOrCreateGuestId, getStoredToken } from "@/lib/session";

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
  } else {
    requestOptions.headers["X-Guest-Id"] = getOrCreateGuestId();
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

export async function fetchBlob(url, options = {}) {
  const requestOptions = {
    method: options.method || "GET",
    headers: {
      ...(options.headers || {}),
    },
  };

  const token = getStoredToken();
  if (token) {
    requestOptions.headers.Authorization = `Bearer ${token}`;
  } else {
    requestOptions.headers["X-Guest-Id"] = getOrCreateGuestId();
  }

  const response = await fetch(url, requestOptions);

  if (response.status === 401) {
    clearStoredToken();
    if (options.redirectOnAuthFailure !== false) {
      window.location.replace("/login");
    }
  }

  if (!response.ok) {
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    throw new Error(payload.error || "Алдаа гарлаа.");
  }

  return {
    blob: await response.blob(),
    contentType: response.headers.get("content-type") || "",
  };
}

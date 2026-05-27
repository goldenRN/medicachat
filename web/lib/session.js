"use client";

export const STORAGE_KEY = "sosmedica_chatbot_token";
export const GUEST_STORAGE_KEY = "sosmedica_chatbot_guest_id";

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

export function getStoredGuestId() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(GUEST_STORAGE_KEY) || "";
}

export function getOrCreateGuestId() {
  if (typeof window === "undefined") {
    return "";
  }

  const existing = getStoredGuestId();
  if (existing) {
    return existing;
  }

  const nextId =
    typeof window.crypto?.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `guest-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(GUEST_STORAGE_KEY, nextId);
  return nextId;
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


function changeExtension(filename, nextExtension) {
  const lastDot = String(filename || "").lastIndexOf(".");
  if (lastDot < 0) {
    return `${filename}${nextExtension}`;
  }
  return `${filename.slice(0, lastDot)}${nextExtension}`;
}


export async function optimizeImageForUpload(file, options = {}) {
  const {
    maxWidth = 1600,
    maxHeight = 1600,
    quality = 0.82,
  } = options;

  if (!file.type.startsWith("image/")) {
    return {
      fileName: file.name,
      mimeType: file.type,
      bytes: new Uint8Array(await file.arrayBuffer()),
    };
  }

  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxWidth / bitmap.width, maxHeight / bitmap.height);
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas context unavailable");
    }

    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();

    const targetType = file.type === "image/png" ? "image/png" : "image/jpeg";
    const optimizedBlob = await new Promise((resolve) =>
      canvas.toBlob(resolve, targetType, targetType === "image/png" ? undefined : quality),
    );

    if (!optimizedBlob) {
      throw new Error("Image optimization failed");
    }

    const optimizedBytes = new Uint8Array(await optimizedBlob.arrayBuffer());
    const originalBytes = new Uint8Array(await file.arrayBuffer());
    if (optimizedBytes.length >= originalBytes.length) {
      return {
        fileName: file.name,
        mimeType: file.type,
        bytes: originalBytes,
      };
    }

    const nextFileName =
      targetType === "image/jpeg" && !/\.(jpe?g)$/i.test(file.name)
        ? changeExtension(file.name, ".jpg")
        : targetType === "image/png" && !/\.png$/i.test(file.name)
          ? changeExtension(file.name, ".png")
          : file.name;

    return {
      fileName: nextFileName,
      mimeType: targetType,
      bytes: optimizedBytes,
    };
  } catch {
    return {
      fileName: file.name,
      mimeType: file.type,
      bytes: new Uint8Array(await file.arrayBuffer()),
    };
  }
}

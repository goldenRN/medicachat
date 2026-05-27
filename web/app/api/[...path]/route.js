const DEFAULT_BACKEND_PORT = process.env.BACKEND_PORT || "4000";
const RETRYABLE_METHODS = new Set(["GET", "HEAD"]);

function normalizeBackendBaseUrl(value) {
  const normalizedBase = String(value || "").trim().replace(/\/+$/, "");
  if (!normalizedBase) {
    return "";
  }
  return normalizedBase.endsWith("/api") ? normalizedBase : `${normalizedBase}/api`;
}

function getBackendBaseUrls() {
  const configuredBase = normalizeBackendBaseUrl(process.env.BACKEND_API_BASE_URL);
  const fallbackBases = [
    `http://127.0.0.1:${DEFAULT_BACKEND_PORT}/api`,
    `http://localhost:${DEFAULT_BACKEND_PORT}/api`,
  ];
  const candidates = [configuredBase, ...fallbackBases].filter(Boolean);
  return [...new Set(candidates)];
}

const BACKEND_BASE_URLS = getBackendBaseUrls();

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function fetchWithRetry(targetUrl, init, attemptCount) {
  let lastError;

  for (let attempt = 0; attempt < attemptCount; attempt += 1) {
    try {
      return await fetch(targetUrl, init);
    } catch (error) {
      lastError = error;
      if (attempt < attemptCount - 1) {
        await wait(150 * (attempt + 1));
      }
    }
  }

  throw lastError;
}

async function proxy(request, { params }) {
  const routeParams = await params;
  const path = Array.isArray(routeParams.path) ? routeParams.path.join("/") : "";
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }

  const attemptCount = RETRYABLE_METHODS.has(request.method) ? 2 : 1;
  const attemptedUrls = [];
  let lastError = null;

  for (const backendBaseUrl of BACKEND_BASE_URLS) {
    const targetUrl = new URL(`${backendBaseUrl}/${path}`);
    targetUrl.search = new URL(request.url).search;
    attemptedUrls.push(targetUrl.toString());

    try {
      const upstream = await fetchWithRetry(targetUrl, init, attemptCount);
      const responseHeaders = new Headers(upstream.headers);
      responseHeaders.delete("content-encoding");
      responseHeaders.delete("content-length");
      responseHeaders.delete("transfer-encoding");

      return new Response(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
      });
    } catch (error) {
      lastError = error;
      console.error("[proxy] upstream fetch failed", {
        method: request.method,
        targetUrl: targetUrl.toString(),
        message: error instanceof Error ? error.message : String(error),
        cause: error && typeof error === "object" && "cause" in error ? error.cause : undefined,
      });
    }
  }

  return Response.json(
    {
      error: "Backend-тэй холбогдож чадсангүй. Backend server асаалттай байгаа эсэхийг шалгана уу.",
      attemptedUrls,
      message: lastError instanceof Error ? lastError.message : String(lastError || ""),
    },
    { status: 502 },
  );
}

export { proxy as GET, proxy as POST, proxy as OPTIONS };

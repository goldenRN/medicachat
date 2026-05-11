const BACKEND_BASE_URL =
  process.env.BACKEND_API_BASE_URL || "http://127.0.0.1:4173/api";

async function proxy(request, { params }) {
  const routeParams = await params;
  const path = Array.isArray(routeParams.path) ? routeParams.path.join("/") : "";
  const targetUrl = new URL(`${BACKEND_BASE_URL}/${path}`);
  targetUrl.search = new URL(request.url).search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = await request.text();
  }

  const upstream = await fetch(targetUrl, init);
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST };

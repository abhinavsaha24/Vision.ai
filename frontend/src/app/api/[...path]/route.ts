import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const ALLOWED_METHODS = new Set([
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "OPTIONS",
  "HEAD",
]);

const DEFAULT_ALLOWED_PREFIXES = [
  "/auth/",
  "/health",
  "/market/",
  "/model/",
  "/portfolio/",
  "/paper-trading/",
  "/trading/",
  "/orders/",
  "/system/",
  "/workers/",
  "/strategies/",
  "/strategy/",
  "/live-trading/",
  "/risk/",
  "/regime/",
  "/sentiment/",
  "/monitoring/",
  "/news",
  "/market-intelligence",
  "/research/",
];

const DEFAULT_DENIED_PREFIXES = ["/admin/", "/internal/", "/debug/"];

function normalizePrefix(prefix: string): string {
  const trimmed = prefix.trim();
  if (!trimmed) return "";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function readPrefixListEnv(envKey: string, fallback: string[]): string[] {
  const raw = process.env[envKey]?.trim();
  if (!raw) return fallback;

  const parsed = raw
    .split(",")
    .map((token) => normalizePrefix(token))
    .filter((token) => token.length > 0);

  return parsed.length > 0 ? parsed : fallback;
}

const ALLOWED_PREFIXES = readPrefixListEnv(
  "NEXT_API_PROXY_ALLOW_PREFIXES",
  DEFAULT_ALLOWED_PREFIXES,
);
const DENIED_PREFIXES = readPrefixListEnv(
  "NEXT_API_PROXY_DENY_PREFIXES",
  DEFAULT_DENIED_PREFIXES,
);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

function resolveBackendBaseUrl(): string {
  const internal = process.env.NEXT_INTERNAL_API_URL?.trim();
  if (internal) return internal.replace(/\/$/, "");

  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");

  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "NEXT_PUBLIC_API_URL or NEXT_INTERNAL_API_URL must be set in production",
    );
  }

  // Local default for non-containerized development.
  return "http://127.0.0.1:8080";
}

function buildBackendUrl(req: NextRequest, path: string[]): string {
  const query = req.nextUrl.search || "";
  const normalizedPath = path.length ? `/${path.join("/")}` : "";
  return `${resolveBackendBaseUrl()}${normalizedPath}${query}`;
}

function normalizePath(path: string[]): string | null {
  const clean = path
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);

  if (clean.length === 0) return "/";

  for (const segment of clean) {
    if (segment === "." || segment === "..") return null;
    if (segment.includes("\\")) return null;
  }

  return `/${clean.join("/")}`;
}

function isAllowedPath(normalizedPath: string): boolean {
  if (normalizedPath === "/") return false;

  const denied = DENIED_PREFIXES.some(
    (prefix) =>
      normalizedPath === prefix.slice(0, -1) ||
      normalizedPath.startsWith(prefix),
  );
  if (denied) return false;

  return ALLOWED_PREFIXES.some(
    (prefix) =>
      normalizedPath === prefix ||
      normalizedPath === prefix.replace(/\/$/, "") ||
      normalizedPath.startsWith(prefix),
  );
}

function buildOutboundHeaders(req: NextRequest): Headers {
  const headers = new Headers();

  req.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP_HEADERS.has(lower)) return;
    if (lower === "content-length") return;
    headers.set(key, value);
  });

  const tokenCookie = req.cookies.get("vision_ai_token")?.value;
  if (tokenCookie && !headers.has("authorization")) {
    headers.set("authorization", `Bearer ${tokenCookie}`);
  }

  headers.set("x-forwarded-host", req.nextUrl.host);
  headers.set("x-forwarded-proto", req.nextUrl.protocol.replace(":", ""));

  return headers;
}

async function proxy(req: NextRequest, params: { path: string[] }) {
  const method = req.method.toUpperCase();
  if (!ALLOWED_METHODS.has(method)) {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  const normalizedPath = normalizePath(params.path ?? []);
  if (!normalizedPath) {
    return Response.json({ error: "Invalid path" }, { status: 400 });
  }

  if (!isAllowedPath(normalizedPath)) {
    return Response.json({ error: "Endpoint not allowed" }, { status: 403 });
  }

  const targetUrl = buildBackendUrl(req, normalizedPath.slice(1).split("/"));
  const isBodyMethod = !["GET", "HEAD"].includes(method);
  const outboundBody = isBodyMethod ? await req.arrayBuffer() : undefined;

  let response: Response;
  try {
    response = await fetch(targetUrl, {
      method,
      headers: buildOutboundHeaders(req),
      body: outboundBody,
      redirect: "manual",
      cache: "no-store",
    });
  } catch (error) {
    return Response.json(
      {
        error: "Backend service unavailable",
        target: targetUrl,
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }

  const downstreamHeaders = new Headers();
  response.headers.forEach((value, key) => {
    const lowerKey = key.toLowerCase();
    if (HOP_BY_HOP_HEADERS.has(lowerKey)) return;
    if (lowerKey === "set-cookie") return; // Manually handled
    downstreamHeaders.set(key, value);
  });

  const setCookies = response.headers.getSetCookie 
    ? response.headers.getSetCookie() 
    : [];
    
  for (const cookie of setCookies) {
    downstreamHeaders.append("set-cookie", cookie);
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: downstreamHeaders,
  });
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function PUT(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function OPTIONS(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

export async function HEAD(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, await ctx.params);
}

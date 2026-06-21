const trimTrailingSlash = (value) => (value ? value.replace(/\/+$/, "") : "");
const ensureLeadingSlash = (value) => (value.startsWith("/") ? value : `/${value}`);

const resolveApiBaseUrl = () => {
  const envValue = trimTrailingSlash(import.meta.env.VITE_API_URL);
  if (envValue) return envValue;
  if (typeof window === "undefined") return "";
  return window.location.origin;
};

const resolveWsBaseUrl = () => {
  const envValue = trimTrailingSlash(import.meta.env.VITE_WS_URL);
  if (envValue) return envValue;
  if (typeof window === "undefined") return "";
  const isDev = import.meta.env.DEV;
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  if (isDev && window.location.host) {
    return `${wsProtocol}://${window.location.host}`;
  }
  return `${wsProtocol}://${window.location.host}`;
};

export const apiBaseUrl = resolveApiBaseUrl();
export const wsBaseUrl = resolveWsBaseUrl();

export const buildApiUrl = (path) => `${apiBaseUrl}${ensureLeadingSlash(path)}`;

const delay = (delayMs) => new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));

const shouldRetryResponse = (response, retryStatuses) => retryStatuses.includes(response.status);

export const fetchWithRetry = async (
  path,
  options = {},
  {
    attempts = 5,
    initialDelayMs = 300,
    maxDelayMs = 4000,
    retryStatuses = [502, 503, 504],
    onRetry = null,
  } = {}
) => {
  let lastError = null;
  const safeAttempts = Math.max(1, Number(attempts) || 1);
  for (let attempt = 1; attempt <= safeAttempts; attempt += 1) {
    try {
      const response = await fetch(buildApiUrl(path), options);
      if (!shouldRetryResponse(response, retryStatuses) || attempt === safeAttempts) {
        return response;
      }
      lastError = new Error(`Retryable response status ${response.status}`);
    } catch (error) {
      lastError = error;
      if (attempt === safeAttempts) throw error;
    }

    const delayMs = Math.min(maxDelayMs, initialDelayMs * 2 ** (attempt - 1));
    onRetry?.({ attempt, delayMs, error: lastError });
    await delay(delayMs);
  }

  throw lastError || new Error("Request failed.");
};

export const fetchJsonWithTimeout = async (
  path,
  options = {},
  { timeoutMs = 15000 } = {}
) => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(buildApiUrl(path), {
      ...options,
      signal: controller.signal,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    return { response, payload };
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("Request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
};
export const buildWsUrl = (path, params = null) => {
  const base = `${wsBaseUrl}${ensureLeadingSlash(path)}`;
  if (!params) return base;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${base}?${query}` : base;
};

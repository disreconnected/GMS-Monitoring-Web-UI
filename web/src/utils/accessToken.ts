const STORAGE_KEY = "gms-access-token";

let cachedToken: string | null | undefined;

export function setAccessToken(token: string): void {
  const trimmed = token.trim();
  cachedToken = trimmed;
  try {
    sessionStorage.setItem(STORAGE_KEY, trimmed);
  } catch {
    // ignore storage failures
  }
}

export function clearAccessToken(): void {
  cachedToken = null;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failures
  }
}

/** Read token from URL fragment, sessionStorage, or build-time env. */
export function consumeAccessTokenFromFragment(): string | null {
  if (cachedToken !== undefined && cachedToken !== null) {
    return cachedToken;
  }

  const hash = window.location.hash;
  if (hash.startsWith("#token=")) {
    const token = decodeURIComponent(hash.slice("#token=".length));
    setAccessToken(token);
    const cleanUrl = window.location.pathname + window.location.search;
    window.history.replaceState(null, "", cleanUrl);
    return token;
  }

  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      cachedToken = stored;
      return stored;
    }
  } catch {
    // ignore storage failures
  }

  const envToken = import.meta.env.VITE_ACCESS_TOKEN;
  if (typeof envToken === "string" && envToken.trim()) {
    setAccessToken(envToken.trim());
    return envToken.trim();
  }

  cachedToken = null;
  return null;
}

export function getAccessToken(): string | null {
  if (cachedToken === undefined) {
    consumeAccessTokenFromFragment();
  }
  return cachedToken ?? null;
}

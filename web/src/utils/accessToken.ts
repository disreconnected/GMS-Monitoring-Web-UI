let cachedToken: string | null | undefined;

/** Read token from URL fragment once and remove it from the address bar. */
export function consumeAccessTokenFromFragment(): string | null {
  if (cachedToken !== undefined) {
    return cachedToken;
  }

  const hash = window.location.hash;
  if (!hash.startsWith("#token=")) {
    cachedToken = null;
    return null;
  }

  const token = decodeURIComponent(hash.slice("#token=".length));
  cachedToken = token;

  const cleanUrl = window.location.pathname + window.location.search;
  window.history.replaceState(null, "", cleanUrl);

  return token;
}

export function getAccessToken(): string | null {
  if (cachedToken === undefined) {
    consumeAccessTokenFromFragment();
  }
  return cachedToken ?? null;
}

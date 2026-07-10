import { useState } from "react";
import { setAccessToken } from "../utils/accessToken";

type TokenEntryPanelProps = {
  onSubmit: (token: string) => void;
};

export function TokenEntryPanel({ onSubmit }: TokenEntryPanelProps) {
  const [token, setToken] = useState("");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) return;
    setAccessToken(trimmed);
    onSubmit(trimmed);
  };

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center bg-bg px-4 text-center">
      <h1 className="text-2xl font-medium text-fg">Access token required</h1>
      <p className="mt-3 max-w-md text-fg-muted">
        Open the secure URL printed by the server, or enter the access token for
        this session below.
      </p>
      <form onSubmit={handleSubmit} className="mt-6 flex w-full max-w-md flex-col gap-3">
        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Paste access token"
          className="rounded-lg border border-edge bg-surface px-4 py-3 font-mono text-sm text-fg outline-none focus:border-accent"
          autoComplete="off"
        />
        <button
          type="submit"
          className="rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-white transition active:scale-[0.98]"
        >
          Connect
        </button>
      </form>
    </div>
  );
}

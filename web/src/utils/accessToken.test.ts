import { beforeEach, describe, expect, it } from "vitest";
import {
  clearAccessToken,
  consumeAccessTokenFromFragment,
  getAccessToken,
  setAccessToken,
} from "./accessToken";

describe("accessToken", () => {
  beforeEach(() => {
    sessionStorage.clear();
    clearAccessToken();
    window.history.replaceState(null, "", "/");
  });

  it("reads token from URL fragment and stores it in sessionStorage", () => {
    window.location.hash = "#token=abc123";
    expect(consumeAccessTokenFromFragment()).toBe("abc123");
    expect(sessionStorage.getItem("gms-access-token")).toBe("abc123");
    expect(window.location.hash).toBe("");
  });

  it("restores token from sessionStorage after refresh", () => {
    setAccessToken("stored-token");
    expect(getAccessToken()).toBe("stored-token");
  });

  it("clears rejected credentials", () => {
    setAccessToken("bad-token");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});

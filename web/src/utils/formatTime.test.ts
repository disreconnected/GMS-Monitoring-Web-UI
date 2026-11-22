import { describe, expect, it } from "vitest";
import { formatHostsSlow } from "./formatTime";

describe("formatHostsSlow", () => {
  it("returns null when nothing is slow or the field is missing", () => {
    expect(formatHostsSlow(undefined)).toBeNull();
    expect(formatHostsSlow([])).toBeNull();
  });

  it("shows seconds under a minute and rounds minutes up", () => {
    expect(
      formatHostsSlow(
        [
          { name: "BWP", retry_at: 1030 },
          { name: "CoreSwitch", retry_at: 1121 },
        ],
        1000,
      ),
    ).toBe("BWP retry in 30s, CoreSwitch retry in 3m");
  });

  it("never shows a negative wait", () => {
    expect(formatHostsSlow([{ name: "BWP", retry_at: 990 }], 1000)).toBe("BWP retry in 0s");
  });
});

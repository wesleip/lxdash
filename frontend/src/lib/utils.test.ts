import { describe, expect, it } from "vitest";
import { cn, formatBytes, formatRelativeTime } from "./utils";

describe("cn", () => {
  it("merges class strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("drops falsy values", () => {
    expect(cn("foo", false, null, undefined, "bar")).toBe("foo bar");
  });

  it("deduplicates Tailwind conflicts", () => {
    // The later class wins in tailwind-merge semantics.
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});

describe("formatBytes", () => {
  it("formats zero", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
  });

  it("formats kilobytes", () => {
    expect(formatBytes(1024)).toBe("1 KB");
  });

  it("formats megabytes with decimals", () => {
    expect(formatBytes(1024 * 1024 * 1.5, 2)).toBe("1.5 MB");
  });

  it("formats gigabytes", () => {
    expect(formatBytes(1024 ** 3)).toBe("1 GB");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date();

  it("returns 'just now' for under a minute", () => {
    const thirtySecondsAgo = new Date(now.getTime() - 30 * 1000).toISOString();
    expect(formatRelativeTime(thirtySecondsAgo)).toBe("just now");
  });

  it("formats minutes", () => {
    const fiveMinAgo = new Date(now.getTime() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveMinAgo)).toBe("5m ago");
  });

  it("formats hours", () => {
    const threeHoursAgo = new Date(now.getTime() - 3 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(threeHoursAgo)).toBe("3h ago");
  });

  it("formats days for under a month", () => {
    const fiveDaysAgo = new Date(now.getTime() - 5 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveDaysAgo)).toBe("5d ago");
  });

  it("falls back to a date for older entries", () => {
    const longAgo = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000).toISOString();
    // The exact format depends on the locale; just check it's not a relative marker.
    const result = formatRelativeTime(longAgo);
    expect(result).not.toMatch(/ago$/);
    expect(result).not.toBe("just now");
  });
});
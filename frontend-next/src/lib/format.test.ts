/**
 * Snapshot-table tests for the format helpers. Each function gets a
 * `it.each` table so adding a regression case is one line + one expected
 * string. Snapshots are intentionally not used here — explicit values keep
 * the contract obvious during review.
 */
import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatCurrency,
  formatDuration,
  formatNumber,
} from "./format";

describe("formatCurrency", () => {
  it.each([
    [0, "$0"],
    [1, "$1"],
    [1.5, "$1.50"],
    [1234, "$1,234"],
    [1234.56, "$1,234.56"],
    [1_000_000, "$1,000,000"],
    [-50, "-$50"],
  ])("formats %s -> %s", (input, expected) => {
    expect(formatCurrency(input)).toBe(expected);
  });
});

describe("formatNumber", () => {
  it.each([
    [0, "0"],
    [42, "42"],
    [999, "999"],
    [1_000, "1.0K"],
    [1_500, "1.5K"],
    [12_345, "12.3K"],
    [1_000_000, "1.0M"],
    [2_500_000, "2.5M"],
  ])("formats %s -> %s", (input, expected) => {
    expect(formatNumber(input)).toBe(expected);
  });
});

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [1, "1 B"],
    [1024, "1 KB"],
    [1536, "1.5 KB"],
    [1024 * 1024, "1 MB"],
    [1024 * 1024 * 1024, "1 GB"],
    [1024 * 1024 * 1024 * 1024, "1 TB"],
  ])("formats %s -> %s", (input, expected) => {
    expect(formatBytes(input)).toBe(expected);
  });
});

describe("formatDuration", () => {
  it.each([
    [500, "500ms"],
    [999, "999ms"],
    [1500, "1.5s"],
    [60_000, "1.0m"],
    [90_000, "1.5m"],
    [3_600_000, "1.0h"],
    [5_400_000, "1.5h"],
  ])("formats %s -> %s", (input, expected) => {
    expect(formatDuration(input)).toBe(expected);
  });
});

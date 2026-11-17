import { expect, it } from "vitest";
import { BUSY_POLL_MS, IDLE_POLL_MS, documentPoll, workspacePoll } from "./live-poll";

const query = <T>(data?: T) => ({ state: { data } });

it("polls briskly only while a generation or board job is in flight", () => {
  expect(documentPoll(query({ generations: [{ status: "running" }] } as never))).toBe(BUSY_POLL_MS);
  expect(documentPoll(query({ generations: [{ status: "completed" }] } as never))).toBe(IDLE_POLL_MS);
  expect(workspacePoll(query({ boards: [{ jobs: [{}] }] } as never))).toBe(BUSY_POLL_MS);
  expect(workspacePoll(query({ boards: [{ jobs: [] }] } as never))).toBe(IDLE_POLL_MS);
});

it("never throws on missing or partial data (a poll must not crash a view)", () => {
  for (const data of [undefined, {}, { generations: undefined }, { boards: [{}] }]) {
    expect(documentPoll(query(data as never))).toBe(IDLE_POLL_MS);
    expect(workspacePoll(query(data as never))).toBe(IDLE_POLL_MS);
  }
});

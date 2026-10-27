import { beforeEach, describe, expect, it } from "vitest";
import { changeCut, draftPrefix, newHistory, readDrafts, redoCut, undoCut, type LocalCut } from "./timeline-draft";
import type { TimelineTrack } from "./types";

const empty: TimelineTrack[] = [{ kind: "video", clips: [] }];
const tracks: TimelineTrack[] = [{ kind: "video", clips: [{ id: "one", source_asset_id: "asset", source_in: 0, source_out: 2, timeline_in: 0, timeline_out: 2 }] }];
beforeEach(() => localStorage.clear());
describe("cut history", () => {
  it("supports undo/redo, ignores no-ops, and clears redo on a new branch", () => {
    const first = newHistory(empty), second = changeCut(first, tracks, "Add");
    expect(changeCut(second, structuredClone(tracks), "No-op")).toBe(second);
    const undone = undoCut(second);
    expect(undone.present.tracks).toEqual(empty);
    expect(redoCut(undone).present.tracks).toEqual(tracks);
    const branched = changeCut(undone, [{ kind: "audio", clips: [] }], "Different edit");
    expect(branched.future).toEqual([]);
    expect(redoCut(branched)).toBe(branched);
    expect(undoCut(first)).toBe(first);
    expect(first.present.tracks).toEqual(empty);
  });
  it("bounds memory to 100 undo entries", () => {
    let history = newHistory(empty);
    for (let i = 0; i < 130; i++) history = changeCut(history, [{ kind: `track-${i}`, clips: [] }], "Edit");
    expect(history.past).toHaveLength(100);
  });
});
describe("draft recovery boundaries", () => {
  it("only reads dirty, valid records for the exact project and timeline", () => {
    const cut: LocalCut = { schema: 1, projectId: "project", timelineId: "timeline", updatedAt: new Date().toISOString(), tracks, baseline: JSON.stringify(empty) };
    const prefix = draftPrefix("project", "timeline");
    localStorage.setItem(prefix + "good", JSON.stringify(cut));
    localStorage.setItem(prefix + "corrupt", "{");
    localStorage.setItem(prefix + "wrong-project", JSON.stringify({ ...cut, projectId: "another" }));
    localStorage.setItem(prefix + "wrong-version", JSON.stringify({ ...cut, base: { id: "v", timeline_id: "foreign", version_number: 1 } }));
    localStorage.setItem(prefix + "clean", JSON.stringify({ ...cut, baseline: JSON.stringify(tracks) }));
    localStorage.setItem(prefix + "bad-time", JSON.stringify({ ...cut, tracks: [{ kind: "video", clips: [{ id: "bad", timeline_in: 2, timeline_out: 1 }] }] }));
    localStorage.setItem(draftPrefix("project", "elsewhere") + "other", JSON.stringify(cut));
    expect(readDrafts(localStorage, "project", "timeline").map((record) => record.key)).toEqual([prefix + "good"]);
  });
});

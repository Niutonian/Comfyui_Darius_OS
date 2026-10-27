import { describe, expect, it } from "vitest";
import { dragTrim, moveClipTo, reorderClipAt, snapTime } from "./timeline-motion";
import { editShortcut } from "./edit-shortcuts";
import { audioGain } from "./timeline-audio";
import { splitClip } from "./edit-timeline";
import type { TimelineTrack } from "./types";

const tracks: TimelineTrack[] = [{ kind: "video", clips: [
  { id: "a", source_asset_id: "source", source_in: 1, source_out: 3, timeline_in: 2, timeline_out: 4, muted: true },
  { id: "b", source_asset_id: "other", source_in: 0, source_out: 2, timeline_in: 6, timeline_out: 8 },
] }, { kind: "audio", clips: [{ id: "sound", timeline_in: 0, timeline_out: 9, source_asset_id: "music", source_in: 0, source_out: 9 }] }];
describe("drag timing", () => {
  it("moves into gaps, rejects overlaps, and retains linked clip metadata and other tracks", () => {
    const moved = moveClipTo(tracks, 0, "a", 4);
    expect(moved[0].clips[0]).toMatchObject({ timeline_in: 4, timeline_out: 6, source_in: 1, muted: true });
    expect(moved[1]).toBe(tracks[1]);
    expect(moveClipTo(tracks, 0, "a", 5)).toBe(tracks);
    expect(moveClipTo(tracks, 0, "a", -1)).toBe(tracks);
    expect(tracks[0].clips[0].timeline_in).toBe(2);
  });
  it("reorders explicitly into an assembly without changing media trims", () => {
    const reordered = reorderClipAt(tracks, 0, "a", 9);
    expect(reordered[0].clips).toMatchObject([{ id: "b", timeline_in: 0, timeline_out: 2 }, { id: "a", timeline_in: 2, timeline_out: 4, source_in: 1, source_out: 3 }]);
    expect(reordered[1]).toBe(tracks[1]);
  });
  it("edge trims clamp against neighbors, source bounds and a minimum frame", () => {
    expect(dragTrim(tracks, 0, "a", "in", 0, 5, 24)[0].clips[0]).toMatchObject({ timeline_in: 1, source_in: 0, timeline_out: 4 });
    expect(dragTrim(tracks, 0, "a", "out", 10, 20, 24)[0].clips[0]).toMatchObject({ timeline_out: 6, source_out: 5 });
    expect(dragTrim(tracks, 0, "a", "out", 10, 4, 24)[0].clips[0]).toMatchObject({ timeline_out: 5, source_out: 4 });
    expect(dragTrim(tracks, 0, "a", "in", 100, 5, 24)[0].clips[0].timeline_in).toBeCloseTo(4 - 1 / 24);
    expect(dragTrim(tracks, 0, "a", "out", 5, 5, 24)[1]).toBe(tracks[1]);
  });
  it("snaps near anchors and otherwise quantizes to project frames", () => {
    expect(snapTime(2.08, [2], 24, .1)).toBe(2);
    expect(snapTime(2.4, [2], 24, .1)).toBe(58 / 24);
    expect(snapTime(2.08, [], 24, .1)).toBe(50 / 24);
    expect(snapTime(-1, [], 24, .1)).toBe(0);
  });
});
describe("editor shortcut mapping", () => {
  const key = (value: string, options = {}) => editShortcut({ key: value, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...options });
  it("maps trim/split/frame/nudge/delete keys without stealing browser command combinations", () => {
    expect(key("q")).toBe("trim-start"); expect(key("w")).toBe("trim-end"); expect(key("s")).toBe("split");
    expect(key("[", { shiftKey: true })).toBe("out-left"); expect(key("}", { shiftKey: true })).toBe("out-right");
    expect(key("ArrowRight", { altKey: true })).toBe("move-right");
    expect(key("Delete", { shiftKey: true })).toBe("ripple-delete");
    expect(key("s", { ctrlKey: true })).toBe("save");
    expect(key("z", { metaKey: true, shiftKey: true })).toBe("redo");
    expect(key("r", { ctrlKey: true })).toBeNull(); expect(key("q", { altKey: true })).toBeNull();
    expect(key("s", { repeat: true })).toBeNull();
  });
});
describe("audio envelopes", () => {
  it("preserves a fade across a split, including a split inside the fade", () => {
    const clip = { id: "fade", source_in: 2, source_out: 5, timeline_in: 1, timeline_out: 4, volume: .5, fade_in: 2, fade_out: 1 };
    const split = splitClip([{ kind: "video", clips: [clip] }], 0, "fade", 2, "right")[0].clips;
    for (const time of [1, 1.5, 2, 2.5, 3.5, 4]) {
      expect(audioGain(time < 2 ? split[0] : split[1], time)).toBeCloseTo(audioGain(clip, time));
    }
    expect(audioGain({ ...clip, muted: true }, 2)).toBe(0);
  });
});

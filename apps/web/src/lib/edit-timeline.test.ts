import { describe, expect, it } from "vitest";
import { assetName, clipAt, pictureClips, previewIssue, reflowClips, removeClip, sequenceDuration, sourceTime, splitClip, trimClip } from "./edit-timeline";
import type { Asset, TimelineTrack } from "./types";
const clip = { id: "c", source_asset_id: "a", source_in: 2, source_out: 5, timeline_in: 1, timeline_out: 4 };
describe("sequence timing", () => {
  it("maps source trims and gaps without treating them as contiguous flex widths", () => {
    const tracks: TimelineTrack[] = [{ kind: "video", clips: [clip] }, { kind: "audio", clips: [{ ...clip, timeline_out: 8 }] }];
    expect(sequenceDuration(tracks)).toBe(8);
    expect(clipAt(pictureClips(tracks), .5)).toBeUndefined();
    expect(clipAt(pictureClips(tracks), 1)).toBe(clip);
    expect(clipAt(pictureClips(tracks), 4)).toBeUndefined();
    expect(sourceTime(clip, 2)).toBe(3);
    expect(reflowClips([clip, { ...clip, id: "d" }])).toMatchObject([{ timeline_in: 0, timeline_out: 3 }, { timeline_in: 3, timeline_out: 6 }]);
  });
  it("identifies unsupported and missing sources instead of silently skipping them", () => {
    expect(previewIssue([{ kind: "video", clips: [clip] }], [])).toMatch(/unavailable/);
    expect(previewIssue([{ kind: "video", clips: [clip] }, { kind: "video", clips: [clip] }], [])).toMatch(/one picture track/);
    expect(previewIssue([{ kind: "subtitle", clips: [clip] }], [])).toMatch(/not rendered/);
    expect(assetName({ id: "abc", kind: "video", metadata: { display_name: "Lake take" } } as unknown as Asset)).toBe("Lake take");
  });
});

describe("precision edits", () => {
  const tracks: TimelineTrack[] = [{ kind: "video", clips: [clip, { ...clip, id: "later", timeline_in: 7, timeline_out: 10 }] }, { kind: "audio", clips: [{ ...clip, id: "sound", timeline_in: 8, timeline_out: 11 }] }];
  it("splits a trimmed clip without moving other clips or losing metadata", () => {
    const result = splitClip(tracks, 0, "c", 2, "new");
    expect(result[0].clips).toMatchObject([
      { id: "c", source_in: 2, source_out: 3, timeline_in: 1, timeline_out: 2 },
      { id: "new", source_in: 3, source_out: 5, timeline_in: 2, timeline_out: 4 },
      { id: "later", timeline_in: 7 },
    ]);
    expect(result[1]).toBe(tracks[1]);
    expect(tracks[0].clips).toHaveLength(2);
    expect(splitClip(tracks, 0, "c", 1, "ignored")).toBe(tracks);
    expect(splitClip(tracks, 0, "c", 4, "ignored")).toBe(tracks);
    expect(splitClip(tracks, 0, "c", NaN, "ignored")).toBe(tracks);
  });
  it("ripple-delete closes only the removed interval on the selected track", () => {
    expect(removeClip(tracks, 0, "c", true)[0].clips[0]).toMatchObject({ timeline_in: 4, timeline_out: 7 });
    expect(removeClip(tracks, 0, "c", false)[0].clips[0]).toMatchObject({ timeline_in: 7, timeline_out: 10 });
    expect(removeClip(tracks, 0, "c", true)[1]).toBe(tracks[1]);
    expect(removeClip(tracks, 0, "absent", true)).toBe(tracks);
  });
  it("trims preserve leading/interior gaps, clamp source bounds and ripple only the duration delta", () => {
    const result = trimClip(tracks, 0, "c", { source_in: 3 }, 5);
    expect(result[0].clips).toMatchObject([{ source_in: 3, source_out: 5, timeline_in: 1, timeline_out: 3 }, { timeline_in: 6, timeline_out: 9 }]);
    expect(result[1]).toBe(tracks[1]);
    const bounded = trimClip(tracks, 0, "c", { source_out: 100 }, 5);
    expect(bounded[0].clips[0].source_out).toBe(5);
    expect(trimClip(tracks, 0, "c", { source_in: NaN }, 5)).toBe(tracks);
  });
});

"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { Group, Image as CanvasImage, Layer, Rect, Stage, Text, Transformer } from "react-konva";
import type Konva from "konva";
import { useCanvasMiddlePan } from "@/lib/use-canvas-middle-pan";
import { clampRect, normalizeDrag, parentRect, resolveRegions, type CanvasContent, type CanvasViewport, type Rect as Box, type ResolvedRegion } from "@/lib/canvas-document";

export type CanvasTool = "select" | "pan" | "draw";
type Props = {
  content: CanvasContent; selectedId: string | null; tool: CanvasTool; drawParent: string | null;
  viewport: CanvasViewport; onViewport: (viewport: CanvasViewport) => void; fitToken: number;
  onSelect: (id: string | null) => void; onRect: (id: string, rect: Box) => void;
  onDraw: (rect: Box, parentId: string | null) => void; onError: (message: string) => void;
  readOnly?: boolean; imageUrl?: string; showLayout: boolean; showResult: boolean; onSize: (size: { width: number; height: number }) => void;
};
const contains = (r: Box, p: { x: number; y: number }) => p.x >= r.x && p.y >= r.y && p.x <= r.x + r.width && p.y <= r.y + r.height;
const subscribePointer = (change: () => void) => { const media = window.matchMedia("(any-pointer: coarse)"); media.addEventListener("change", change); return () => media.removeEventListener("change", change); };

function RegionShape({ value, selected, scale, tool, onSelect, onRect, registerNode }: {
  value: ResolvedRegion; selected: boolean; scale: number; tool: CanvasTool;
  onSelect: () => void; onRect: (rect: Box) => void;
  registerNode: (id: string, node: Konva.Rect | null) => void;
}) {
  const shape = useRef<Konva.Rect>(null);
  const attach = useCallback((node: Konva.Rect | null) => { shape.current = node; registerNode(value.region.id, node); }, [registerNode, value.region.id]);
  const color = selected ? "#365c3d" : value.region.kind === "text" ? "#a37748" : value.region.kind === "character" ? "#6b6997" : "#688c73";
  const finish = () => {
    const node = shape.current;
    if (!node) return;
    const rect = { x: node.x(), y: node.y(), width: node.width() * node.scaleX(), height: node.height() * node.scaleY() };
    node.scale({ x: 1, y: 1 }); onRect(rect);
  };
  return <>
    <Rect ref={attach} {...value.rect} fill={selected ? "#365c3d0c" : "#688c7305"} stroke={color} strokeWidth={selected ? 2 : 1}
      strokeScaleEnabled={false} dash={value.region.kind === "group" ? [8 / scale, 5 / scale] : undefined}
      draggable={selected && !value.locked && tool === "select"} onDragEnd={finish} onTransformEnd={finish}
      onPointerDown={event => { if (tool === "select") { event.cancelBubble = true; onSelect(); } }} />
    <Group x={value.rect.x} y={Math.max(0, value.rect.y - 24 / scale)} listening={false}>
      <Rect width={Math.min(value.rect.width, 180 / scale)} height={22 / scale} fill={selected ? "#365c3d" : "#f7faf4e8"} cornerRadius={4 / scale} />
      <Text text={(value.locked ? "▣ " : "") + value.region.name} fill={selected ? "#f7faf4" : "#294332"} fontSize={11 / scale}
        padding={5 / scale} width={Math.min(value.rect.width, 180 / scale)} height={22 / scale} ellipsis wrap="none" />
    </Group>
  </>;
}

export default function CanvasStage(props: Props) {
  const { content, viewport, onViewport, tool } = props;
  const host = useRef<HTMLDivElement>(null), stage = useRef<Konva.Stage>(null);
  const { panning: middlePanning, attach: attachMiddlePan } = useCanvasMiddlePan(host, viewport, onViewport);
  const transformer = useRef<Konva.Transformer>(null), regionNodes = useRef(new Map<string, Konva.Rect>());
  const coarsePointer = useSyncExternalStore(subscribePointer, () => window.matchMedia("(any-pointer: coarse)").matches, () => false);
  const registerNode = useCallback((id: string, node: Konva.Rect | null) => { if (node) regionNodes.current.set(id, node); else regionNodes.current.delete(id); }, []);
  const styleAnchor = useCallback((anchor: Konva.Rect) => { anchor.hitStrokeWidth(coarsePointer ? 28 : 16); }, [coarsePointer]);
  const [size, setSize] = useState({ width: 0, height: 0 }), [loaded, setLoaded] = useState<{ url: string; image: HTMLImageElement } | null>(null);
  const image = loaded?.url === props.imageUrl ? loaded?.image : null;
  const [drawing, setDrawing] = useState<Box | null>(null);
  const gesture = useRef<{ type: "draw" | "pan"; start: { x: number; y: number }; viewport: CanvasViewport; parentId: string | null } | null>(null);
  const resolved = resolveRegions(content);
  const selection = resolved.find(value => value.region.id === props.selectedId);
  const canResize = Boolean(selection && !selection.hidden && !selection.locked && tool === "select" && props.showLayout);
  useLayoutEffect(() => {
    const node = props.selectedId ? regionNodes.current.get(props.selectedId) : null;
    transformer.current?.nodes(canResize && node ? [node] : []);
  }, [props.selectedId, canResize]);
  const latest = useRef(props);
  useLayoutEffect(() => { latest.current = props; }, [props]);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const resize = () => {
      const next = { width: Math.max(1, element.clientWidth), height: Math.max(1, element.clientHeight) };
      setSize(old => old.width === next.width && old.height === next.height ? old : next);
      latest.current.onSize(next);
    };
    const observer = new ResizeObserver(resize); observer.observe(element); resize();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!props.imageUrl) return;
    const url = props.imageUrl;
    let cancelled = false;
    const next = new window.Image();
    next.onload = () => { if (!cancelled) setLoaded({ url, image: next }); };
    next.onerror = () => { if (!cancelled) { setLoaded(null); latest.current.onError("The saved result could not load. Your regions are unchanged."); } };
    next.src = props.imageUrl;
    return () => { cancelled = true; };
  }, [props.imageUrl]);
  const fit = useRef(-1);
  useEffect(() => {
    if (viewport.scale !== 0 && fit.current === props.fitToken) return;
    if (viewport.scale !== 0 && fit.current === -1) { fit.current = props.fitToken; return; }
    if (size.width < 2 || size.height < 2) return;
    fit.current = props.fitToken;
    const scale = Math.max(.08, Math.min((size.width - 72) / content.artboard.width, (size.height - 64) / content.artboard.height, 1));
    onViewport({ scale, x: (size.width - content.artboard.width * scale) / 2, y: (size.height - content.artboard.height * scale) / 2 });
  }, [props.fitToken, size, content.artboard.width, content.artboard.height, viewport.scale, onViewport]);
  const point = () => {
    const p = stage.current?.getPointerPosition();
    return p ? { x: (p.x - viewport.x) / viewport.scale, y: (p.y - viewport.y) / viewport.scale } : null;
  };
  const hit = (p: { x: number; y: number }) => [...resolved].reverse().filter(value => !value.hidden && contains(value.rect, p)).sort((a, b) => b.depth - a.depth)[0];
  const down = (event: Konva.KonvaEventObject<PointerEvent>) => {
    // Handles extend outside the region. Never re-pick/deselect underneath them.
    if (event.target.findAncestor("Transformer", true)) return;
    const p = point(), pointer = stage.current?.getPointerPosition();
    if (!p || !pointer || !viewport.scale) return;
    if (tool === "pan") { gesture.current = { type: "pan", start: pointer, viewport, parentId: null }; return; }
    if (tool === "select") { props.onSelect(hit(p)?.region.id ?? null); return; }
    const parent = parentRect(content, props.drawParent);
    if (props.drawParent && resolved.find(v => v.region.id === props.drawParent)?.locked) { props.onError("Unlock the parent before drawing inside it"); return; }
    if (!contains(parent, p)) return;
    gesture.current = { type: "draw", start: p, viewport, parentId: props.drawParent };
    setDrawing({ ...p, width: 0, height: 0 });
  };
  const move = () => {
    const active = gesture.current, p = point(), pointer = stage.current?.getPointerPosition();
    if (!active || !p || !pointer) return;
    if (active.type === "pan") { onViewport({ ...active.viewport, x: active.viewport.x + pointer.x - active.start.x, y: active.viewport.y + pointer.y - active.start.y }); return; }
    const parent = parentRect(content, active.parentId);
    const end = { x: Math.max(parent.x, Math.min(parent.x + parent.width, p.x)), y: Math.max(parent.y, Math.min(parent.y + parent.height, p.y)) };
    setDrawing(normalizeDrag(active.start, end));
  };
  const up = () => {
    const active = gesture.current;
    if (active?.type === "draw" && drawing && drawing.width >= 3 && drawing.height >= 3) props.onDraw(clampRect(drawing, parentRect(content, active.parentId)), active.parentId);
    gesture.current = null; setDrawing(null);
  };
  const zoom = (factor: number, anchor: { x: number; y: number }) => {
    const old = viewport.scale || 1, scale = Math.max(.08, Math.min(4, old * factor));
    onViewport({ scale, x: anchor.x - (anchor.x - viewport.x) * scale / old, y: anchor.y - (anchor.y - viewport.y) * scale / old });
  };
  const s = viewport.scale || 1;
  const imageScale = image ? Math.min(content.artboard.width / image.width, content.artboard.height / image.height) : 1;
  return <div className={`canvas-surface tool-${tool} ${middlePanning ? "is-middle-panning" : ""}`} ref={attachMiddlePan} role="application" data-scale={viewport.scale} data-pan-x={viewport.x} data-pan-y={viewport.y} data-result-ready={Boolean(image)}
    aria-label={props.readOnly ? "Image preview. Wheel to zoom, drag or hold the middle button to pan." : "Canvas artboard. Draw with R, select with V, pan with H. Regions are also editable in Layers and the inspector."}>
    <Stage ref={stage} width={size.width} height={size.height} onPointerDown={down} onPointerMove={move} onPointerUp={up}
      onPointerCancel={() => { gesture.current = null; setDrawing(null); }}
      onWheel={event => { event.evt.preventDefault(); const p = stage.current?.getPointerPosition();
        if (event.evt.shiftKey) onViewport({ ...viewport, x: viewport.x - event.evt.deltaX, y: viewport.y - event.evt.deltaY });
        else if (p && event.evt.deltaY) zoom(event.evt.deltaY > 0 ? .92 : 1.08, p); }}>
      <Layer><Group x={viewport.x} y={viewport.y} scaleX={s} scaleY={s}>
        <Rect width={content.artboard.width} height={content.artboard.height} fill="#f8f4e9" stroke="#a3afa0" strokeWidth={1} strokeScaleEnabled={false}
          shadowColor="#24392b" shadowBlur={18} shadowOpacity={.12} />
        {image && props.showResult ? <CanvasImage image={image} width={image.width * imageScale} height={image.height * imageScale}
          x={(content.artboard.width - image.width * imageScale) / 2} y={(content.artboard.height - image.height * imageScale) / 2} listening={false} /> : null}
        {!content.regions.length && !image ? <Text text="A little space for an idea.\n\nDraw your first region, or describe the whole composition." x={content.artboard.width * .15} y={content.artboard.height * .4}
          width={content.artboard.width * .7} align="center" fontSize={18 / s} lineHeight={1.7} fill="#788576" listening={false} /> : null}
        {props.showLayout ? resolved.filter(value => !value.hidden).map(value => <RegionShape key={value.region.id} value={value} selected={props.selectedId === value.region.id}
          scale={s} tool={tool} registerNode={registerNode} onSelect={() => { const p = point(); props.onSelect(p ? hit(p)?.region.id ?? value.region.id : value.region.id); }} onRect={rect => props.onRect(value.region.id, rect)} />) : null}
        {drawing ? <Rect {...drawing} fill="#365c3d16" stroke="#365c3d" strokeWidth={1.5} strokeScaleEnabled={false} dash={[6 / s, 4 / s]} listening={false} /> : null}
      </Group></Layer>
      {/* Screen-space controls stay above every region, with a generous invisible hit area. */}
      <Layer>{canResize ? <Transformer ref={transformer} rotateEnabled={false} flipEnabled={false} ignoreStroke
        keepRatio={false} borderStroke="#365c3d" anchorStroke="#365c3d" anchorFill="#f7faf4" anchorStrokeWidth={1.5}
        anchorSize={coarsePointer ? 12 : 10} anchorCornerRadius={2} anchorStyleFunc={styleAnchor}
        onPointerDown={event => { event.cancelBubble = true; }}
        boundBoxFunc={(oldBox, next) => next.width < 4 || next.height < 4 ? oldBox : next} /> : null}</Layer>
    </Stage>
    <span className="canvas-dimensions">{content.artboard.width} × {content.artboard.height} · {Math.round(content.artboard.width * content.artboard.height / 1048576 * 10) / 10} MP</span>
  </div>;
}

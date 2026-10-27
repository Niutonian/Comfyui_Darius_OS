"use client";

import { useEffect, useRef } from "react";

export function AmbientBackground() {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let x = 0, y = 0, targetX = 0, targetY = 0;
    const paint = () => {
      element.current?.style.setProperty("--parallax-x", `${x.toFixed(2)}px`);
      element.current?.style.setProperty("--parallax-y", `${y.toFixed(2)}px`);
    };
    const animate = () => {
      x += (targetX - x) * .075;
      y += (targetY - y) * .075;
      paint();
      frame = Math.abs(targetX - x) + Math.abs(targetY - y) > .05 ? requestAnimationFrame(animate) : 0;
    };
    const move = (event: PointerEvent) => {
      if (motion.matches || event.pointerType === "touch") return;
      targetX = (event.clientX / innerWidth - .5) * 28;
      targetY = (event.clientY / innerHeight - .5) * 22;
      if (!frame) frame = requestAnimationFrame(animate);
    };
    const reset = () => {
      cancelAnimationFrame(frame); frame = 0;
      x = y = targetX = targetY = 0;
      paint();
    };
    const leave = () => { targetX = targetY = 0; if (!frame && !motion.matches) frame = requestAnimationFrame(animate); };
    window.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    motion.addEventListener("change", reset);
    document.addEventListener("visibilitychange", reset);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
      motion.removeEventListener("change", reset);
      document.removeEventListener("visibilitychange", reset);
    };
  }, []);
  return <div ref={element} aria-hidden="true" className="ambient-scene"><div className="ambient-orbit orbit-one" /><div className="ambient-orbit orbit-two" /><div className="ambient-orbit orbit-three" /></div>;
}

"use client";

import { useEffect, useId, useRef } from "react";
import type { DariusMood } from "@/lib/types";

type Drop = { x: number; y: number; r: number; thought?: boolean };

// The droplets share a thresholded mask, so touching surfaces merge into one volume.
const droplets: Drop[] = [
  { x: 0, y: 0, r: 61 },
  { x: -23, y: -14, r: 43 },
  { x: 25, y: -12, r: 38 },
  { x: -14, y: 24, r: 35 },
  { x: 23, y: 23, r: 30 },
  { x: 8, y: -78, r: 16, thought: true },
  { x: 62, y: -48, r: 11, thought: true },
  { x: -56, y: -52, r: 9, thought: true },
];

const energy: Record<DariusMood, number> = { idle: 1, listening: 1.28, speaking: 1.55, thinking: 2.45 };

export function LiquidOrb({ mood = "idle", size = "presence" }: { mood?: DariusMood; size?: "presence" | "thought" | "mark" }) {
  const id = useId().replaceAll(":", "");
  const svg = useRef<SVGSVGElement>(null);
  const shapes = useRef<Array<SVGCircleElement | null>>([]);
  const pointer = useRef({ x: 0, y: 0, active: false });
  const moodRef = useRef(mood);
  useEffect(() => { moodRef.current = mood; }, [mood]);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const particles = droplets.map((drop) => ({ x: 160 + drop.x, y: 153 + drop.y, vx: 0, vy: 0, r: drop.thought ? 0 : drop.r }));
    let frame = 0;
    let previous = 0;
    let elapsed = 0;
    function paint() {
      particles.forEach((particle, index) => {
        const circle = shapes.current[index];
        if (!circle) return;
        circle.setAttribute("cx", particle.x.toFixed(2));
        circle.setAttribute("cy", particle.y.toFixed(2));
        circle.setAttribute("r", Math.max(0, particle.r).toFixed(2));
      });
    }
    function animate(now: number) {
      const dt = previous ? Math.min((now - previous) / 16.667, 2) : 1;
      previous = now;
      elapsed += dt / 60;
      const current = moodRef.current;
      const force = energy[current];
      particles.forEach((particle, index) => {
        const drop = droplets[index];
        const thinking = current === "thinking";
        const speaking = current === "speaking";
        const listening = current === "listening";
        const phase = elapsed * (.65 + force * .22) + index * 1.7;
        const wander = drop.thought && thinking ? 18 : 5 * force;
        const homeX = 160 + (drop.thought && !thinking ? 0 : drop.x) + Math.sin(phase) * wander;
        const homeY = 153 + (drop.thought && !thinking ? 0 : drop.y) + Math.cos(phase * .8) * (drop.thought && thinking ? 22 : 7 * force);
        const pull = drop.thought && thinking ? .02 : .012;
        particle.vx += (homeX - particle.x) * pull * dt;
        particle.vy += (homeY - particle.y) * pull * dt;
        const targetR = drop.thought ? (thinking ? drop.r + Math.sin(phase * 1.4) * 3 : 0) : drop.r * (speaking ? 1 + Math.sin(elapsed * 3.2 + index) * .06 : 1);
        particle.r += (targetR - particle.r) * .08 * dt;
        if (pointer.current.active || listening) {
          const px = pointer.current.active ? pointer.current.x : 160 + Math.sin(elapsed * 1.4) * 40;
          const py = pointer.current.active ? pointer.current.y : 153 + Math.cos(elapsed * 1.1) * 28;
          let dx = particle.x - px;
          let dy = particle.y - py;
          const distance = Math.hypot(dx, dy);
          const reach = listening ? 128 : 102;
          if (distance < reach) {
            if (distance < 1) { dx = Math.cos(index * 2.4); dy = Math.sin(index * 2.4); }
            const length = Math.hypot(dx, dy);
            const push = (1 - distance / reach) * (listening ? 1.6 : 2.5) * (thinking ? 1.35 : 1);
            particle.vx += dx / length * push * dt;
            particle.vy += dy / length * push * dt;
          }
        }
        particle.vx *= Math.pow(thinking ? .92 : .89, dt);
        particle.vy *= Math.pow(thinking ? .92 : .89, dt);
        const bound = drop.thought && thinking ? 18 : 8;
        particle.x = Math.max(drop.r + bound, Math.min(312 - drop.r, particle.x + particle.vx * dt));
        particle.y = Math.max(drop.r + bound, Math.min(312 - drop.r, particle.y + particle.vy * dt));
      });
      paint();
      frame = requestAnimationFrame(animate);
    }
    function restart() {
      cancelAnimationFrame(frame);
      previous = 0;
      if (motion.matches) {
        particles.forEach((particle, index) => Object.assign(particle, { x: 160 + droplets[index].x, y: 153 + droplets[index].y, vx: 0, vy: 0, r: droplets[index].thought ? 0 : droplets[index].r }));
        paint();
      } else if (!document.hidden) frame = requestAnimationFrame(animate);
    }
    restart();
    motion.addEventListener("change", restart);
    document.addEventListener("visibilitychange", restart);
    return () => {
      cancelAnimationFrame(frame);
      motion.removeEventListener("change", restart);
      document.removeEventListener("visibilitychange", restart);
    };
  }, []);

  return <svg aria-hidden="true" className={`liquid-orb size-${size} mood-${mood}`} data-mood={mood} ref={svg} viewBox="0 0 320 320"
    onPointerMove={(event) => {
      const rect = svg.current!.getBoundingClientRect();
      pointer.current = { x: (event.clientX - rect.left) * 320 / rect.width, y: (event.clientY - rect.top) * 320 / rect.height, active: true };
    }}
    onPointerLeave={() => { pointer.current.active = false; }}
    onPointerUp={(event) => { if (event.pointerType !== "mouse") pointer.current.active = false; }}
    onPointerCancel={() => { pointer.current.active = false; }}>
    <defs>
      <filter id={`${id}-merge`} x="-30%" y="-30%" width="160%" height="160%" colorInterpolationFilters="sRGB">
        <feGaussianBlur stdDeviation="7" />
        <feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9" />
      </filter>
      <mask id={`${id}-shape`} maskUnits="userSpaceOnUse" x="0" y="0" width="320" height="320">
        <g filter={`url(#${id}-merge)`} fill="white">
          {droplets.map((drop, index) => <circle key={index} ref={(element) => { shapes.current[index] = element; }} cx={160 + drop.x} cy={153 + drop.y} r={drop.thought ? 0 : drop.r} />)}
        </g>
      </mask>
      <radialGradient id={`${id}-shade`} gradientUnits="userSpaceOnUse" cx="121" cy="104" r="162">
        <stop stopColor="#eff5c4" /><stop offset=".25" stopColor="#c7df91" /><stop offset=".55" stopColor="#91b078" /><stop offset=".83" stopColor="#527554" /><stop offset="1" stopColor="#395b48" />
      </radialGradient>
    </defs>
    <g mask={`url(#${id}-shape)`}><rect width="320" height="320" fill={`url(#${id}-shade)`} /></g>
  </svg>;
}

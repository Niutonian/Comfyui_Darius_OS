"use client";

import { useCallback, useLayoutEffect, useState, type RefObject, type SetStateAction } from "react";

// Document-local UI continuity. Never persisted: files, credentials and media do
// not enter browser storage. Callers are keyed by their owning project/record.
const values = new Map<string, unknown>();
const listeners = new Map<string, Set<(value: unknown) => void>>();
export function readWorkspaceValue<T>(key: string): T | undefined { return values.get(key) as T | undefined; }
export function rememberWorkspaceValue<T>(key: string, value: T) { values.set(key, value); listeners.get(key)?.forEach(update => update(value)); }
export function clearWorkspaceSession() { values.clear(); }

export function useWorkspaceState<T>(key: string, initial: T | (() => T)) {
  const [value, setValue] = useState<T>(() => {
    if (values.has(key)) return readWorkspaceValue<T>(key)!;
    const result = typeof initial === "function" ? (initial as () => T)() : initial;
    rememberWorkspaceValue(key, result);
    return result;
  });
  useLayoutEffect(() => {
    const update = (next: unknown) => setValue(next as T);
    const subscribers = listeners.get(key) ?? new Set();
    subscribers.add(update); listeners.set(key, subscribers);
    return () => { subscribers.delete(update); if (!subscribers.size) listeners.delete(key); };
  }, [key]);
  const update = useCallback((next: SetStateAction<T>) => {
    const result = typeof next === "function" ? (next as (previous: T) => T)(readWorkspaceValue<T>(key)!) : next;
    rememberWorkspaceValue(key, result);
    setValue(result);
  }, [key]);
  return [value, update] as const;
}

export function useWorkspaceScroll(key: string, ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const saved = readWorkspaceValue<{ top: number; left: number }>(key);
    if (saved) { element.scrollTop = saved.top; element.scrollLeft = saved.left; }
    const save = () => rememberWorkspaceValue(key, { top: element.scrollTop, left: element.scrollLeft });
    element.addEventListener("scroll", save, { passive: true });
    return () => { element.removeEventListener("scroll", save); };
  }, [key, ref]);
}

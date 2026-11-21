"use client";
import { useEffect, useRef } from "react";

/**
 * Shows a number that rolls from its previous value to the new one.
 *
 * The first time it renders it counts up from zero. After that it tweens from
 * whatever was last on screen, so switching ticker or range slides the digits
 * across instead of resetting to zero and counting up again.
 */
export function CountValue({ text }: { text: string }) {
  const node = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);

  useEffect(() => {
    const element = node.current;
    const parts = text.match(/^([^0-9-]*)(-?[0-9][0-9,]*(?:[.][0-9]+)?)(.*)$/);
    if (!element || !parts || matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const [, prefix, digits, suffix] = parts;
    const target = Number(digits.replaceAll(",", ""));
    const from = shown.current ?? 0;
    if (!Number.isFinite(target) || from === target) {
      shown.current = target;
      element.textContent = text;
      return;
    }

    const decimals = digits.split(".")[1]?.length ?? 0;
    const formatter = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: digits.includes(","),
    });
    // Short hops finish quickly; large jumps get a little more time.
    const duration = Math.min(620, 260 + Math.abs(target - from) / (Math.abs(target) + 1) * 360);
    const start = performance.now();
    let frame = 0;

    function tick(now: number) {
      // Clamp: a frame timestamp can predate `start`, which would overshoot.
      const progress = Math.min(1, Math.max(0, (now - start) / duration));
      const eased = 1 - (1 - progress) ** 3;
      const value = from + (target - from) * eased;
      shown.current = value;
      element!.textContent = progress === 1 ? text : prefix + formatter.format(value) + suffix;
      if (progress < 1) frame = requestAnimationFrame(tick);
      else shown.current = target;
    }

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text]);

  return <span style={{fontVariantNumeric:"tabular-nums"}}><span aria-hidden="true" ref={node}>{text}</span><span className="count-accessible">{text}</span></span>;
}

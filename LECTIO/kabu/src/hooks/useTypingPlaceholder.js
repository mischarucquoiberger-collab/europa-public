import { useEffect, useRef, useState } from "react";

/**
 * Cycles through `phrases` with a typewriter animation:
 *   type phrase → hold → erase → gap → next phrase → (loop)
 *
 * Returns the current partial string, which callers typically pass straight
 * to an <input>/<textarea> `placeholder` attribute.
 *
 * The animation freezes entirely while `active` is false (e.g. while the user
 * is typing or after they've sent their first message) so there's no wasted
 * CPU and no distracting movement behind real content.
 *
 * Note: `phrases` is captured via a ref so callers can pass a module-level
 * constant OR an inline literal without restarting the animation every render.
 */
export default function useTypingPlaceholder(
  phrases,
  {
    active = true,
    typeMs = 55,
    eraseMs = 22,
    holdMs = 1400,
    gapMs = 180,
    startDelayMs = 120,
  } = {}
) {
  // Seed the initial state with the first character of the first phrase so
  // the placeholder never renders as an empty string (which would let any
  // `||` fallback flash the old static hint for one frame).
  const firstChar = (phrases && phrases.length > 0 && phrases[0].length > 0) ? phrases[0][0] : "";
  const [text, setText] = useState(firstChar);
  const phrasesRef = useRef(phrases);
  phrasesRef.current = phrases;

  // Preserve position across active→inactive→active transitions so pausing
  // (e.g. user starts typing then clears) resumes on the next phrase rather
  // than restarting mid-word. Start at char=1 to match the seeded state.
  const cursor = useRef({ idx: 0, char: 1, phase: "typing" });

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timerId = null;

    const step = () => {
      if (cancelled) return;
      const list = phrasesRef.current;
      if (!list || list.length === 0) return;
      const state = cursor.current;
      const phrase = list[state.idx % list.length];

      if (state.phase === "typing") {
        state.char += 1;
        setText(phrase.slice(0, state.char));
        if (state.char >= phrase.length) {
          state.phase = "holding";
          timerId = setTimeout(step, holdMs);
        } else {
          // tiny jitter makes it feel hand-typed instead of metronomic
          timerId = setTimeout(step, typeMs + Math.random() * 35);
        }
      } else if (state.phase === "holding") {
        state.phase = "erasing";
        timerId = setTimeout(step, eraseMs);
      } else if (state.phase === "erasing") {
        state.char -= 1;
        setText(phrase.slice(0, Math.max(0, state.char)));
        if (state.char <= 0) {
          state.idx += 1;
          state.phase = "typing";
          timerId = setTimeout(step, gapMs);
        } else {
          timerId = setTimeout(step, eraseMs);
        }
      }
    };

    timerId = setTimeout(step, startDelayMs);
    return () => {
      cancelled = true;
      if (timerId) clearTimeout(timerId);
    };
  }, [active, typeMs, eraseMs, holdMs, gapMs, startDelayMs]);

  return text;
}

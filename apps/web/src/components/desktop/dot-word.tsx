/** 5×7 dot-matrix glyphs for the Darius wordmark. Rendered as SVG so it needs no web font. */
const glyphs: Record<string, string[]> = {
  A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
  C: ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
  D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
  E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
  I: ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
  O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
  R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
  S: ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
  T: ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
  U: ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
  " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
};

export function DotWord({ text, height = 28, className }: { text: string; height?: number; className?: string }) {
  const letters = [...text.toUpperCase()].map(letter => glyphs[letter] ?? glyphs[" "]);
  const pitch = 10, gap = 1, width = letters.length * (5 + gap) - gap;
  return <svg className={`dot-word ${className ?? ""}`} role="img" aria-label={text} height={height} viewBox={`0 0 ${width * pitch} ${7 * pitch}`}>
    {letters.flatMap((rows, index) => rows.flatMap((row, y) => [...row].map((bit, x) => bit === "1"
      ? <rect key={`${index}-${x}-${y}`} x={(index * (5 + gap) + x) * pitch + 1.5} y={y * pitch + 1.5} width={pitch - 3} height={pitch - 3} rx={1.2} fill="currentColor" />
      : null)))}
  </svg>;
}

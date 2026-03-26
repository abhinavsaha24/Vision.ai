"use client";

import { useMemo, useState } from "react";

interface LadderRow {
  price: number;
  size: number;
}

interface VirtualizedLadderProps {
  rows: LadderRow[];
  side: "bids" | "asks";
  maxHeight?: number;
  rowHeight?: number;
}

export function VirtualizedLadder({
  rows,
  side,
  maxHeight = 420,
  rowHeight = 26,
}: VirtualizedLadderProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const visibleCount = Math.ceil(maxHeight / rowHeight) + 8;

  const { slicedRows, spacerTop, spacerBottom, maxSize } = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 3);
    const end = Math.min(rows.length, start + visibleCount);
    const max = rows.reduce((acc, row) => Math.max(acc, row.size), 0);

    return {
      slicedRows: rows.slice(start, end),
      spacerTop: start * rowHeight,
      spacerBottom: Math.max(0, (rows.length - end) * rowHeight),
      maxSize: max || 1,
    };
  }, [rowHeight, rows, scrollTop, visibleCount]);

  return (
    <div
      className="overflow-y-auto rounded-xl border border-white/10 bg-slate-950/50"
      style={{ maxHeight }}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <div style={{ paddingTop: spacerTop, paddingBottom: spacerBottom }}>
        {slicedRows.map((row) => {
          const depth = Math.max(0.08, row.size / maxSize);
          const tint =
            side === "bids"
              ? `rgba(16,185,129,${Math.min(0.65, depth)})`
              : `rgba(244,63,94,${Math.min(0.65, depth)})`;

          return (
            <div
              key={`${side}-${row.price}`}
              className="grid grid-cols-2 items-center px-3 text-xs"
              style={{
                height: rowHeight,
                background: `linear-gradient(90deg, ${tint}, transparent)`,
              }}
            >
              <span
                className={
                  side === "bids" ? "text-emerald-200" : "text-rose-200"
                }
              >
                {row.price.toFixed(2)}
              </span>
              <span className="text-right font-mono text-slate-300">
                {row.size.toFixed(4)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

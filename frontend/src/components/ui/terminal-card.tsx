import { clsx } from "clsx";
import { ReactNode } from "react";

interface TerminalCardProps {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function TerminalCard({
  title,
  right,
  children,
  className,
}: TerminalCardProps) {
  return (
    <section
      className={clsx(
        "rounded-2xl border border-white/10 bg-slate-950/60 shadow-[0_20px_50px_-30px_rgba(0,0,0,0.8)] backdrop-blur-lg",
        className,
      )}
    >
      <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
          {title}
        </h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

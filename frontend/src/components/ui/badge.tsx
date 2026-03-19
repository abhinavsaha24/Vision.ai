import * as React from "react"
import { cn } from "@/utils/cn"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "success" | "danger" | "warning" | "outline";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants = {
    default: "border-transparent bg-slate-800 text-slate-100",
    success: "border-transparent bg-emerald-500/20 text-emerald-400",
    danger: "border-transparent bg-rose-500/20 text-rose-400",
    warning: "border-transparent bg-amber-500/20 text-amber-400",
    outline: "text-slate-100",
  }

  return (
    <div className={cn("inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2", variants[variant], className)} {...props} />
  )
}

export { Badge }

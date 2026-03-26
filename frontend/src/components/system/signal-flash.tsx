"use client";

import { motion } from "framer-motion";

interface SignalFlashProps {
  active: boolean;
  color: "buy" | "sell" | "neutral";
}

function flashColor(color: SignalFlashProps["color"]) {
  if (color === "buy") return "rgba(16,185,129,0.65)";
  if (color === "sell") return "rgba(244,63,94,0.65)";
  return "rgba(59,130,246,0.45)";
}

export function SignalFlash({ active, color }: SignalFlashProps) {
  return (
    <motion.div
      className="h-2 w-2 rounded-full"
      animate={
        active
          ? {
              opacity: [0.2, 1, 0.2],
              scale: [1, 1.35, 1],
              boxShadow: [
                `0 0 0px ${flashColor(color)}`,
                `0 0 12px ${flashColor(color)}`,
                `0 0 0px ${flashColor(color)}`,
              ],
            }
          : { opacity: 0.25, scale: 1 }
      }
      transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
      style={{ backgroundColor: flashColor(color) }}
    />
  );
}

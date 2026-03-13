import React from "react";

/**
 * RSI.js — RSI indicator display with visual zones
 */

function RSI({ value }) {
  const rsi = value || 50;

  const getColor = (v) => {
    if (v >= 70) return "var(--accent-red)";
    if (v <= 30) return "var(--accent-green)";
    return "var(--accent-blue)";
  };

  const getLabel = (v) => {
    if (v >= 70) return "Overbought";
    if (v <= 30) return "Oversold";
    return "Neutral";
  };

  return (
    <div>
      <div className="card-title">RSI Indicator</div>

      {/* RSI Bar */}
      <div style={{
        position: "relative",
        height: 8,
        background: "var(--bg-secondary)",
        borderRadius: 4,
        margin: "12px 0",
        overflow: "hidden",
      }}>
        {/* Zones */}
        <div style={{ position: "absolute", left: 0, width: "30%", height: "100%", background: "rgba(0,230,118,0.15)" }} />
        <div style={{ position: "absolute", right: 0, width: "30%", height: "100%", background: "rgba(255,71,87,0.15)" }} />

        {/* Pointer */}
        <div style={{
          position: "absolute",
          left: `${rsi}%`,
          top: -3,
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: getColor(rsi),
          transform: "translateX(-50%)",
          boxShadow: `0 0 8px ${getColor(rsi)}`,
          transition: "left 0.5s ease",
        }} />
      </div>

      <div className="row-between" style={{ fontSize: "0.7rem" }}>
        <span className="text-green">30 — Oversold</span>
        <span style={{ color: getColor(rsi), fontWeight: 700, fontFamily: "'JetBrains Mono'" }}>
          {rsi.toFixed(0)} — {getLabel(rsi)}
        </span>
        <span className="text-red">70 — Overbought</span>
      </div>
    </div>
  );
}

export default RSI;
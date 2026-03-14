import React from 'react';
import { ShieldAlert, Zap, AlertTriangle } from 'lucide-react';

export default function RiskDashboard({ riskData, loading }) {
  if (loading || !riskData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted min-h-32">
        <ShieldAlert className="w-6 h-6 mb-2 opacity-50" />
        <span className="text-xs font-mono">RISK ENVELOPE</span>
      </div>
    );
  }

  const { risk_level, risk_score, kill_switch, events = [] } = riskData;

  const getRiskColor = (level) => {
    switch(level?.toLowerCase()) {
      case 'low': return 'text-trade-green';
      case 'medium': return 'text-trade-yellow';
      case 'high': return 'text-trade-red';
      default: return 'text-dark-muted';
    }
  };

  const rColor = getRiskColor(risk_level);

  return (
    <div className="panel h-full flex flex-col justify-between relative overflow-hidden">
      {/* Background Warning Glow if Kill Switch Active */}
      {kill_switch && (
        <div className="absolute inset-0 bg-trade-red/10 animate-pulse pointer-events-none" />
      )}

      <div className="flex items-center justify-between mb-4 z-10">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <ShieldAlert className="w-4 h-4" />
          <span>Risk Command</span>
        </h2>
        {kill_switch ? (
          <span className="text-xs bg-trade-red px-2 py-1 rounded text-white font-bold animate-pulse">KILL SWITCH ACTIVE</span>
        ) : (
          <span className="text-xs bg-trade-green/20 text-trade-green border border-trade-green/30 px-2 py-1 rounded font-mono">SYSTEM SAFE</span>
        )}
      </div>

      <div className="flex items-center space-x-6 z-10 mb-4">
        <div className="flex-1 bg-dark-bg border border-dark-border rounded-lg p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-dark-muted uppercase font-mono mb-1">Risk Level</div>
            <div className={`text-2xl font-black uppercase tracking-wider ${rColor}`}>{risk_level || 'UNKNOWN'}</div>
          </div>
          <AlertTriangle className={`w-8 h-8 opacity-50 ${rColor}`} />
        </div>

        <div className="flex-1 bg-dark-bg border border-dark-border rounded-lg p-4 flex flex-col justify-between">
           <div className="flex items-center justify-between mb-2">
             <div className="text-xs text-dark-muted uppercase font-mono">Risk Score</div>
             <div className="font-mono font-bold">{(risk_score * 100).toFixed(0)}/100</div>
           </div>
           <div className="w-full bg-dark-panel h-2 mt-1 rounded-full overflow-hidden">
             <div 
               className={`h-full ${rColor.replace('text-', 'bg-')}`} 
               style={{ width: `${Math.min(risk_score * 100, 100)}%` }} 
             />
           </div>
        </div>
      </div>

      <div className="z-10 bg-dark-bg border border-dark-border rounded-lg p-3">
        <div className="text-xs text-dark-muted uppercase font-mono mb-2 flex items-center"><Zap className="w-3 h-3 mr-1"/> Recent Events</div>
        <div className="space-y-2 h-16 overflow-y-auto custom-scrollbar">
          {events.length === 0 ? (
             <div className="text-xs font-mono text-dark-muted italic">No recent risk events</div>
          ) : (
            events.map((ev, i) => (
              <div key={i} className="flex justify-between items-center text-xs font-mono">
                <span className="text-dark-text truncate pr-2">{ev.message || ev.type}</span>
                <span className="text-dark-muted whitespace-nowrap opacity-50">{new Date(ev.timestamp).toLocaleTimeString()}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

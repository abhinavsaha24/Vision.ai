import React from 'react';
import { TrendingUp, TrendingDown, Minus, Cpu, Server } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function AiSignalPanel({ signalData, loading }) {
  if (loading) {
    return (
      <div className="panel h-full flex items-center justify-center">
        <div className="animate-spin text-dark-muted"><Cpu className="w-8 h-8" /></div>
      </div>
    );
  }

  if (!signalData) {
    return (
      <div className="panel h-full flex flex-col items-center justify-center text-dark-muted">
        <Server className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm font-mono">SIGNAL UNAVAILABLE</p>
      </div>
    );
  }

  const { signal, confidence, position_size } = signalData;

  const getSignalConfig = () => {
    switch (signal) {
      case 'BUY': return { color: 'text-trade-green', bg: 'bg-trade-green/10', border: 'border-trade-green/30', Icon: TrendingUp };
      case 'SELL': return { color: 'text-trade-red', bg: 'bg-trade-red/10', border: 'border-trade-red/30', Icon: TrendingDown };
      default: return { color: 'text-trade-yellow', bg: 'bg-trade-yellow/10', border: 'border-trade-yellow/30', Icon: Minus };
    }
  };

  const { color, bg, border, Icon } = getSignalConfig();

  return (
    <div className={`panel h-full border-t-4 ${color.replace('text', 'border')} flex flex-col justify-between`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <Cpu className="w-4 h-4" />
          <span>VISION-AI SIGNAL</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted">ENSEMBLE</span>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={signal}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="flex-1 flex flex-col justify-center"
        >
          <div className="flex items-center space-x-4 mb-6">
            <div className={`p-4 rounded-xl ${bg} ${border} border`}>
              <Icon className={`w-10 h-10 ${color}`} />
            </div>
            <div>
              <div className={`text-4xl font-black tracking-widest ${color}`}>{signal}</div>
              <div className="text-sm text-dark-muted mt-1 uppercase tracking-widest">Master Signal</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-dark-bg border border-dark-border rounded-lg p-3">
              <div className="text-xs text-dark-muted mb-1 font-mono">CONFIDENCE</div>
              <div className="text-xl font-bold font-mono">{(confidence * 100).toFixed(1)}%</div>
              <div className="w-full bg-dark-panel h-1 mt-2 rounded-full overflow-hidden">
                <div 
                  className={`h-full ${color.replace('text-', 'bg-')}`} 
                  style={{ width: `${confidence * 100}%` }} 
                />
              </div>
            </div>

            <div className="bg-dark-bg border border-dark-border rounded-lg p-3">
              <div className="text-xs text-dark-muted mb-1 font-mono">POSITION SIZE</div>
              <div className="text-xl font-bold font-mono text-white">{(position_size * 100).toFixed(1)}%</div>
              <div className="text-xs text-dark-muted mt-1 font-mono">CAPITAL ALLOC</div>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

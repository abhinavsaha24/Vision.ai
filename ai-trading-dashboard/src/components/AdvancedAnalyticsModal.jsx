import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Activity, BarChart2, Globe, Server, AlertTriangle } from 'lucide-react';
import { useApi } from '../hooks/useApi';

export default function AdvancedAnalyticsModal({ isOpen, onClose }) {
  const { get, loading } = useApi();
  const [activeTab, setActiveTab] = useState('insights');
  
  // Data State
  const [featureImportance, setFeatureImportance] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [marketIntel, setMarketIntel] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    
    let mounted = true;
    const fetchTabData = async () => {
      try {
        if (activeTab === 'insights' && !featureImportance) {
          const res = await get('/research/feature-importance');
          if (mounted) setFeatureImportance(res?.importance || {});
        } else if (activeTab === 'health' && !metrics) {
          const res = await get('/monitoring/metrics');
          if (mounted) setMetrics(res);
        } else if (activeTab === 'market' && !marketIntel) {
          const res = await get('/market-intelligence');
          if (mounted) setMarketIntel(res);
        }
      } catch (err) {
        console.warn(`[VISION API] failed to load ${activeTab} data`);
      }
    };
    
    fetchTabData();
    return () => { mounted = false; };
  }, [isOpen, activeTab, get]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  const tabs = [
    { id: 'insights', label: 'ML Model Insights', icon: BarChart2 },
    { id: 'health', label: 'System Metrics', icon: Activity },
    { id: 'market', label: 'Global Context', icon: Globe },
  ];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 backdrop-blur-sm bg-[#0b1220]/80">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ duration: 0.2 }}
          className="w-full max-w-5xl bg-[#0b1220] border border-slate-800 rounded-xl shadow-2xl flex flex-col h-[85vh] max-h-[800px] overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-slate-800 bg-[#0f172a]/50">
            <div className="flex items-center space-x-3">
              <div className="p-2 bg-trade-green/10 rounded-lg">
                <Activity className="w-6 h-6 text-trade-green" />
              </div>
              <div>
                <h2 className="text-xl font-bold font-mono tracking-wider text-slate-100 uppercase">Advanced Diagnostics</h2>
                <p className="text-xs text-slate-400 font-mono">Deep-dive backend cluster metrics</p>
              </div>
            </div>
            <button 
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          <div className="flex flex-1 overflow-hidden">
            {/* Sidebar Tabs */}
            <div className="w-64 border-r border-slate-800 bg-[#0b1220] p-4 flex flex-col gap-2">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center space-x-3 w-full px-4 py-3 rounded-lg font-mono text-sm transition-all ${
                    activeTab === tab.id 
                      ? 'bg-slate-800 text-white border border-slate-700 shadow-md' 
                      : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200 border border-transparent'
                  }`}
                >
                  <tab.icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-6 bg-[#020617]">
              {/* ML Insights Tab */}
              {activeTab === 'insights' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-bold font-mono text-slate-200 border-b border-slate-800 pb-2 flex items-center shadow-none gap-2">
                    <BarChart2 className="w-4 h-4 text-trade-green" />
                    XGBoost Feature Importances
                  </h3>
                  
                  {loading['get-/research/feature-importance'] && !featureImportance ? (
                    <div className="text-slate-400 font-mono text-sm animate-pulse">Computing ML Matrices...</div>
                  ) : Object.keys(featureImportance || {}).length === 0 ? (
                    <div className="text-slate-500 font-mono text-sm flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4" />
                      Model not fully trained yet or feature data unreachable.
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {Object.entries(featureImportance).map(([feature, value]) => (
                        <div key={feature}>
                          <div className="flex justify-between text-xs font-mono text-slate-400 mb-1">
                            <span>{feature.replace(/_/g, ' ').toUpperCase()}</span>
                            <span>{(value * 100).toFixed(2)}%</span>
                          </div>
                          <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                            <motion.div 
                              initial={{ width: 0 }}
                              animate={{ width: `${value * 100}%` }}
                              transition={{ duration: 1, ease: 'easeOut' }}
                              className="h-full bg-trade-green"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* System Metrics Tab */}
              {activeTab === 'health' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-bold font-mono text-slate-200 border-b border-slate-800 pb-2 flex items-center gap-2">
                    <Server className="w-4 h-4 text-trade-green" />
                    Process Telemetry
                  </h3>
                  
                  {loading['get-/monitoring/metrics'] && !metrics ? (
                    <div className="text-slate-400 font-mono text-sm animate-pulse">Pulling Server Memory...</div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4">
                      {/* Latency card */}
                      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                        <div className="text-xs text-slate-400 font-mono mb-2">AVG LATENCY (MS)</div>
                        <div className="text-2xl font-black font-mono text-white">
                          {(metrics?.latency?.average || 0).toFixed(1)}
                        </div>
                        <div className="text-xs text-trade-green font-mono mt-2 flex justify-between">
                          <span>p95: {metrics?.latency?.p95?.toFixed(1) || 0}ms</span>
                          <span>max: {metrics?.latency?.max?.toFixed(1) || 0}ms</span>
                        </div>
                      </div>

                      {/* Request counts */}
                      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                        <div className="text-xs text-slate-400 font-mono mb-2">TOTAL REQUESTS</div>
                        <div className="text-2xl font-black font-mono text-white">
                          {metrics?.requests?.total || 0}
                        </div>
                        <div className="text-xs text-trade-red font-mono mt-2 flex justify-between">
                          <span>Errors: {metrics?.requests?.errors || 0}</span>
                        </div>
                      </div>
                      
                      {/* Raw Dump */}
                      <div className="col-span-2 bg-slate-900 border border-slate-800 rounded-lg p-4">
                        <div className="text-xs text-slate-400 font-mono mb-2">RAW JSON</div>
                        <pre className="text-xs font-mono text-slate-500 overflow-x-auto p-2 bg-black rounded border border-slate-800">
                          {JSON.stringify(metrics, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Market Context Tab */}
              {activeTab === 'market' && (
                <div className="space-y-6">
                  <h3 className="text-lg font-bold font-mono text-slate-200 border-b border-slate-800 pb-2 flex items-center gap-2">
                    <Globe className="w-4 h-4 text-trade-green" />
                    Global Crypto Intelligence
                  </h3>
                  
                  {loading['get-/market-intelligence'] && !marketIntel ? (
                    <div className="text-slate-400 font-mono text-sm animate-pulse">Fetching CoinGecko Aggregates...</div>
                  ) : !marketIntel ? (
                     <div className="text-slate-500 font-mono text-sm">Waiting for telemetry...</div>
                  ) : (
                    <div className="space-y-6">
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                        <div className="bg-slate-900 border border-slate-800 p-3 rounded-lg text-center">
                          <div className="text-xs font-mono text-slate-400">BTC DOMINANCE</div>
                          <div className="text-lg font-bold font-mono mt-1 text-trade-green">{marketIntel.btc_dominance?.toFixed(2)}%</div>
                        </div>
                        <div className="bg-slate-900 border border-slate-800 p-3 rounded-lg text-center">
                          <div className="text-xs font-mono text-slate-400">ACTIVE COINS</div>
                          <div className="text-lg font-bold font-mono mt-1 text-white">{marketIntel.active_cryptocurrencies?.toLocaleString()}</div>
                        </div>
                        <div className="col-span-2 bg-slate-900 border border-slate-800 p-3 rounded-lg text-center">
                          <div className="text-xs font-mono text-slate-400">TOTAL GLOBAL MARKET CAP</div>
                          <div className="text-lg font-bold font-mono mt-1 text-white">${marketIntel.total_market_cap_usd?.toLocaleString()}</div>
                        </div>
                      </div>
                      
                      <div>
                        <h4 className="text-sm font-bold font-mono text-slate-400 mb-3 uppercase">Trending Altcoins (24H)</h4>
                        <div className="grid grid-cols-2 gap-3">
                          {marketIntel.trending_coins?.map((coin, idx) => (
                            <div key={idx} className="bg-slate-900 border border-slate-800 p-3 rounded-lg flex items-center space-x-3">
                              <img src={coin.thumb} alt={coin.symbol} className="w-6 h-6 rounded-full" />
                              <div className="flex-1">
                                <div className="text-sm font-bold text-white">{coin.name}</div>
                                <div className="text-xs text-slate-400 font-mono">{coin.symbol} • Rank #{coin.rank}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

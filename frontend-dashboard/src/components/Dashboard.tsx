"use client";
import React, { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { Activity, ShieldAlert, Cpu, CheckCircle2, XCircle, TrendingUp } from "lucide-react";
import { format } from "date-fns";

export default function Dashboard() {
  const [activeTrades, setActiveTrades] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [botSettings, setBotSettings] = useState<any>(null);

  useEffect(() => {
    // initial fetch
    const fetchInitialData = async () => {
      const { data: trades } = await supabase.from("active_trades").select("*").eq("current_status", "OPEN").order("created_at", { ascending: false });
      if (trades) setActiveTrades(trades);

      const { data: s } = await supabase.from("market_signals").select("*").order("created_at", { ascending: false }).limit(10);
      if (s) setSignals(s);

      const { data: b } = await supabase.from("account_settings").select("*").limit(1).single();
      if (b) setBotSettings(b);
    };

    fetchInitialData();

    // realtime
    const tradesSub = supabase.channel("active_trades")
      .on("postgres_changes", { event: "*", schema: "public", table: "active_trades" }, fetchInitialData)
      .subscribe();
    const signalsSub = supabase.channel("market_signals")
      .on("postgres_changes", { event: "*", schema: "public", table: "market_signals" }, fetchInitialData)
      .subscribe();
    
    return () => {
      supabase.removeChannel(tradesSub);
      supabase.removeChannel(signalsSub);
    };
  }, []);

  const handleForceClose = async (id: number) => {
    await supabase.from("active_trades").update({ closing_requested: true }).eq("id", id);
  };

  return (
    <div className="container mx-auto p-4 md:p-8 space-y-8">
      <header className="flex flex-col md:flex-row items-center justify-between mb-12">
        <div>
          <h1 className="text-4xl md:text-5xl font-black tracking-tighter text-gradient mb-2">STEALTH TERMINAL</h1>
          <p className="text-slate-400 font-jetbrains">Investment-AI_T V4 Core Engine</p>
        </div>
        <div className="mt-4 md:mt-0 glass-panel px-6 py-3 flex items-center gap-3">
          <Activity className={botSettings?.enabled ? "text-primary animate-pulse" : "text-red-500"} />
          <span className="font-bold text-lg">{botSettings?.enabled ? "SYSTEM ONLINE" : "SYSTEM OFFLINE"}</span>
        </div>
      </header>

      {/* Grid Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass-panel p-6 flex flex-col justify-between">
          <div className="flex items-center gap-3 text-secondary mb-4">
            <Cpu size={24} />
            <h3 className="font-bold">Active Trades</h3>
          </div>
          <div className="text-5xl font-black">{activeTrades.length}</div>
        </div>
        <div className="glass-panel p-6 flex flex-col justify-between">
          <div className="flex items-center gap-3 text-accent mb-4">
            <ShieldAlert size={24} />
            <h3 className="font-bold">Risk Guard</h3>
          </div>
          <div className="text-2xl font-bold flex items-center gap-2">
            <CheckCircle2 className="text-green-400" /> Active & Scanning
          </div>
        </div>
        <div className="glass-panel p-6 flex flex-col justify-between">
          <div className="flex items-center gap-3 text-primary mb-4">
            <TrendingUp size={24} />
            <h3 className="font-bold">Daily Drawdown</h3>
          </div>
          <div className="text-3xl font-black text-green-400">0.00%</div>
        </div>
      </div>

      {/* Main Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-12">
        <div className="lg:col-span-2 space-y-6">
          <h2 className="text-2xl font-bold border-b border-borderDark pb-2 flex items-center gap-2">
            <Activity className="text-primary" /> Live Positions
          </h2>
          <div className="glass-panel overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-[rgba(255,255,255,0.02)] border-b border-borderDark font-jetbrains text-sm">
                  <tr>
                    <th className="p-4">Ticket</th>
                    <th className="p-4">Symbol</th>
                    <th className="p-4">Action</th>
                    <th className="p-4">Lot</th>
                    <th className="p-4">Style</th>
                    <th className="p-4">V-SL/TP</th>
                    <th className="p-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-borderDark">
                  {activeTrades.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="p-8 text-center text-slate-500">No active positions.</td>
                    </tr>
                  ) : activeTrades.map(t => (
                    <tr key={t.id} className="hover:bg-[rgba(255,255,255,0.02)] transition-colors">
                      <td className="p-4 font-jetbrains">{t.ticket}</td>
                      <td className="p-4 font-bold">{t.symbol}</td>
                      <td className={`p-4 font-black ${t.direction === 'BUY' ? 'text-primary' : 'text-accent'}`}>{t.direction}</td>
                      <td className="p-4">{t.lot}</td>
                      <td className="p-4 text-sm">{t.trade_style}</td>
                      <td className="p-4 font-jetbrains text-sm">
                        <span className="text-accent">{t.virtual_sl?.toFixed(5) || '0.00'}</span> / <span className="text-green-400">{t.virtual_tp?.toFixed(5) || '0.00'}</span>
                      </td>
                      <td className="p-4 text-right">
                        <button 
                          onClick={() => handleForceClose(t.id)}
                          disabled={t.closing_requested}
                          className="px-4 py-1.5 rounded-full text-xs font-bold bg-[rgba(255,8,68,0.1)] text-accent border border-accent hover:bg-accent hover:text-white transition-all disabled:opacity-50"
                        >
                          {t.closing_requested ? "CLOSING..." : "FORCE CLOSE"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <h2 className="text-2xl font-bold border-b border-borderDark pb-2 flex items-center gap-2">
            <Cpu className="text-secondary" /> AI Signal Log
          </h2>
          <div className="glass-panel p-4 space-y-4 max-h-[600px] overflow-y-auto">
            {signals.map(s => (
              <div key={s.id} className="border border-borderDark rounded-lg p-3 bg-[rgba(0,0,0,0.2)]">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold text-sm">{s.symbol}</span>
                  <span className="text-xs text-slate-400 font-jetbrains">{format(new Date(s.created_at), 'HH:mm:ss')}</span>
                </div>
                <div className="flex justify-between items-end">
                  <div>
                    <div className={`text-xl font-black ${s.action === 'BUY' ? 'text-primary' : s.action === 'SELL' ? 'text-accent' : 'text-slate-300'}`}>{s.action}</div>
                    <div className="text-xs text-slate-400">{s.trade_style} • Conf: {(s.confidence * 100).toFixed(0)}%</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

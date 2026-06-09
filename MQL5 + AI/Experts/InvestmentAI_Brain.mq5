//+------------------------------------------------------------------+
//|                                          InvestmentAI_Brain.mq5 |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|  All-in-one EA: AI analysis + execution + virtual SL/TP + sync  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Investment-AI_T"
#property link      "https://github.com/hdanial211/Investment-AI_T"
#property version   "5.00"
#property description "Standalone AI Trading EA — calls Groq directly, no Python needed."

#include "..\Include\AIBrain\JsonParser.mqh"
#include "..\Include\AIBrain\HttpClient.mqh"
#include "..\Include\AIBrain\SupabaseClient.mqh"
#include "..\Include\AIBrain\MarketData.mqh"
#include "..\Include\AIBrain\AIProvider.mqh"
#include "..\Include\AIBrain\RiskGuard.mqh"
#include "..\Include\AIBrain\TradeExecutor.mqh"
#include "..\Include\AIBrain\VirtualManager.mqh"

//============================================================
// INPUT PARAMETERS
//============================================================

// ── Identity ─────────────────────────────────────────────
input string   Inp_AccountID       = "";             // Account ID (matches Supabase)

// ── Supabase ──────────────────────────────────────────────
input string   Inp_SupabaseURL     = "https://kusyjtpcjyflxgfcqenb.supabase.co"; // Supabase URL
input string   Inp_SupabaseAnon    = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt1c3lqdHBjanlmbHhnZmNxZW5iIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk4MDE0NzIsImV4cCI6MjA5NTM3NzQ3Mn0.D8qN-s92JUloY7jb_jwiUnqikRKxHb9Qap9HQod-78g"; // Supabase Anon Key

// ── Groq API Keys (3 keys — rotate on quota/failure) ─────
input string   Inp_GroqKey1        = "";             // Groq API Key #1 (Primary)
input string   Inp_GroqKey2        = "";             // Groq API Key #2 (Backup 1)
input string   Inp_GroqKey3        = "";             // Groq API Key #3 (Backup 2)
input string   Inp_GroqModel       = "llama-3.3-70b-versatile"; // Groq Model

// ── Symbol ────────────────────────────────────────────────
input string   Inp_Symbol          = "XAUUSDc";     // Gold symbol (XAUUSDc or XAUUSD)

// ── Trading Styles Enable/Disable ────────────────────────
input bool     Inp_EnableScalping  = true;           // Enable SCALPING (every 5min)
input bool     Inp_EnableIntraday  = true;           // Enable INTRADAY (every 1hr)
input bool     Inp_EnableSwing     = true;           // Enable SWING (every 2hr)

// ── Risk (overridden by Supabase if settings exist) ──────
input int      Inp_MinConfidence   = 70;             // Min AI confidence to trade (%)
input int      Inp_MaxSpread       = 50;             // Max spread in points
input int      Inp_MaxTrades       = 5;              // Max concurrent trades
input double   Inp_MaxDrawdown     = 5.0;            // Max daily drawdown (%)

// ── Magic Numbers ─────────────────────────────────────────
input ulong    Inp_MagicBase       = 999000;         // Base magic (+1=Scalp,+2=Intra,+3=Swing)

//============================================================
// GLOBAL OBJECTS
//============================================================

CSupabaseClient g_supa;
CAIProvider     g_ai;
CRiskGuard      g_risk;
CTradeExecutor  g_exec;
CVirtualManager g_virt;

// Analysis timestamps per style (Unix seconds of last run)
datetime g_last_scalping  = 0;
datetime g_last_intraday  = 0;
datetime g_last_swing     = 0;

// Settings sync
datetime g_last_settings  = 0;
datetime g_last_heartbeat = 0;

// Intervals (seconds)
#define INTERVAL_SCALPING   300     // 5 minit
#define INTERVAL_INTRADAY   1800    // 30 minit
#define INTERVAL_SWING      3600    // 1 jam
#define INTERVAL_SETTINGS   60      // 1 minute
#define INTERVAL_HEARTBEAT  60      // 1 minute

//============================================================
// HELPER: Check if analysis should run based on interval
//         aligned to midnight (time % interval == 0)
//============================================================
bool ShouldRun(datetime &last_run, int interval_sec)
{
   datetime now  = TimeCurrent();
   long     sod  = (long)now % 86400;  // seconds since midnight (server time)
   long     slot = (sod / interval_sec) * interval_sec;
   // Run if we're in a new slot since last run
   datetime slot_start = now - (now % interval_sec);
   if(last_run < slot_start)
   {
      last_run = now;
      return true;
   }
   return false;
}

//============================================================
// HELPER: Run full AI analysis → risk check → execute
//============================================================
void RunAnalysis(const string style)
{
   string sym = Inp_Symbol;

   // 1. Collect market data
   string mkt_json = BuildMarketDataJson(sym, style);
   if(mkt_json == "")
   {
      PrintFormat("[Brain] ⚠ Could not build market data for %s", style);
      return;
   }

   // 2. Call AI
   AIDecision decision = g_ai.Analyze(mkt_json);
   if(!decision.valid || decision.action == "HOLD")
   {
      PrintFormat("[Brain] 🤔 [%s] AI says HOLD (conf=%d)", style, decision.confidence);
      return;
   }

   // 3. Log signal to Supabase (for dashboard visibility)
   g_supa.LogSignal(decision.action, style, decision.confidence,
                    decision.sl, decision.tp, decision.reason);

   // 4. Risk Guard check
   RiskResult rr = g_risk.Check(sym, decision.action, style,
                                 decision.confidence, PositionsTotal());
   if(!rr.passed)
   {
      PrintFormat("[Brain] 🛡 [%s] Risk Guard blocked: %s", style, rr.reason);
      return;
   }

   // 5. Determine lot size
   double lot = g_supa.lot_intraday;
   ulong  magic = Inp_MagicBase + 2;
   double be_trig = g_supa.intraday_be_trigger, be_off = g_supa.intraday_be_offset;
   double trail_s = g_supa.intraday_trail_start, trail_d = g_supa.intraday_trail_dist;

   if(style == "SCALPING")
   {
      lot     = g_supa.lot_scalping;
      magic   = Inp_MagicBase + 1;
      be_trig = g_supa.scalping_be_trigger;
      be_off  = g_supa.scalping_be_offset;
      trail_s = g_supa.scalping_trail_start;
      trail_d = g_supa.scalping_trail_dist;
   }
   else if(style == "SWING")
   {
      lot     = g_supa.lot_swing;
      magic   = Inp_MagicBase + 3;
      be_trig = g_supa.swing_be_trigger;
      be_off  = g_supa.swing_be_offset;
      trail_s = g_supa.swing_trail_start;
      trail_d = g_supa.swing_trail_dist;
   }

   lot = g_exec.NormalizeLot(sym, lot);

   // 6. Execute trade
   string comment = "AI_" + style;
   ulong ticket = g_exec.OpenOrder(sym, decision.action, lot, magic, comment);
   if(ticket == 0)
   {
      PrintFormat("[Brain] ❌ [%s] Trade execution failed.", style);
      return;
   }

   // 7. Calculate final Virtual SL/TP
   double entry   = g_exec.GetEntryPrice(sym, decision.action);
   double pip     = 0.01; // Gold pip
   double v_sl    = decision.sl;
   double v_tp    = decision.tp;

   // Fallback SL/TP from style params if AI didn't provide valid ones
   if(v_sl <= 0 || v_tp <= 0)
   {
      double sl_pips = 20, tp_pips = 40;
      if(style == "INTRADAY") { sl_pips = 50;  tp_pips = 100; }
      if(style == "SWING")    { sl_pips = 150; tp_pips = 300; }

      if(decision.action == "BUY")
      {
         v_sl = entry - sl_pips * pip;
         v_tp = entry + tp_pips * pip;
      }
      else
      {
         v_sl = entry + sl_pips * pip;
         v_tp = entry - tp_pips * pip;
      }
   }

   // 8. Write to Supabase active_trades
   g_supa.WriteTrade(ticket, sym, decision.action, lot, entry, style,
                     v_sl, v_tp, be_trig, be_off, trail_s, trail_d);

   // 9. Register with VirtualManager
   g_virt.Register(ticket, sym, decision.action, style, lot, entry,
                   v_sl, v_tp, be_trig, be_off, trail_s, trail_d);

   PrintFormat("[Brain] ✅ [%s] %s %s %.2f lots | Ticket:%d | SL:%.2f TP:%.2f",
               style, decision.action, sym, lot, ticket, v_sl, v_tp);
}

//============================================================
// OnInit
//============================================================
int OnInit()
{
   if(Inp_AccountID == "")
   {
      Alert("⛔ CRITICAL: Account ID kosong! Sila isi Account ID dalam EA Inputs.");
      return INIT_FAILED;
   }
   if(Inp_GroqKey1 == "" && Inp_GroqKey2 == "" && Inp_GroqKey3 == "")
   {
      Alert("⛔ CRITICAL: Tiada Groq API Key! Sila isi sekurang-kurangnya Key #1.");
      return INIT_FAILED;
   }

   // Ensure symbol is in MarketWatch
   SymbolSelect(Inp_Symbol, true);
   if(!SymbolInfoInteger(Inp_Symbol, SYMBOL_EXIST))
   {
      Alert("⛔ Symbol '" + Inp_Symbol + "' tidak ditemui. Semak nama simbol.");
      return INIT_FAILED;
   }

   // Init subsystems
   g_supa.Init(Inp_SupabaseURL, Inp_SupabaseAnon, Inp_AccountID);
   // Override defaults from Supabase
   g_supa.min_confidence  = Inp_MinConfidence;
   g_supa.max_spread_points = Inp_MaxSpread;
   g_supa.max_total_trades = Inp_MaxTrades;
   g_supa.max_drawdown_pct = Inp_MaxDrawdown;

   g_ai.Init(Inp_GroqKey1, Inp_GroqKey2, Inp_GroqKey3, Inp_GroqModel);
   g_exec.Init(Inp_MagicBase);
   g_risk.Init(&g_supa);
   g_virt.Init(&g_supa, &g_exec, &g_risk);

   // Fetch live settings from Supabase (overrides inputs)
   g_supa.SyncSettings();
   g_last_settings = TimeCurrent();

   EventSetTimer(1); // 1-second timer

   PrintFormat("✅ InvestmentAI Brain v5.0 | Account: %s | Symbol: %s | Magic: %d",
               Inp_AccountID, Inp_Symbol, (int)Inp_MagicBase);
   PrintFormat("   Scalping:%s | Intraday:%s | Swing:%s",
               Inp_EnableScalping ? "ON" : "OFF",
               Inp_EnableIntraday ? "ON" : "OFF",
               Inp_EnableSwing    ? "ON" : "OFF");

   return INIT_SUCCEEDED;
}

//============================================================
// OnDeinit
//============================================================
void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, "VSL_");
   ObjectsDeleteAll(0, "VTP_");
   ObjectsDeleteAll(0, "VTR_");
   Print("[Brain] EA stopped. Virtual lines cleared.");
}

//============================================================
// OnTick — manage virtual SL/TP on every tick
//============================================================
void OnTick()
{
   g_virt.OnTick();
}

//============================================================
// OnTimer — analysis, settings sync, heartbeat (1s timer)
//============================================================
void OnTimer()
{
   datetime now = TimeCurrent();

   // ── Settings sync ──────────────────────────────────────
   if(now - g_last_settings >= INTERVAL_SETTINGS)
   {
      g_supa.SyncSettings();
      g_last_settings = now;
   }

   // ── Heartbeat ─────────────────────────────────────────
   if(now - g_last_heartbeat >= INTERVAL_HEARTBEAT)
   {
      g_supa.Heartbeat(AccountInfoDouble(ACCOUNT_BALANCE),
                       AccountInfoDouble(ACCOUNT_EQUITY));
      g_last_heartbeat = now;
   }

   // ── SCALPING (every 5 minutes, midnight-aligned) ───────
   if(Inp_EnableScalping && ShouldRun(g_last_scalping, INTERVAL_SCALPING))
   {
      PrintFormat("[Brain] ⏰ SCALPING analysis triggered at %s", TimeToString(now));
      RunAnalysis("SCALPING");
   }

   // ── INTRADAY (every 1 hour, midnight-aligned) ──────────
   if(Inp_EnableIntraday && ShouldRun(g_last_intraday, INTERVAL_INTRADAY))
   {
      PrintFormat("[Brain] ⏰ INTRADAY analysis triggered at %s", TimeToString(now));
      RunAnalysis("INTRADAY");
   }

   // ── SWING (every 2 hours, midnight-aligned) ────────────
   if(Inp_EnableSwing && ShouldRun(g_last_swing, INTERVAL_SWING))
   {
      PrintFormat("[Brain] ⏰ SWING analysis triggered at %s", TimeToString(now));
      RunAnalysis("SWING");
   }
}

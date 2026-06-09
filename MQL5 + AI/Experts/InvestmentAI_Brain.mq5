//+------------------------------------------------------------------+
//|                                          InvestmentAI_Brain.mq5 |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|    All-in-one: AI analysis + virtual SL/TP — NO Supabase        |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Investment-AI_T"
#property link      "https://github.com/hdanial211/Investment-AI_T"
#property version   "5.10"
#property description "Standalone AI Trading EA — Groq AI + MT5 execution. No cloud required."

#include "..\Include\AIBrain\JsonParser.mqh"
#include "..\Include\AIBrain\HttpClient.mqh"
#include "..\Include\AIBrain\MarketData.mqh"
#include "..\Include\AIBrain\AIProvider.mqh"
#include "..\Include\AIBrain\RiskGuard.mqh"
#include "..\Include\AIBrain\TradeExecutor.mqh"
#include "..\Include\AIBrain\VirtualManager.mqh"

//============================================================
// INPUT PARAMETERS
//============================================================

// ── Groq API Keys (3-key rotation) ───────────────────────
input string   Inp_GroqKey1        = "";             // Groq API Key #1 (Primary)
input string   Inp_GroqKey2        = "";             // Groq API Key #2 (Backup 1)
input string   Inp_GroqKey3        = "";             // Groq API Key #3 (Backup 2)
input string   Inp_GroqModel       = "llama-3.3-70b-versatile"; // Groq Model

// ── Symbol ────────────────────────────────────────────────
input string   Inp_Symbol          = "XAUUSDc";     // Gold symbol

// ── Trading Styles Enable/Disable ────────────────────────
input bool     Inp_EnableScalping  = true;           // Enable SCALPING (5 min)
input bool     Inp_EnableIntraday  = true;           // Enable INTRADAY (30 min)
input bool     Inp_EnableSwing     = true;           // Enable SWING (1 jam)

// ── Lot Sizes ─────────────────────────────────────────────
input double   Inp_LotScalping     = 0.01;           // Lot size — SCALPING
input double   Inp_LotIntraday     = 0.02;           // Lot size — INTRADAY
input double   Inp_LotSwing        = 0.03;           // Lot size — SWING

// ── Risk Settings ─────────────────────────────────────────
input int      Inp_MinConfidence   = 70;             // Min AI confidence (%)
input int      Inp_MaxSpread       = 50;             // Max spread (points)
input int      Inp_MaxTrades       = 5;              // Max concurrent trades
input double   Inp_MaxDrawdown     = 5.0;            // Max daily drawdown (%)
input bool     Inp_BlockAsia       = false;          // Block Asia session (00-08)

// ── Virtual SL/TP — SCALPING ──────────────────────────────
input double   Inp_S_BETrigger     = 15;             // Scalping: BE trigger (pips)
input double   Inp_S_BEOffset      = 2;              // Scalping: BE offset (pips)
input double   Inp_S_TrailStart    = 20;             // Scalping: Trail start (pips)
input double   Inp_S_TrailDist     = 10;             // Scalping: Trail distance (pips)

// ── Virtual SL/TP — INTRADAY ──────────────────────────────
input double   Inp_I_BETrigger     = 25;             // Intraday: BE trigger (pips)
input double   Inp_I_BEOffset      = 5;              // Intraday: BE offset (pips)
input double   Inp_I_TrailStart    = 40;             // Intraday: Trail start (pips)
input double   Inp_I_TrailDist     = 20;             // Intraday: Trail distance (pips)

// ── Virtual SL/TP — SWING ─────────────────────────────────
input double   Inp_W_BETrigger     = 60;             // Swing: BE trigger (pips)
input double   Inp_W_BEOffset      = 15;             // Swing: BE offset (pips)
input double   Inp_W_TrailStart    = 100;            // Swing: Trail start (pips)
input double   Inp_W_TrailDist     = 50;             // Swing: Trail distance (pips)

// ── Magic Numbers ─────────────────────────────────────────
input ulong    Inp_MagicBase       = 999000;         // Base magic number

//============================================================
// GLOBAL OBJECTS
//============================================================

CAIProvider     g_ai;
CRiskGuard      g_risk;
CTradeExecutor  g_exec;
CVirtualManager g_virt;

datetime g_last_scalping = 0;
datetime g_last_intraday = 0;
datetime g_last_swing    = 0;

// Analysis intervals (seconds)
#define INTERVAL_SCALPING   300     // 5 minit
#define INTERVAL_INTRADAY   1800    // 30 minit
#define INTERVAL_SWING      3600    // 1 jam

//============================================================
// HELPER: Run if new time slot reached (midnight-aligned)
//============================================================
bool ShouldRun(datetime &last_run, int interval_sec)
{
   datetime now       = TimeCurrent();
   datetime slot_start = now - (now % interval_sec);
   if(last_run < slot_start)
   {
      last_run = now;
      return true;
   }
   return false;
}

//============================================================
// HELPER: Run AI analysis → risk check → execute trade
//============================================================
void RunAnalysis(const string style)
{
   string sym = Inp_Symbol;

   // 1. Collect market data
   string mkt_json = BuildMarketDataJson(sym, style);
   if(mkt_json == "")
   {
      PrintFormat("[Brain] ⚠ Cannot build market data for %s", style);
      return;
   }

   // 2. Call AI
   AIDecision d = g_ai.Analyze(mkt_json);
   if(!d.valid || d.action == "HOLD")
   {
      PrintFormat("[Brain] 🤔 [%s] HOLD (conf=%d)", style, d.confidence);
      return;
   }

   // 3. Risk Guard
   RiskResult rr = g_risk.Check(sym, d.action, style, d.confidence, PositionsTotal());
   if(!rr.passed)
   {
      PrintFormat("[Brain] 🛡 [%s] Blocked: %s", style, rr.reason);
      return;
   }

   // 4. Lot size and magic per style
   double lot   = Inp_LotIntraday;
   ulong  magic = Inp_MagicBase + 2;
   double be_t  = Inp_I_BETrigger, be_o = Inp_I_BEOffset;
   double tr_s  = Inp_I_TrailStart, tr_d = Inp_I_TrailDist;

   if(style == "SCALPING")
   {
      lot   = Inp_LotScalping; magic = Inp_MagicBase + 1;
      be_t  = Inp_S_BETrigger; be_o = Inp_S_BEOffset;
      tr_s  = Inp_S_TrailStart; tr_d = Inp_S_TrailDist;
   }
   else if(style == "SWING")
   {
      lot   = Inp_LotSwing; magic = Inp_MagicBase + 3;
      be_t  = Inp_W_BETrigger; be_o = Inp_W_BEOffset;
      tr_s  = Inp_W_TrailStart; tr_d = Inp_W_TrailDist;
   }

   lot = g_exec.NormalizeLot(sym, lot);

   // 5. Execute
   ulong ticket = g_exec.OpenOrder(sym, d.action, lot, magic, "AI_" + style);
   if(ticket == 0)
   {
      PrintFormat("[Brain] ❌ [%s] Execution failed.", style);
      return;
   }

   // 6. Calculate virtual SL/TP
   double entry = g_exec.GetEntryPrice(sym, d.action);
   double pip   = 0.01; // Gold pip
   double v_sl  = d.sl;
   double v_tp  = d.tp;

   // Fallback SL/TP if AI didn't provide valid values
   if(v_sl <= 0 || v_tp <= 0)
   {
      double sl_p = 20, tp_p = 40;
      if(style == "INTRADAY") { sl_p = 50;  tp_p = 100; }
      if(style == "SWING")    { sl_p = 150; tp_p = 300; }

      v_sl = (d.action == "BUY") ? entry - sl_p * pip : entry + sl_p * pip;
      v_tp = (d.action == "BUY") ? entry + tp_p * pip : entry - tp_p * pip;
   }

   // 7. Register with VirtualManager
   g_virt.Register(ticket, sym, d.action, style, lot, entry,
                   v_sl, v_tp, be_t, be_o, tr_s, tr_d);

   PrintFormat("[Brain] ✅ [%s] %s %s %.2f lots | #%d | SL:%.2f TP:%.2f | %s",
               style, d.action, sym, lot, ticket, v_sl, v_tp, d.reason);
}

//============================================================
// OnInit
//============================================================
int OnInit()
{
   if(Inp_GroqKey1 == "" && Inp_GroqKey2 == "" && Inp_GroqKey3 == "")
   {
      Alert("⛔ Tiada Groq API Key! Sila isi sekurang-kurangnya Key #1.");
      return INIT_FAILED;
   }

   SymbolSelect(Inp_Symbol, true);
   if(!SymbolInfoInteger(Inp_Symbol, SYMBOL_EXIST))
   {
      Alert("⛔ Symbol '" + Inp_Symbol + "' tidak dijumpai.");
      return INIT_FAILED;
   }

   // Init subsystems
   g_ai.Init(Inp_GroqKey1, Inp_GroqKey2, Inp_GroqKey3, Inp_GroqModel);
   g_risk.SetParams(Inp_MinConfidence, Inp_MaxTrades, Inp_MaxSpread, Inp_MaxDrawdown, Inp_BlockAsia);
   g_exec.Init(Inp_MagicBase);
   g_virt.Init(&g_exec, &g_risk);

   EventSetTimer(1);

   PrintFormat("✅ InvestmentAI Brain v5.1 | Symbol: %s | Magic: %d",
               Inp_Symbol, (int)Inp_MagicBase);
   PrintFormat("   Lots — S:%.2f I:%.2f Sw:%.2f | MinConf:%d MaxTrades:%d",
               Inp_LotScalping, Inp_LotIntraday, Inp_LotSwing,
               Inp_MinConfidence, Inp_MaxTrades);
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
   Print("[Brain] EA stopped.");
}

//============================================================
// OnTick — VirtualManager checks SL/TP every tick
//============================================================
void OnTick()
{
   g_virt.OnTick();
}

//============================================================
// OnTimer — AI analysis trigger (1 second timer)
//============================================================
void OnTimer()
{
   if(Inp_EnableScalping && ShouldRun(g_last_scalping, INTERVAL_SCALPING))
   {
      PrintFormat("[Brain] ⏰ SCALPING @ %s", TimeToString(TimeCurrent()));
      RunAnalysis("SCALPING");
   }

   if(Inp_EnableIntraday && ShouldRun(g_last_intraday, INTERVAL_INTRADAY))
   {
      PrintFormat("[Brain] ⏰ INTRADAY @ %s", TimeToString(TimeCurrent()));
      RunAnalysis("INTRADAY");
   }

   if(Inp_EnableSwing && ShouldRun(g_last_swing, INTERVAL_SWING))
   {
      PrintFormat("[Brain] ⏰ SWING @ %s", TimeToString(TimeCurrent()));
      RunAnalysis("SWING");
   }
}

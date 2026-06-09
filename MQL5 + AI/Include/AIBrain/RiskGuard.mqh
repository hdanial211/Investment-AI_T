//+------------------------------------------------------------------+
//|                                                   RiskGuard.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|          Pre-trade risk filter: confidence, spread, drawdown     |
//+------------------------------------------------------------------+
#ifndef RISKGUARD_MQH
#define RISKGUARD_MQH

#include "SupabaseClient.mqh"

//--- Result struct from risk check
struct RiskResult
{
   bool   passed;
   string reason;   // Why it was blocked (empty if passed)
};

class CRiskGuard
{
private:
   CSupabaseClient *m_supa;

   // Cooling-off: track last loss timestamp per style
   datetime m_last_loss_scalping;
   datetime m_last_loss_intraday;
   datetime m_last_loss_swing;

public:
   void Init(CSupabaseClient *supa)
   {
      m_supa = supa;
      m_last_loss_scalping = 0;
      m_last_loss_intraday = 0;
      m_last_loss_swing    = 0;
   }

   //--- Call this when a trade closes in loss (for cooling-off tracking)
   void RecordLoss(const string style)
   {
      if(style == "SCALPING") m_last_loss_scalping = TimeCurrent();
      else if(style == "INTRADAY") m_last_loss_intraday = TimeCurrent();
      else if(style == "SWING")    m_last_loss_swing    = TimeCurrent();
   }

   //--- Main filter function
   RiskResult Check(const string symbol, const string action,
                    const string style, int confidence,
                    int open_positions)
   {
      RiskResult r;
      r.passed = true;
      r.reason = "";

      // 1. Confidence threshold
      if(confidence < m_supa.min_confidence)
      {
         r.passed = false;
         r.reason = StringFormat("Confidence %d < Min %d", confidence, m_supa.min_confidence);
         return r;
      }

      // 2. Max open trades
      if(open_positions >= m_supa.max_total_trades)
      {
         r.passed = false;
         r.reason = StringFormat("Open trades %d >= Max %d", open_positions, m_supa.max_total_trades);
         return r;
      }

      // 3. Spread check
      long spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
      if(spread > m_supa.max_spread_points)
      {
         r.passed = false;
         r.reason = StringFormat("Spread %d > Max %d", (int)spread, m_supa.max_spread_points);
         return r;
      }

      // 4. Daily drawdown check
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(balance > 0 && equity < balance)
      {
         double dd = (balance - equity) / balance * 100.0;
         if(dd > m_supa.max_drawdown_pct)
         {
            r.passed = false;
            r.reason = StringFormat("Drawdown %.1f%% > Max %.1f%%", dd, m_supa.max_drawdown_pct);
            return r;
         }
      }

      // 5. Asia session block
      if(m_supa.block_asia)
      {
         MqlDateTime dt;
         TimeCurrent(dt);
         if(dt.hour >= 0 && dt.hour < 8)
         {
            r.passed = false;
            r.reason = StringFormat("Asia session blocked (hour %d)", dt.hour);
            return r;
         }
      }

      // 6. Cooling-off: 15-min after loss for scalping, 30-min for intraday, 60-min for swing
      datetime now = TimeCurrent();
      if(style == "SCALPING" && m_last_loss_scalping > 0)
      {
         if(now - m_last_loss_scalping < 900)
         {
            r.passed = false;
            r.reason = "Cooling-off: 15min after SCALPING loss";
            return r;
         }
      }
      if(style == "INTRADAY" && m_last_loss_intraday > 0)
      {
         if(now - m_last_loss_intraday < 1800)
         {
            r.passed = false;
            r.reason = "Cooling-off: 30min after INTRADAY loss";
            return r;
         }
      }
      if(style == "SWING" && m_last_loss_swing > 0)
      {
         if(now - m_last_loss_swing < 3600)
         {
            r.passed = false;
            r.reason = "Cooling-off: 60min after SWING loss";
            return r;
         }
      }

      return r; // All passed
   }

   //--- Check if there's already an open trade for a given style+direction
   bool HasOpenTradeForStyle(const string style, const string direction, ulong magic_base)
   {
      ulong target_magic = magic_base;
      if(style == "SCALPING") target_magic = magic_base + 1;
      else if(style == "INTRADAY") target_magic = magic_base + 2;
      else if(style == "SWING")    target_magic = magic_base + 3;

      for(int i = 0; i < PositionsTotal(); i++)
      {
         ulong tkt = PositionGetTicket(i);
         if(tkt <= 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) == (long)target_magic)
            return true;
      }
      return false;
   }
};

#endif

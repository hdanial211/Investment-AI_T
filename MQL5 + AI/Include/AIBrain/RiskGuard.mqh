//+------------------------------------------------------------------+
//|                                                   RiskGuard.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|     Pre-trade risk filter — standalone, no Supabase required     |
//+------------------------------------------------------------------+
#ifndef RISKGUARD_MQH
#define RISKGUARD_MQH

struct RiskResult
{
   bool   passed;
   string reason;
};

class CRiskGuard
{
private:
   // Settings — set via SetParams()
   int    m_min_confidence;
   int    m_max_trades;
   int    m_max_spread;
   double m_max_drawdown;
   bool   m_block_asia;

   // Cooling-off timestamps per style
   datetime m_last_loss_scalping;
   datetime m_last_loss_intraday;
   datetime m_last_loss_swing;

public:
   void SetParams(int min_conf, int max_trades, int max_spread,
                  double max_dd, bool block_asia)
   {
      m_min_confidence = min_conf;
      m_max_trades     = max_trades;
      m_max_spread     = max_spread;
      m_max_drawdown   = max_dd;
      m_block_asia     = block_asia;

      m_last_loss_scalping = 0;
      m_last_loss_intraday = 0;
      m_last_loss_swing    = 0;
   }

   void RecordLoss(const string style)
   {
      if(style == "SCALPING") m_last_loss_scalping = TimeCurrent();
      else if(style == "INTRADAY") m_last_loss_intraday = TimeCurrent();
      else if(style == "SWING")    m_last_loss_swing    = TimeCurrent();
   }

   RiskResult Check(const string symbol, const string action,
                    const string style, int confidence, int open_positions)
   {
      RiskResult r;
      r.passed = true;
      r.reason = "";

      // 1. Confidence
      if(confidence < m_min_confidence)
      {
         r.passed = false;
         r.reason = StringFormat("Confidence %d < Min %d", confidence, m_min_confidence);
         return r;
      }

      // 2. Max open trades
      if(open_positions >= m_max_trades)
      {
         r.passed = false;
         r.reason = StringFormat("Open %d >= Max %d", open_positions, m_max_trades);
         return r;
      }

      // 3. Spread
      long spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
      if(spread > m_max_spread)
      {
         r.passed = false;
         r.reason = StringFormat("Spread %d > Max %d", (int)spread, m_max_spread);
         return r;
      }

      // 4. Daily drawdown
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(balance > 0 && equity < balance)
      {
         double dd = (balance - equity) / balance * 100.0;
         if(dd > m_max_drawdown)
         {
            r.passed = false;
            r.reason = StringFormat("Drawdown %.1f%% > Max %.1f%%", dd, m_max_drawdown);
            return r;
         }
      }

      // 5. Asia session block
      if(m_block_asia)
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

      // 6. Cooling-off
      datetime now = TimeCurrent();
      if(style == "SCALPING" && m_last_loss_scalping > 0 && now - m_last_loss_scalping < 900)
         { r.passed = false; r.reason = "Cooling-off: 15min after SCALPING loss"; return r; }
      if(style == "INTRADAY" && m_last_loss_intraday > 0 && now - m_last_loss_intraday < 1800)
         { r.passed = false; r.reason = "Cooling-off: 30min after INTRADAY loss"; return r; }
      if(style == "SWING" && m_last_loss_swing > 0 && now - m_last_loss_swing < 3600)
         { r.passed = false; r.reason = "Cooling-off: 60min after SWING loss"; return r; }

      return r;
   }
};

#endif

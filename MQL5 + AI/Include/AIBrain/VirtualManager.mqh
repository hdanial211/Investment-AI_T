//+------------------------------------------------------------------+
//|                                              VirtualManager.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|   Manages virtual SL/TP/Trailing on every tick; syncs Supabase  |
//+------------------------------------------------------------------+
#ifndef VIRTUALMANAGER_MQH
#define VIRTUALMANAGER_MQH

#include "SupabaseClient.mqh"
#include "TradeExecutor.mqh"

//--- Per-position state cache
struct VirtTradeState
{
   ulong   ticket;
   string  symbol;
   string  direction;   // "BUY" or "SELL"
   string  style;
   double  lot;
   double  open_price;
   double  v_sl;        // Virtual stop-loss price
   double  v_tp;        // Virtual take-profit price
   double  v_trail;     // Current virtual trailing price (0 = not activated)
   double  be_pips;
   double  be_offset;
   double  trail_start;
   double  trail_dist;
   double  pip_size;    // For gold: 0.01
};

class CVirtualManager
{
private:
   CSupabaseClient *m_supa;
   CTradeExecutor  *m_exec;
   CRiskGuard      *m_risk;

   VirtTradeState   m_states[];
   int              m_count;

   //--- Find state index by ticket, returns -1 if not found
   int _FindIdx(ulong ticket)
   {
      for(int i = 0; i < m_count; i++)
         if(m_states[i].ticket == ticket) return i;
      return -1;
   }

   //--- Draw/update a horizontal line on chart
   void _DrawLine(const string name, double price, color clr, ENUM_LINE_STYLE lstyle, const string label)
   {
      if(price <= 0) return;
      if(ObjectFind(0, name) < 0)
      {
         ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
         ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
         ObjectSetInteger(0, name, OBJPROP_STYLE, lstyle);
         ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
         ObjectSetString(0, name, OBJPROP_TEXT, label);
      }
      ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   }

   //--- Remove chart lines for a ticket
   void _RemoveLines(ulong ticket)
   {
      string base = IntegerToString(ticket);
      ObjectDelete(0, "VSL_" + base);
      ObjectDelete(0, "VTP_" + base);
      ObjectDelete(0, "VTR_" + base);
   }

public:
   void Init(CSupabaseClient *supa, CTradeExecutor *exec, CRiskGuard *risk)
   {
      m_supa  = supa;
      m_exec  = exec;
      m_risk  = risk;
      m_count = 0;
      ArrayResize(m_states, 0);
   }

   //--- Register a newly opened position
   void Register(ulong ticket, const string symbol, const string direction,
                 const string style, double lot, double open_price,
                 double v_sl, double v_tp,
                 double be_pips, double be_offset,
                 double trail_start, double trail_dist)
   {
      if(_FindIdx(ticket) != -1) return; // Already registered

      ArrayResize(m_states, m_count + 1);
      VirtTradeState &s = m_states[m_count];
      s.ticket      = ticket;
      s.symbol      = symbol;
      s.direction   = direction;
      s.style       = style;
      s.lot         = lot;
      s.open_price  = open_price;
      s.v_sl        = v_sl;
      s.v_tp        = v_tp;
      s.v_trail     = 0;
      s.be_pips     = be_pips;
      s.be_offset   = be_offset;
      s.trail_start = trail_start;
      s.trail_dist  = trail_dist;
      s.pip_size    = (StringFind(symbol, "XAU") != -1) ? 0.01 : 0.0001;
      m_count++;

      // Draw initial lines
      string base = IntegerToString(ticket);
      _DrawLine("VSL_" + base, v_sl, clrRed,       STYLE_SOLID, style + " " + direction + " SL");
      _DrawLine("VTP_" + base, v_tp, clrLimeGreen,  STYLE_SOLID, style + " " + direction + " TP");

      PrintFormat("[VirtMgr] Registered ticket %d | %s %s | SL:%.2f TP:%.2f",
                  ticket, direction, symbol, v_sl, v_tp);
   }

   //--- Called on every tick — checks all registered positions
   //    Returns list of closed tickets to remove from state
   void OnTick()
   {
      for(int i = m_count - 1; i >= 0; i--)
      {
         VirtTradeState &s = m_states[i];
         if(!PositionSelectByTicket(s.ticket)) continue; // Already closed externally

         double cur_price = (s.direction == "BUY")
                          ? SymbolInfoDouble(s.symbol, SYMBOL_BID)
                          : SymbolInfoDouble(s.symbol, SYMBOL_ASK);
         double profit_pips = (s.direction == "BUY")
                            ? (cur_price - s.open_price) / s.pip_size
                            : (s.open_price - cur_price) / s.pip_size;

         bool   should_close   = false;
         string close_reason   = "";

         // ── Check Virtual SL / TP ────────────────────────────────
         if(s.direction == "BUY")
         {
            if(s.v_sl > 0 && cur_price <= s.v_sl) { should_close = true; close_reason = "Virtual SL Hit"; }
            if(s.v_tp > 0 && cur_price >= s.v_tp) { should_close = true; close_reason = "Virtual TP Hit"; }
         }
         else
         {
            if(s.v_sl > 0 && cur_price >= s.v_sl) { should_close = true; close_reason = "Virtual SL Hit"; }
            if(s.v_tp > 0 && cur_price <= s.v_tp) { should_close = true; close_reason = "Virtual TP Hit"; }
         }

         // ── Check Trailing/BE line hit ───────────────────────────
         if(!should_close && s.v_trail > 0)
         {
            if(s.direction == "BUY"  && cur_price <= s.v_trail) { should_close = true; close_reason = "Trailing/BE Hit"; }
            if(s.direction == "SELL" && cur_price >= s.v_trail) { should_close = true; close_reason = "Trailing/BE Hit"; }
         }

         // ── Close if needed ──────────────────────────────────────
         if(should_close)
         {
            double pnl = PositionGetDouble(POSITION_PROFIT)
                       + PositionGetDouble(POSITION_SWAP);
            bool closed = m_exec.ClosePosition(s.ticket);
            if(closed)
            {
               Sleep(200);
               double final_pnl = m_exec.GetRealisedPL(s.ticket);
               if(final_pnl == 0) final_pnl = pnl;
               m_supa.CloseTrade(s.ticket, s.symbol, s.direction, s.lot, s.style, final_pnl, close_reason);
               if(final_pnl < 0) m_risk.RecordLoss(s.style);
               _RemoveLines(s.ticket);
               PrintFormat("[VirtMgr] ✅ Closed ticket %d | %s | PnL: %.2f", s.ticket, close_reason, final_pnl);
               // Remove from array
               for(int k = i; k < m_count - 1; k++) m_states[k] = m_states[k + 1];
               m_count--;
               ArrayResize(m_states, m_count);
            }
            continue;
         }

         // ── Update Trailing Stop / Break-Even ────────────────────
         bool updated_trail = false;
         string base = IntegerToString(s.ticket);

         if(s.direction == "BUY")
         {
            // Break-Even activation
            if(s.be_pips > 0 && profit_pips >= s.be_pips && (s.v_trail < s.open_price || s.v_trail == 0))
            {
               s.v_trail    = s.open_price + s.be_offset * s.pip_size;
               updated_trail = true;
            }
            // Trailing activation
            if(s.trail_start > 0 && profit_pips >= s.trail_start)
            {
               double new_trail = cur_price - s.trail_dist * s.pip_size;
               if(s.v_trail == 0 || new_trail > s.v_trail)
               {
                  s.v_trail    = new_trail;
                  updated_trail = true;
               }
            }
         }
         else // SELL
         {
            if(s.be_pips > 0 && profit_pips >= s.be_pips && (s.v_trail > s.open_price || s.v_trail == 0))
            {
               s.v_trail    = s.open_price - s.be_offset * s.pip_size;
               updated_trail = true;
            }
            if(s.trail_start > 0 && profit_pips >= s.trail_start)
            {
               double new_trail = cur_price + s.trail_dist * s.pip_size;
               if(s.v_trail == 0 || new_trail < s.v_trail)
               {
                  s.v_trail    = new_trail;
                  updated_trail = true;
               }
            }
         }

         if(updated_trail)
         {
            _DrawLine("VTR_" + base, s.v_trail, clrOrange, STYLE_DASH, s.style + " TRAIL/BE");
            m_supa.UpdateTradeVSL(s.ticket, s.v_trail);
            // Also update the SL line visually
            s.v_sl = s.v_trail;
            ObjectSetDouble(0, "VSL_" + base, OBJPROP_PRICE, s.v_sl);
         }
      }

      // ── Clean up orphaned chart objects ──────────────────────────
      for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
      {
         string obj = ObjectName(0, i);
         if(StringFind(obj, "VSL_") == 0 || StringFind(obj, "VTP_") == 0 || StringFind(obj, "VTR_") == 0)
         {
            string tkt_str = StringSubstr(obj, 4);
            ulong  tkt     = (ulong)StringToInteger(tkt_str);
            if(tkt > 0 && !PositionSelectByTicket(tkt))
               ObjectDelete(0, obj);
         }
      }
   }

   //--- Get count of currently managed positions
   int Count() { return m_count; }
};

#endif

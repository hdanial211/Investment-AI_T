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
      // Assign directly by index — MQL5 struct array references require constant index
      m_states[m_count].ticket      = ticket;
      m_states[m_count].symbol      = symbol;
      m_states[m_count].direction   = direction;
      m_states[m_count].style       = style;
      m_states[m_count].lot         = lot;
      m_states[m_count].open_price  = open_price;
      m_states[m_count].v_sl        = v_sl;
      m_states[m_count].v_tp        = v_tp;
      m_states[m_count].v_trail     = 0;
      m_states[m_count].be_pips     = be_pips;
      m_states[m_count].be_offset   = be_offset;
      m_states[m_count].trail_start = trail_start;
      m_states[m_count].trail_dist  = trail_dist;
      m_states[m_count].pip_size    = (StringFind(symbol, "XAU") != -1) ? 0.01 : 0.0001;
      m_count++;

      // Draw initial lines
      string base = IntegerToString(ticket);
      _DrawLine("VSL_" + base, v_sl, clrRed,       STYLE_SOLID, style + " " + direction + " SL");
      _DrawLine("VTP_" + base, v_tp, clrLimeGreen,  STYLE_SOLID, style + " " + direction + " TP");

      PrintFormat("[VirtMgr] Registered ticket %d | %s %s | SL:%.2f TP:%.2f",
                  ticket, direction, symbol, v_sl, v_tp);
   }

   //--- Called on every tick — checks all registered positions
   void OnTick()
   {
      for(int i = m_count - 1; i >= 0; i--)
      {
         // Use local copy for reads; write back to array where needed
         ulong  tkt        = m_states[i].ticket;
         string sym        = m_states[i].symbol;
         string dir        = m_states[i].direction;
         string sty        = m_states[i].style;
         double lot        = m_states[i].lot;
         double open_px    = m_states[i].open_price;
         double v_sl       = m_states[i].v_sl;
         double v_tp       = m_states[i].v_tp;
         double v_trail    = m_states[i].v_trail;
         double be_p       = m_states[i].be_pips;
         double be_o       = m_states[i].be_offset;
         double ts_p       = m_states[i].trail_start;
         double td_p       = m_states[i].trail_dist;
         double pip        = m_states[i].pip_size;

         if(!PositionSelectByTicket(tkt)) continue; // Closed externally

         double cur_price  = (dir == "BUY")
                           ? SymbolInfoDouble(sym, SYMBOL_BID)
                           : SymbolInfoDouble(sym, SYMBOL_ASK);
         double profit_pips = (dir == "BUY")
                            ? (cur_price - open_px) / pip
                            : (open_px - cur_price) / pip;

         bool   should_close = false;
         string close_reason = "";

         // ── Check Virtual SL / TP ────────────────────────────────
         if(dir == "BUY")
         {
            if(v_sl > 0 && cur_price <= v_sl) { should_close = true; close_reason = "Virtual SL Hit"; }
            if(v_tp > 0 && cur_price >= v_tp) { should_close = true; close_reason = "Virtual TP Hit"; }
         }
         else
         {
            if(v_sl > 0 && cur_price >= v_sl) { should_close = true; close_reason = "Virtual SL Hit"; }
            if(v_tp > 0 && cur_price <= v_tp) { should_close = true; close_reason = "Virtual TP Hit"; }
         }

         // ── Check Trailing/BE line hit ───────────────────────────
         if(!should_close && v_trail > 0)
         {
            if(dir == "BUY"  && cur_price <= v_trail) { should_close = true; close_reason = "Trailing/BE Hit"; }
            if(dir == "SELL" && cur_price >= v_trail) { should_close = true; close_reason = "Trailing/BE Hit"; }
         }

         // ── Close if needed ──────────────────────────────────────
         if(should_close)
         {
            double pnl    = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
            bool   closed = m_exec.ClosePosition(tkt);
            if(closed)
            {
               Sleep(200);
               double final_pnl = m_exec.GetRealisedPL(tkt);
               if(final_pnl == 0) final_pnl = pnl;
               m_supa.CloseTrade(tkt, sym, dir, lot, sty, final_pnl, close_reason);
               if(final_pnl < 0) m_risk.RecordLoss(sty);
               _RemoveLines(tkt);
               PrintFormat("[VirtMgr] ✅ Closed ticket %d | %s | PnL: %.2f", tkt, close_reason, final_pnl);
               // Remove from array by shifting
               for(int k = i; k < m_count - 1; k++) m_states[k] = m_states[k + 1];
               m_count--;
               ArrayResize(m_states, m_count);
            }
            continue;
         }

         // ── Update Trailing Stop / Break-Even ────────────────────
         bool   updated_trail = false;
         string base          = IntegerToString(tkt);

         if(dir == "BUY")
         {
            if(be_p > 0 && profit_pips >= be_p && (v_trail < open_px || v_trail == 0))
            {
               v_trail       = open_px + be_o * pip;
               updated_trail = true;
            }
            if(ts_p > 0 && profit_pips >= ts_p)
            {
               double new_tr = cur_price - td_p * pip;
               if(v_trail == 0 || new_tr > v_trail)
               {
                  v_trail       = new_tr;
                  updated_trail = true;
               }
            }
         }
         else // SELL
         {
            if(be_p > 0 && profit_pips >= be_p && (v_trail > open_px || v_trail == 0))
            {
               v_trail       = open_px - be_o * pip;
               updated_trail = true;
            }
            if(ts_p > 0 && profit_pips >= ts_p)
            {
               double new_tr = cur_price + td_p * pip;
               if(v_trail == 0 || new_tr < v_trail)
               {
                  v_trail       = new_tr;
                  updated_trail = true;
               }
            }
         }

         if(updated_trail)
         {
            _DrawLine("VTR_" + base, v_trail, clrOrange, STYLE_DASH, sty + " TRAIL/BE");
            m_supa.UpdateTradeVSL(tkt, v_trail);
            // Write back updated values to array
            m_states[i].v_trail = v_trail;
            m_states[i].v_sl    = v_trail;
            ObjectSetDouble(0, "VSL_" + base, OBJPROP_PRICE, v_trail);
         }
      }

      // ── Clean up orphaned chart objects ──────────────────────────
      int total_objs = ObjectsTotal(0);
      for(int j = total_objs - 1; j >= 0; j--)
      {
         string obj = ObjectName(0, j);
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

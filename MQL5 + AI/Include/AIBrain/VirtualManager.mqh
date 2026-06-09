//+------------------------------------------------------------------+
//|                                              VirtualManager.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|   Manages virtual SL/TP/Trailing on every tick — no Supabase    |
//+------------------------------------------------------------------+
#ifndef VIRTUALMANAGER_MQH
#define VIRTUALMANAGER_MQH

#include "TradeExecutor.mqh"
#include "RiskGuard.mqh"

struct VirtTradeState
{
   ulong   ticket;
   string  symbol;
   string  direction;
   string  style;
   double  lot;
   double  open_price;
   double  v_sl;
   double  v_tp;
   double  v_trail;
   double  be_pips;
   double  be_offset;
   double  trail_start;
   double  trail_dist;
   double  pip_size;
};

class CVirtualManager
{
private:
   CTradeExecutor *m_exec;
   CRiskGuard     *m_risk;

   VirtTradeState  m_states[];
   int             m_count;

   int _FindIdx(ulong ticket)
   {
      for(int i = 0; i < m_count; i++)
         if(m_states[i].ticket == ticket) return i;
      return -1;
   }

   void _DrawLine(const string name, double price, color clr,
                  ENUM_LINE_STYLE lstyle, const string label)
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

   void _RemoveLines(ulong ticket)
   {
      string b = IntegerToString(ticket);
      ObjectDelete(0, "VSL_" + b);
      ObjectDelete(0, "VTP_" + b);
      ObjectDelete(0, "VTR_" + b);
   }

public:
   void Init(CTradeExecutor *exec, CRiskGuard *risk)
   {
      m_exec  = exec;
      m_risk  = risk;
      m_count = 0;
      ArrayResize(m_states, 0);
   }

   void Register(ulong ticket, const string symbol, const string direction,
                 const string style, double lot, double open_price,
                 double v_sl, double v_tp,
                 double be_pips, double be_offset,
                 double trail_start, double trail_dist)
   {
      if(_FindIdx(ticket) != -1) return;

      ArrayResize(m_states, m_count + 1);
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

      string base = IntegerToString(ticket);
      _DrawLine("VSL_" + base, v_sl, clrRed,      STYLE_SOLID, style + " " + direction + " SL");
      _DrawLine("VTP_" + base, v_tp, clrLimeGreen, STYLE_SOLID, style + " " + direction + " TP");

      PrintFormat("[VirtMgr] Registered #%d | %s %s | SL:%.2f TP:%.2f", ticket, direction, symbol, v_sl, v_tp);
   }

   void OnTick()
   {
      for(int i = m_count - 1; i >= 0; i--)
      {
         ulong  tkt       = m_states[i].ticket;
         string sym       = m_states[i].symbol;
         string dir       = m_states[i].direction;
         string sty       = m_states[i].style;
         double lot       = m_states[i].lot;
         double open_px   = m_states[i].open_price;
         double v_sl      = m_states[i].v_sl;
         double v_tp      = m_states[i].v_tp;
         double v_trail   = m_states[i].v_trail;
         double be_p      = m_states[i].be_pips;
         double be_o      = m_states[i].be_offset;
         double ts_p      = m_states[i].trail_start;
         double td_p      = m_states[i].trail_dist;
         double pip       = m_states[i].pip_size;

         if(!PositionSelectByTicket(tkt)) continue;

         double cur       = (dir == "BUY") ? SymbolInfoDouble(sym, SYMBOL_BID)
                                           : SymbolInfoDouble(sym, SYMBOL_ASK);
         double profit_p  = (dir == "BUY") ? (cur - open_px) / pip
                                           : (open_px - cur) / pip;

         bool   close_it  = false;
         string reason    = "";

         // Virtual SL / TP hit
         if(dir == "BUY")
         {
            if(v_sl > 0 && cur <= v_sl) { close_it = true; reason = "Virtual SL Hit"; }
            if(v_tp > 0 && cur >= v_tp) { close_it = true; reason = "Virtual TP Hit"; }
         }
         else
         {
            if(v_sl > 0 && cur >= v_sl) { close_it = true; reason = "Virtual SL Hit"; }
            if(v_tp > 0 && cur <= v_tp) { close_it = true; reason = "Virtual TP Hit"; }
         }

         // Trailing / BE line hit
         if(!close_it && v_trail > 0)
         {
            if(dir == "BUY"  && cur <= v_trail) { close_it = true; reason = "Trail/BE Hit"; }
            if(dir == "SELL" && cur >= v_trail) { close_it = true; reason = "Trail/BE Hit"; }
         }

         if(close_it)
         {
            double pnl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
            if(m_exec.ClosePosition(tkt))
            {
               Sleep(200);
               double final_pnl = m_exec.GetRealisedPL(tkt);
               if(final_pnl == 0) final_pnl = pnl;
               if(final_pnl < 0) m_risk.RecordLoss(sty);
               _RemoveLines(tkt);
               PrintFormat("[VirtMgr] ✅ Closed #%d | %s | PnL: %.2f", tkt, reason, final_pnl);
               for(int k = i; k < m_count - 1; k++) m_states[k] = m_states[k + 1];
               m_count--;
               ArrayResize(m_states, m_count);
            }
            continue;
         }

         // Update trailing / break-even
         bool   upd  = false;
         string base = IntegerToString(tkt);

         if(dir == "BUY")
         {
            if(be_p > 0 && profit_p >= be_p && (v_trail < open_px || v_trail == 0))
               { v_trail = open_px + be_o * pip; upd = true; }
            if(ts_p > 0 && profit_p >= ts_p)
            {
               double nt = cur - td_p * pip;
               if(v_trail == 0 || nt > v_trail) { v_trail = nt; upd = true; }
            }
         }
         else
         {
            if(be_p > 0 && profit_p >= be_p && (v_trail > open_px || v_trail == 0))
               { v_trail = open_px - be_o * pip; upd = true; }
            if(ts_p > 0 && profit_p >= ts_p)
            {
               double nt = cur + td_p * pip;
               if(v_trail == 0 || nt < v_trail) { v_trail = nt; upd = true; }
            }
         }

         if(upd)
         {
            _DrawLine("VTR_" + base, v_trail, clrOrange, STYLE_DASH, sty + " TRAIL/BE");
            m_states[i].v_trail = v_trail;
            m_states[i].v_sl    = v_trail;
            ObjectSetDouble(0, "VSL_" + base, OBJPROP_PRICE, v_trail);
            PrintFormat("[VirtMgr] Trail/BE #%d → %.2f", tkt, v_trail);
         }
      }

      // Clean orphaned lines
      for(int j = ObjectsTotal(0) - 1; j >= 0; j--)
      {
         string obj = ObjectName(0, j);
         if(StringFind(obj, "VSL_") == 0 || StringFind(obj, "VTP_") == 0 || StringFind(obj, "VTR_") == 0)
         {
            ulong tkt = (ulong)StringToInteger(StringSubstr(obj, 4));
            if(tkt > 0 && !PositionSelectByTicket(tkt)) ObjectDelete(0, obj);
         }
      }
   }

   int Count() { return m_count; }
};

#endif

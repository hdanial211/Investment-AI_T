//+------------------------------------------------------------------+
//|                                               TradeExecutor.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|    Opens/closes orders with auto filling mode & retry logic      |
//+------------------------------------------------------------------+
#ifndef TRADEEXECUTOR_MQH
#define TRADEEXECUTOR_MQH

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

class CTradeExecutor
{
private:
   CTrade        m_trade;
   CPositionInfo m_pos;

   //--- Auto-detect the correct filling mode for a symbol
   ENUM_ORDER_TYPE_FILLING _GetFillingMode(const string symbol)
   {
      uint filling = (uint)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
      // Bit 0 = FOK (0), Bit 1 = IOC (1), Bit 2 = RETURN (2)
      if(filling & 1) return ORDER_FILLING_FOK;
      if(filling & 2) return ORDER_FILLING_IOC;
      return ORDER_FILLING_RETURN;
   }

public:
   void Init(ulong magic)
   {
      m_trade.SetExpertMagicNumber(magic);
      m_trade.SetDeviationInPoints(30);
      m_trade.SetTypeFilling(ORDER_FILLING_FOK); // will be overridden per order
      m_trade.LogLevel(LOG_LEVEL_ERRORS);
   }

   //--- Open a market order, returns ticket > 0 on success
   ulong OpenOrder(const string symbol, const string direction,
                   double lot, ulong magic,
                   const string comment = "AI_Brain")
   {
      m_trade.SetExpertMagicNumber(magic);
      ENUM_ORDER_TYPE_FILLING fill = _GetFillingMode(symbol);
      m_trade.SetTypeFilling(fill);

      bool ok = false;
      if(direction == "BUY")
      {
         double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
         ok = m_trade.Buy(lot, symbol, ask, 0, 0, comment);
      }
      else if(direction == "SELL")
      {
         double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
         ok = m_trade.Sell(lot, symbol, bid, 0, 0, comment);
      }

      if(ok)
      {
         ulong ticket = m_trade.ResultOrder();
         PrintFormat("[TradeExecutor] ✅ %s %s %.2f lots | Ticket: %d | Fill: %d",
                     direction, symbol, lot, ticket, (int)fill);
         return ticket;
      }

      // Log failure details
      PrintFormat("[TradeExecutor] ❌ %s %s failed | Retcode: %d | Comment: %s",
                  direction, symbol,
                  (int)m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
      return 0;
   }

   //--- Close a position by ticket
   bool ClosePosition(ulong ticket)
   {
      if(!m_pos.SelectByTicket(ticket)) return false;
      ENUM_ORDER_TYPE_FILLING fill = _GetFillingMode(m_pos.Symbol());
      m_trade.SetTypeFilling(fill);
      bool ok = m_trade.PositionClose(ticket, 30);
      if(!ok)
         PrintFormat("[TradeExecutor] ❌ ClosePosition %d failed: %s",
                     ticket, m_trade.ResultRetcodeDescription());
      return ok;
   }

   //--- Get current market price
   double GetEntryPrice(const string symbol, const string direction)
   {
      if(direction == "BUY")  return SymbolInfoDouble(symbol, SYMBOL_ASK);
      return SymbolInfoDouble(symbol, SYMBOL_BID);
   }

   //--- Get realised P&L from deal history for a ticket
   double GetRealisedPL(ulong ticket)
   {
      double pnl = 0;
      if(HistorySelect(TimeCurrent() - 604800, TimeCurrent() + 86400))
      {
         int total = HistoryDealsTotal();
         for(int i = total - 1; i >= 0; i--)
         {
            ulong deal = HistoryDealGetTicket(i);
            if(HistoryDealGetInteger(deal, DEAL_POSITION_ID) == (long)ticket &&
               HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_OUT)
            {
               pnl = HistoryDealGetDouble(deal, DEAL_PROFIT)
                   + HistoryDealGetDouble(deal, DEAL_SWAP)
                   + HistoryDealGetDouble(deal, DEAL_COMMISSION);
               break;
            }
         }
      }
      return pnl;
   }

   //--- Normalize lot size to broker requirements
   double NormalizeLot(const string symbol, double lot)
   {
      double lot_min  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double lot_max  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      if(lot_step <= 0) lot_step = 0.01;
      lot = MathRound(lot / lot_step) * lot_step;
      lot = MathMax(lot, lot_min);
      lot = MathMin(lot, lot_max);
      return NormalizeDouble(lot, 2);
   }
};

#endif

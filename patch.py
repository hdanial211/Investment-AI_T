import sys
import re

path = r'E:\PROJECTS\SAHAM\Investment-AI_T_latest\MQL5\Experts\InvestmentAI_Executor.mq5'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add ActiveTradeCache struct and g_cached_trades array before CheckForSignals (around line 280)
struct_str = '''
//+------------------------------------------------------------------+
//| Active Trade Cache from Supabase                                 |
//+------------------------------------------------------------------+
struct ActiveTradeCache {
   ulong ticket;
   double v_sl;
   double v_tp;
   string style;
   string dir;
   string sym;
   double be_pips;
   double be_offset;
   double trail_start;
   double trail_dist;
};
ActiveTradeCache g_cached_trades[];

void SyncActiveTrades() {
   string json = SupabaseGET("/rest/v1/active_trades?account_id=eq." + InpAccountID + "&current_status=eq.OPEN");
   if (json == "" || StringFind(json, "[]") != -1) {
      ArrayResize(g_cached_trades, 0);
      return;
   }
   
   StringReplace(json, "},{", "|");
   string chunks[];
   int count = StringSplit(json, '|', chunks);
   ArrayResize(g_cached_trades, count);
   
   for (int i = 0; i < count; i++) {
      g_cached_trades[i].ticket = StringToInteger(ExtractJSONValue(chunks[i], "ticket"));
      g_cached_trades[i].v_sl = StringToDouble(ExtractJSONValue(chunks[i], "virtual_sl"));
      g_cached_trades[i].v_tp = StringToDouble(ExtractJSONValue(chunks[i], "virtual_tp"));
      g_cached_trades[i].style = ExtractJSONValue(chunks[i], "trade_style");
      g_cached_trades[i].dir = ExtractJSONValue(chunks[i], "direction");
      g_cached_trades[i].sym = ExtractJSONValue(chunks[i], "symbol");
      g_cached_trades[i].be_pips = StringToDouble(ExtractJSONValue(chunks[i], "be_trigger_pips"));
      g_cached_trades[i].be_offset = StringToDouble(ExtractJSONValue(chunks[i], "be_offset_pips"));
      g_cached_trades[i].trail_start = StringToDouble(ExtractJSONValue(chunks[i], "trail_start_pips"));
      g_cached_trades[i].trail_dist = StringToDouble(ExtractJSONValue(chunks[i], "trail_dist_pips"));
      
      if (g_cached_trades[i].v_sl > 0 || g_cached_trades[i].v_tp > 0) {
         DrawIndividualLines(g_cached_trades[i].ticket, g_cached_trades[i].sym, g_cached_trades[i].style, g_cached_trades[i].dir, g_cached_trades[i].v_sl, g_cached_trades[i].v_tp);
      }
   }
}
'''
if 'struct ActiveTradeCache' not in content:
    content = content.replace('//| Fetch New Signals', struct_str + '\n//| Fetch New Signals')

# 2. Add SyncActiveTrades() to OnTimer
if 'SyncActiveTrades();' not in content:
    content = content.replace('SyncSLTPUpdates();', 'SyncSLTPUpdates();\n      SyncActiveTrades();')

# 3. Replace DrawBasketLines with DrawIndividualLines
draw_ind_str = '''void DrawIndividualLines(ulong ticket, string sym, string style, string dir_str, double sl, double tp) {
   string sl_name = "V_SL_" + IntegerToString(ticket);
   string tp_name = "V_TP_" + IntegerToString(ticket);
   
   ChartSetInteger(0, CHART_SHOW_OBJECT_DESCR, true);
   
   if (sl > 0 && ObjectFind(0, sl_name) < 0) {
      ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, sl);
      ObjectSetDouble(0, sl_name, OBJPROP_PRICE, sl);
      ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
      ObjectSetInteger(0, sl_name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, sl_name, OBJPROP_TEXT, style + " " + dir_str + " SL");
   }
   if (tp > 0 && ObjectFind(0, tp_name) < 0) {
      ObjectCreate(0, tp_name, OBJ_HLINE, 0, 0, tp);
      ObjectSetDouble(0, tp_name, OBJPROP_PRICE, tp);
      ObjectSetInteger(0, tp_name, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, tp_name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, tp_name, OBJPROP_TEXT, style + " " + dir_str + " TP");
   }
}'''
content = re.sub(r'void DrawBasketLines.*?\}', draw_ind_str, content, flags=re.DOTALL)

# 4. Replace ManageBaskets() and ProcessBasket() entirely with ManageIndividualTrades
manage_str = '''void ManageIndividualTrades() {
   for(int j = PositionsTotal()-1; j >= 0; j--) {
      if(position.SelectByIndex(j)) {
         ulong tkt = position.Ticket();
         string sym = position.Symbol();
         long pos_type = position.PositionType();
         
         int cache_idx = -1;
         for(int k=0; k<ArraySize(g_cached_trades); k++) {
            if(g_cached_trades[k].ticket == tkt) { cache_idx = k; break; }
         }
         
         if (cache_idx == -1) continue;
         
         double v_sl = g_cached_trades[cache_idx].v_sl;
         double v_tp = g_cached_trades[cache_idx].v_tp;
         string style = g_cached_trades[cache_idx].style;
         string dir_str = g_cached_trades[cache_idx].dir;
         double be_p = g_cached_trades[cache_idx].be_pips;
         double be_o = g_cached_trades[cache_idx].be_offset;
         double ts_p = g_cached_trades[cache_idx].trail_start;
         double td_p = g_cached_trades[cache_idx].trail_dist;
         
         double current_price = (pos_type == POSITION_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
         double open_price = position.PriceOpen();
         double pip_size = (StringFind(sym, "JPY") != -1 || StringFind(sym, "XAU") != -1) ? 0.01 : 0.0001;
         
         string tr_name = "V_TR_" + IntegerToString(tkt);
         double v_tr = 0;
         if (ObjectFind(0, tr_name) >= 0) v_tr = ObjectGetDouble(0, tr_name, OBJPROP_PRICE);
         
         bool hit = false;
         string close_reason = "";
         
         if (pos_type == POSITION_TYPE_BUY) {
            if (v_sl > 0 && current_price <= v_sl) { hit = true; close_reason = "Virtual SL Hit"; }
            else if (v_tp > 0 && current_price >= v_tp) { hit = true; close_reason = "Virtual TP Hit"; }
            else if (v_tr > 0 && current_price <= v_tr) { hit = true; close_reason = "Virtual BE/Trailing Hit"; }
         } else {
            if (v_sl > 0 && current_price >= v_sl) { hit = true; close_reason = "Virtual SL Hit"; }
            else if (v_tp > 0 && current_price <= v_tp) { hit = true; close_reason = "Virtual TP Hit"; }
            else if (v_tr > 0 && current_price >= v_tr) { hit = true; close_reason = "Virtual BE/Trailing Hit"; }
         }
         
         if (hit) {
            double lot_close = position.Volume();
            if (trade.PositionClose(tkt)) {
               Sleep(200);
               double final_pl = 0;
               if(HistorySelect(TimeCurrent()-86400, TimeCurrent()+86400)) {
                  int deals_total = HistoryDealsTotal();
                  for(int d = deals_total-1; d >= 0; d--) {
                     ulong deal_ticket = HistoryDealGetTicket(d);
                     if(HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID) == tkt && HistoryDealGetInteger(deal_ticket, DEAL_ENTRY) == DEAL_ENTRY_OUT) {
                        final_pl = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT) + HistoryDealGetDouble(deal_ticket, DEAL_SWAP) + HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
                        break;
                     }
                  }
               }
               if(final_pl == 0) final_pl = position.Profit() + position.Swap() + position.Commission();
               
               string payload = "{\\"ticket\\":" + IntegerToString(tkt) + ",\\"account_id\\":\\"" + InpAccountID + "\\",\\"symbol\\":\\"" + sym + "\\",\\"direction\\":\\"" + dir_str + "\\",\\"lot\\":" + DoubleToString(lot_close, 2) + ",\\"trade_style\\":\\"" + style + "\\",\\"pnl\\":" + DoubleToString(final_pl, 2) + ",\\"close_reason\\":\\"" + close_reason + "\\"}";
               SupabasePOST("/rest/v1/closed_trades", payload);
               SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(tkt), "{\\"exit_reason\\":\\"" + close_reason + "\\",\\"current_status\\":\\"CLOSED\\"}");
               
               ObjectDelete(0, "V_SL_" + IntegerToString(tkt));
               ObjectDelete(0, "V_TP_" + IntegerToString(tkt));
               ObjectDelete(0, tr_name);
            }
            continue;
         }
         
         bool updated_tr = false;
         if (pos_type == POSITION_TYPE_BUY) {
            double profit_pips = (current_price - open_price) / pip_size;
            if (be_p > 0 && profit_pips >= be_p && (v_tr < open_price || v_tr == 0)) {
               v_tr = open_price + (be_o * pip_size);
               updated_tr = true;
            }
            if (ts_p > 0 && profit_pips >= ts_p) {
               double new_tr = current_price - (td_p * pip_size);
               if (v_tr == 0 || new_tr > v_tr) {
                  v_tr = new_tr;
                  updated_tr = true;
               }
            }
         } else {
            double profit_pips = (open_price - current_price) / pip_size;
            if (be_p > 0 && profit_pips >= be_p && (v_tr > open_price || v_tr == 0)) {
               v_tr = open_price - (be_o * pip_size);
               updated_tr = true;
            }
            if (ts_p > 0 && profit_pips >= ts_p) {
               double new_tr = current_price + (td_p * pip_size);
               if (v_tr == 0 || new_tr < v_tr) {
                  v_tr = new_tr;
                  updated_tr = true;
               }
            }
         }
         
         if (updated_tr) {
            if (ObjectFind(0, tr_name) < 0) {
               ObjectCreate(0, tr_name, OBJ_HLINE, 0, 0, v_tr);
               ObjectSetInteger(0, tr_name, OBJPROP_COLOR, clrOrange);
               ObjectSetInteger(0, tr_name, OBJPROP_STYLE, STYLE_DASH);
               ObjectSetString(0, tr_name, OBJPROP_TEXT, style + " " + dir_str + " TRAIL/BE");
            }
            ObjectSetDouble(0, tr_name, OBJPROP_PRICE, v_tr);
            SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(tkt), "{\\"virtual_sl\\":" + DoubleToString(v_tr, 5) + "}");
            g_cached_trades[cache_idx].v_sl = v_tr;
         }
      }
   }
}'''

content = re.sub(r'void ManageBaskets\(\) \{.*?(?=void ProcessGridRecovery)', manage_str + '\n\n', content, flags=re.DOTALL)
content = content.replace('ManageBaskets();', 'ManageIndividualTrades();')
content = content.replace('void ManageBaskets();', 'void ManageIndividualTrades();')
content = content.replace('void ProcessBasket(string sym, ulong mag, string style_str, ENUM_POSITION_TYPE pos_type);', '')
content = content.replace('DrawBasketLines', 'DrawIndividualLines')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Script finished successfully!')

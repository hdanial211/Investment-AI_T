import sys

path = r'E:\PROJECTS\SAHAM\Investment-AI_T_latest\MQL5\Experts\InvestmentAI_Executor.mq5'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add ManageManualBaskets(); to OnTick
if 'ManageManualBaskets();' not in content:
    content = content.replace('   ManageIndividualTrades();', '   ManageIndividualTrades();\n   ManageManualBaskets();')

# 2. Add continue if MANUAL_ in ManageIndividualTrades
target = 'if (cache_idx == -1) continue;'
replacement = 'if (cache_idx == -1) continue;\n         if (StringFind(g_cached_trades[cache_idx].style, "MANUAL_") == 0) continue;'
if 'StringFind(g_cached_trades[cache_idx].style, "MANUAL_") == 0' not in content:
    content = content.replace(target, replacement)

# 3. Add ManageManualBaskets function definition
new_func = """
void ManageManualBaskets() {
   string processed_baskets[];
   int p_count = 0;
   
   for(int j = PositionsTotal()-1; j >= 0; j--) {
      if(position.SelectByIndex(j)) {
         ulong tkt = position.Ticket();
         string sym = position.Symbol();
         long pos_type = position.PositionType();
         string dir_str = (pos_type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
         
         int cache_idx = -1;
         for(int k=0; k<ArraySize(g_cached_trades); k++) {
            if(g_cached_trades[k].ticket == tkt) { cache_idx = k; break; }
         }
         if (cache_idx == -1) continue;
         
         string style = g_cached_trades[cache_idx].style;
         if (StringFind(style, "MANUAL_") != 0) continue;
         
         string basket_id = sym + "_" + dir_str;
         bool already_processed = false;
         for(int p=0; p<p_count; p++) {
            if (processed_baskets[p] == basket_id) { already_processed = true; break; }
         }
         if (already_processed) continue;
         
         ArrayResize(processed_baskets, p_count+1);
         processed_baskets[p_count] = basket_id;
         p_count++;
         
         double total_vol = 0;
         double total_value = 0;
         double avg_v_sl = 0;
         double avg_v_tp = 0;
         int ticket_count = 0;
         double be_p = 0, be_o = 0, ts_p = 0, td_p = 0;
         
         ulong basket_tickets[];
         int bt_count = 0;
         
         for(int m = PositionsTotal()-1; m >= 0; m--) {
            if(position.SelectByIndex(m)) {
               if (position.Symbol() == sym && position.PositionType() == pos_type) {
                  ulong mtkt = position.Ticket();
                  int c_idx = -1;
                  for(int k=0; k<ArraySize(g_cached_trades); k++) {
                     if(g_cached_trades[k].ticket == mtkt) { c_idx = k; break; }
                  }
                  if (c_idx != -1 && StringFind(g_cached_trades[c_idx].style, "MANUAL_") == 0) {
                     total_vol += position.Volume();
                     total_value += position.PriceOpen() * position.Volume();
                     avg_v_sl += g_cached_trades[c_idx].v_sl;
                     avg_v_tp += g_cached_trades[c_idx].v_tp;
                     ticket_count++;
                     
                     ArrayResize(basket_tickets, bt_count+1);
                     basket_tickets[bt_count] = mtkt;
                     bt_count++;
                     
                     if (be_p == 0) { 
                        be_p = g_cached_trades[c_idx].be_pips;
                        be_o = g_cached_trades[c_idx].be_offset;
                        ts_p = g_cached_trades[c_idx].trail_start;
                        td_p = g_cached_trades[c_idx].trail_dist;
                     }
                  }
               }
            }
         }
         
         if (ticket_count > 0 && total_vol > 0) {
            double avg_price = total_value / total_vol;
            avg_v_sl /= ticket_count;
            avg_v_tp /= ticket_count;
            
            string sl_name = "B_SL_MANUAL_" + basket_id;
            string tp_name = "B_TP_MANUAL_" + basket_id;
            string tr_name = "B_TR_MANUAL_" + basket_id;
            
            double current_price = (pos_type == POSITION_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
            double pip_size = (StringFind(sym, "JPY") != -1 || StringFind(sym, "XAU") != -1) ? 0.01 : 0.0001;
            
            if (avg_v_sl > 0) {
               if (ObjectFind(0, sl_name) < 0) ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, avg_v_sl);
               ObjectSetDouble(0, sl_name, OBJPROP_PRICE, avg_v_sl);
               ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
               ObjectSetString(0, sl_name, OBJPROP_TEXT, "MANUAL " + dir_str + " SL");
            }
            if (avg_v_tp > 0) {
               if (ObjectFind(0, tp_name) < 0) ObjectCreate(0, tp_name, OBJ_HLINE, 0, 0, avg_v_tp);
               ObjectSetDouble(0, tp_name, OBJPROP_PRICE, avg_v_tp);
               ObjectSetInteger(0, tp_name, OBJPROP_COLOR, clrLimeGreen);
               ObjectSetString(0, tp_name, OBJPROP_TEXT, "MANUAL " + dir_str + " TP");
            }
            
            double b_tr = 0;
            if (ObjectFind(0, tr_name) >= 0) b_tr = ObjectGetDouble(0, tr_name, OBJPROP_PRICE);
            
            double profit_pips = 0;
            if (pos_type == POSITION_TYPE_BUY) profit_pips = (current_price - avg_price) / pip_size;
            else profit_pips = (avg_price - current_price) / pip_size;
            
            double new_tr = 0;
            if (ts_p > 0 && td_p > 0 && profit_pips >= ts_p) {
               if (pos_type == POSITION_TYPE_BUY) new_tr = current_price - (td_p * pip_size);
               else new_tr = current_price + (td_p * pip_size);
               
               if (b_tr == 0 || (pos_type == POSITION_TYPE_BUY && new_tr > b_tr) || (pos_type == POSITION_TYPE_SELL && new_tr < b_tr)) {
                  b_tr = new_tr;
                  if (ObjectFind(0, tr_name) < 0) ObjectCreate(0, tr_name, OBJ_HLINE, 0, 0, b_tr);
                  ObjectSetDouble(0, tr_name, OBJPROP_PRICE, b_tr);
                  ObjectSetInteger(0, tr_name, OBJPROP_COLOR, clrGold);
                  ObjectSetString(0, tr_name, OBJPROP_TEXT, "MANUAL " + dir_str + " TRAIL");
               }
            } else if (b_tr == 0 && be_p > 0 && be_o > 0 && profit_pips >= be_p) {
               if (pos_type == POSITION_TYPE_BUY) new_tr = avg_price + (be_o * pip_size);
               else new_tr = avg_price - (be_o * pip_size);
               b_tr = new_tr;
               if (ObjectFind(0, tr_name) < 0) ObjectCreate(0, tr_name, OBJ_HLINE, 0, 0, b_tr);
               ObjectSetDouble(0, tr_name, OBJPROP_PRICE, b_tr);
               ObjectSetInteger(0, tr_name, OBJPROP_COLOR, clrGold);
               ObjectSetString(0, tr_name, OBJPROP_TEXT, "MANUAL " + dir_str + " BE");
            }
            
            bool hit = false;
            string close_reason = "";
            if (pos_type == POSITION_TYPE_BUY) {
               if (avg_v_sl > 0 && current_price <= avg_v_sl) { hit = true; close_reason = "Basket SL Hit"; }
               else if (avg_v_tp > 0 && current_price >= avg_v_tp) { hit = true; close_reason = "Basket TP Hit"; }
               else if (b_tr > 0 && current_price <= b_tr) { hit = true; close_reason = "Basket BE/Trailing Hit"; }
            } else {
               if (avg_v_sl > 0 && current_price >= avg_v_sl) { hit = true; close_reason = "Basket SL Hit"; }
               else if (avg_v_tp > 0 && current_price <= avg_v_tp) { hit = true; close_reason = "Basket TP Hit"; }
               else if (b_tr > 0 && current_price >= b_tr) { hit = true; close_reason = "Basket BE/Trailing Hit"; }
            }
            
            if (hit) {
               for(int m=0; m<bt_count; m++) {
                  CloseTradeWithReason(basket_tickets[m], close_reason);
               }
               ObjectDelete(0, sl_name);
               ObjectDelete(0, tp_name);
               ObjectDelete(0, tr_name);
            }
         }
      }
   }
}
"""

if 'void ManageManualBaskets()' not in content:
    content += "\n" + new_func

# 4. Add declaration at top if needed
if 'void ManageManualBaskets();' not in content:
    content = content.replace('void ManageIndividualTrades();', 'void ManageIndividualTrades();\nvoid ManageManualBaskets();')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("MQL5 patch applied successfully.")

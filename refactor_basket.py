import re

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace DrawVirtualLines
draw_lines_old = r"""void DrawVirtualLines\(ulong ticket, double sl, double tp\) \{
   string sl_name = "V_SL_" \+ IntegerToString\(ticket\);
   string tp_name = "V_TP_" \+ IntegerToString\(ticket\);
   
   ObjectCreate\(0, sl_name, OBJ_HLINE, 0, 0, sl\);
   ObjectSetInteger\(0, sl_name, OBJPROP_COLOR, clrRed\);
   ObjectSetInteger\(0, sl_name, OBJPROP_STYLE, STYLE_DASH\);
   
   ObjectCreate\(0, tp_name, OBJ_HLINE, 0, 0, tp\);
   ObjectSetInteger\(0, tp_name, OBJPROP_COLOR, clrLimeGreen\);
   ObjectSetInteger\(0, tp_name, OBJPROP_STYLE, STYLE_SOLID\);
\}"""

draw_lines_new = """void DrawVirtualLines(ulong ticket, double sl, double tp) {
   // Deprecated for individual trades. Use Basket lines instead.
}

void DrawBasketLines(string style, string dir_str, string sym, double sl, double tp) {
   string sl_name = "B_SL_" + style + "_" + dir_str + "_" + sym;
   string tp_name = "B_TP_" + style + "_" + dir_str + "_" + sym;
   
   if (sl > 0) {
      ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, sl);
      ObjectSetDouble(0, sl_name, OBJPROP_PRICE, sl);
      ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
      ObjectSetInteger(0, sl_name, OBJPROP_STYLE, STYLE_DASH);
   }
   if (tp > 0) {
      ObjectCreate(0, tp_name, OBJ_HLINE, 0, 0, tp);
      ObjectSetDouble(0, tp_name, OBJPROP_PRICE, tp);
      ObjectSetInteger(0, tp_name, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, tp_name, OBJPROP_STYLE, STYLE_SOLID);
   }
}"""
content = re.sub(draw_lines_old, draw_lines_new, content, flags=re.DOTALL)


# 2. Update ExecuteTrade
exec_trade_old = r"""      SupabasePOST\("/rest/v1/active_trades", payload\);
      
      DrawVirtualLines\(ticket, virtual_sl, virtual_tp\);"""
exec_trade_new = """      SupabasePOST("/rest/v1/active_trades", payload);
      
      string dir_str = (action == "BUY") ? "BUY" : "SELL";
      DrawBasketLines(style, dir_str, sym, virtual_sl, virtual_tp);"""
content = re.sub(exec_trade_old, exec_trade_new, content, flags=re.DOTALL)


# 3. Update RestoreVirtualLines
restore_old = r"""      long ticket = StringToInteger\(ExtractJSONValue\(chunks\[i\], "ticket"\)\);
      double v_sl = StringToDouble\(ExtractJSONValue\(chunks\[i\], "virtual_sl"\)\);
      double v_tp = StringToDouble\(ExtractJSONValue\(chunks\[i\], "virtual_tp"\)\);
      
      if \(ticket > 0 && \(v_sl > 0 \|\| v_tp > 0\)\) \{
         DrawVirtualLines\(ticket, v_sl, v_tp\);
         Print\("Restored Virtual SL/TP for ticket: ", ticket\);
      \}"""

restore_new = """      long ticket = StringToInteger(ExtractJSONValue(chunks[i], "ticket"));
      double v_sl = StringToDouble(ExtractJSONValue(chunks[i], "virtual_sl"));
      double v_tp = StringToDouble(ExtractJSONValue(chunks[i], "virtual_tp"));
      string style = ExtractJSONValue(chunks[i], "trade_style");
      string dir_str = ExtractJSONValue(chunks[i], "direction");
      string sym = ExtractJSONValue(chunks[i], "symbol");
      
      if (ticket > 0 && (v_sl > 0 || v_tp > 0) && style != "") {
         DrawBasketLines(style, dir_str, sym, v_sl, v_tp);
         Print("Restored Basket Virtual SL/TP for: ", style, " ", dir_str, " ", sym);
      }"""
content = re.sub(restore_old, restore_new, content, flags=re.DOTALL)


# 4. Replace OnTick completely up to ProcessGridRecovery
ontick_old_pattern = r"void OnTick\(\) \{.*?\} // End of OnTick loop" # We don't have that end comment.
# I'll just use string find for OnTick() and ProcessGridRecovery
idx_ontick = content.find("void OnTick()")
idx_grid = content.find("void ProcessGridRecovery()")

new_ontick = """void ManageBaskets();
void ProcessBasket(string sym, ulong mag, string style_str, ENUM_POSITION_TYPE pos_type);

void OnTick() {
   ProcessGridRecovery();
   ManageBaskets();
   
   // Clean up orphaned virtual lines for closed trades
   int total_objs = ObjectsTotal(0);
   for (int i = total_objs - 1; i >= 0; i--) {
      string obj_name = ObjectName(0, i);
      if (StringFind(obj_name, "V_SL_") == 0 || StringFind(obj_name, "V_TP_") == 0) {
         string ticket_str = StringSubstr(obj_name, 5);
         long ticket = StringToInteger(ticket_str);
         if (ticket > 0 && !PositionSelectByTicket(ticket)) {
            ObjectDelete(0, obj_name);
         }
      }
   }
}

void ManageBaskets() {
   for(int m = 1; m <= 3; m++) {
      ulong mag = InpMagicNumber + m;
      string style_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
      
      string symbols[];
      int sym_count = 0;
      for(int j = 0; j < PositionsTotal(); j++) {
         if(position.SelectByIndex(j) && position.Magic() == mag) {
            bool found = false;
            for(int k=0; k<sym_count; k++) { if(symbols[k] == position.Symbol()) { found = true; break; } }
            if(!found) {
               ArrayResize(symbols, sym_count+1);
               symbols[sym_count] = position.Symbol();
               sym_count++;
            }
         }
      }
      
      for(int k=0; k<sym_count; k++) {
         string sym = symbols[k];
         ProcessBasket(sym, mag, style_str, POSITION_TYPE_BUY);
         ProcessBasket(sym, mag, style_str, POSITION_TYPE_SELL);
      }
   }
}

void ProcessBasket(string sym, ulong mag, string style_str, ENUM_POSITION_TYPE pos_type) {
   double total_vol = 0;
   double total_cost = 0;
   int ticket_count = 0;
   
   for(int j = 0; j < PositionsTotal(); j++) {
      if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == pos_type) {
         total_vol += position.Volume();
         total_cost += position.Volume() * position.PriceOpen();
         ticket_count++;
      }
   }
   
   string dir_str = (pos_type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   string sl_name = "B_SL_" + style_str + "_" + dir_str + "_" + sym;
   string tp_name = "B_TP_" + style_str + "_" + dir_str + "_" + sym;
   
   if (ticket_count == 0) {
      ObjectsDeleteAll(0, sl_name);
      ObjectsDeleteAll(0, tp_name);
      return;
   }
   
   double avg_price = total_cost / total_vol;
   double current_price = (pos_type == POSITION_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
   
   double b_sl = ObjectGetDouble(0, sl_name, OBJPROP_PRICE);
   double b_tp = ObjectGetDouble(0, tp_name, OBJPROP_PRICE);
   
   bool hit = false;
   string close_reason = "";
   if (pos_type == POSITION_TYPE_BUY) {
      if (b_sl > 0 && current_price <= b_sl) { hit = true; close_reason = "Basket SL Hit"; }
      if (b_tp > 0 && current_price >= b_tp) { hit = true; close_reason = "Basket TP Hit"; }
   } else {
      if (b_sl > 0 && current_price >= b_sl) { hit = true; close_reason = "Basket SL Hit"; }
      if (b_tp > 0 && current_price <= b_tp) { hit = true; close_reason = "Basket TP Hit"; }
   }
   
   if (hit) {
      for(int j = PositionsTotal()-1; j >= 0; j--) {
         if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == pos_type) {
            ulong tkt = position.Ticket();
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
               
               string payload = "{\\"ticket\\":" + IntegerToString(tkt) + ",\\"account_id\\":\\"" + InpAccountID + "\\",\\"symbol\\":\\"" + sym + "\\",\\"direction\\":\\"" + dir_str + "\\",\\"lot\\":" + DoubleToString(lot_close, 2) + ",\\"trade_style\\":\\"" + style_str + "\\",\\"pnl\\":" + DoubleToString(final_pl, 2) + ",\\"close_reason\\":\\"" + close_reason + "\\"}";
               SupabasePOST("/rest/v1/closed_trades", payload);
               SupabaseDELETE("/rest/v1/active_trades?ticket=eq." + IntegerToString(tkt));
            }
         }
      }
      ObjectsDeleteAll(0, sl_name);
      ObjectsDeleteAll(0, tp_name);
      return;
   }
   
   double style_be_trigger = 0;
   double style_trail_start = 0;
   double style_trail_dist = 0;
   
   if (style_str == "SCALPING") { style_be_trigger = g_scalping_be_trigger; style_trail_start = g_scalping_trail_start; style_trail_dist = g_scalping_trail_dist; }
   else if (style_str == "INTRADAY") { style_be_trigger = g_intraday_be_trigger; style_trail_start = g_intraday_trail_start; style_trail_dist = g_intraday_trail_dist; }
   else if (style_str == "SWING") { style_be_trigger = g_swing_be_trigger; style_trail_start = g_swing_trail_start; style_trail_dist = g_swing_trail_dist; }
   
   double atr_value = 0.0010;
   if(g_atr_handle != INVALID_HANDLE) { double atr_arr[]; CopyBuffer(g_atr_handle, 0, 1, 1, atr_arr); if(ArraySize(atr_arr) > 0) atr_value = atr_arr[0]; }
   double pip_size = (StringFind(sym, "JPY") != -1 || StringFind(sym, "XAU") != -1) ? 0.01 : 0.0001;
   
   double be_trigger_price_dist = style_be_trigger * atr_value;
   double trail_start_price_dist = style_trail_start * atr_value;
   double trail_dist_price = style_trail_dist * atr_value;
   
   bool updated_sl = false;
   if (pos_type == POSITION_TYPE_BUY) {
      double profit_dist = current_price - avg_price;
      if (profit_dist >= be_trigger_price_dist && (b_sl < avg_price || b_sl == 0)) { b_sl = avg_price + (pip_size * 2); updated_sl = true; }
      if (profit_dist >= trail_start_price_dist) {
         double new_sl = current_price - trail_dist_price;
         if (b_sl == 0 || new_sl > b_sl) { b_sl = new_sl; updated_sl = true; }
      }
   } else {
      double profit_dist = avg_price - current_price;
      if (profit_dist >= be_trigger_price_dist && (b_sl > avg_price || b_sl == 0)) { b_sl = avg_price - (pip_size * 2); updated_sl = true; }
      if (profit_dist >= trail_start_price_dist) {
         double new_sl = current_price + trail_dist_price;
         if (new_sl < b_sl || b_sl == 0) { b_sl = new_sl; updated_sl = true; }
      }
   }
   
   if (updated_sl || ObjectFind(0, sl_name) < 0) {
      if (b_sl > 0) {
         ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, b_sl);
         ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
         ObjectSetInteger(0, sl_name, OBJPROP_STYLE, STYLE_DASH);
         ObjectSetDouble(0, sl_name, OBJPROP_PRICE, b_sl);
         if (updated_sl) {
            for(int j = 0; j < PositionsTotal(); j++) {
               if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == pos_type) {
                  SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(position.Ticket()), "{\\"virtual_sl\\":" + DoubleToString(b_sl, 5) + "}");
               }
            }
         }
      }
   }
}
"""

content = content[:idx_ontick] + new_ontick + "\n" + content[idx_grid:]

# 5. Fix ProcessGridRecovery to read Basket SL/TP instead of individual
grid_sl_old = r"""                  if \(grid_v_sl_buy == 0 && grid_v_tp_buy == 0\) \{
                     grid_v_sl_buy = ObjectGetDouble\(0, "V_SL_" \+ IntegerToString\(position\.Ticket\(\)\), OBJPROP_PRICE\);
                     grid_v_tp_buy = ObjectGetDouble\(0, "V_TP_" \+ IntegerToString\(position\.Ticket\(\)\), OBJPROP_PRICE\);
                  \}"""
grid_sl_new = """                  if (grid_v_sl_buy == 0 && grid_v_tp_buy == 0) {
                     string s_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                     grid_v_sl_buy = ObjectGetDouble(0, "B_SL_" + s_str + "_BUY_" + sym, OBJPROP_PRICE);
                     grid_v_tp_buy = ObjectGetDouble(0, "B_TP_" + s_str + "_BUY_" + sym, OBJPROP_PRICE);
                  }"""
content = re.sub(grid_sl_old, grid_sl_new, content, flags=re.DOTALL)

grid_sl_sell_old = r"""                  if \(grid_v_sl_sell == 0 && grid_v_tp_sell == 0\) \{
                     grid_v_sl_sell = ObjectGetDouble\(0, "V_SL_" \+ IntegerToString\(position\.Ticket\(\)\), OBJPROP_PRICE\);
                     grid_v_tp_sell = ObjectGetDouble\(0, "V_TP_" \+ IntegerToString\(position\.Ticket\(\)\), OBJPROP_PRICE\);
                  \}"""
grid_sl_sell_new = """                  if (grid_v_sl_sell == 0 && grid_v_tp_sell == 0) {
                     string s_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                     grid_v_sl_sell = ObjectGetDouble(0, "B_SL_" + s_str + "_SELL_" + sym, OBJPROP_PRICE);
                     grid_v_tp_sell = ObjectGetDouble(0, "B_TP_" + s_str + "_SELL_" + sym, OBJPROP_PRICE);
                  }"""
content = re.sub(grid_sl_sell_old, grid_sl_sell_new, content, flags=re.DOTALL)


# 6. Update SyncSLTPUpdates in OnTimer
sync_old = r"""      if \(ticket > 0\) \{
         if \(PositionSelectByTicket\(ticket\)\) \{
            double v_sl = ObjectGetDouble\(0, "V_SL_" \+ IntegerToString\(ticket\), OBJPROP_PRICE\);
            double v_tp = ObjectGetDouble\(0, "V_TP_" \+ IntegerToString\(ticket\), OBJPROP_PRICE\);"""

sync_new = """      if (ticket > 0) {
         if (PositionSelectByTicket(ticket)) {
            ulong mag = PositionGetInteger(POSITION_MAGIC);
            int m = (int)(mag - InpMagicNumber);
            string style_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
            string dir_str = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            string sym = PositionGetString(POSITION_SYMBOL);
            
            double v_sl = ObjectGetDouble(0, "B_SL_" + style_str + "_" + dir_str + "_" + sym, OBJPROP_PRICE);
            double v_tp = ObjectGetDouble(0, "B_TP_" + style_str + "_" + dir_str + "_" + sym, OBJPROP_PRICE);"""
content = re.sub(sync_old, sync_new, content, flags=re.DOTALL)

sync_draw_old = r"""            if \(sl_tighter \|\| tp_tighter\) \{
               DrawVirtualLines\(ticket, final_sl, final_tp\);
               SupabasePATCH\("/rest/v1/active_trades\?ticket=eq\." \+ IntegerToString\(ticket\), "\{\\"virtual_sl\\":" \+ DoubleToString\(final_sl, 5\) \+ ",\\"virtual_tp\\":" \+ DoubleToString\(final_tp, 5\) \+ "\}"\);
            \}"""
sync_draw_new = """            if (sl_tighter || tp_tighter) {
               DrawBasketLines(style_str, dir_str, sym, final_sl, final_tp);
               // Update all tickets in basket
               for(int j = 0; j < PositionsTotal(); j++) {
                  if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == PositionGetInteger(POSITION_TYPE)) {
                     SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(position.Ticket()), "{\\"virtual_sl\\":" + DoubleToString(final_sl, 5) + ",\\"virtual_tp\\":" + DoubleToString(final_tp, 5) + "}");
                  }
               }
            }"""
content = re.sub(sync_draw_old, sync_draw_new, content, flags=re.DOTALL)

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "w", encoding="utf-8") as f:
    f.write(content)
print("Done refactoring MQL5!")

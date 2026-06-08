import re

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update DrawBasketLines to set OBJPROP_TEXT and support colors
draw_basket_old = r"""void DrawBasketLines\(string style, string dir_str, string sym, double sl, double tp\) \{
   string sl_name = "B_SL_" \+ style \+ "_" \+ dir_str \+ "_" \+ sym;
   string tp_name = "B_TP_" \+ style \+ "_" \+ dir_str \+ "_" \+ sym;
   
   if \(sl > 0\) \{
      ObjectCreate\(0, sl_name, OBJ_HLINE, 0, 0, sl\);
      ObjectSetDouble\(0, sl_name, OBJPROP_PRICE, sl\);
      ObjectSetInteger\(0, sl_name, OBJPROP_COLOR, clrRed\);
      ObjectSetInteger\(0, sl_name, OBJPROP_STYLE, STYLE_DASH\);
   \}
   if \(tp > 0\) \{
      ObjectCreate\(0, tp_name, OBJ_HLINE, 0, 0, tp\);
      ObjectSetDouble\(0, tp_name, OBJPROP_PRICE, tp\);
      ObjectSetInteger\(0, tp_name, OBJPROP_COLOR, clrLimeGreen\);
      ObjectSetInteger\(0, tp_name, OBJPROP_STYLE, STYLE_SOLID\);
   \}
\}"""

draw_basket_new = """void DrawBasketLines(string style, string dir_str, string sym, double sl, double tp) {
   string sl_name = "B_SL_" + style + "_" + dir_str + "_" + sym;
   string tp_name = "B_TP_" + style + "_" + dir_str + "_" + sym;
   
   ChartSetInteger(0, CHART_SHOW_OBJECT_DESCR, true); // Ensure descriptions are shown
   
   if (sl > 0 && ObjectFind(0, sl_name) < 0) {
      ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, sl);
      ObjectSetDouble(0, sl_name, OBJPROP_PRICE, sl);
      ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
      ObjectSetInteger(0, sl_name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, sl_name, OBJPROP_TEXT, style + " " + dir_str + " SL (Fixed)");
   }
   if (tp > 0 && ObjectFind(0, tp_name) < 0) {
      ObjectCreate(0, tp_name, OBJ_HLINE, 0, 0, tp);
      ObjectSetDouble(0, tp_name, OBJPROP_PRICE, tp);
      ObjectSetInteger(0, tp_name, OBJPROP_COLOR, clrLimeGreen);
      ObjectSetInteger(0, tp_name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, tp_name, OBJPROP_TEXT, style + " " + dir_str + " TP");
   }
}"""
content = re.sub(draw_basket_old, draw_basket_new, content, flags=re.DOTALL)


# 2. Update ProcessBasket logic to separate Fixed SL and Trailing
# First, let's find the string replacement target inside ProcessBasket
process_basket_old = r"""   string sl_name = "B_SL_" \+ style_str \+ "_" \+ dir_str \+ "_" \+ sym;
   string tp_name = "B_TP_" \+ style_str \+ "_" \+ dir_str \+ "_" \+ sym;
   
   if \(ticket_count == 0\) \{
      ObjectsDeleteAll\(0, sl_name\);
      ObjectsDeleteAll\(0, tp_name\);
      return;
   \}
   
   double avg_price = total_cost / total_vol;
   double current_price = \(pos_type == POSITION_TYPE_BUY\) \? SymbolInfoDouble\(sym, SYMBOL_BID\) : SymbolInfoDouble\(sym, SYMBOL_ASK\);
   
   double b_sl = ObjectGetDouble\(0, sl_name, OBJPROP_PRICE\);
   double b_tp = ObjectGetDouble\(0, tp_name, OBJPROP_PRICE\);
   
   bool hit = false;
   string close_reason = "";
   if \(pos_type == POSITION_TYPE_BUY\) \{
      if \(b_sl > 0 && current_price <= b_sl\) \{ hit = true; close_reason = "Basket SL Hit"; \}
      if \(b_tp > 0 && current_price >= b_tp\) \{ hit = true; close_reason = "Basket TP Hit"; \}
   \} else \{
      if \(b_sl > 0 && current_price >= b_sl\) \{ hit = true; close_reason = "Basket SL Hit"; \}
      if \(b_tp > 0 && current_price <= b_tp\) \{ hit = true; close_reason = "Basket TP Hit"; \}
   \}"""

process_basket_new = """   string sl_name = "B_SL_" + style_str + "_" + dir_str + "_" + sym;
   string tp_name = "B_TP_" + style_str + "_" + dir_str + "_" + sym;
   string tr_name = "B_TR_" + style_str + "_" + dir_str + "_" + sym;
   
   if (ticket_count == 0) {
      ObjectsDeleteAll(0, sl_name);
      ObjectsDeleteAll(0, tp_name);
      ObjectsDeleteAll(0, tr_name);
      return;
   }
   
   double avg_price = total_cost / total_vol;
   double current_price = (pos_type == POSITION_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
   
   double b_sl = ObjectGetDouble(0, sl_name, OBJPROP_PRICE);
   double b_tp = ObjectGetDouble(0, tp_name, OBJPROP_PRICE);
   double b_tr = ObjectGetDouble(0, tr_name, OBJPROP_PRICE);
   
   bool hit = false;
   string close_reason = "";
   if (pos_type == POSITION_TYPE_BUY) {
      if (b_sl > 0 && current_price <= b_sl) { hit = true; close_reason = "Basket Fixed SL Hit"; }
      if (b_tp > 0 && current_price >= b_tp) { hit = true; close_reason = "Basket TP Hit"; }
      if (b_tr > 0 && current_price <= b_tr) { hit = true; close_reason = "Basket Trailing Hit"; }
   } else {
      if (b_sl > 0 && current_price >= b_sl) { hit = true; close_reason = "Basket Fixed SL Hit"; }
      if (b_tp > 0 && current_price <= b_tp) { hit = true; close_reason = "Basket TP Hit"; }
      if (b_tr > 0 && current_price >= b_tr) { hit = true; close_reason = "Basket Trailing Hit"; }
   }"""
content = re.sub(process_basket_old, process_basket_new, content, flags=re.DOTALL)


# 3. Update the deletion of lines when hit
close_cleanup_old = r"""      \}
      ObjectsDeleteAll\(0, sl_name\);
      ObjectsDeleteAll\(0, tp_name\);
      return;
   \}"""

close_cleanup_new = """      }
      ObjectsDeleteAll(0, sl_name);
      ObjectsDeleteAll(0, tp_name);
      ObjectsDeleteAll(0, tr_name);
      return;
   }"""
content = re.sub(close_cleanup_old, close_cleanup_new, content, flags=re.DOTALL)


# 4. Update the trailing logic inside ProcessBasket
trail_logic_old = r"""   bool updated_sl = false;
   if \(pos_type == POSITION_TYPE_BUY\) \{
      double profit_dist = current_price - avg_price;
      if \(profit_dist >= be_trigger_price_dist && \(b_sl < avg_price \|\| b_sl == 0\)\) \{ b_sl = avg_price \+ \(pip_size \* 2\); updated_sl = true; \}
      if \(profit_dist >= trail_start_price_dist\) \{
         double new_sl = current_price - trail_dist_price;
         if \(b_sl == 0 \|\| new_sl > b_sl\) \{ b_sl = new_sl; updated_sl = true; \}
      \}
   \} else \{
      double profit_dist = avg_price - current_price;
      if \(profit_dist >= be_trigger_price_dist && \(b_sl > avg_price \|\| b_sl == 0\)\) \{ b_sl = avg_price - \(pip_size \* 2\); updated_sl = true; \}
      if \(profit_dist >= trail_start_price_dist\) \{
         double new_sl = current_price \+ trail_dist_price;
         if \(new_sl < b_sl \|\| b_sl == 0\) \{ b_sl = new_sl; updated_sl = true; \}
      \}
   \}
   
   if \(updated_sl \|\| ObjectFind\(0, sl_name\) < 0\) \{
      if \(b_sl > 0\) \{
         ObjectCreate\(0, sl_name, OBJ_HLINE, 0, 0, b_sl\);
         ObjectSetInteger\(0, sl_name, OBJPROP_COLOR, clrRed\);
         ObjectSetInteger\(0, sl_name, OBJPROP_STYLE, STYLE_DASH\);
         ObjectSetDouble\(0, sl_name, OBJPROP_PRICE, b_sl\);
         if \(updated_sl\) \{
            for\(int j = 0; j < PositionsTotal\(\); j\+\+\) \{
               if\(position\.SelectByIndex\(j\) && position\.Magic\(\) == mag && position\.Symbol\(\) == sym && position\.PositionType\(\) == pos_type\) \{
                  SupabasePATCH\("/rest/v1/active_trades\?ticket=eq\." \+ IntegerToString\(position\.Ticket\(\)\), "\{\\"virtual_sl\\":" \+ DoubleToString\(b_sl, 5\) \+ "\}"\);
               \}
            \}
         \}
      \}
   \}"""

trail_logic_new = """   bool updated_tr = false;
   if (pos_type == POSITION_TYPE_BUY) {
      double profit_dist = current_price - avg_price;
      // BE Trigger
      if (profit_dist >= be_trigger_price_dist && (b_tr < avg_price || b_tr == 0)) { 
         b_tr = avg_price + (pip_size * 2); 
         updated_tr = true; 
      }
      // Trailing
      if (profit_dist >= trail_start_price_dist) {
         double new_tr = current_price - trail_dist_price;
         if (b_tr == 0 || new_tr > b_tr) { 
            b_tr = new_tr; 
            updated_tr = true; 
         }
      }
   } else {
      double profit_dist = avg_price - current_price;
      // BE Trigger
      if (profit_dist >= be_trigger_price_dist && (b_tr > avg_price || b_tr == 0)) { 
         b_tr = avg_price - (pip_size * 2); 
         updated_tr = true; 
      }
      // Trailing
      if (profit_dist >= trail_start_price_dist) {
         double new_tr = current_price + trail_dist_price;
         if (new_tr < b_tr || b_tr == 0) { 
            b_tr = new_tr; 
            updated_tr = true; 
         }
      }
   }
   
   if (updated_tr) {
      if (ObjectFind(0, tr_name) < 0) {
         ObjectCreate(0, tr_name, OBJ_HLINE, 0, 0, b_tr);
         ObjectSetInteger(0, tr_name, OBJPROP_COLOR, clrOrange);
         ObjectSetInteger(0, tr_name, OBJPROP_STYLE, STYLE_DASH);
         ObjectSetString(0, tr_name, OBJPROP_TEXT, style_str + " " + dir_str + " TRAILING");
      }
      ObjectSetDouble(0, tr_name, OBJPROP_PRICE, b_tr);
      
      // Update Supabase active_trades with the trailing stop value so Python knows about it.
      // We will override virtual_sl in Supabase so the dashboard shows the active trailing level.
      for(int j = 0; j < PositionsTotal(); j++) {
         if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == pos_type) {
            SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(position.Ticket()), "{\\"virtual_sl\\":" + DoubleToString(b_tr, 5) + "}");
         }
      }
   }"""
content = re.sub(trail_logic_old, trail_logic_new, content, flags=re.DOTALL)


# 5. Make sure the clean-up loops also clean up old B_TR lines just in case
cleanup_old = r"""      if \(StringFind\(obj_name, "V_SL_"\) == 0 \|\| StringFind\(obj_name, "V_TP_"\) == 0\) \{"""
cleanup_new = """      if (StringFind(obj_name, "V_SL_") == 0 || StringFind(obj_name, "V_TP_") == 0) {"""
# No change needed here, this loop is for orphaned V_SL.

with open("MQL5/Experts/InvestmentAI_Executor.mq5", "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching EA for 3 separate lines and labels!")

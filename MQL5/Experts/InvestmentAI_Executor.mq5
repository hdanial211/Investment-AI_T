//+------------------------------------------------------------------+
//|                                     InvestmentAI_Executor.mq5    |
//|                                  Copyright 2026, Antigravity     |
//|                                        https://investment-ai.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, InvestmentAI"
#property link      "https://investment-ai.com"
#property version   "4.00"
#property description "100% Cloud-Native Stealth Virtual SL/TP EA"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

input string   InpAccountID      = "Ammar";           // Account ID (matches Supabase)
input string   InpSupabaseURL    = "https://kusyjtpcjyflxgfcqenb.supabase.co"; // Supabase URL
input string   InpSupabaseAnon   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt1c3lqdHBjanlmbHhnZmNxZW5iIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk4MDE0NzIsImV4cCI6MjA5NTM3NzQ3Mn0.D8qN-s92JUloY7jb_jwiUnqikRKxHb9Qap9HQod-78g"; // Supabase Anon Key
input ulong    InpMagicNumber    = 888999;            // EA Magic Number

CTrade         trade;
CPositionInfo  position;

// --- Global Settings from Supabase ---
bool     g_scalping_grid_enabled = true;
double   g_scalping_grid_dist = 1.0;
double   g_scalping_grid_mult = 1.5;
int      g_scalping_grid_steps = 3;

bool     g_intraday_grid_enabled = true;
double   g_intraday_grid_dist = 1.5;
double   g_intraday_grid_mult = 1.5;
int      g_intraday_grid_steps = 3;

bool     g_swing_grid_enabled = true;
double   g_swing_grid_dist = 2.0;
double   g_swing_grid_mult = 1.5;
int      g_swing_grid_steps = 3;

double   g_scalping_be_trigger = 1.0;
double   g_scalping_trail_start = 1.5;
double   g_scalping_trail_dist = 0.5;

double   g_intraday_be_trigger = 1.5;
double   g_intraday_trail_start = 2.0;
double   g_intraday_trail_dist = 1.0;

double   g_swing_be_trigger = 2.0;
double   g_swing_trail_start = 3.0;
double   g_swing_trail_dist = 1.5;

int      g_max_total_trades = 5;
double   g_max_daily_drawdown_pct = 5.0;
int      g_min_ai_confidence = 70;
int      g_max_spread_points = 30;

bool     g_block_news = false;
bool     g_block_asia_session = false;
bool     g_allow_hedging = true;

double   g_scalping_lot = 0.01;
double   g_intraday_lot = 0.01;
double   g_swing_lot = 0.01;

bool     g_manage_manual_sl = false;
bool     g_manage_manual_tp = false;
bool     g_manage_manual_be = false;

// --- Timers ---
datetime last_settings_sync = 0;
datetime last_signal_check = 0;
datetime last_heartbeat = 0;
datetime last_sltp_sync = 0;

int g_atr_handle = INVALID_HANDLE;

string   last_processed_signal = "";

//+------------------------------------------------------------------+
//| Simple JSON String Extractor                                     |
//+------------------------------------------------------------------+
string ExtractJSONValue(string json, string key) {
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if (pos == -1) return "";
   pos += StringLen(search);
   
   while(pos < StringLen(json) && (StringSubstr(json, pos, 1) == " " || StringSubstr(json, pos, 1) == "\r" || StringSubstr(json, pos, 1) == "\n")) pos++;
   
   string result = "";
   string firstChar = StringSubstr(json, pos, 1);
   
   if (firstChar == "\"") {
      pos++;
      int endPos = StringFind(json, "\"", pos);
      if (endPos != -1) result = StringSubstr(json, pos, endPos - pos);
   } else {
      int endPos1 = StringFind(json, ",", pos);
      int endPos2 = StringFind(json, "}", pos);
      int endPos = endPos1;
      if (endPos1 == -1 || (endPos2 != -1 && endPos2 < endPos1)) endPos = endPos2;
      
      if (endPos != -1) {
         result = StringSubstr(json, pos, endPos - pos);
         StringReplace(result, " ", "");
         StringReplace(result, "\r", "");
         StringReplace(result, "\n", "");
      }
   }
   return result;
}

//+------------------------------------------------------------------+
//| HTTP GET Wrapper                                                 |
//+------------------------------------------------------------------+
string SupabaseGET(string endpoint) {
   string headers = "apikey: " + InpSupabaseAnon + "\r\nAuthorization: Bearer " + InpSupabaseAnon + "\r\nAccept: application/json\r\n";
   char post[], result[];
   string result_headers;
   string url = InpSupabaseURL + endpoint;
   
   int res = WebRequest("GET", url, headers, 5000, post, result, result_headers);
   if (res == 200) {
      return CharArrayToString(result);
   }
   Print("WebRequest GET failed! Error: ", GetLastError(), " HTTP Code: ", res);
   return "";
}

//+------------------------------------------------------------------+
//| HTTP POST Wrapper                                                |
//+------------------------------------------------------------------+
bool SupabasePOST(string endpoint, string payload) {
   string headers = "apikey: " + InpSupabaseAnon + "\r\nAuthorization: Bearer " + InpSupabaseAnon + "\r\nContent-Type: application/json\r\nPrefer: return=minimal\r\n";
   char post[], result[];
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   
   // Remove null terminator at the end of the array size
   ArrayResize(post, ArraySize(post)-1); 
   
   string result_headers;
   string url = InpSupabaseURL + endpoint;
   
   int res = WebRequest("POST", url, headers, 5000, post, result, result_headers);
   if (res == 200 || res == 201 || res == 204) {
      return true;
   }
   Print("WebRequest POST failed! Error: ", GetLastError(), " HTTP Code: ", res);
   return false;
}

//+------------------------------------------------------------------+
//| HTTP PATCH Wrapper                                               |
//+------------------------------------------------------------------+
bool SupabasePATCH(string endpoint, string payload) {
   string headers = "apikey: " + InpSupabaseAnon + "\r\nAuthorization: Bearer " + InpSupabaseAnon + "\r\nContent-Type: application/json\r\nPrefer: return=minimal\r\n";
   char post[], result[];
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post)-1);
   string result_headers;
   string url = InpSupabaseURL + endpoint;
   
   int res = WebRequest("PATCH", url, headers, 5000, post, result, result_headers);
   if (res == 200 || res == 204) {
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| HTTP DELETE Wrapper                                              |
//+------------------------------------------------------------------+
bool SupabaseDELETE(string endpoint) {
   string headers = "apikey: " + InpSupabaseAnon + "\r\nAuthorization: Bearer " + InpSupabaseAnon + "\r\n";
   char post[], result[];
   string result_headers;
   string url = InpSupabaseURL + endpoint;
   
   int res = WebRequest("DELETE", url, headers, 5000, post, result, result_headers);
   if (res == 200 || res == 204) {
      return true;
   }
   Print("WebRequest DELETE failed! Error: ", GetLastError(), " HTTP Code: ", res);
   return false;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit() {
   Print("Initializing InvestmentAI Executor for Account: ", InpAccountID);
   trade.SetExpertMagicNumber(InpMagicNumber);
   
   if (!SyncAccountSettings()) {
      Print("Failed to fetch account settings. Halting initialization.");
      return INIT_FAILED;
   }
   
   RestoreVirtualLines();
   
   g_atr_handle = iATR(_Symbol, PERIOD_H1, 14);
   
   EventSetTimer(1); // 1-second timer for polling tasks
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   EventKillTimer();
   if(g_atr_handle != INVALID_HANDLE) {
      IndicatorRelease(g_atr_handle);
   }
   ObjectsDeleteAll(0, "V_SL_");
   ObjectsDeleteAll(0, "V_TP_");
   Print("InvestmentAI Executor stopped.");
}

//+------------------------------------------------------------------+
//| Sync Account Settings from Supabase                              |
//+------------------------------------------------------------------+
bool SyncAccountSettings() {
   string json = SupabaseGET("/rest/v1/account_settings?account_id=eq." + InpAccountID);
   if (json == "" || StringFind(json, "[]") != -1) return false;
   
   g_scalping_lot = StringToDouble(ExtractJSONValue(json, "scalping_lot"));
   g_intraday_lot = StringToDouble(ExtractJSONValue(json, "intraday_lot"));
   g_swing_lot    = StringToDouble(ExtractJSONValue(json, "swing_lot"));
   
   g_scalping_grid_enabled = (ExtractJSONValue(json, "scalping_grid_enabled") == "true");
   g_scalping_grid_dist = StringToDouble(ExtractJSONValue(json, "scalping_grid_distance_atr"));
   g_scalping_grid_mult = StringToDouble(ExtractJSONValue(json, "scalping_grid_lot_multiplier"));
   g_scalping_grid_steps = (int)StringToInteger(ExtractJSONValue(json, "scalping_max_grid_steps"));
   
   g_intraday_grid_enabled = (ExtractJSONValue(json, "intraday_grid_enabled") == "true");
   g_intraday_grid_dist = StringToDouble(ExtractJSONValue(json, "intraday_grid_distance_atr"));
   g_intraday_grid_mult = StringToDouble(ExtractJSONValue(json, "intraday_grid_lot_multiplier"));
   g_intraday_grid_steps = (int)StringToInteger(ExtractJSONValue(json, "intraday_max_grid_steps"));
   
   g_swing_grid_enabled = (ExtractJSONValue(json, "swing_grid_enabled") == "true");
   g_swing_grid_dist = StringToDouble(ExtractJSONValue(json, "swing_grid_distance_atr"));
   g_swing_grid_mult = StringToDouble(ExtractJSONValue(json, "swing_grid_lot_multiplier"));
   g_swing_grid_steps = (int)StringToInteger(ExtractJSONValue(json, "swing_max_grid_steps"));
   
   g_scalping_be_trigger = StringToDouble(ExtractJSONValue(json, "scalping_be_trigger"));
   g_scalping_trail_start = StringToDouble(ExtractJSONValue(json, "scalping_trail_start"));
   g_scalping_trail_dist = StringToDouble(ExtractJSONValue(json, "scalping_trail_dist"));
   
   g_intraday_be_trigger = StringToDouble(ExtractJSONValue(json, "intraday_be_trigger"));
   g_intraday_trail_start = StringToDouble(ExtractJSONValue(json, "intraday_trail_start"));
   g_intraday_trail_dist = StringToDouble(ExtractJSONValue(json, "intraday_trail_dist"));
   
   g_swing_be_trigger = StringToDouble(ExtractJSONValue(json, "swing_be_trigger"));
   g_swing_trail_start = StringToDouble(ExtractJSONValue(json, "swing_trail_start"));
   g_swing_trail_dist = StringToDouble(ExtractJSONValue(json, "swing_trail_dist"));
   
   g_max_total_trades = (int)StringToInteger(ExtractJSONValue(json, "max_total_trades"));
   g_min_ai_confidence = (int)StringToInteger(ExtractJSONValue(json, "min_ai_confidence"));
   
   string b_asia = ExtractJSONValue(json, "block_asia_session");
   g_block_asia_session = (b_asia == "true" || b_asia == "True");
   
   g_manage_manual_sl = (ExtractJSONValue(json, "manage_manual_sl") == "true");
   g_manage_manual_tp = (ExtractJSONValue(json, "manage_manual_tp") == "true");
   g_manage_manual_be = (ExtractJSONValue(json, "manage_manual_be") == "true");
   
   Print("Settings Synced | Scalping Grid: ", g_scalping_grid_enabled, " | Intraday Grid: ", g_intraday_grid_enabled, " | Manual BE: ", g_manage_manual_be);
   return true;
}

//+------------------------------------------------------------------+
//| Fetch New Signals                                                |
//+------------------------------------------------------------------+
void CheckForSignals() {
   string json = SupabaseGET("/rest/v1/signals?account_id=eq." + InpAccountID + "&is_active=eq.true&order=generated_at.desc&limit=1");
   if (json == "" || StringFind(json, "[]") != -1) return;
   
   string sig_id = ExtractJSONValue(json, "signal_id");
   if (sig_id == last_processed_signal) return; // Already processed
   
   string action = ExtractJSONValue(json, "action");
   string sym = ExtractJSONValue(json, "symbol");
   double sl = StringToDouble(ExtractJSONValue(json, "sl"));
   double tp = StringToDouble(ExtractJSONValue(json, "tp"));
   int conf = (int)StringToInteger(ExtractJSONValue(json, "confidence"));
   string style = ExtractJSONValue(json, "style");
   
   if (!IsSignalSafeToTrade(sym, action, conf)) {
      Print("Signal ", sig_id, " rejected by Risk Guard.");
   } else {
      ExecuteTrade(sym, action, sl, tp, style, sig_id);
   }
   
   // Mark signal inactive to avoid reprocessing
   SupabasePATCH("/rest/v1/signals?signal_id=eq." + sig_id, "{\"is_active\":false}");
   last_processed_signal = sig_id;
}

//+------------------------------------------------------------------+
//| Fetch SL/TP Updates from AI Evaluator                            |
//+------------------------------------------------------------------+
void SyncSLTPUpdates() {
   string json = SupabaseGET("/rest/v1/sl_tp_updates?account_id=eq." + InpAccountID + "&applied=eq.false&order=created_at.asc");
   if (json == "" || StringFind(json, "[]") != -1) return;
   
   StringReplace(json, "},{", "|");
   string chunks[];
   int count = StringSplit(json, '|', chunks);
   
   for (int i = 0; i < count; i++) {
      long ticket = StringToInteger(ExtractJSONValue(chunks[i], "ticket"));
      double new_sl = StringToDouble(ExtractJSONValue(chunks[i], "new_sl"));
      double new_tp = StringToDouble(ExtractJSONValue(chunks[i], "new_tp"));
      
      if (ticket > 0) {
         if (PositionSelectByTicket(ticket)) {
            double v_sl = ObjectGetDouble(0, "V_SL_" + IntegerToString(ticket), OBJPROP_PRICE);
            double v_tp = ObjectGetDouble(0, "V_TP_" + IntegerToString(ticket), OBJPROP_PRICE);
            
            bool sl_tighter = false;
            bool tp_tighter = false;
            
            if (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) {
               if (new_sl > 0 && (v_sl == 0 || new_sl > v_sl)) sl_tighter = true;
               if (new_tp > 0 && (v_tp == 0 || new_tp < v_tp)) tp_tighter = true;
            } else {
               if (new_sl > 0 && (v_sl == 0 || new_sl < v_sl)) sl_tighter = true;
               if (new_tp > 0 && (v_tp == 0 || new_tp > v_tp)) tp_tighter = true;
            }
            
            double final_sl = sl_tighter ? new_sl : v_sl;
            double final_tp = tp_tighter ? new_tp : v_tp;
            
            if (sl_tighter || tp_tighter) {
               DrawVirtualLines(ticket, final_sl, final_tp);
               SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket), "{\"virtual_sl\":" + DoubleToString(final_sl, 5) + ",\"virtual_tp\":" + DoubleToString(final_tp, 5) + "}");
            }
         }
         SupabasePATCH("/rest/v1/sl_tp_updates?ticket=eq." + IntegerToString(ticket) + "&applied=eq.false", "{\"applied\":true}");
      }
   }
}

//+------------------------------------------------------------------+
//| Risk Guard: Safe To Trade Check                                  |
//+------------------------------------------------------------------+
bool IsSignalSafeToTrade(string sym, string action, int conf) {
   if (conf < g_min_ai_confidence) {
      Print("Risk Guard: Confidence ", conf, " < ", g_min_ai_confidence);
      return false;
   }
   
   if (PositionsTotal() >= g_max_total_trades) {
      Print("Risk Guard: Max open trades reached (", g_max_total_trades, ")");
      return false;
   }
   
   long spread = SymbolInfoInteger(sym, SYMBOL_SPREAD);
   if (spread > g_max_spread_points) {
      Print("Risk Guard: Spread ", spread, " > Max ", g_max_spread_points);
      return false;
   }
   
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if (equity < balance && balance > 0) {
      double current_drawdown = ((balance - equity) / balance) * 100.0;
      if (current_drawdown > g_max_daily_drawdown_pct) {
         Print("Risk Guard: Drawdown ", DoubleToString(current_drawdown, 2), "% > Max ", DoubleToString(g_max_daily_drawdown_pct, 2), "%");
         return false;
      }
   }
   
   if (g_block_asia_session) {
      MqlDateTime dt;
      TimeCurrent(dt);
      if (dt.hour >= 0 && dt.hour <= 8) {
         Print("Risk Guard: Asia Session blocked (Server hour ", dt.hour, ")");
         return false;
      }
   }
   
   return true;
}

//+------------------------------------------------------------------+
//| Execute Stealth Trade                                            |
//+------------------------------------------------------------------+
void ExecuteTrade(string sym, string action, double virtual_sl, double virtual_tp, string style, string sig_id) {
   double lot = g_intraday_lot;
   ulong magic = InpMagicNumber; // Default
   
   if (style == "SCALPING") {
      lot = g_scalping_lot;
      magic = InpMagicNumber + 1; // e.g. 888991
   }
   else if (style == "INTRADAY") {
      lot = g_intraday_lot;
      magic = InpMagicNumber + 2; // e.g. 888992
   }
   else if (style == "SWING") {
      lot = g_swing_lot;
      magic = InpMagicNumber + 3; // e.g. 888993
   }
   
   trade.SetExpertMagicNumber(magic);
   
   double price = 0;
   bool res = false;
   
   if (action == "BUY") {
      price = SymbolInfoDouble(sym, SYMBOL_ASK);
      res = trade.Buy(lot, sym, price, 0, 0, "AI_" + style + "_" + sig_id); // SL=0, TP=0 for Stealth
   } else if (action == "SELL") {
      price = SymbolInfoDouble(sym, SYMBOL_BID);
      res = trade.Sell(lot, sym, price, 0, 0, "AI_" + style + "_" + sig_id);
   }
   
   if (res) {
      ulong ticket = trade.ResultOrder();
      Print("Stealth Trade Opened: ", ticket, " | V_SL: ", virtual_sl, " | V_TP: ", virtual_tp);
      
      // Save Virtual SL/TP to Supabase
      string payload = "{\"ticket\":" + IntegerToString(ticket) + ",\"account_id\":\"" + InpAccountID + "\",\"signal_id\":\"" + sig_id + "\",\"symbol\":\"" + sym + "\",\"direction\":\"" + action + "\",\"lot\":" + DoubleToString(lot, 2) + ",\"virtual_sl\":" + DoubleToString(virtual_sl, 5) + ",\"virtual_tp\":" + DoubleToString(virtual_tp, 5) + ",\"trade_style\":\"" + style + "\"}";
      SupabasePOST("/rest/v1/active_trades", payload);
      
      DrawVirtualLines(ticket, virtual_sl, virtual_tp);
   } else {
      Print("Trade execution failed: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Restore Virtual Lines from Supabase after MT5 Restart            |
//+------------------------------------------------------------------+
void RestoreVirtualLines() {
   string json = SupabaseGET("/rest/v1/active_trades?account_id=eq." + InpAccountID);
   if (json == "" || StringFind(json, "[]") != -1) return;
   
   StringReplace(json, "},{", "|");
   string chunks[];
   int count = StringSplit(json, '|', chunks);
   
   for (int i = 0; i < count; i++) {
      long ticket = StringToInteger(ExtractJSONValue(chunks[i], "ticket"));
      double v_sl = StringToDouble(ExtractJSONValue(chunks[i], "virtual_sl"));
      double v_tp = StringToDouble(ExtractJSONValue(chunks[i], "virtual_tp"));
      
      if (ticket > 0 && (v_sl > 0 || v_tp > 0)) {
         DrawVirtualLines(ticket, v_sl, v_tp);
         Print("Restored Virtual SL/TP for ticket: ", ticket);
      }
   }
}

//+------------------------------------------------------------------+
//| Draw Visual Lines on Chart for Virtual SL/TP                     |
//+------------------------------------------------------------------+
void DrawVirtualLines(ulong ticket, double sl, double tp) {
   string sl_name = "V_SL_" + IntegerToString(ticket);
   string tp_name = "V_TP_" + IntegerToString(ticket);
   
   ObjectCreate(0, sl_name, OBJ_HLINE, 0, 0, sl);
   ObjectSetInteger(0, sl_name, OBJPROP_COLOR, clrRed);
   ObjectSetInteger(0, sl_name, OBJPROP_STYLE, STYLE_DASH);
   
   ObjectCreate(0, tp_name, OBJ_HLINE, 0, 0, tp);
   ObjectSetInteger(0, tp_name, OBJPROP_COLOR, clrLimeGreen);
   ObjectSetInteger(0, tp_name, OBJPROP_STYLE, STYLE_SOLID);
}

//+------------------------------------------------------------------+
//| Expert timer function                                            |
//+------------------------------------------------------------------+
void OnTimer() {
   datetime now = TimeCurrent();
   
   // Sync Settings every 60s
   if (now - last_settings_sync >= 60) {
      SyncAccountSettings();
      last_settings_sync = now;
   }
   
   // Check Signals every 10s
   if (now - last_signal_check >= 10) {
      CheckForSignals();
      last_signal_check = now;
   }
   
   // Fetch SL/TP Updates every 10s
   if (now - last_sltp_sync >= 10) {
      SyncSLTPUpdates();
      last_sltp_sync = now;
   }
   
   // Heartbeat every 60s
   if (now - last_heartbeat >= 60) {
      string payload = "{\"account_id\":\"" + InpAccountID + "\",\"status\":\"online\",\"last_seen_at\":\"" + TimeToString(now, TIME_DATE|TIME_MINUTES) + "\"}";
      SupabasePOST("/rest/v1/bot_heartbeat", payload);
      last_heartbeat = now;
   }
}

//+------------------------------------------------------------------+
//| Expert tick function (Stealth Manager)                           |
//+------------------------------------------------------------------+
void OnTick() {
   ProcessGridRecovery();
   
   // Iterate over all open positions
   for(int i = PositionsTotal()-1; i >= 0; i--) {
      if(position.SelectByIndex(i)) {
         ulong mag = position.Magic();
         
         bool is_manual = false;
         if (mag == 0) {
            if (!g_manage_manual_be && !g_manage_manual_sl && !g_manage_manual_tp) continue;
            is_manual = true;
            ulong ticket = position.Ticket();
            string man_flag = "V_MANUAL_" + IntegerToString(ticket);
            if (ObjectFind(0, man_flag) < 0) {
               double lot = position.Volume();
               string sym = position.Symbol();
               string action = (position.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
               double virtual_sl = 0;
               double virtual_tp = 0;
               string payload = "{\"ticket\":" + IntegerToString(ticket) + ",\"account_id\":\"" + InpAccountID + "\",\"signal_id\":\"MANUAL_" + IntegerToString(ticket) + "\",\"symbol\":\"" + sym + "\",\"direction\":\"" + action + "\",\"lot\":" + DoubleToString(lot, 2) + ",\"virtual_sl\":" + DoubleToString(virtual_sl, 5) + ",\"virtual_tp\":" + DoubleToString(virtual_tp, 5) + ",\"trade_style\":\"MANUAL\"}";
               if (SupabasePOST("/rest/v1/active_trades", payload)) {
                  ObjectCreate(0, man_flag, OBJ_LABEL, 0, 0, 0);
                  ObjectSetString(0, man_flag, OBJPROP_TEXT, "MANUAL");
                  ObjectSetInteger(0, man_flag, OBJPROP_HIDDEN, true);
                  Print("Registered Manual Trade to Supabase: ", ticket);
               }
            }
         } else if (mag < InpMagicNumber || mag > InpMagicNumber + 3) {
            continue; // Ignore other EAs
         }
         
         ulong ticket = position.Ticket();
         double current_price = (position.PositionType() == POSITION_TYPE_BUY) ? SymbolInfoDouble(position.Symbol(), SYMBOL_BID) : SymbolInfoDouble(position.Symbol(), SYMBOL_ASK);
         double entry_price = position.PriceOpen();
         
         // Read Virtual SL/TP from the chart objects
         string sl_name = "V_SL_" + IntegerToString(ticket);
         string tp_name = "V_TP_" + IntegerToString(ticket);
         
         double v_sl = ObjectGetDouble(0, sl_name, OBJPROP_PRICE);
         double v_tp = ObjectGetDouble(0, tp_name, OBJPROP_PRICE);
         
         string close_reason_text = "Virtual Exit";
         bool should_close = false;
         
         if (position.PositionType() == POSITION_TYPE_BUY) {
            if (v_sl > 0 && current_price <= v_sl) { close_reason_text = "Virtual SL Hit"; should_close = true; }
            if (v_tp > 0 && current_price >= v_tp) { close_reason_text = "Virtual TP Hit"; should_close = true; }
         } else {
            if (v_sl > 0 && current_price >= v_sl) { close_reason_text = "Virtual SL Hit"; should_close = true; }
            if (v_tp > 0 && current_price <= v_tp) { close_reason_text = "Virtual TP Hit"; should_close = true; }
         }
         
         if (should_close) {
            string sym_close = position.Symbol();
            string action_close = (position.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            double lot_close = position.Volume();
            string style_close = "UNKNOWN";
            if (mag == 0) style_close = "MANUAL";
            else if (mag == InpMagicNumber+1) style_close = "SCALPING";
            else if (mag == InpMagicNumber+2) style_close = "INTRADAY";
            else if (mag == InpMagicNumber+3) style_close = "SWING";
            
            if (trade.PositionClose(ticket)) {
               Sleep(500); // Give MT5 time to log deal
               double final_pl = 0;
               if(HistorySelect(TimeCurrent()-86400, TimeCurrent()+86400)) {
                  int deals_total = HistoryDealsTotal();
                  for(int d = deals_total-1; d >= 0; d--) {
                     ulong deal_ticket = HistoryDealGetTicket(d);
                     if(HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID) == ticket && HistoryDealGetInteger(deal_ticket, DEAL_ENTRY) == DEAL_ENTRY_OUT) {
                        final_pl = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT) + HistoryDealGetDouble(deal_ticket, DEAL_SWAP) + HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
                        break;
                     }
                  }
               }
               if(final_pl == 0) { // fallback
                  final_pl = position.Profit() + position.Swap() + position.Commission();
               }

               ObjectsDeleteAll(0, "V_SL_" + IntegerToString(ticket));
               ObjectsDeleteAll(0, "V_TP_" + IntegerToString(ticket));
               ObjectsDeleteAll(0, "V_MANUAL_" + IntegerToString(ticket));
               
               Print("Closed ticket ", ticket, " due to ", close_reason_text);
               string payload = "{\"ticket\":" + IntegerToString(ticket) + ",\"account_id\":\"" + InpAccountID + "\",\"symbol\":\"" + sym_close + "\",\"direction\":\"" + action_close + "\",\"lot\":" + DoubleToString(lot_close, 2) + ",\"trade_style\":\"" + style_close + "\",\"pnl\":" + DoubleToString(final_pl, 2) + ",\"close_reason\":\"" + close_reason_text + "\"}";
               SupabasePOST("/rest/v1/closed_trades", payload);
               SupabaseDELETE("/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket));
            }
         } else {
            // Load individual settings based on magic number style
            bool   style_grid_enabled = false;
            double style_grid_dist = 0;
            double style_grid_mult = 1.0;
            int    style_grid_steps = 0;
            double style_be_trigger = 0;
            double style_trail_start = 0;
            double style_trail_dist = 0;
            
            if (mag == InpMagicNumber + 1) { // SCALPING
               style_grid_enabled = g_scalping_grid_enabled;
               style_grid_dist = g_scalping_grid_dist;
               style_grid_mult = g_scalping_grid_mult;
               style_grid_steps = g_scalping_grid_steps;
               style_be_trigger = g_scalping_be_trigger;
               style_trail_start = g_scalping_trail_start;
               style_trail_dist = g_scalping_trail_dist;
            }
            else if (mag == InpMagicNumber + 2 || is_manual) { // INTRADAY or MANUAL
               style_grid_enabled = g_intraday_grid_enabled;
               style_grid_dist = g_intraday_grid_dist;
               style_grid_mult = g_intraday_grid_mult;
               style_grid_steps = g_intraday_grid_steps;
               style_be_trigger = g_intraday_be_trigger;
               style_trail_start = g_intraday_trail_start;
               style_trail_dist = g_intraday_trail_dist;
            }
            else if (mag == InpMagicNumber + 3) { // SWING
               style_grid_enabled = g_swing_grid_enabled;
               style_grid_dist = g_swing_grid_dist;
               style_grid_mult = g_swing_grid_mult;
               style_grid_steps = g_swing_grid_steps;
               style_be_trigger = g_swing_be_trigger;
               style_trail_start = g_swing_trail_start;
               style_trail_dist = g_swing_trail_dist;
            }
            
            if (is_manual && (!g_manage_manual_be && !g_manage_manual_sl)) {
               // Skip BE/Trail if not managed
            } else {
               // Calculate ATR dynamically for distance conversions
               double atr_value = 0.0010; // Fallback 10 pips
               if(g_atr_handle != INVALID_HANDLE) {
                  double atr_arr[];
                  CopyBuffer(g_atr_handle, 0, 1, 1, atr_arr);
                  if(ArraySize(atr_arr) > 0) atr_value = atr_arr[0];
               }
               
               double pip_size = (StringFind(position.Symbol(), "JPY") != -1 || StringFind(position.Symbol(), "XAU") != -1) ? 0.01 : 0.0001;
               
               double be_trigger_price_dist = style_be_trigger * atr_value;
               double trail_start_price_dist = style_trail_start * atr_value;
               double trail_dist_price = style_trail_dist * atr_value;
               
               bool updated_sl = false;
               
               if (position.PositionType() == POSITION_TYPE_BUY) {
                  double profit_dist = current_price - entry_price;
                  // Break-Even
                  if (profit_dist >= be_trigger_price_dist && (v_sl < entry_price || v_sl == 0)) {
                     v_sl = entry_price + (pip_size * 2); // BE + 2 pips
                     updated_sl = true;
                  }
                  // Trailing Stop
                  if (profit_dist >= trail_start_price_dist) {
                     double new_sl = current_price - trail_dist_price;
                     if (v_sl == 0 || new_sl > v_sl) {
                        v_sl = new_sl;
                        updated_sl = true;
                     }
                  }
               } else {
                  double profit_dist = entry_price - current_price;
                  // Break-Even
                  if (profit_dist >= be_trigger_price_dist && (v_sl > entry_price || v_sl == 0)) {
                     v_sl = entry_price - (pip_size * 2); // BE + 2 pips
                     updated_sl = true;
                  }
                  // Trailing Stop
                  if (profit_dist >= trail_start_price_dist) {
                     double new_sl = current_price + trail_dist_price;
                     if (new_sl < v_sl || v_sl == 0) {
                        v_sl = new_sl;
                        updated_sl = true;
                     }
                  }
               }
               
               if (updated_sl) {
                  DrawVirtualLines(ticket, v_sl, v_tp);
                  SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket), "{\"virtual_sl\":" + DoubleToString(v_sl, 5) + "}");
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Process Grid Recovery (Averaging)                                |
//+------------------------------------------------------------------+
void ProcessGridRecovery() {
   for(int m = 1; m <= 3; m++) {
      ulong mag = InpMagicNumber + m;
      
      bool   style_grid_enabled = false;
      double style_grid_dist = 0;
      double style_grid_mult = 1.0;
      int    style_grid_steps = 0;
      
      if (m == 1) {
         style_grid_enabled = g_scalping_grid_enabled;
         style_grid_dist = g_scalping_grid_dist;
         style_grid_mult = g_scalping_grid_mult;
         style_grid_steps = g_scalping_grid_steps;
      }
      else if (m == 2) {
         style_grid_enabled = g_intraday_grid_enabled;
         style_grid_dist = g_intraday_grid_dist;
         style_grid_mult = g_intraday_grid_mult;
         style_grid_steps = g_intraday_grid_steps;
      }
      else if (m == 3) {
         style_grid_enabled = g_swing_grid_enabled;
         style_grid_dist = g_swing_grid_dist;
         style_grid_mult = g_swing_grid_mult;
         style_grid_steps = g_swing_grid_steps;
      }
      
      if (!style_grid_enabled || style_grid_steps <= 0) continue;
      
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
         
         int total_buy_layers = 0;
         int total_sell_layers = 0;
         double lowest_buy_price = 0;
         double highest_sell_price = 0;
         double last_buy_lot = 0;
         double last_sell_lot = 0;
         
         double grid_v_sl_buy = 0;
         double grid_v_tp_buy = 0;
         double grid_v_sl_sell = 0;
         double grid_v_tp_sell = 0;
         
         for(int j = 0; j < PositionsTotal(); j++) {
            if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym) {
               if (position.PositionType() == POSITION_TYPE_BUY) {
                  total_buy_layers++;
                  if (grid_v_sl_buy == 0 && grid_v_tp_buy == 0) {
                     grid_v_sl_buy = ObjectGetDouble(0, "V_SL_" + IntegerToString(position.Ticket()), OBJPROP_PRICE);
                     grid_v_tp_buy = ObjectGetDouble(0, "V_TP_" + IntegerToString(position.Ticket()), OBJPROP_PRICE);
                  }
                  if (lowest_buy_price == 0 || position.PriceOpen() < lowest_buy_price) {
                     lowest_buy_price = position.PriceOpen();
                     last_buy_lot = position.Volume();
                  }
               } else {
                  total_sell_layers++;
                  if (grid_v_sl_sell == 0 && grid_v_tp_sell == 0) {
                     grid_v_sl_sell = ObjectGetDouble(0, "V_SL_" + IntegerToString(position.Ticket()), OBJPROP_PRICE);
                     grid_v_tp_sell = ObjectGetDouble(0, "V_TP_" + IntegerToString(position.Ticket()), OBJPROP_PRICE);
                  }
                  if (highest_sell_price == 0 || position.PriceOpen() > highest_sell_price) {
                     highest_sell_price = position.PriceOpen();
                     last_sell_lot = position.Volume();
                  }
               }
            }
         }
         
         double atr_value = 0.0010;
         if(g_atr_handle != INVALID_HANDLE) {
            double atr_arr[];
            CopyBuffer(g_atr_handle, 0, 1, 1, atr_arr);
            if(ArraySize(atr_arr) > 0) atr_value = atr_arr[0];
         }
         
         double grid_dist_price = style_grid_dist * atr_value;
         
         if (total_buy_layers > 0 && total_buy_layers < (style_grid_steps + 1)) {
            double current_ask = SymbolInfoDouble(sym, SYMBOL_ASK);
            if (current_ask <= lowest_buy_price - grid_dist_price) {
               double new_lot = last_buy_lot * style_grid_mult;
               trade.SetExpertMagicNumber(mag);
               if (trade.Buy(new_lot, sym, current_ask, 0, 0, "GridLayer_" + IntegerToString(total_buy_layers))) {
                  ulong tkt = trade.ResultOrder();
                  string style_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                  string payload = "{\"ticket\":" + IntegerToString(tkt) + ",\"account_id\":\"" + InpAccountID + "\",\"signal_id\":\"GRID_" + IntegerToString(tkt) + "\",\"symbol\":\"" + sym + "\",\"direction\":\"BUY\",\"lot\":" + DoubleToString(new_lot, 2) + ",\"virtual_sl\":" + DoubleToString(grid_v_sl_buy, 5) + ",\"virtual_tp\":" + DoubleToString(grid_v_tp_buy, 5) + ",\"trade_style\":\"" + style_str + "\"}";
                  SupabasePOST("/rest/v1/active_trades", payload);
                  DrawVirtualLines(tkt, grid_v_sl_buy, grid_v_tp_buy);
                  Print("Grid BUY opened for ", sym, " Layer ", total_buy_layers);
               }
            }
         }
         
         if (total_sell_layers > 0 && total_sell_layers < (style_grid_steps + 1)) {
            double current_bid = SymbolInfoDouble(sym, SYMBOL_BID);
            if (current_bid >= highest_sell_price + grid_dist_price) {
               double new_lot = last_sell_lot * style_grid_mult;
               trade.SetExpertMagicNumber(mag);
               if (trade.Sell(new_lot, sym, current_bid, 0, 0, "GridLayer_" + IntegerToString(total_sell_layers))) {
                  ulong tkt = trade.ResultOrder();
                  string style_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                  string payload = "{\"ticket\":" + IntegerToString(tkt) + ",\"account_id\":\"" + InpAccountID + "\",\"signal_id\":\"GRID_" + IntegerToString(tkt) + "\",\"symbol\":\"" + sym + "\",\"direction\":\"SELL\",\"lot\":" + DoubleToString(new_lot, 2) + ",\"virtual_sl\":" + DoubleToString(grid_v_sl_sell, 5) + ",\"virtual_tp\":" + DoubleToString(grid_v_tp_sell, 5) + ",\"trade_style\":\"" + style_str + "\"}";
                  SupabasePOST("/rest/v1/active_trades", payload);
                  DrawVirtualLines(tkt, grid_v_sl_sell, grid_v_tp_sell);
                  Print("Grid SELL opened for ", sym, " Layer ", total_sell_layers);
               }
            }
         }
      }
   }
}
//+------------------------------------------------------------------+

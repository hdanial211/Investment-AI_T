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
input string   InpSupabaseAnon   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."; // Supabase Anon Key
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

// --- Timers ---
datetime last_settings_sync = 0;
datetime last_signal_check = 0;
datetime last_heartbeat = 0;

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
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit() {
   Print("Initializing InvestmentAI Executor for Account: ", InpAccountID);
   trade.SetExpertMagicNumber(InpMagicNumber);
   
   if (!SyncAccountSettings()) {
      Print("Failed to fetch account settings. Halting initialization.");
      return INIT_FAILED;
   }
   
   EventSetTimer(1); // 1-second timer for polling tasks
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   EventKillTimer();
   ObjectsDeleteAll(0, "V_SL_");
   ObjectsDeleteAll(0, "V_TP_");
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
   
   Print("Settings Synced | Scalping Grid: ", g_scalping_grid_enabled, " | Intraday Grid: ", g_intraday_grid_enabled);
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
   
   if (conf < g_min_ai_confidence) {
      Print("Signal ", sig_id, " rejected: Confidence ", conf, " < ", g_min_ai_confidence);
   } else {
      ExecuteTrade(sym, action, sl, tp, style, sig_id);
   }
   
   // Mark signal inactive to avoid reprocessing
   SupabasePATCH("/rest/v1/signals?signal_id=eq." + sig_id, "{\"is_active\":false}");
   last_processed_signal = sig_id;
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
      string payload = "{\"ticket\":" + IntegerToString(ticket) + ",\"account_id\":\"" + InpAccountID + "\",\"signal_id\":\"" + sig_id + "\",\"symbol\":\"" + sym + "\",\"direction\":\"" + action + "\",\"lot\":" + DoubleToString(lot, 2) + ",\"virtual_sl\":" + DoubleToString(virtual_sl, 5) + ",\"virtual_tp\":" + DoubleToString(virtual_tp, 5) + "}";
      SupabasePOST("/rest/v1/active_trades", payload);
      
      DrawVirtualLines(ticket, virtual_sl, virtual_tp);
   } else {
      Print("Trade execution failed: ", GetLastError());
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
   // Iterate over all open positions
   for(int i = PositionsTotal()-1; i >= 0; i--) {
      if(position.SelectByIndex(i)) {
         ulong mag = position.Magic();
         // Check if magic number belongs to our EA (888991, 888992, 888993 or base 888999)
         if(mag >= InpMagicNumber && mag <= InpMagicNumber + 3) {
            ulong ticket = position.Ticket();
            double current_price = (position.PositionType() == POSITION_TYPE_BUY) ? SymbolInfoDouble(position.Symbol(), SYMBOL_BID) : SymbolInfoDouble(position.Symbol(), SYMBOL_ASK);
            
            // Read Virtual SL/TP from the chart objects (or memory)
            string sl_name = "V_SL_" + IntegerToString(ticket);
            string tp_name = "V_TP_" + IntegerToString(ticket);
            
            double v_sl = ObjectGetDouble(0, sl_name, OBJPROP_PRICE);
            double v_tp = ObjectGetDouble(0, tp_name, OBJPROP_PRICE);
            
            bool should_close = false;
            
            if (position.PositionType() == POSITION_TYPE_BUY) {
               if (v_sl > 0 && current_price <= v_sl) { Print("Virtual SL Hit!"); should_close = true; }
               if (v_tp > 0 && current_price >= v_tp) { Print("Virtual TP Hit!"); should_close = true; }
            } else {
               if (v_sl > 0 && current_price >= v_sl) { Print("Virtual SL Hit!"); should_close = true; }
               if (v_tp > 0 && current_price <= v_tp) { Print("Virtual TP Hit!"); should_close = true; }
            }
            
            if (should_close) {
               if (trade.PositionClose(ticket)) {
                  ObjectsDeleteAll(0, "V_SL_" + IntegerToString(ticket));
                  ObjectsDeleteAll(0, "V_TP_" + IntegerToString(ticket));
                  SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket), "{\"current_status\":\"CLOSED\"}");
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
               else if (mag == InpMagicNumber + 2) { // INTRADAY
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
               
               // Implement Break-Even & Trailing Stop logic here using style_* variables
               // If style_grid_enabled is true, execute layer recovery based on style_grid_dist
               // ...
            }
         }
      }
   }
}
//+------------------------------------------------------------------+

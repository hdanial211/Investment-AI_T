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
int      g_max_spread_points = 100;

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
   
   ResetLastError();
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
   
   ResetLastError();
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
   
   ResetLastError();
   int res = WebRequest("PATCH", url, headers, 5000, post, result, result_headers);
   if (res == 200 || res == 204) {
      return true;
   }
   Print("WebRequest PATCH failed! Error: ", GetLastError(), " HTTP Code: ", res);
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
   
   ResetLastError();
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
   
   double min_conf_val = StringToDouble(ExtractJSONValue(json, "min_ai_confidence"));
   if (min_conf_val <= 1.0 && min_conf_val > 0) min_conf_val *= 100.0;
   g_min_ai_confidence = (int)min_conf_val;
   
   double dd_val = StringToDouble(ExtractJSONValue(json, "max_daily_drawdown_pct"));
   if (dd_val > 0) g_max_daily_drawdown_pct = dd_val;
   
   int spread_val = (int)StringToInteger(ExtractJSONValue(json, "max_spread_points"));
   if (spread_val > 0) g_max_spread_points = spread_val;
   
   string b_asia = ExtractJSONValue(json, "block_asia_session");
   g_block_asia_session = (b_asia == "true" || b_asia == "True");
   
   g_manage_manual_sl = (ExtractJSONValue(json, "manage_manual_sl") == "true");
   g_manage_manual_tp = (ExtractJSONValue(json, "manage_manual_tp") == "true");
   g_manage_manual_be = (ExtractJSONValue(json, "manage_manual_be") == "true");
   
   Print("Settings Synced | Scalping Grid: ", g_scalping_grid_enabled, " | Intraday Grid: ", g_intraday_grid_enabled, " | Manual BE: ", g_manage_manual_be);
   return true;
}

//+------------------------------------------------------------------+

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
   double raw_conf = StringToDouble(ExtractJSONValue(json, "confidence"));
   int conf = (int)(raw_conf * 100);
   if (raw_conf > 1) conf = (int)raw_conf; // Fallback if already 85
   string style = ExtractJSONValue(json, "style");
   
   // Map AI symbol to chart symbol (e.g. XAUUSD -> XAUUSDc)
   string trade_sym = sym;
   if (StringFind(_Symbol, sym) != -1 || StringFind(sym, _Symbol) != -1) {
      trade_sym = _Symbol;
   }
   
   if (!IsSignalSafeToTrade(trade_sym, action, conf)) {
      Print("Signal ", sig_id, " rejected by Risk Guard.");
   } else {
      ExecuteTrade(trade_sym, action, sl, tp, style, sig_id);
   }
   
   // Mark signal inactive to avoid reprocessing
   SupabasePATCH("/rest/v1/signals?signal_id=eq." + sig_id, "{\"is_active\":false}");
   last_processed_signal = sig_id;
}

//+------------------------------------------------------------------+
//| Fetch SL/TP Updates from AI Evaluator                            |
//+------------------------------------------------------------------+
void SyncSLTPUpdates() {
   string json = SupabaseGET("/rest/v1/sl_tp_updates?account_id=eq." + InpAccountID + "&applied=eq.false");
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
            ulong mag = PositionGetInteger(POSITION_MAGIC);
            int m = (int)(mag - InpMagicNumber);
            string style_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
            string dir_str = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            string sym = PositionGetString(POSITION_SYMBOL);
            
            double v_sl = ObjectGetDouble(0, "B_SL_" + style_str + "_" + dir_str + "_" + sym, OBJPROP_PRICE);
            double v_tp = ObjectGetDouble(0, "B_TP_" + style_str + "_" + dir_str + "_" + sym, OBJPROP_PRICE);
            
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
               DrawIndividualLines(ticket, sym, style_str, dir_str, final_sl, final_tp);
               // Update all tickets in basket
               for(int j = 0; j < PositionsTotal(); j++) {
                  if(position.SelectByIndex(j) && position.Magic() == mag && position.Symbol() == sym && position.PositionType() == PositionGetInteger(POSITION_TYPE)) {
                     SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(position.Ticket()), "{\"virtual_sl\":" + DoubleToString(final_sl, 5) + ",\"virtual_tp\":" + DoubleToString(final_tp, 5) + "}");
                  }
               }
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
      
      string dir_str = (action == "BUY") ? "BUY" : "SELL";
      DrawIndividualLines(ticket, sym, style, dir_str, virtual_sl, virtual_tp);
   } else {
      Print("Trade execution failed: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Restore Virtual Lines from Supabase after MT5 Restart            |
//+------------------------------------------------------------------+
void RestoreVirtualLines() {
   string json = SupabaseGET("/rest/v1/active_trades?account_id=eq." + InpAccountID + "&current_status=eq.OPEN");
   if (json == "" || StringFind(json, "[]") != -1) return;
   
   StringReplace(json, "},{", "|");
   string chunks[];
   int count = StringSplit(json, '|', chunks);
   
   for (int i = 0; i < count; i++) {
      long ticket = StringToInteger(ExtractJSONValue(chunks[i], "ticket"));
      double v_sl = StringToDouble(ExtractJSONValue(chunks[i], "virtual_sl"));
      double v_tp = StringToDouble(ExtractJSONValue(chunks[i], "virtual_tp"));
      string style = ExtractJSONValue(chunks[i], "trade_style");
      string dir_str = ExtractJSONValue(chunks[i], "direction");
      string sym = ExtractJSONValue(chunks[i], "symbol");
      
      if (ticket > 0 && (v_sl > 0 || v_tp > 0) && style != "") {
         DrawIndividualLines((ulong)ticket, sym, style, dir_str, v_sl, v_tp);
         Print("Restored Basket Virtual SL/TP for: ", style, " ", dir_str, " ", sym);
      }
   }
}

//+------------------------------------------------------------------+
//| Draw Visual Lines on Chart for Virtual SL/TP                     |
//+------------------------------------------------------------------+
void DrawVirtualLines(ulong ticket, double sl, double tp) {
   // Deprecated for individual trades. Use Basket lines instead.
}

void DrawIndividualLines(ulong ticket, string sym, string style, string dir_str, double sl, double tp) {
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
      // CheckForSignals(); // MOVED TO PYTHON EVALUATOR
      last_signal_check = now;
   }
   
   // Fetch SL/TP Updates every 10s
   if (now - last_sltp_sync >= 10) {
      SyncSLTPUpdates();
      SyncActiveTrades();
      last_sltp_sync = now;
   }
   
   // Heartbeat every 60s
   if (now - last_heartbeat >= 60) {
      string payload = "{\"account_id\":\"" + InpAccountID + "\",\"status\":\"online\",\"last_seen_at\":\"" + TimeToString(now, TIME_DATE|TIME_MINUTES) + "\"}";
      string url = "/rest/v1/bot_heartbeat?account_id=eq." + InpAccountID;
      if (!SupabasePATCH(url, payload)) {
         // If PATCH fails, try POST
         SupabasePOST("/rest/v1/bot_heartbeat", payload);
      }
      last_heartbeat = now;
   }
}

//+------------------------------------------------------------------+
//| Expert tick function (Stealth Manager)                           |
//+------------------------------------------------------------------+
void ManageIndividualTrades();
void ManageManualBaskets();


void OnTick() {
   ProcessGridRecovery();
   ManageIndividualTrades();
   ManageManualBaskets();
   
   // Clean up orphaned virtual and basket lines for closed trades
   int total_objs = ObjectsTotal(0);
   for (int i = total_objs - 1; i >= 0; i--) {
      string obj_name = ObjectName(0, i);
      if (StringFind(obj_name, "V_SL_") == 0 || StringFind(obj_name, "V_TP_") == 0) {
         string ticket_str = StringSubstr(obj_name, 5);
         long ticket = StringToInteger(ticket_str);
         if (ticket > 0 && !PositionSelectByTicket(ticket)) {
            ObjectDelete(0, obj_name);
         }
      } else if (StringFind(obj_name, "B_SL_") == 0 || StringFind(obj_name, "B_TP_") == 0 || StringFind(obj_name, "B_TR_") == 0) {
         string parts[];
         StringSplit(obj_name, '_', parts);
         if (ArraySize(parts) >= 5) {
            string style = parts[2];
            string dir = parts[3];
            string sym = parts[4];
            
            ulong mag = InpMagicNumber;
            if (style == "SCALPING") mag = InpMagicNumber + 1;
            else if (style == "INTRADAY") mag = InpMagicNumber + 2;
            else if (style == "SWING") mag = InpMagicNumber + 3;
            
            long pos_type = (dir == "BUY") ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;
            
            bool has_trades = false;
            for(int j = 0; j < PositionsTotal(); j++) {
               ulong tkt = PositionGetTicket(j);
               if(tkt > 0 && PositionGetString(POSITION_SYMBOL) == sym) {
                  ulong p_mag = PositionGetInteger(POSITION_MAGIC);
                  long p_type = PositionGetInteger(POSITION_TYPE);
                  if (style == "MANUAL" && (p_mag == 0 || p_mag == InpMagicNumber) && p_type == pos_type) {
                     has_trades = true; break;
                  } else if (p_mag == mag && p_type == pos_type) {
                     has_trades = true; break;
                  }
               }
            }
            if (!has_trades) {
               ObjectDelete(0, obj_name);
            }
         }
      }
   }
}

void ManageIndividualTrades() {
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
         if (StringFind(g_cached_trades[cache_idx].style, "MANUAL_") == 0) continue;
         
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
               
               string payload = "{\"ticket\":" + IntegerToString(tkt) + ",\"account_id\":\"" + InpAccountID + "\",\"symbol\":\"" + sym + "\",\"direction\":\"" + dir_str + "\",\"lot\":" + DoubleToString(lot_close, 2) + ",\"trade_style\":\"" + style + "\",\"pnl\":" + DoubleToString(final_pl, 2) + ",\"close_reason\":\"" + close_reason + "\"}";
               SupabasePOST("/rest/v1/closed_trades", payload);
               SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(tkt), "{\"exit_reason\":\"" + close_reason + "\",\"current_status\":\"CLOSED\"}");
               
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
            SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(tkt), "{\"virtual_sl\":" + DoubleToString(v_tr, 5) + "}");
            g_cached_trades[cache_idx].v_sl = v_tr;
         }
      }
   }
}

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
                     string s_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                     grid_v_sl_buy = ObjectGetDouble(0, "B_SL_" + s_str + "_BUY_" + sym, OBJPROP_PRICE);
                     grid_v_tp_buy = ObjectGetDouble(0, "B_TP_" + s_str + "_BUY_" + sym, OBJPROP_PRICE);
                  }
                  if (lowest_buy_price == 0 || position.PriceOpen() < lowest_buy_price) {
                     lowest_buy_price = position.PriceOpen();
                     last_buy_lot = position.Volume();
                  }
               } else {
                  total_sell_layers++;
                  if (grid_v_sl_sell == 0 && grid_v_tp_sell == 0) {
                     string s_str = (m == 1) ? "SCALPING" : (m == 2) ? "INTRADAY" : "SWING";
                     grid_v_sl_sell = ObjectGetDouble(0, "B_SL_" + s_str + "_SELL_" + sym, OBJPROP_PRICE);
                     grid_v_tp_sell = ObjectGetDouble(0, "B_TP_" + s_str + "_SELL_" + sym, OBJPROP_PRICE);
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
                  ulong mtkt = basket_tickets[m];
                  if(position.SelectByTicket(mtkt)) {
                     double lot_close = position.Volume();
                     double prof = position.Profit() + position.Swap() + position.Commission();
                     if (trade.PositionClose(mtkt)) {
                        Sleep(200);
                        double final_pl = prof;
                        if(HistorySelect(TimeCurrent()-86400, TimeCurrent()+86400)) {
                           int deals_total = HistoryDealsTotal();
                           for(int d = deals_total-1; d >= 0; d--) {
                              ulong deal_ticket = HistoryDealGetTicket(d);
                              if(HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID) == mtkt && HistoryDealGetInteger(deal_ticket, DEAL_ENTRY) == DEAL_ENTRY_OUT) {
                                 final_pl = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT) + HistoryDealGetDouble(deal_ticket, DEAL_SWAP) + HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
                                 break;
                              }
                           }
                        }
                        string payload = "{\\"ticket\\":" + IntegerToString(mtkt) + ",\\"account_id\\":\\"" + InpAccountID + "\\",\\"symbol\\":\\"" + sym + "\\",\\"direction\\":\\"" + dir_str + "\\",\\"lot\\":" + DoubleToString(lot_close, 2) + ",\\"trade_style\\":\\"MANUAL_BASKET\\",\\"pnl\\":" + DoubleToString(final_pl, 2) + ",\\"close_reason\\":\\"" + close_reason + "\\"}";
                        SupabasePOST("/rest/v1/closed_trades", payload);
                        SupabasePATCH("/rest/v1/active_trades?ticket=eq." + IntegerToString(mtkt), "{\\"exit_reason\\":\\"" + close_reason + "\\",\\"current_status\\":\\"CLOSED\\"}");
                        
                        ObjectDelete(0, "V_SL_" + IntegerToString(mtkt));
                        ObjectDelete(0, "V_TP_" + IntegerToString(mtkt));
                        ObjectDelete(0, "V_TR_" + IntegerToString(mtkt));
                     }
                  }
               }
               ObjectDelete(0, sl_name);
               ObjectDelete(0, tp_name);
               ObjectDelete(0, tr_name);
            }
         }
      }
   }
}

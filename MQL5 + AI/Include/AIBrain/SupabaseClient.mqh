//+------------------------------------------------------------------+
//|                                               SupabaseClient.mqh |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|               Supabase REST API client (GET/POST/PATCH)          |
//+------------------------------------------------------------------+
#ifndef SUPABASECLIENT_MQH
#define SUPABASECLIENT_MQH

#include "HttpClient.mqh"
#include "JsonParser.mqh"

class CSupabaseClient
{
private:
   string m_base_url;
   string m_anon_key;
   string m_account_id;

   string _BuildHeaders(bool with_content_type = false)
   {
      string h = "apikey: " + m_anon_key + "\r\n"
               + "Authorization: Bearer " + m_anon_key + "\r\n"
               + "Accept: application/json\r\n";
      if(with_content_type)
         h += "Content-Type: application/json\r\nPrefer: return=minimal\r\n";
      return h;
   }

public:
   // Settings cache (populated by SyncSettings)
   double   lot_scalping;
   double   lot_intraday;
   double   lot_swing;
   int      max_total_trades;
   int      min_confidence;
   double   max_drawdown_pct;
   int      max_spread_points;
   bool     block_asia;
   bool     enabled;

   // Trailing/BE params per style
   double   scalping_be_trigger;
   double   scalping_be_offset;
   double   scalping_trail_start;
   double   scalping_trail_dist;
   double   intraday_be_trigger;
   double   intraday_be_offset;
   double   intraday_trail_start;
   double   intraday_trail_dist;
   double   swing_be_trigger;
   double   swing_be_offset;
   double   swing_trail_start;
   double   swing_trail_dist;

   void Init(const string base_url, const string anon_key, const string account_id)
   {
      m_base_url   = base_url;
      m_anon_key   = anon_key;
      m_account_id = account_id;

      // Safe defaults
      lot_scalping        = 0.01;
      lot_intraday        = 0.01;
      lot_swing           = 0.01;
      max_total_trades    = 5;
      min_confidence      = 70;
      max_drawdown_pct    = 5.0;
      max_spread_points   = 50;
      block_asia          = false;
      enabled             = true;
      scalping_be_trigger = 15;
      scalping_be_offset  = 2;
      scalping_trail_start= 20;
      scalping_trail_dist = 10;
      intraday_be_trigger = 25;
      intraday_be_offset  = 5;
      intraday_trail_start= 40;
      intraday_trail_dist = 20;
      swing_be_trigger    = 60;
      swing_be_offset     = 15;
      swing_trail_start   = 100;
      swing_trail_dist    = 50;
   }

   //--- Fetch & cache account settings from Supabase
   bool SyncSettings()
   {
      string url = m_base_url + "/rest/v1/account_settings?account_id=eq." + m_account_id;
      string json = HttpGET(url, _BuildHeaders());
      if(json == "" || StringFind(json, "account_id") == -1) return false;

      // Strip array brackets if present
      if(StringSubstr(json, 0, 1) == "[") json = StringSubstr(json, 1, StringLen(json) - 2);

      lot_scalping        = JsonGetDouble(json, "scalping_lot");
      lot_intraday        = JsonGetDouble(json, "intraday_lot");
      lot_swing           = JsonGetDouble(json, "swing_lot");
      if(lot_scalping <= 0) lot_scalping = 0.01;
      if(lot_intraday <= 0) lot_intraday = 0.01;
      if(lot_swing    <= 0) lot_swing    = 0.01;

      max_total_trades  = JsonGetInt(json, "max_total_trades");
      if(max_total_trades <= 0) max_total_trades = 5;

      double mc = JsonGetDouble(json, "min_ai_confidence");
      min_confidence = (mc > 0 && mc <= 1.0) ? (int)(mc * 100) : (int)mc;
      if(min_confidence <= 0) min_confidence = 70;

      double dd = JsonGetDouble(json, "max_daily_drawdown_pct");
      if(dd > 0) max_drawdown_pct = dd;

      int sp = JsonGetInt(json, "max_spread_points");
      if(sp > 0) max_spread_points = sp;

      block_asia = JsonGetBool(json, "block_asia_session");
      enabled    = !(JsonGetBool(json, "enabled") == false); // default true

      scalping_be_trigger  = JsonGetDouble(json, "scalping_be_trigger");
      scalping_be_offset   = JsonGetDouble(json, "scalping_be_offset_pips");
      scalping_trail_start = JsonGetDouble(json, "scalping_trail_start");
      scalping_trail_dist  = JsonGetDouble(json, "scalping_trail_dist");
      if(scalping_be_trigger  <= 0) scalping_be_trigger  = 15;
      if(scalping_be_offset   <= 0) scalping_be_offset   = 2;
      if(scalping_trail_start <= 0) scalping_trail_start = 20;
      if(scalping_trail_dist  <= 0) scalping_trail_dist  = 10;

      intraday_be_trigger  = JsonGetDouble(json, "intraday_be_trigger");
      intraday_be_offset   = JsonGetDouble(json, "intraday_be_offset_pips");
      intraday_trail_start = JsonGetDouble(json, "intraday_trail_start");
      intraday_trail_dist  = JsonGetDouble(json, "intraday_trail_dist");
      if(intraday_be_trigger  <= 0) intraday_be_trigger  = 25;
      if(intraday_be_offset   <= 0) intraday_be_offset   = 5;
      if(intraday_trail_start <= 0) intraday_trail_start = 40;
      if(intraday_trail_dist  <= 0) intraday_trail_dist  = 20;

      swing_be_trigger  = JsonGetDouble(json, "swing_be_trigger");
      swing_be_offset   = JsonGetDouble(json, "swing_be_offset_pips");
      swing_trail_start = JsonGetDouble(json, "swing_trail_start");
      swing_trail_dist  = JsonGetDouble(json, "swing_trail_dist");
      if(swing_be_trigger  <= 0) swing_be_trigger  = 60;
      if(swing_be_offset   <= 0) swing_be_offset   = 15;
      if(swing_trail_start <= 0) swing_trail_start = 100;
      if(swing_trail_dist  <= 0) swing_trail_dist  = 50;

      PrintFormat("[Supabase] Settings synced | S:%.2f I:%.2f Sw:%.2f | MinConf:%d MaxTrades:%d",
                  lot_scalping, lot_intraday, lot_swing, min_confidence, max_total_trades);
      return true;
   }

   //--- Write a new trade to active_trades
   bool WriteTrade(ulong ticket, const string symbol, const string direction,
                   double lot, double entry, const string style,
                   double v_sl, double v_tp,
                   double be_trig, double be_off,
                   double trail_start, double trail_dist)
   {
      string now = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS);
      StringReplace(now, ".", "-");  // 2026-06-10 → keep dashes
      // Supabase expects ISO 8601: replace space with T and add Z
      StringReplace(now, " ", "T");

      string payload = StringFormat(
         "{\"ticket\":%d,\"account_id\":\"%s\",\"symbol\":\"%s\","
         "\"direction\":\"%s\",\"lot\":%.2f,\"entry_price\":%.5f,"
         "\"trade_style\":\"%s\",\"virtual_sl\":%.5f,\"virtual_tp\":%.5f,"
         "\"be_trigger_pips\":%.1f,\"be_offset_pips\":%.1f,"
         "\"trail_start_pips\":%.1f,\"trail_dist_pips\":%.1f,"
         "\"current_status\":\"OPEN\",\"floating_profit\":0,"
         "\"opened_at\":\"%sZ\",\"updated_at\":\"%sZ\"}",
         ticket, m_account_id, symbol,
         direction, lot, entry,
         style, v_sl, v_tp,
         be_trig, be_off,
         trail_start, trail_dist,
         now, now
      );

      string url = m_base_url + "/rest/v1/active_trades";
      string extra_hdr = "apikey: " + m_anon_key + "\r\n"
                       + "Authorization: Bearer " + m_anon_key + "\r\n"
                       + "Content-Type: application/json\r\n"
                       + "Prefer: resolution=merge-duplicates,return=minimal\r\n";
      string resp;
      return HttpPOST(url, extra_hdr, payload, resp);
   }

   //--- Update active trade virtual SL/trailing in Supabase
   bool UpdateTradeVSL(ulong ticket, double new_vsl)
   {
      string url = m_base_url + "/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket);
      string payload = StringFormat("{\"virtual_sl\":%.5f}", new_vsl);
      return HttpPATCH(url, _BuildHeaders(true), payload);
   }

   //--- Close trade — write to closed_trades and update active_trades
   bool CloseTrade(ulong ticket, const string symbol, const string direction,
                   double lot, const string style, double pnl, const string reason)
   {
      // Write to closed_trades
      string now = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS);
      StringReplace(now, " ", "T");
      string cl_payload = StringFormat(
         "{\"ticket\":%d,\"account_id\":\"%s\",\"symbol\":\"%s\","
         "\"direction\":\"%s\",\"lot\":%.2f,\"trade_style\":\"%s\","
         "\"pnl\":%.2f,\"close_reason\":\"%s\",\"closed_at\":\"%sZ\"}",
         ticket, m_account_id, symbol,
         direction, lot, style,
         pnl, JsonEscape(reason), now
      );
      string extra_hdr = "apikey: " + m_anon_key + "\r\n"
                       + "Authorization: Bearer " + m_anon_key + "\r\n"
                       + "Content-Type: application/json\r\n"
                       + "Prefer: return=minimal\r\n";
      string resp;
      HttpPOST(m_base_url + "/rest/v1/closed_trades", extra_hdr, cl_payload, resp);

      // Update active_trades status
      string up_url = m_base_url + "/rest/v1/active_trades?ticket=eq." + IntegerToString(ticket);
      string up_payload = StringFormat(
         "{\"current_status\":\"CLOSED\",\"exit_reason\":\"%s\",\"floating_profit\":%.2f}",
         JsonEscape(reason), pnl
      );
      return HttpPATCH(up_url, _BuildHeaders(true), up_payload);
   }

   //--- Update balance/equity heartbeat (UPSERT via merge-duplicates)
   void Heartbeat(double balance, double equity)
   {
      string now = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS);
      StringReplace(now, ".", "-");
      StringReplace(now, " ", "T");

      // Minimal payload — only columns confirmed by Supabase schema
      string payload = StringFormat(
         "{\"account_id\":\"%s\",\"status\":\"online\","
         "\"balance\":%.2f,\"equity\":%.2f,\"last_seen_at\":\"%sZ\"}",
         m_account_id, balance, equity, now
      );

      string hdr = "apikey: " + m_anon_key + "\r\n"
                 + "Authorization: Bearer " + m_anon_key + "\r\n"
                 + "Content-Type: application/json\r\n"
                 + "Prefer: resolution=merge-duplicates,return=minimal\r\n";
      string resp;
      bool ok = HttpPOST(m_base_url + "/rest/v1/bot_heartbeat", hdr, payload, resp);
      if(!ok)
         PrintFormat("[Supabase] Heartbeat failed for account: %s", m_account_id);
   }

   //--- Write AI signal log to Supabase signals table (for dashboard visibility)
   void LogSignal(const string action, const string style, int confidence,
                  double sl, double tp, const string reason)
   {
      string now = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS);
      StringReplace(now, " ", "T");
      string payload = StringFormat(
         "{\"account_id\":\"%s\",\"symbol\":\"XAUUSD\",\"action\":\"%s\","
         "\"style\":\"%s\",\"confidence\":%d,\"sl\":%.5f,\"tp\":%.5f,"
         "\"reason\":\"%s\",\"is_active\":false,\"generated_at\":\"%sZ\"}",
         m_account_id, action, style, confidence, sl, tp,
         JsonEscape(reason), now
      );
      string extra_hdr = "apikey: " + m_anon_key + "\r\n"
                       + "Authorization: Bearer " + m_anon_key + "\r\n"
                       + "Content-Type: application/json\r\nPrefer: return=minimal\r\n";
      string resp;
      HttpPOST(m_base_url + "/rest/v1/signals", extra_hdr, payload, resp);
   }
};

#endif

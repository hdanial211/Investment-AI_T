//+------------------------------------------------------------------+
//|                                                  MarketData.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|        Collects OHLC, indicators and formats AI prompt JSON      |
//+------------------------------------------------------------------+
#ifndef MARKETDATA_MQH
#define MARKETDATA_MQH

//--- Collect and format market data for XAUUSDc into a JSON string for the AI prompt
//    symbol  : e.g. "XAUUSDc"
//    style   : "SCALPING", "INTRADAY", or "SWING"
//    Returns : compact JSON string, or "" on error
string BuildMarketDataJson(const string symbol, const string style)
{
   // ── 1. Determine timeframes based on style ────────────────────
   ENUM_TIMEFRAMES tf_main  = PERIOD_M5;
   ENUM_TIMEFRAMES tf_trend = PERIOD_H1;
   int bars_main  = 24;
   int bars_trend = 12;

   if(style == "INTRADAY")
   {
      tf_main  = PERIOD_M30;
      tf_trend = PERIOD_H4;
      bars_main  = 24;
      bars_trend = 10;
   }
   else if(style == "SWING")
   {
      tf_main  = PERIOD_H1;
      tf_trend = PERIOD_D1;
      bars_main  = 24;
      bars_trend = 10;
   }

   // ── 2. Compute indicators on tf_main ─────────────────────────
   // EMA 9 & 21
   int h_ema9  = iMA(symbol, tf_main, 9,  0, MODE_EMA, PRICE_CLOSE);
   int h_ema21 = iMA(symbol, tf_main, 21, 0, MODE_EMA, PRICE_CLOSE);
   int h_rsi   = iRSI(symbol, tf_main, 14, PRICE_CLOSE);
   int h_atr   = iATR(symbol, tf_main, 14);
   int h_macd  = iMACD(symbol, tf_main, 12, 26, 9, PRICE_CLOSE);

   // Trend EMA 50 on higher tf
   int h_ema50_trend = iMA(symbol, tf_trend, 50, 0, MODE_EMA, PRICE_CLOSE);

   if(h_ema9 == INVALID_HANDLE || h_ema21 == INVALID_HANDLE ||
      h_rsi  == INVALID_HANDLE || h_atr   == INVALID_HANDLE ||
      h_macd == INVALID_HANDLE || h_ema50_trend == INVALID_HANDLE)
   {
      Print("[MarketData] Failed to create indicator handles.");
      return "";
   }

   double ema9_buf[3], ema21_buf[3], rsi_buf[3], atr_buf[3];
   double macd_main[3], macd_signal[3];
   double ema50_trend[3];

   if(CopyBuffer(h_ema9,  0, 0, 3, ema9_buf)       <= 0 ||
      CopyBuffer(h_ema21, 0, 0, 3, ema21_buf)       <= 0 ||
      CopyBuffer(h_rsi,   0, 0, 3, rsi_buf)         <= 0 ||
      CopyBuffer(h_atr,   0, 0, 3, atr_buf)         <= 0 ||
      CopyBuffer(h_macd,  0, 0, 3, macd_main)       <= 0 ||
      CopyBuffer(h_macd,  1, 0, 3, macd_signal)     <= 0 ||
      CopyBuffer(h_ema50_trend, 0, 0, 3, ema50_trend) <= 0)
   {
      Print("[MarketData] Failed to copy indicator buffers.");
      IndicatorRelease(h_ema9); IndicatorRelease(h_ema21);
      IndicatorRelease(h_rsi);  IndicatorRelease(h_atr);
      IndicatorRelease(h_macd); IndicatorRelease(h_ema50_trend);
      return "";
   }

   // ── 3. Get recent OHLC bars (main TF) ────────────────────────
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, tf_main, 0, bars_main, rates);
   if(copied <= 0)
   {
      Print("[MarketData] Failed to copy OHLC rates.");
      return "";
   }

   // ── 4. Release handles ────────────────────────────────────────
   IndicatorRelease(h_ema9);       IndicatorRelease(h_ema21);
   IndicatorRelease(h_rsi);        IndicatorRelease(h_atr);
   IndicatorRelease(h_macd);       IndicatorRelease(h_ema50_trend);

   // ── 5. Determine session ──────────────────────────────────────
   MqlDateTime dt;
   TimeCurrent(dt);
   string session = "OTHER";
   if(dt.hour >= 0  && dt.hour < 8)  session = "ASIA";
   if(dt.hour >= 8  && dt.hour < 16) session = "LONDON";
   if(dt.hour >= 13 && dt.hour < 22) session = "NEWYORK";

   // ── 6. Trend direction ────────────────────────────────────────
   double cur_price = SymbolInfoDouble(symbol, SYMBOL_BID);
   string trend = (cur_price > ema50_trend[0]) ? "BULLISH" : "BEARISH";
   string macd_signal_str = (macd_main[0] > macd_signal[0]) ? "BULLISH_CROSS" : "BEARISH_CROSS";

   // ── 7. Build OHLC bars JSON array (last 8 bars) ───────────────
   string bars_json = "[";
   int max_bars = (copied < 8) ? copied : 8;
   for(int i = max_bars - 1; i >= 0; i--)
   {
      if(i != max_bars - 1) bars_json += ",";
      bars_json += StringFormat(
         "{\"o\":%.2f,\"h\":%.2f,\"l\":%.2f,\"c\":%.2f}",
         rates[i].open, rates[i].high, rates[i].low, rates[i].close
      );
   }
   bars_json += "]";

   // ── 8. Calculate spread ───────────────────────────────────────
   double ask  = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid  = SymbolInfoDouble(symbol, SYMBOL_BID);
   double spread_pts = (ask - bid) / SymbolInfoDouble(symbol, SYMBOL_POINT);

   // ── 9. Assemble final JSON ────────────────────────────────────
   string json = StringFormat(
      "{\"symbol\":\"XAUUSD\",\"style\":\"%s\","
      "\"tf_main\":\"%s\",\"tf_trend\":\"%s\","
      "\"price\":%.2f,\"spread_pts\":%.0f,"
      "\"ema9\":%.2f,\"ema21\":%.2f,"
      "\"rsi14\":%.1f,\"atr14\":%.2f,"
      "\"macd_hist\":%.4f,\"macd_signal\":\"%s\","
      "\"trend_higher_tf\":\"%s\","
      "\"session\":\"%s\","
      "\"bars_recent\":%s}",
      style,
      EnumToString(tf_main), EnumToString(tf_trend),
      cur_price, spread_pts,
      ema9_buf[0], ema21_buf[0],
      rsi_buf[0], atr_buf[0],
      (macd_main[0] - macd_signal[0]), macd_signal_str,
      trend,
      session,
      bars_json
   );

   return json;
}

#endif

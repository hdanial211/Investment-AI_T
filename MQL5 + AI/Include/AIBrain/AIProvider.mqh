//+------------------------------------------------------------------+
//|                                                  AIProvider.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|   Calls Groq API with 3-key rotation; parses AI JSON response   |
//+------------------------------------------------------------------+
#ifndef AIPROVIDER_MQH
#define AIPROVIDER_MQH

#include "HttpClient.mqh"
#include "JsonParser.mqh"

#define GROQ_ENDPOINT "https://api.groq.com/openai/v1/chat/completions"

//--- Struct to hold a parsed AI decision
struct AIDecision
{
   string action;        // "BUY", "SELL", or "HOLD"
   int    confidence;    // 0–100
   string style;         // "SCALPING", "INTRADAY", "SWING"
   double sl;            // Absolute SL price (0 = not given)
   double tp;            // Absolute TP price (0 = not given)
   string reason;        // Short explanation
   bool   valid;         // true if parsing succeeded
};

class CAIProvider
{
private:
   string m_keys[3];          // Up to 3 Groq API keys
   int    m_num_keys;
   string m_model;
   int    m_current_key;      // Key index to try next

   //--- Build the Groq POST body
   string _BuildBody(const string market_json)
   {
      // System role: concise gold trading analyst
      string sys_msg =
         "You are an expert XAUUSD (Gold) trading AI. "
         "Analyze the provided market data JSON and return ONLY a valid JSON object with fields: "
         "action (BUY/SELL/HOLD), confidence (0-100 integer), style (SCALPING/INTRADAY/SWING), "
         "sl (stop-loss price as float), tp (take-profit price as float), reason (max 30 words). "
         "Rules: "
         "SCALPING: tight SL 10-30 pips, TP 20-50 pips. "
         "INTRADAY: SL 30-80 pips, TP 60-150 pips. "
         "SWING: SL 80-200 pips, TP 150-400 pips. "
         "1 pip = $0.10 for Gold. Only output JSON, no other text.";

      string user_msg = "Market data: " + market_json
                      + "\nProvide your trading decision for the style: " 
                      + JsonGetString(market_json, "style");

      // Escape for JSON embedding
      string sys_escaped  = JsonEscape(sys_msg);
      string user_escaped = JsonEscape(user_msg);

      return StringFormat(
         "{\"model\":\"%s\","
         "\"messages\":["
           "{\"role\":\"system\",\"content\":\"%s\"},"
           "{\"role\":\"user\",\"content\":\"%s\"}"
         "],"
         "\"temperature\":0.1,"
         "\"max_tokens\":256,"
         "\"response_format\":{\"type\":\"json_object\"}"
         "}",
         m_model, sys_escaped, user_escaped
      );
   }

   //--- Parse the Groq response envelope → extract content string
   string _ExtractContent(const string response)
   {
      // Groq returns: {"choices":[{"message":{"content":"..."}}]}
      string choices_part = JsonGetString(response, "content");
      if(choices_part != "") return choices_part;

      // Fallback: find "content":" manually
      int pos = StringFind(response, "\"content\":\"");
      if(pos == -1) return "";
      pos += 11;
      int end = StringFind(response, "\"", pos);
      // Handle escaped quotes
      while(end != -1 && StringSubstr(response, end - 1, 1) == "\\")
         end = StringFind(response, "\"", end + 1);
      if(end == -1) return "";
      string raw = StringSubstr(response, pos, end - pos);
      StringReplace(raw, "\\\"", "\"");
      StringReplace(raw, "\\n", " ");
      return raw;
   }

   //--- Try a single Groq key, return AI response body or ""
   string _CallSingleKey(const string body, int key_idx)
   {
      if(key_idx >= m_num_keys || m_keys[key_idx] == "") return "";

      string headers = "Authorization: Bearer " + m_keys[key_idx] + "\r\n"
                     + "Content-Type: application/json\r\n";
      string resp;
      bool ok = HttpPOST(GROQ_ENDPOINT, headers, body, resp);
      if(ok && StringFind(resp, "\"content\"") != -1) return resp;
      PrintFormat("[AIProvider] Key[%d] failed or no content.", key_idx);
      return "";
   }

public:
   void Init(const string key1, const string key2, const string key3, const string model)
   {
      m_keys[0]     = key1;
      m_keys[1]     = key2;
      m_keys[2]     = key3;
      m_model       = (model != "") ? model : "llama-3.3-70b-versatile";
      m_num_keys    = 0;
      m_current_key = 0;
      for(int i = 0; i < 3; i++)
         if(m_keys[i] != "") m_num_keys++;
      PrintFormat("[AIProvider] Initialized with %d Groq key(s), model: %s", m_num_keys, m_model);
   }

   //--- Main entry point: call AI, rotate keys on failure
   AIDecision Analyze(const string market_json)
   {
      AIDecision result;
      result.valid      = false;
      result.action     = "HOLD";
      result.confidence = 0;
      result.style      = "";
      result.sl         = 0;
      result.tp         = 0;
      result.reason     = "";

      if(m_num_keys == 0)
      {
         Print("[AIProvider] No API keys configured!");
         return result;
      }

      string body = _BuildBody(market_json);
      string resp = "";

      // Rotate through keys
      for(int attempt = 0; attempt < m_num_keys; attempt++)
      {
         int idx = (m_current_key + attempt) % m_num_keys;
         resp = _CallSingleKey(body, idx);
         if(resp != "")
         {
            m_current_key = (idx + 1) % m_num_keys; // next call starts from next key
            break;
         }
      }

      if(resp == "")
      {
         Print("[AIProvider] All Groq keys exhausted, no response.");
         return result;
      }

      // Extract content JSON
      string content = _ExtractContent(resp);
      if(content == "")
      {
         Print("[AIProvider] Could not extract content from response.");
         return result;
      }

      // Strip ```json fences if present
      if(StringFind(content, "```json") != -1)
         StringReplace(content, "```json", "");
      StringReplace(content, "```", "");
      
      // Trim whitespace
      StringTrimLeft(content);
      StringTrimRight(content);

      // Parse decision fields
      result.action     = JsonGetString(content, "action");
      result.confidence = JsonGetInt(content, "confidence");
      result.style      = JsonGetString(content, "style");
      result.sl         = JsonGetDouble(content, "sl");
      result.tp         = JsonGetDouble(content, "tp");
      result.reason     = JsonGetString(content, "reason");

      // Validate
      StringToUpper(result.action);
      if(result.action != "BUY" && result.action != "SELL" && result.action != "HOLD")
         result.action = "HOLD";
      if(result.confidence < 0 || result.confidence > 100) result.confidence = 0;

      result.valid = true;
      PrintFormat("[AIProvider] Decision: %s | Conf: %d%% | Style: %s | SL: %.2f | TP: %.2f | %s",
                  result.action, result.confidence, result.style, result.sl, result.tp, result.reason);
      return result;
   }
};

#endif

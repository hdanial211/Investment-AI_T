//+------------------------------------------------------------------+
//|                                                   JsonParser.mqh |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|          JSON string extraction utilities (no external library)  |
//+------------------------------------------------------------------+
#ifndef JSONPARSER_MQH
#define JSONPARSER_MQH

//--- Extract a string or number value by key from a flat JSON object
string JsonGetString(const string json, const string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos == -1) return "";
   pos += StringLen(search);

   // Skip whitespace
   while(pos < StringLen(json) && StringSubstr(json, pos, 1) == " ") pos++;

   string result = "";
   string fc = StringSubstr(json, pos, 1);

   if(fc == "\"") // String value
   {
      pos++;
      int endPos = StringFind(json, "\"", pos);
      if(endPos == -1) return "";
      result = StringSubstr(json, pos, endPos - pos);
   }
   else // Number / bool / null
   {
      int e1 = StringFind(json, ",", pos);
      int e2 = StringFind(json, "}", pos);
      int e3 = StringFind(json, "]", pos);
      int endPos = e1;
      if(endPos == -1 || (e2 != -1 && e2 < endPos)) endPos = e2;
      if(endPos == -1 || (e3 != -1 && e3 < endPos)) endPos = e3;
      if(endPos == -1) return "";
      result = StringSubstr(json, pos, endPos - pos);
      StringReplace(result, " ", "");
      StringReplace(result, "\r", "");
      StringReplace(result, "\n", "");
   }
   return result;
}

double JsonGetDouble(const string json, const string key)
{
   string v = JsonGetString(json, key);
   if(v == "" || v == "null") return 0.0;
   return StringToDouble(v);
}

int JsonGetInt(const string json, const string key)
{
   string v = JsonGetString(json, key);
   if(v == "" || v == "null") return 0;
   return (int)StringToInteger(v);
}

bool JsonGetBool(const string json, const string key)
{
   string v = JsonGetString(json, key);
   StringToLower(v);
   return (v == "true" || v == "1");
}

//--- Extract the first array element that matches a key prefix
//    (splits array objects by "},{"  then searches each chunk)
int JsonSplitArray(const string json, string &chunks[])
{
   string work = json;
   // Strip outer [ ]
   int s = StringFind(work, "[");
   int e = StringFind(work, "]");
   if(s == -1 || e == -1) { ArrayResize(chunks, 0); return 0; }
   work = StringSubstr(work, s + 1, e - s - 1);
   if(StringFind(work, "{") == -1) { ArrayResize(chunks, 0); return 0; }

   StringReplace(work, "},{", "|");
   return StringSplit(work, '|', chunks);
}

//--- Extract nested object string for a key (returns the {...} block)
string JsonGetObject(const string json, const string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos == -1) return "";
   pos += StringLen(search);
   while(pos < StringLen(json) && StringSubstr(json, pos, 1) == " ") pos++;
   if(StringSubstr(json, pos, 1) != "{") return "";
   int depth = 0, start = pos;
   for(int i = pos; i < StringLen(json); i++)
   {
      string c = StringSubstr(json, i, 1);
      if(c == "{") depth++;
      else if(c == "}") { depth--; if(depth == 0) return StringSubstr(json, start, i - start + 1); }
   }
   return "";
}

//--- Escape a string for safe inclusion in a JSON payload
string JsonEscape(const string s)
{
   string r = s;
   StringReplace(r, "\\", "\\\\");
   StringReplace(r, "\"", "\\\"");
   StringReplace(r, "\n", "\\n");
   StringReplace(r, "\r", "\\r");
   return r;
}

#endif

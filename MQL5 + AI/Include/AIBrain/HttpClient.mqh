//+------------------------------------------------------------------+
//|                                                  HttpClient.mqh  |
//|                         Investment-AI_T v5 — MQL5+AI Standalone  |
//|          WebRequest wrapper with timeout + retry + logging       |
//+------------------------------------------------------------------+
#ifndef HTTPCLIENT_MQH
#define HTTPCLIENT_MQH

// Max retry attempts for any HTTP request
#define HTTP_MAX_RETRIES   3
#define HTTP_TIMEOUT_MS    8000
#define HTTP_RETRY_WAIT_MS 1500

//--- Perform GET request, returns response body string or "" on failure
string HttpGET(const string url, const string headers, int timeout = HTTP_TIMEOUT_MS)
{
   char   post[], result[];
   string result_headers;

   for(int attempt = 1; attempt <= HTTP_MAX_RETRIES; attempt++)
   {
      ResetLastError();
      int code = WebRequest("GET", url, headers, timeout, post, result, result_headers);
      if(code == 200 || code == 201)
         return CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);

      if(code == -1)
         PrintFormat("[HttpGET] Attempt %d failed — WinError %d | URL: %s", attempt, GetLastError(), url);
      else
         PrintFormat("[HttpGET] Attempt %d HTTP %d | URL: %s", attempt, code, url);

      if(attempt < HTTP_MAX_RETRIES) Sleep(HTTP_RETRY_WAIT_MS);
   }
   return "";
}

//--- Perform POST request, returns true on success (200/201/204)
bool HttpPOST(const string url, const string headers, const string payload,
              string &response_out, int timeout = HTTP_TIMEOUT_MS)
{
   char   post[], result[];
   string result_headers;
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(post) > 0) ArrayResize(post, ArraySize(post) - 1); // remove null terminator

   for(int attempt = 1; attempt <= HTTP_MAX_RETRIES; attempt++)
   {
      ResetLastError();
      int code = WebRequest("POST", url, headers, timeout, post, result, result_headers);
      if(code == 200 || code == 201 || code == 204)
      {
         response_out = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
         return true;
      }
      PrintFormat("[HttpPOST] Attempt %d HTTP %d (WinErr %d) | URL: %s", attempt, code, GetLastError(), url);
      if(attempt < HTTP_MAX_RETRIES) Sleep(HTTP_RETRY_WAIT_MS);
   }
   response_out = "";
   return false;
}

//--- Perform PATCH request
bool HttpPATCH(const string url, const string headers, const string payload,
               int timeout = HTTP_TIMEOUT_MS)
{
   char   post[], result[];
   string result_headers;
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(post) > 0) ArrayResize(post, ArraySize(post) - 1);

   for(int attempt = 1; attempt <= HTTP_MAX_RETRIES; attempt++)
   {
      ResetLastError();
      int code = WebRequest("PATCH", url, headers, timeout, post, result, result_headers);
      if(code == 200 || code == 204) return true;
      PrintFormat("[HttpPATCH] Attempt %d HTTP %d | URL: %s", attempt, code, url);
      if(attempt < HTTP_MAX_RETRIES) Sleep(HTTP_RETRY_WAIT_MS);
   }
   return false;
}

//--- Perform DELETE request
bool HttpDELETE(const string url, const string headers, int timeout = HTTP_TIMEOUT_MS)
{
   char   post[], result[];
   string result_headers;

   for(int attempt = 1; attempt <= HTTP_MAX_RETRIES; attempt++)
   {
      ResetLastError();
      int code = WebRequest("DELETE", url, headers, timeout, post, result, result_headers);
      if(code == 200 || code == 204) return true;
      PrintFormat("[HttpDELETE] Attempt %d HTTP %d | URL: %s", attempt, code, url);
      if(attempt < HTTP_MAX_RETRIES) Sleep(HTTP_RETRY_WAIT_MS);
   }
   return false;
}

#endif

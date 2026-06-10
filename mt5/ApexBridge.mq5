//+------------------------------------------------------------------+
//| ApexBridge.mq5 — connects MetaTrader 5 to your Apex Forex Bot    |
//|                                                                  |
//| The bot (running on your Railway server) does all the analysis. |
//| This EA only feeds it market data and executes its commands —   |
//| so every trade appears right here in your MetaTrader, with      |
//| SL/TP visible on the chart.                                     |
//|                                                                  |
//| SETUP                                                            |
//| 1. Copy this file to MetaTrader: File → Open Data Folder →      |
//|    MQL5/Experts, then restart MT5 (or refresh the Navigator).   |
//| 2. Tools → Options → Expert Advisors →                          |
//|    ✓ "Allow WebRequest for listed URL" → add your bot URL       |
//|      (e.g. https://your-app.up.railway.app)                     |
//| 3. Drag the EA onto the chart of the pair you want to trade.    |
//| 4. Set BotURL + Secret (same as MT_BRIDGE_SECRET in the bot).   |
//| 5. Enable Algo Trading (toolbar button). Done.                  |
//+------------------------------------------------------------------+
#property copyright "Apex Forex Bot"
#property link      "https://aicashsystem.space"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input string BotURL      = "https://your-app.up.railway.app"; // Bot URL (no trailing slash)
input string Secret      = "";                                // MT_BRIDGE_SECRET from the bot
input int    SyncSeconds = 10;                                // Sync interval (seconds)
input int    CandleCount = 210;                               // Candles sent to the bot
input ENUM_TIMEFRAMES Timeframe = PERIOD_M5;                  // Must match bot TIMEFRAME

CTrade  trade;
string  g_acks = "";        // ACK lines queued for the next sync
int     g_failures = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   if(StringLen(Secret) < 8)
   {
      Alert("ApexBridge: set a Secret (8+ chars, same as MT_BRIDGE_SECRET in the bot).");
      return(INIT_PARAMETERS_INCORRECT);
   }
   trade.SetDeviationInPoints(20);
   EventSetTimer(SyncSeconds);
   Print("ApexBridge started → ", BotURL, " (", _Symbol, " ", EnumToString(Timeframe), ")");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| Build the snapshot and exchange it with the bot                  |
//+------------------------------------------------------------------+
void OnTimer()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;

   string body = "SECRET=" + Secret + "\n";
   body += "SYMBOL=" + _Symbol + "\n";
   body += "BID=" + DoubleToString(tick.bid, _Digits) + "\n";
   body += "ASK=" + DoubleToString(tick.ask, _Digits) + "\n";
   body += "BALANCE=" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\n";
   body += "EQUITY=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + "\n";

   if(PositionSelect(_Symbol))
   {
      string side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      body += "POSITION=" + side + "|" +
              DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + "|" +
              DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), _Digits) + "\n";
   }
   else body += "POSITION=NONE\n";

   body += g_acks;

   MqlRates rates[];
   int n = CopyRates(_Symbol, Timeframe, 0, CandleCount, rates);
   for(int i = 0; i < n; i++)
   {
      body += "CANDLE=" + (string)(long)rates[i].time + "|" +
              DoubleToString(rates[i].open,  _Digits) + "|" +
              DoubleToString(rates[i].high,  _Digits) + "|" +
              DoubleToString(rates[i].low,   _Digits) + "|" +
              DoubleToString(rates[i].close, _Digits) + "|" +
              (string)rates[i].tick_volume + "\n";
   }

   char data[], result[];
   string headers;
   StringToCharArray(body, data, 0, StringLen(body), CP_UTF8);

   ResetLastError();
   int status = WebRequest("POST", BotURL + "/api/mt/sync",
                           "Content-Type: text/plain\r\n", 10000,
                           data, result, headers);
   if(status != 200)
   {
      g_failures++;
      if(g_failures == 1 || g_failures % 30 == 0)
         Print("ApexBridge: sync failed (HTTP ", status, ", err ", GetLastError(),
               "). Is the URL whitelisted in Tools->Options->Expert Advisors?");
      return;
   }
   if(g_failures > 0) { Print("ApexBridge: reconnected."); g_failures = 0; }
   g_acks = "";

   string resp = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   string lines[];
   int k = StringSplit(resp, '\n', lines);
   for(int i = 0; i < k; i++)
      if(StringFind(lines[i], "CMD=") == 0)
         HandleCommand(StringSubstr(lines[i], 4));
}

//+------------------------------------------------------------------+
//| Execute one bot command: id|OPEN|side|lots|sl|tp  or  id|CLOSE   |
//+------------------------------------------------------------------+
void HandleCommand(string cmd)
{
   string p[];
   int n = StringSplit(cmd, '|', p);
   if(n < 2) return;
   string id = p[0], action = p[1];

   if(action == "OPEN" && n >= 6)
   {
      double lots = NormalizeLots(StringToDouble(p[3]));
      double sl   = StringToDouble(p[4]);
      double tp   = StringToDouble(p[5]);
      bool ok;
      if(p[2] == "BUY")
         ok = trade.Buy(lots, _Symbol, 0.0, sl, tp, "ApexBot");
      else
         ok = trade.Sell(lots, _Symbol, 0.0, sl, tp, "ApexBot");
      double fill = trade.ResultPrice();
      g_acks += "ACK=" + id + "|" + (ok ? "FILLED" : "REJECTED") + "|" +
                DoubleToString(fill, _Digits) + "\n";
      Print("ApexBridge: OPEN ", p[2], " ", DoubleToString(lots, 2), " → ",
            ok ? "filled @ " + DoubleToString(fill, _Digits) : "REJECTED " + (string)trade.ResultRetcode());
   }
   else if(action == "CLOSE")
   {
      bool ok = true;
      double px = 0;
      if(PositionSelect(_Symbol))
      {
         ok = trade.PositionClose(_Symbol);
         px = trade.ResultPrice();
      }
      g_acks += "ACK=" + id + "|" + (ok ? "CLOSED" : "REJECTED") + "|" +
                DoubleToString(px, _Digits) + "\n";
      Print("ApexBridge: CLOSE → ", ok ? "done" : "REJECTED");
   }
   else
   {
      // Unknown command — ack it so the queue doesn't jam
      g_acks += "ACK=" + id + "|REJECTED|0\n";
   }
}

//+------------------------------------------------------------------+
//| Clamp lots to the broker's min/step/max                          |
//+------------------------------------------------------------------+
double NormalizeLots(double lots)
{
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step > 0) lots = MathFloor(lots / step) * step;
   return(MathMin(MathMax(lots, minLot), maxLot));
}
//+------------------------------------------------------------------+

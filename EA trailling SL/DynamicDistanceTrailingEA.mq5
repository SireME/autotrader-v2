//+------------------------------------------------------------------+
//|                  Dynamic Distance Trailing EA v1.1               |
//| Trails SL maintaining original entry→SL distance as price moves  |
//| Removes TP on first SL modification only                         |
//+------------------------------------------------------------------+
#property strict

//--- Inputs
input int    InpMagicNumber  = 123456;   // Magic Number (0 = all positions)
input double InpMinStepPoints = 1.0;     // Min SL movement in points before modifying

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("Dynamic Distance Trailing EA v1.1 started. Magic=", InpMagicNumber,
         " MinStep=", InpMinStepPoints, " pts");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   TrailPositions();
}

//+------------------------------------------------------------------+
//| Main trailing logic                                              |
//+------------------------------------------------------------------+
void TrailPositions()
{
   int total = PositionsTotal();

   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);

      if(!PositionSelectByTicket(ticket))
         continue;

      //--- Filter by symbol
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;

      //--- Filter by magic number (0 = manage all)
      if(InpMagicNumber != 0 && PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      long   type  = PositionGetInteger(POSITION_TYPE);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      //--- Skip positions with no SL set
      if(sl == 0.0)
         continue;

      double point    = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      double minStep  = InpMinStepPoints * point;

      //--- Fetch broker minimum stop distance (in price)
      long   stopLevelPts = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
      double stopLevel    = stopLevelPts * point;

      double newSL = 0.0;

      //--- BUY: SL must be below current bid
      if(type == POSITION_TYPE_BUY)
      {
         double distance = entry - sl;   // original gap (always positive for valid buy SL)

         if(distance <= 0.0) continue;  // malformed position, skip

         newSL = bid - distance;

         //--- Only modify if improvement exceeds minimum step
         if(newSL - sl < minStep)
            continue;

         //--- Broker stop-level check: SL must be >= stopLevel below bid
         if(bid - newSL < stopLevel)
            newSL = bid - stopLevel;

         //--- After clipping, still an improvement?
         if(newSL - sl < minStep)
            continue;
      }

      //--- SELL: SL must be above current ask
      else if(type == POSITION_TYPE_SELL)
      {
         double distance = sl - entry;   // original gap (always positive for valid sell SL)

         if(distance <= 0.0) continue;  // malformed position, skip

         newSL = ask + distance;

         //--- Only modify if improvement exceeds minimum step
         if(sl - newSL < minStep)
            continue;

         //--- Broker stop-level check: SL must be >= stopLevel above ask
         if(newSL - ask < stopLevel)
            newSL = ask + stopLevel;

         //--- After clipping, still an improvement?
         if(sl - newSL < minStep)
            continue;
      }
      else
         continue;

      //--- Remove TP only on the first SL modification (while TP still exists)
      double newTP = tp;          // preserve existing TP by default
      if(tp != 0.0) newTP = 0.0; // clear TP once, and only once

      ModifySL(ticket, newSL, newTP);
   }
}

//+------------------------------------------------------------------+
//| Modify SL (and optionally TP) via TRADE_ACTION_SLTP             |
//+------------------------------------------------------------------+
void ModifySL(ulong ticket, double newSL, double newTP)
{
   MqlTradeRequest request;
   MqlTradeResult  result;

   ZeroMemory(request);
   ZeroMemory(result);

   request.action   = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.symbol   = _Symbol;
   request.sl       = NormalizeDouble(newSL, _Digits);
   request.tp       = NormalizeDouble(newTP, _Digits);
   request.magic    = InpMagicNumber;

   bool sent = OrderSend(request, result);

   if(!sent || result.retcode != TRADE_RETCODE_DONE)
   {
      Print("Modify failed | Ticket=", ticket,
            " retcode=", result.retcode,
            " comment=", result.comment,
            " newSL=",   DoubleToString(newSL, _Digits),
            " newTP=",   DoubleToString(newTP, _Digits));
   }
   else
   {
      Print("Trail OK | Ticket=", ticket,
            " SL: ", DoubleToString(request.sl, _Digits),
            " TP: ", (newTP == 0.0 ? "removed" : DoubleToString(request.tp, _Digits)));
   }
}
//+------------------------------------------------------------------+

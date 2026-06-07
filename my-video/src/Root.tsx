import "./index.css";
import { Composition } from "remotion";
import { MyComposition } from "./Composition";
import { BotScanComposition, TradeExecComposition, DailyStatsComposition } from "./TradingScenes";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Original promo ad — 11s square + wide */}
      <Composition
        id="AiCashAd"
        component={MyComposition}
        durationInFrames={330}
        fps={30}
        width={1080}
        height={1080}
      />
      <Composition
        id="AiCashAdWide"
        component={MyComposition}
        durationInFrames={330}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* Bot Scan — 15s: AI scanning 847 pairs, signal found */}
      <Composition
        id="BotScan"
        component={BotScanComposition}
        durationInFrames={450}
        fps={30}
        width={1080}
        height={1080}
      />
      <Composition
        id="BotScanWide"
        component={BotScanComposition}
        durationInFrames={450}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* Trade Execution — 12s: order placed → P&L → profit closed */}
      <Composition
        id="TradeExec"
        component={TradeExecComposition}
        durationInFrames={360}
        fps={30}
        width={1080}
        height={1080}
      />
      <Composition
        id="TradeExecWide"
        component={TradeExecComposition}
        durationInFrames={360}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* Daily Stats — 10s: all 6 trades, +$84 today */}
      <Composition
        id="DailyStats"
        component={DailyStatsComposition}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1080}
      />
      <Composition
        id="DailyStatsWide"
        component={DailyStatsComposition}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};

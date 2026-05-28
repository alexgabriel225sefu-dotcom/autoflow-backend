# Apex Trade Bot V2 — Complete Feature Documentation

## Overview

Apex Trade Bot V2 is a production-ready algorithmic trading dashboard featuring advanced risk management, AI-powered signal generation, and comprehensive performance tracking. Built with React 19, Express 4, tRPC 11, and Drizzle ORM.

## Core Features

### 1. Real-Time Trading Dashboard

**Live Statistics Cards**
- **Account Balance**: Current trading account balance with historical tracking
- **Profit/Loss (PnL)**: Real-time profit or loss calculation
- **Win Rate**: Percentage of winning trades vs total trades
- **Open Position**: Current active trade with entry price and unrealized PnL
- **Tick Counter**: Real-time market activity indicator

**Responsive Grid Layout**
- Cinematic dark theme with teal/burnt-orange gradients
- Glowing effect on stats cards for visual emphasis
- Mobile-responsive design for all screen sizes
- Smooth animations and transitions

### 2. Trade History Management

**Interactive Trade Table**
- Symbol, side (LONG/SHORT), entry price, exit price, PnL, close reason
- Trade filtering and sorting capabilities
- Pagination for large datasets
- Real-time updates as trades execute
- Color-coded rows (green for wins, red for losses)

**Trade Lifecycle Tracking**
- Automatic trade creation on entry signal
- Real-time position updates
- Trade closure with exit price and PnL calculation
- Close reason tracking (TAKE_PROFIT, STOP_LOSS, MANUAL, etc.)

### 3. Advanced Risk Management

**Breakeven Protection**
- Automatically moves stop loss to entry price after reaching X% profit
- Configurable profit trigger percentage
- Eliminates risk after initial profit target
- Prevents catastrophic losses on winning trades

**Partial Take Profit**
- Closes configurable percentage of position at first TP level
- Locks in profits while allowing remainder to run
- Typical configuration: Close 50% at TP1, let 50% run to TP2
- Improves risk/reward ratio

**Daily Loss Limit**
- Stops all trading when daily losses exceed threshold
- Prevents over-trading during losing streaks
- Configurable in USD amount
- Automatic enforcement with owner notifications

### 4. AI Signal Panel

**Real-Time Signal Generation**
- BUY, SELL, or HOLD recommendations
- Confidence percentage (0-100%)
- Criteria score (0-5 stars)
- LLM-generated reasoning and analysis

**Strategy Confluence Display**
- **Turtle Breakout**: Breakout-based entry signals with strength indicator
- **Livermore Structure**: Price structure and support/resistance analysis
- **Soros Momentum**: Momentum-based directional signals
- Visual strength indicators (STRONG, MODERATE, WEAK)

**On-Demand Analysis**
- "Analyze Now" button triggers fresh market assessment
- Real-time indicator confluence evaluation
- Recommended action with detailed reasoning
- Timestamp tracking for signal history

### 5. Multi-Timeframe Analysis

**Trend Confirmation**
- Analyzes 1h and 4h trends alongside 5m signals
- Prevents counter-trend entries on lower timeframes
- Confluence detection for higher probability setups
- Visual trend indicators (UPTREND, DOWNTREND, RANGING)

**Timeframe Alignment**
- Ensures trading direction aligns with larger timeframe bias
- Reduces false signals from lower timeframe noise
- Improves win rate through trend confirmation

### 6. Paper Trading Simulator

**Virtual Trading Environment**
- Simulates trades without risking real capital
- Configurable starting balance (default: $10,000)
- Real-time balance tracking
- Automatic PnL calculation

**Performance Metrics**
- Total trades executed
- Win/loss count and win rate percentage
- Maximum drawdown calculation
- Equity curve visualization
- Reset functionality for new simulations

**Strategy Testing**
- Test bot configuration before live trading
- Validate risk management settings
- Backtest strategy performance
- Optimize parameters based on results

### 7. Bot Configuration Panel

**Trading Parameters**
- Symbol selection (e.g., SOLUSDT, ETHUSDT)
- Timeframe selection (1m, 5m, 15m, 1h, 4h, 1d)
- Risk per trade percentage (default: 2%)
- Stop loss percentage (default: 0.8%)
- Take profit percentage (default: 1.6%)

**AI Confidence Settings**
- Minimum confidence threshold for entries (0-100%)
- Criteria score requirements
- Signal filtering options

**Live Updates**
- Changes saved immediately to database
- Environment variables updated in real-time
- No restart required for config changes
- Configuration validation before saving

### 8. Telegram Alert Log

**Alert Management**
- Displays last 20 alerts with type icons and timestamps
- Search functionality for finding specific alerts
- Filter by alert type (TRADE_OPEN, TRADE_CLOSE, STOP_HIT, DAILY_LIMIT, etc.)
- Alert statistics summary

**Alert Types**
- 📈 **TRADE_OPEN**: New trade initiated
- 📉 **TRADE_CLOSE**: Trade closed with PnL
- 🛑 **STOP_HIT**: Stop loss triggered
- ⚠️ **DAILY_LIMIT**: Daily loss limit reached
- 🚫 **STRATEGY_STOP**: Strategy-based stop triggered
- 🔇 **SIGNAL_FILTERED**: Signal filtered out by criteria

**Alert Persistence**
- All alerts stored in database
- Historical alert tracking
- Alert filtering by date range
- Export capability for analysis

### 9. In-App Notifications

**Real-Time Alerts**
- Instant notification on trade open
- Immediate alert on trade close with PnL
- Stop loss hit notifications
- Daily loss limit breach alerts
- Strategy-based stop notifications

**Notification Channels**
- In-app toast notifications
- Email notifications to bot owner
- Telegram integration for mobile alerts
- Notification history in alert log

### 10. Database Persistence

**Trade History**
- Complete trade record with all parameters
- Entry/exit prices and timestamps
- PnL calculation and tracking
- Close reason documentation

**Configuration Storage**
- Bot parameters persisted across sessions
- Risk management settings saved
- Paper trading state maintained
- User preferences stored

**Daily Snapshots**
- End-of-day performance summary
- Daily PnL tracking
- Trade count and win rate
- Equity curve data points
- Historical performance analysis

**Alert Logging**
- All alerts stored with timestamps
- Alert type categorization
- Trade association for context
- Searchable alert history

## Technical Architecture

### Frontend Stack
- **React 19**: Modern UI framework with hooks
- **TypeScript**: Type-safe development
- **Tailwind CSS 4**: Utility-first styling with gradients
- **shadcn/ui**: Pre-built accessible components
- **tRPC**: End-to-end type-safe API calls
- **Framer Motion**: Smooth animations

### Backend Stack
- **Express 4**: HTTP server framework
- **tRPC 11**: Type-safe RPC procedures
- **Drizzle ORM**: Type-safe database queries
- **MySQL/TiDB**: Relational database
- **Node.js**: JavaScript runtime

### Database Schema
- **users**: User authentication and profile
- **trades**: Trade history and execution records
- **botConfigs**: Bot parameters and settings
- **alerts**: Alert log and notifications
- **dailySnapshots**: Performance tracking and statistics
- **paperTradingStates**: Paper trading simulation data

## Security Features

- **OAuth2 Authentication**: Manus OAuth integration
- **JWT Sessions**: Secure session management
- **Environment Variables**: Secrets never committed
- **Database Encryption**: Sensitive data protection
- **HTTPS Enforcement**: Secure transport layer
- **Input Validation**: tRPC schema validation
- **SQL Injection Prevention**: Drizzle ORM parameterized queries

## Performance Optimizations

- **Lazy Loading**: Components load on demand
- **Query Optimization**: Efficient database queries
- **Caching**: Response caching for repeated queries
- **Pagination**: Large datasets paginated
- **Real-Time Updates**: Efficient polling mechanism
- **Code Splitting**: Optimized bundle size

## Deployment

### Local Development
```bash
pnpm install
pnpm dev
```

### Production Deployment
```bash
pnpm build
pnpm start
```

### Railway Deployment
See `DEPLOYMENT.md` for complete Railway setup instructions.

## Configuration

### Environment Variables
```
DATABASE_URL=mysql://user:pass@host/db
JWT_SECRET=your-secret-key
VITE_APP_ID=your-app-id
OAUTH_SERVER_URL=https://api.manus.im
OWNER_OPEN_ID=your-owner-id
```

### Bot Parameters
- Symbol: Trading pair (e.g., SOLUSDT)
- Timeframe: Candle period (5m, 15m, 1h, 4h)
- Risk %: Percentage of balance to risk per trade
- SL %: Stop loss distance from entry
- TP %: Take profit distance from entry
- Min Confidence: Minimum AI confidence for entry

## Future Enhancements

- Real-time WebSocket updates instead of polling
- Advanced backtesting engine
- Multiple strategy support
- Portfolio management across symbols
- Advanced charting with TradingView integration
- Machine learning signal optimization
- Risk analytics and portfolio metrics
- Automated report generation
- API for third-party integrations

## Support & Documentation

- **DEPLOYMENT.md**: Railway deployment guide
- **README.md**: Project overview
- **FEATURES.md**: This file
- **Inline Comments**: Code documentation
- **Type Definitions**: TypeScript for IDE support

## License

MIT License - See LICENSE file for details

---

**Version**: 1.0.0  
**Last Updated**: May 28, 2026  
**Status**: Production Ready

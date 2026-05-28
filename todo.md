# Apex Trade Bot V2 — Project TODO

## Database & Backend
- [ ] Design database schema (trades, alerts, bot_config, daily_snapshots)
- [ ] Create Drizzle schema migrations
- [ ] Build tRPC procedures for trade history, bot stats, and configuration
- [ ] Implement bot state management (balance, open position, session data)
- [ ] Create alert logging system (Telegram alerts to database)
- [ ] Build LLM integration for on-demand market analysis

## Dashboard UI — Core Layout
- [ ] Design cinematic dark theme with teal/burnt-orange gradients
- [ ] Create main dashboard layout with sidebar navigation
- [ ] Implement responsive grid system for stats cards
- [ ] Build loading skeletons and error states

## Real-Time Stats & Monitoring
- [ ] Build live stats cards (balance, PnL, win rate, tick counter)
- [ ] Implement open position status display
- [ ] Create real-time update mechanism (polling or WebSocket)
- [ ] Add performance metrics visualization

## Trade History & Charts
- [ ] Build interactive trade history table
- [ ] Implement TradingView chart widget integration
- [ ] Add RSI and Moving Average overlays to charts
- [ ] Create trade filtering and sorting functionality

## Multi-Timeframe Analysis
- [ ] Build multi-timeframe trend panel (1h/4h vs 5m)
- [ ] Implement trend visualization with color indicators
- [ ] Add confluence detection logic

## Strategy Confluence Panel
- [ ] Display Turtle Breakout signals with strength
- [ ] Display Livermore Structure signals with strength
- [ ] Display Soros Momentum signals with direction
- [ ] Create visual strength indicators (bars, percentages)

## AI Signal Panel
- [ ] Display current AI action (BUY/SELL/HOLD)
- [ ] Show confidence percentage and criteria score
- [ ] Render LLM reasoning in formatted text
- [ ] Implement "Analyze Now" button for on-demand analysis
- [ ] Add signal history/logging

## Advanced Risk Management
- [ ] Implement Breakeven control (auto-move SL after X% profit)
- [ ] Implement Partial Take Profit (close 50% at TP1)
- [ ] Build daily loss limit configuration and enforcement
- [ ] Create risk management status display
- [ ] Add manual position close functionality

## Bot Configuration Panel
- [ ] Build configuration form (symbol, timeframe, risk %, SL/TP %)
- [ ] Implement live save to environment variables
- [ ] Add validation and error handling
- [ ] Create configuration history/audit log
- [ ] Add preset configurations for different assets

## Telegram Alert Log
- [ ] Build alert feed UI (last 20 alerts)
- [ ] Add type icons and timestamps
- [ ] Implement alert filtering and search
- [ ] Create alert detail view
- [ ] Add alert statistics

## Paper Trading Mode
- [ ] Build simulator mode toggle
- [ ] Implement virtual balance management
- [ ] Create performance stats display
- [ ] Add virtual balance reset functionality
- [ ] Build comparison view (paper vs live)

## Notifications
- [ ] Implement in-app toast notifications
- [ ] Build email notification system
- [ ] Add notification preferences/settings
- [ ] Create notification history log
- [ ] Implement notification triggers (trade open/close, stop hit, daily loss limit)

## Database Persistence
- [ ] Persist trade history to database
- [ ] Store daily PnL snapshots
- [ ] Save bot configuration changes
- [ ] Create performance tracking queries
- [ ] Build historical charts and statistics

## Testing & Quality
- [ ] Write unit tests for tRPC procedures
- [ ] Create integration tests for bot logic
- [ ] Test UI components with Vitest
- [ ] Performance optimization and profiling
- [ ] Security audit and validation

## Deployment
- [ ] Set up GitHub repository connection
- [ ] Configure Railway environment variables
- [ ] Deploy to Railway with GitHub integration
- [ ] Set up CI/CD pipeline
- [ ] Create deployment documentation

## Completed Features
- [x] Project initialized with web-db-user scaffold
- [x] Initial project structure created

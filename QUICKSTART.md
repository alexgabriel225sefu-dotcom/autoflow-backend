# Apex Trade Bot V2 — Quick Start Guide

## Getting Started in 5 Minutes

### 1. Access the Dashboard

Once deployed, navigate to your Railway URL:
```
https://your-app-name.railway.app
```

### 2. Login

- Click "Login" button
- Authenticate via Manus OAuth
- You'll be redirected to the dashboard

### 3. Configure Your Bot

**Go to Settings → Basic Settings**

Set your trading parameters:
- **Symbol**: SOLUSDT (or your preferred pair)
- **Timeframe**: 5m (recommended for active trading)
- **Risk Per Trade**: 2% (of your account balance)
- **Stop Loss**: 0.8% (distance from entry)
- **Take Profit**: 1.6% (distance from entry)
- **Min Confidence**: 62% (AI signal threshold)

Click **Save Settings**

### 4. Enable Risk Management

**Go to Settings → Risk Management**

Enable these critical features:

**Breakeven Protection**
- Toggle: ON
- Trigger: 0.5% profit
- This moves your stop loss to entry after reaching 0.5% profit

**Partial Take Profit**
- Toggle: ON
- Close: 50%
- This closes half your position at TP1, lets the rest run

**Daily Loss Limit**
- Set to: $500 (or your preferred daily max loss)
- Bot stops trading when this limit is hit

Click **Save Risk Management Settings**

### 5. Test with Paper Trading

**Go to Settings → Paper Trading**

- Toggle: ON
- Starting Balance: $10,000 (default)
- Click **Start Paper Trading**

The bot will now simulate trades without real money. Monitor performance for a few days to validate your strategy.

### 6. Monitor Your Trades

**Dashboard → Overview Tab**

Watch real-time stats:
- Current balance and PnL
- Win rate and open positions
- Live tick counter

**Dashboard → Trade History Tab**

Review all executed trades:
- Entry/exit prices
- PnL for each trade
- Close reason (TP, SL, Manual)

### 7. Check Alerts

**Alerts Page**

View all system notifications:
- Trade opens and closes
- Stop loss hits
- Daily loss limit alerts
- Strategy signals

Search and filter by alert type.

### 8. Go Live (When Ready)

When you're confident in your strategy:

1. **Disable Paper Trading** in Settings
2. **Connect Your Exchange API** (Binance, Bybit, etc.)
3. **Start with Small Position Size** (1-2% risk)
4. **Monitor Closely** for first week
5. **Gradually Increase** as you gain confidence

## Key Features to Know

### Real-Time Stats Cards
- **Balance**: Your current account value
- **PnL**: Profit/loss for the session
- **Win Rate**: Percentage of winning trades
- **Position**: Current open trade info

### AI Signal Panel
- Shows BUY/SELL/HOLD recommendations
- Confidence percentage (0-100%)
- Strategy confluence (Turtle, Livermore, Soros)
- Click "Analyze Now" for fresh market assessment

### Risk Management
- **Breakeven**: Automatically protects profits
- **Partial TP**: Locks in gains while letting profits run
- **Daily Limit**: Prevents over-trading during losses

### Paper Trading
- Test your strategy risk-free
- Track performance metrics
- Reset and try different parameters
- Validate before live trading

## Common Settings Combinations

### Conservative (Low Risk)
```
Risk Per Trade: 1%
Stop Loss: 1.0%
Take Profit: 2.0%
Min Confidence: 70%
Daily Loss Limit: $200
Breakeven: ON (at 0.5%)
Partial TP: ON (50%)
```

### Balanced (Medium Risk)
```
Risk Per Trade: 2%
Stop Loss: 0.8%
Take Profit: 1.6%
Min Confidence: 62%
Daily Loss Limit: $500
Breakeven: ON (at 0.5%)
Partial TP: ON (50%)
```

### Aggressive (Higher Risk)
```
Risk Per Trade: 3%
Stop Loss: 0.5%
Take Profit: 1.5%
Min Confidence: 55%
Daily Loss Limit: $1000
Breakeven: ON (at 0.3%)
Partial TP: ON (30%)
```

## Troubleshooting

### "Configuration not saving"
- Check your internet connection
- Verify all required fields are filled
- Try refreshing the page

### "Paper trading not updating"
- Ensure paper trading is toggled ON
- Check that trades are being generated
- Reset paper trading account and try again

### "Alerts not showing"
- Refresh the alerts page
- Check alert filters aren't hiding results
- Verify bot is running and generating signals

### "High loss rate"
- Increase Min Confidence threshold
- Enable Breakeven Protection
- Reduce Risk Per Trade percentage
- Test in Paper Trading first

## Best Practices

1. **Start with Paper Trading**: Always test your strategy first
2. **Use Risk Management**: Enable Breakeven and Partial TP
3. **Set Daily Loss Limit**: Protect against catastrophic losses
4. **Monitor Alerts**: Check alerts regularly for system status
5. **Review Trade History**: Analyze closed trades for patterns
6. **Adjust Gradually**: Change one parameter at a time
7. **Keep Logs**: Document your settings and results
8. **Backup Configuration**: Save your best-performing settings

## Support Resources

- **FEATURES.md**: Complete feature documentation
- **DEPLOYMENT.md**: Deployment and configuration guide
- **Dashboard Help**: Hover over icons for tooltips
- **Alert Log**: Check alerts for system messages

## Next Steps

1. Configure your trading parameters
2. Enable risk management features
3. Test with paper trading
4. Monitor performance for 1-2 weeks
5. Go live with small position size
6. Gradually increase as you gain confidence

---

**Need Help?**
- Check the FEATURES.md for detailed documentation
- Review your alert log for system messages
- Test settings in paper trading mode first

**Happy Trading! 🚀**

# Apex Trade Bot V2 — Deployment Guide

## Overview

Apex Trade Bot V2 is a modern, cinematic algorithmic trading dashboard with advanced risk management, AI integration, and database persistence. This guide covers deployment to Railway with GitHub integration.

## Prerequisites

- GitHub account with a repository
- Railway account (https://railway.app)
- Node.js 18+ (for local development)
- pnpm package manager

## Local Development

### Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd apex-trade-bot-v2

# Install dependencies
pnpm install

# Start development server
pnpm dev
```

The app will be available at `http://localhost:3000`

### Environment Variables

Create a `.env.local` file in the project root:

```
DATABASE_URL=mysql://user:password@host:port/database
JWT_SECRET=your-jwt-secret-key
VITE_APP_ID=your-manus-app-id
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://manus.im/oauth
OWNER_OPEN_ID=your-owner-id
OWNER_NAME=Your Name
BUILT_IN_FORGE_API_URL=https://api.manus.im
BUILT_IN_FORGE_API_KEY=your-api-key
VITE_FRONTEND_FORGE_API_KEY=your-frontend-key
VITE_FRONTEND_FORGE_API_URL=https://api.manus.im
```

## Deployment to Railway

### Step 1: Connect GitHub Repository

1. Push your code to GitHub
2. Go to https://railway.app
3. Click "New Project"
4. Select "Deploy from GitHub"
5. Authorize Railway and select your repository

### Step 2: Configure Database

1. In Railway dashboard, click "Add Service"
2. Select "MySQL"
3. Configure the database:
   - Database name: `apex_trade_bot`
   - Username: `root`
   - Password: (auto-generated, copy it)

### Step 3: Set Environment Variables

In Railway project settings, add the following environment variables:

```
DATABASE_URL=mysql://root:PASSWORD@HOST:PORT/apex_trade_bot
JWT_SECRET=generate-a-random-secret-key
VITE_APP_ID=your-manus-app-id
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://manus.im/oauth
OWNER_OPEN_ID=your-owner-id
OWNER_NAME=Your Name
BUILT_IN_FORGE_API_URL=https://api.manus.im
BUILT_IN_FORGE_API_KEY=your-api-key
VITE_FRONTEND_FORGE_API_KEY=your-frontend-key
VITE_FRONTEND_FORGE_API_URL=https://api.manus.im
NODE_ENV=production
```

### Step 4: Configure Build & Deploy

Railway should auto-detect the Node.js project. Verify:

- **Build Command**: `pnpm build`
- **Start Command**: `pnpm start`
- **Port**: `3000`

### Step 5: Deploy

1. Push changes to GitHub
2. Railway will automatically deploy on push
3. Monitor deployment in the Railway dashboard
4. Once deployed, you'll get a public URL

## Database Migrations

After deployment, run migrations:

```bash
# Generate migrations (local)
pnpm drizzle-kit generate

# Apply migrations (on Railway)
# Use Railway CLI or connect to database directly
pnpm drizzle-kit migrate
```

## Features

### Dashboard
- Real-time stats cards (balance, PnL, win rate, position)
- Interactive trade history table
- Alert log feed with filtering
- Performance metrics

### Risk Management
- **Breakeven Protection**: Auto-move stop loss to entry after X% profit
- **Partial Take Profit**: Close 50% of position at TP1
- **Daily Loss Limit**: Stop trading when daily loss exceeds threshold

### AI Signals
- BUY/SELL/HOLD recommendations
- Confidence percentage (0-100%)
- Criteria score (0-5)
- Strategy confluence display (Turtle Breakout, Livermore Structure, Soros Momentum)
- On-demand market analysis

### Paper Trading
- Simulate trades without real money
- Track balance, win rate, max drawdown
- Performance statistics
- Reset functionality

### Configuration
- Symbol and timeframe selection
- Risk parameters (risk %, SL %, TP %)
- Confidence threshold
- Advanced risk management settings

## Monitoring

### Health Checks

Railway provides built-in health monitoring. The app responds to:
- `GET /health` — Application health status
- `GET /api/trpc/system.health` — System health via tRPC

### Logs

View logs in Railway dashboard:
1. Go to your project
2. Click "Logs" tab
3. Filter by service (web, database)

### Performance

Monitor performance metrics:
- Response times
- Error rates
- Database queries
- Memory usage

## Troubleshooting

### Database Connection Issues

```bash
# Test database connection
mysql -h HOST -u root -p -D apex_trade_bot
```

### Build Failures

Check build logs in Railway dashboard. Common issues:
- Missing environment variables
- TypeScript compilation errors
- Dependency conflicts

### Runtime Errors

1. Check Railway logs
2. Verify environment variables
3. Test locally with same config
4. Check database migrations

## Scaling

For production use:

1. **Database**: Upgrade MySQL plan for higher throughput
2. **Server**: Increase Railway instance size
3. **CDN**: Add Railway's built-in CDN for static assets
4. **Monitoring**: Set up alerts for errors and performance

## Security

- All secrets stored in Railway environment variables
- JWT tokens for session management
- OAuth2 authentication via Manus
- Database credentials never committed to Git
- HTTPS enforced on all connections

## Support

For issues:
1. Check Railway documentation: https://docs.railway.app
2. Review application logs
3. Test locally first
4. Contact Railway support if infrastructure issues

## Next Steps

1. Deploy to Railway
2. Test all features in production
3. Set up monitoring and alerts
4. Configure custom domain (optional)
5. Enable auto-scaling for high traffic

---

**Version**: 1.0.0  
**Last Updated**: May 28, 2026

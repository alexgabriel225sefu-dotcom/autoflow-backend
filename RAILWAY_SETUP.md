# Railway Deployment — Complete Setup Instructions

## Prerequisites

- GitHub account with your repository pushed
- Railway account (https://railway.app)
- Access to your Manus OAuth credentials
- Database connection details (if using external DB)

## Step-by-Step Deployment

### Step 1: Create Railway Project

1. Go to https://railway.app
2. Click "New Project"
3. Select "Deploy from GitHub"
4. Authorize Railway to access your GitHub account
5. Select your `apex-trade-bot-v2` repository
6. Click "Deploy"

Railway will auto-detect the Node.js project and start the build.

### Step 2: Add MySQL Database

1. In your Railway project, click "Add Service"
2. Select "MySQL"
3. Wait for the database to initialize
4. Click on the MySQL service to view credentials
5. Copy the connection details:
   - Host
   - Port
   - Username
   - Password
   - Database name

### Step 3: Configure Environment Variables

1. Click on your web service (the Node.js app)
2. Go to "Variables" tab
3. Add the following environment variables:

```
DATABASE_URL=mysql://USERNAME:PASSWORD@HOST:PORT/DATABASE
JWT_SECRET=generate-a-strong-random-string-here
VITE_APP_ID=your-manus-app-id
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://manus.im/oauth
OWNER_OPEN_ID=your-owner-open-id
OWNER_NAME=Your Name
BUILT_IN_FORGE_API_URL=https://api.manus.im
BUILT_IN_FORGE_API_KEY=your-forge-api-key
VITE_FRONTEND_FORGE_API_KEY=your-frontend-forge-key
VITE_FRONTEND_FORGE_API_URL=https://api.manus.im
NODE_ENV=production
```

**How to generate JWT_SECRET:**
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

### Step 4: Configure Build Settings

1. Go to "Settings" tab
2. Verify build command: `pnpm build`
3. Verify start command: `pnpm start`
4. Verify port: `3000`
5. Set Node version to `18.x` or higher

### Step 5: Run Database Migrations

After the first deployment:

1. Click "Connect" on your Railway project
2. Use Railway CLI or SSH to access the database
3. Run migrations:

```bash
# Option 1: Using Railway CLI
railway run "pnpm drizzle-kit migrate"

# Option 2: Manual SQL execution
# Connect to MySQL and run the migration SQL files
```

### Step 6: Configure Custom Domain (Optional)

1. Go to your web service settings
2. Click "Add Domain"
3. Choose option:
   - Use Railway's subdomain (auto-generated)
   - Use your custom domain (requires DNS setup)

### Step 7: Enable Auto-Deploy

1. Go to "Settings"
2. Enable "Auto Deploy on Push"
3. Select branch: `main` (or your default branch)

Now every push to GitHub will automatically deploy!

## Verification Checklist

After deployment, verify everything works:

- [ ] App loads at Railway URL
- [ ] Can login via Manus OAuth
- [ ] Dashboard displays correctly
- [ ] Can navigate to Settings page
- [ ] Can navigate to Alerts page
- [ ] Trade history loads (may be empty initially)
- [ ] Can save configuration changes
- [ ] Paper trading mode works
- [ ] Alerts page displays properly

## Monitoring & Logs

### View Logs

1. Click on your web service
2. Go to "Logs" tab
3. Filter by service:
   - Web (Node.js app)
   - MySQL (database)

### Common Log Messages

**Successful startup:**
```
[OAuth] Initialized with baseURL: https://api.manus.im
Server running on http://localhost:3000/
```

**Database connected:**
```
[Database] Connected successfully
```

**Error indicators:**
```
[Error] Failed to connect to database
[Error] Missing environment variable: DATABASE_URL
[Error] OAuth initialization failed
```

## Troubleshooting

### Build Fails

**Error: "Cannot find module 'pnpm'"**
- Solution: Railway should auto-detect pnpm. Check package.json has `"packageManager": "pnpm@..."`

**Error: "TypeScript compilation failed"**
- Solution: Check for TypeScript errors locally with `pnpm check`
- Fix errors and push to GitHub

**Error: "Missing dependencies"**
- Solution: Run `pnpm install` locally to verify
- Commit `pnpm-lock.yaml` to Git

### Runtime Errors

**Error: "Cannot connect to database"**
- Verify DATABASE_URL is correct
- Check MySQL service is running in Railway
- Verify firewall allows connections

**Error: "OAuth callback failed"**
- Verify VITE_APP_ID is correct
- Check OAUTH_SERVER_URL is correct
- Verify redirect URL is configured in Manus OAuth

**Error: "Missing environment variable"**
- Check all required variables are set
- Verify no typos in variable names
- Redeploy after adding variables

### Performance Issues

**Slow response times:**
- Check database query performance
- Increase Railway instance size
- Enable caching for frequently accessed data

**High memory usage:**
- Check for memory leaks in logs
- Reduce query batch sizes
- Restart the service

## Scaling for Production

### Database Scaling
- Upgrade MySQL plan for higher throughput
- Enable read replicas for read-heavy workloads
- Set up automated backups

### Application Scaling
- Increase Railway instance size (CPU/RAM)
- Enable auto-scaling for variable load
- Add CDN for static assets

### Monitoring & Alerts
- Set up Railway alerts for errors
- Monitor response times
- Track database performance
- Set up uptime monitoring

## Security Hardening

1. **Rotate Secrets Regularly**
   - Change JWT_SECRET monthly
   - Rotate API keys quarterly

2. **Enable HTTPS**
   - Railway provides HTTPS by default
   - Verify certificate is valid

3. **Database Security**
   - Use strong MySQL password
   - Restrict database access to app only
   - Enable SSL for database connections

4. **Environment Variables**
   - Never commit secrets to Git
   - Use Railway's variable management
   - Audit who has access

## Backup & Recovery

### Automated Backups
1. Go to MySQL service settings
2. Enable automated backups
3. Set backup frequency (daily recommended)
4. Set retention period (30 days recommended)

### Manual Backup
```bash
# Export database
mysqldump -h HOST -u USER -p DATABASE > backup.sql

# Import database
mysql -h HOST -u USER -p DATABASE < backup.sql
```

## Rollback Procedure

If deployment goes wrong:

1. Go to "Deployments" tab
2. Find the previous stable deployment
3. Click "Rollback"
4. Confirm rollback
5. App will revert to previous version

## Next Steps

1. **Monitor the app** for 24 hours
2. **Test all features** thoroughly
3. **Set up alerts** for errors
4. **Configure backups** for database
5. **Document your setup** for future reference
6. **Plan scaling strategy** as usage grows

## Support

- Railway Docs: https://docs.railway.app
- Railway Status: https://status.railway.app
- GitHub Issues: Create issue in your repository

---

**Deployment Status**: Ready for Production  
**Last Updated**: May 28, 2026  
**Version**: 1.0.0

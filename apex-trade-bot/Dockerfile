FROM node:20-alpine
WORKDIR /app
# Build context is the full repo root (Railway behavior when Root Directory is set)
COPY apex-trade-bot/package*.json ./
RUN npm install --production
COPY apex-trade-bot/src/ ./src/
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "src/index.js"]

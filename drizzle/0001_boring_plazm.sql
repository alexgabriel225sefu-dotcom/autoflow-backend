CREATE TABLE `alerts` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`type` varchar(50) NOT NULL,
	`title` text NOT NULL,
	`content` text NOT NULL,
	`tradeId` int,
	`sentAt` timestamp NOT NULL,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `alerts_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `botConfigs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`symbol` varchar(20) NOT NULL DEFAULT 'SOLUSDT',
	`timeframe` varchar(10) NOT NULL DEFAULT '5m',
	`riskPerTrade` varchar(16) NOT NULL DEFAULT '0.02',
	`stopLossPct` varchar(16) NOT NULL DEFAULT '0.008',
	`takeProfitPct` varchar(16) NOT NULL DEFAULT '0.016',
	`minConfidence` int NOT NULL DEFAULT 62,
	`dailyLossLimit` varchar(32),
	`breakevenEnabled` int NOT NULL DEFAULT 1,
	`breakevenTrigger` varchar(16) DEFAULT '0.5',
	`partialTPEnabled` int NOT NULL DEFAULT 1,
	`partialTPPercent` varchar(16) DEFAULT '0.5',
	`trailingStopEnabled` int NOT NULL DEFAULT 1,
	`trailingStopDist` varchar(16) DEFAULT '0.01',
	`paperTradingMode` int NOT NULL DEFAULT 0,
	`paperBalance` varchar(32) DEFAULT '10',
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `botConfigs_id` PRIMARY KEY(`id`),
	CONSTRAINT `botConfigs_userId_unique` UNIQUE(`userId`)
);
--> statement-breakpoint
CREATE TABLE `dailySnapshots` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`date` varchar(10) NOT NULL,
	`startBalance` varchar(32) NOT NULL,
	`endBalance` varchar(32) NOT NULL,
	`dailyPnL` varchar(32) NOT NULL,
	`dailyPnLPercent` varchar(16) NOT NULL,
	`totalTrades` int NOT NULL DEFAULT 0,
	`wins` int NOT NULL DEFAULT 0,
	`losses` int NOT NULL DEFAULT 0,
	`maxDrawdown` varchar(16),
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `dailySnapshots_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `paperTradingStates` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`currentBalance` varchar(32) NOT NULL,
	`startBalance` varchar(32) NOT NULL,
	`totalTrades` int NOT NULL DEFAULT 0,
	`wins` int NOT NULL DEFAULT 0,
	`losses` int NOT NULL DEFAULT 0,
	`maxDrawdown` varchar(16),
	`peakBalance` varchar(32),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `paperTradingStates_id` PRIMARY KEY(`id`),
	CONSTRAINT `paperTradingStates_userId_unique` UNIQUE(`userId`)
);
--> statement-breakpoint
CREATE TABLE `trades` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`symbol` varchar(20) NOT NULL,
	`side` enum('BUY','SELL') NOT NULL,
	`entryPrice` varchar(32) NOT NULL,
	`exitPrice` varchar(32),
	`quantity` varchar(32) NOT NULL,
	`pnl` varchar(32),
	`pnlPercent` varchar(16),
	`closeReason` varchar(50),
	`openedAt` timestamp NOT NULL,
	`closedAt` timestamp,
	`confidence` int,
	`criteriaScore` int,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `trades_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
ALTER TABLE `alerts` ADD CONSTRAINT `alerts_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `alerts` ADD CONSTRAINT `alerts_tradeId_trades_id_fk` FOREIGN KEY (`tradeId`) REFERENCES `trades`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `botConfigs` ADD CONSTRAINT `botConfigs_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `dailySnapshots` ADD CONSTRAINT `dailySnapshots_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `paperTradingStates` ADD CONSTRAINT `paperTradingStates_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `trades` ADD CONSTRAINT `trades_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;
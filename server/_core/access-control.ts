import { TRPCError } from '@trpc/server';

export type Tier = 'starter' | 'professional' | 'enterprise' | 'free';

export const tierLimits = {
  free: {
    socialPosts: 10,
    emails: 50,
    contentPieces: 5,
    apiCalls: 100,
  },
  starter: {
    socialPosts: 100,
    emails: 1000,
    contentPieces: 50,
    apiCalls: 10000,
  },
  professional: {
    socialPosts: 999999,
    emails: 999999,
    contentPieces: 999999,
    apiCalls: 999999,
  },
  enterprise: {
    socialPosts: 999999,
    emails: 999999,
    contentPieces: 999999,
    apiCalls: 999999,
  },
};

export const toolAccess = {
  free: ['social-media-scheduler'],
  starter: ['social-media-scheduler', 'email-marketing', 'content-creation'],
  professional: ['social-media-scheduler', 'email-marketing', 'content-creation', 'ai-automation', 'lead-generation'],
  enterprise: ['social-media-scheduler', 'email-marketing', 'content-creation', 'ai-automation', 'lead-generation'],
};

export function checkTierAccess(tier: Tier, tool: string) {
  const allowedTools = toolAccess[tier];
  if (!allowedTools.includes(tool)) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: `This tool is not available in your ${tier} plan. Upgrade to access it.`,
    });
  }
}

export function checkUsageLimit(tier: Tier, feature: keyof typeof tierLimits.free, used: number) {
  const limit = tierLimits[tier][feature];
  if (used >= limit) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: `You've reached your ${feature} limit for this month. Upgrade your plan for more.`,
    });
  }
}

export function getRemainingUsage(tier: Tier, feature: keyof typeof tierLimits.free, used: number) {
  const limit = tierLimits[tier][feature];
  return Math.max(0, limit - used);
}

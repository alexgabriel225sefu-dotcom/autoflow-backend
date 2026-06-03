import { protectedProcedure, router } from '../_core/trpc';
import { z } from 'zod';
import { invokeLLM } from '../_core/llm';

export const aiRouter = router({
  generateSocialCaption: protectedProcedure
    .input(z.object({ topic: z.string(), platform: z.string() }))
    .mutation(async ({ input }) => {
      const response = await invokeLLM({
        messages: [
          {
            role: 'system',
            content: `You are an expert social media marketer. Generate engaging captions for ${input.platform}.`,
          },
          {
            role: 'user',
            content: `Create a viral ${input.platform} caption about: ${input.topic}. Make it engaging and include relevant hashtags.`,
          },
        ],
      });

      const content = response.choices[0]?.message?.content || '';
      return { caption: content };
    }),

  generateEmailSubject: protectedProcedure
    .input(z.object({ topic: z.string(), style: z.string() }))
    .mutation(async ({ input }) => {
      const response = await invokeLLM({
        messages: [
          {
            role: 'system',
            content: 'You are an expert email copywriter. Generate compelling email subject lines.',
          },
          {
            role: 'user',
            content: `Generate 5 high-converting email subject lines for a ${input.style} email about: ${input.topic}. Format as a numbered list.`,
          },
        ],
      });

      const content = response.choices[0]?.message?.content || '';
      return { subjects: content };
    }),

  generateBlogPost: protectedProcedure
    .input(z.object({ title: z.string(), keywords: z.string() }))
    .mutation(async ({ input }) => {
      const response = await invokeLLM({
        messages: [
          {
            role: 'system',
            content: 'You are an expert SEO content writer. Write engaging, SEO-optimized blog posts.',
          },
          {
            role: 'user',
            content: `Write a 1000-word blog post titled "${input.title}" targeting keywords: ${input.keywords}. Include an introduction, 3 main sections, and conclusion.`,
          },
        ],
      });

      const content = response.choices[0]?.message?.content || '';
      return { post: content };
    }),

  generateVideoScript: protectedProcedure
    .input(z.object({ topic: z.string(), duration: z.string() }))
    .mutation(async ({ input }) => {
      const response = await invokeLLM({
        messages: [
          {
            role: 'system',
            content: 'You are an expert video scriptwriter. Write engaging, conversion-focused video scripts.',
          },
          {
            role: 'user',
            content: `Write a ${input.duration} video script about: ${input.topic}. Include hook, main content, and CTA.`,
          },
        ],
      });

      const content = response.choices[0]?.message?.content || '';
      return { script: content };
    }),

  generateLeadMagnet: protectedProcedure
    .input(z.object({ niche: z.string(), type: z.string() }))
    .mutation(async ({ input }) => {
      const response = await invokeLLM({
        messages: [
          {
            role: 'system',
            content: 'You are an expert at creating high-converting lead magnets.',
          },
          {
            role: 'user',
            content: `Create a ${input.type} lead magnet for the ${input.niche} niche. Include title, description, and key benefits.`,
          },
        ],
      });

      const content = response.choices[0]?.message?.content || '';
      return { magnet: content };
    }),
});

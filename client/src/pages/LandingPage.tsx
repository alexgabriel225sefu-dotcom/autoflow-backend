import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Check, Zap, Users, TrendingUp, Lock, Sparkles } from 'lucide-react';

export function LandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-800 to-slate-900 text-white">
      {/* Hero Section */}
      <section className="relative px-4 py-20 md:py-32">
        <div className="max-w-6xl mx-auto grid md:grid-cols-2 gap-12 items-center">
          <div className="space-y-6">
            <h1 className="text-5xl md:text-6xl font-bold leading-tight">
              The All-in-One AI Platform for Modern Entrepreneurs
            </h1>
            <p className="text-xl text-slate-300">
              Get 5 professional AI tools + community + education. No subscriptions. No hidden fees. Real results.
            </p>
            <div className="flex gap-4">
              <Button size="lg" className="bg-amber-500 hover:bg-amber-600 text-black">
                Get Started - $297
              </Button>
              <Button size="lg" variant="outline">
                Watch Demo
              </Button>
            </div>
            <p className="text-sm text-slate-400">✓ 30-day money-back guarantee • ✓ Lifetime access • ✓ Free updates</p>
          </div>
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-r from-amber-500 to-orange-500 rounded-2xl blur-3xl opacity-20" />
            <div className="relative bg-slate-800 rounded-2xl p-8 border border-slate-700">
              <div className="space-y-4">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-4 bg-slate-700 rounded w-full" />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="px-4 py-20 bg-slate-800/50">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-4xl font-bold text-center mb-16">5 Powerful AI Tools</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-6">
            {[
              { icon: Zap, title: 'Social Media Scheduler', desc: 'AI captions + scheduling' },
              { icon: TrendingUp, title: 'Email Marketing', desc: 'AI copywriting + automation' },
              { icon: Sparkles, title: 'Content Creation', desc: 'Blog, scripts, SEO' },
              { icon: Lock, title: 'AI Automation', desc: 'Workflow builder' },
              { icon: Users, title: 'Lead Generation', desc: 'AI lead scoring' },
            ].map((tool, i) => (
              <Card key={i} className="bg-slate-700 border-slate-600 hover:border-amber-500 transition">
                <CardContent className="p-6 text-center space-y-3">
                  <tool.icon className="w-8 h-8 mx-auto text-amber-500" />
                  <h3 className="font-bold">{tool.title}</h3>
                  <p className="text-sm text-slate-300">{tool.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section className="px-4 py-20">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-4xl font-bold text-center mb-16">Simple, Transparent Pricing</h2>
          <div className="grid md:grid-cols-3 gap-8">
            {/* Starter */}
            <Card className="bg-slate-800 border-slate-700">
              <CardContent className="p-8 space-y-6">
                <div>
                  <h3 className="text-2xl font-bold">Starter</h3>
                  <p className="text-slate-400">One-time payment</p>
                </div>
                <div className="text-4xl font-bold">$297</div>
                <ul className="space-y-3">
                  {['All 5 AI tools', '100 social posts/month', '1,000 emails/month', 'Community access', 'Email support'].map((item, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <Check className="w-5 h-5 text-green-500" />
                      <span className="text-sm">{item}</span>
                    </li>
                  ))}
                </ul>
                <Button className="w-full bg-amber-500 hover:bg-amber-600 text-black">
                  Get Starter
                </Button>
              </CardContent>
            </Card>

            {/* Professional */}
            <Card className="bg-amber-500/10 border-amber-500 relative">
              <div className="absolute top-0 left-0 right-0 bg-amber-500 text-black py-2 text-center text-sm font-bold">
                MOST POPULAR
              </div>
              <CardContent className="p-8 space-y-6 pt-16">
                <div>
                  <h3 className="text-2xl font-bold">Professional</h3>
                  <p className="text-slate-400">Monthly subscription</p>
                </div>
                <div className="text-4xl font-bold">$97<span className="text-lg text-slate-400">/mo</span></div>
                <ul className="space-y-3">
                  {['Everything in Starter', 'Unlimited everything', 'Priority support', 'Advanced analytics', 'API access'].map((item, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <Check className="w-5 h-5 text-green-500" />
                      <span className="text-sm">{item}</span>
                    </li>
                  ))}
                </ul>
                <Button className="w-full bg-amber-500 hover:bg-amber-600 text-black">
                  Get Professional
                </Button>
              </CardContent>
            </Card>

            {/* Enterprise */}
            <Card className="bg-slate-800 border-slate-700">
              <CardContent className="p-8 space-y-6">
                <div>
                  <h3 className="text-2xl font-bold">Enterprise</h3>
                  <p className="text-slate-400">Custom pricing</p>
                </div>
                <div className="text-4xl font-bold">$997<span className="text-lg text-slate-400">/mo</span></div>
                <ul className="space-y-3">
                  {['Everything in Pro', 'Dedicated account manager', '1-on-1 strategy sessions', 'Custom integrations', 'Profit sharing (10%)'].map((item, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <Check className="w-5 h-5 text-green-500" />
                      <span className="text-sm">{item}</span>
                    </li>
                  ))}
                </ul>
                <Button className="w-full bg-slate-700 hover:bg-slate-600">
                  Contact Sales
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Trust Signals */}
      <section className="px-4 py-20 bg-slate-800/50">
        <div className="max-w-6xl mx-auto grid md:grid-cols-3 gap-8 text-center">
          <div>
            <p className="text-4xl font-bold text-amber-500">10K+</p>
            <p className="text-slate-300">Active Users</p>
          </div>
          <div>
            <p className="text-4xl font-bold text-amber-500">$50M+</p>
            <p className="text-slate-300">Generated by Users</p>
          </div>
          <div>
            <p className="text-4xl font-bold text-amber-500">98%</p>
            <p className="text-slate-300">Satisfaction Rate</p>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="px-4 py-20">
        <div className="max-w-2xl mx-auto text-center space-y-6">
          <h2 className="text-4xl font-bold">Ready to Get Started?</h2>
          <p className="text-xl text-slate-300">
            Join thousands of entrepreneurs building profitable AI businesses.
          </p>
          <Button size="lg" className="bg-amber-500 hover:bg-amber-600 text-black">
            Get Lifetime Access - $297
          </Button>
          <p className="text-sm text-slate-400">30-day money-back guarantee. No questions asked.</p>
        </div>
      </section>
    </div>
  );
}

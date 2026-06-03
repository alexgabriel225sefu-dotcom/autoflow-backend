import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ArrowRight, Zap, TrendingUp, Sparkles, Lock, Users, Play } from 'lucide-react';

export function PremiumLanding() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // Animated background particles
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const particles: Array<{
      x: number;
      y: number;
      vx: number;
      vy: number;
      size: number;
      opacity: number;
    }> = [];

    for (let i = 0; i < 50; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
        size: Math.random() * 2 + 1,
        opacity: Math.random() * 0.5 + 0.2,
      });
    }

    const animate = () => {
      ctx.fillStyle = 'rgba(15, 23, 42, 0.1)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;

        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;

        ctx.fillStyle = `rgba(251, 146, 60, ${p.opacity})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      });

      requestAnimationFrame(animate);
    };

    animate();

    const handleResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setMousePos({ x: e.clientX, y: e.clientY });
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Animated background */}
      <canvas
        ref={canvasRef}
        className="fixed inset-0 pointer-events-none"
      />

      {/* Radial gradient overlay */}
      <div className="fixed inset-0 pointer-events-none">
        <div
          className="absolute w-96 h-96 bg-amber-500/20 rounded-full blur-3xl transition-all duration-300"
          style={{
            left: `${mousePos.x - 192}px`,
            top: `${mousePos.y - 192}px`,
          }}
        />
      </div>

      {/* Content */}
      <div className="relative z-10">
        {/* Hero Section */}
        <section className="min-h-screen flex items-center justify-center px-4 py-20">
          <div className="max-w-6xl mx-auto grid md:grid-cols-2 gap-12 items-center">
            <div className="space-y-8 animate-fade-in">
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 px-4 py-2 bg-amber-500/10 border border-amber-500/30 rounded-full backdrop-blur-sm">
                  <Sparkles className="w-4 h-4 text-amber-500" />
                  <span className="text-sm text-amber-400">AI-Powered Platform</span>
                </div>

                <h1 className="text-6xl md:text-7xl font-black bg-gradient-to-r from-amber-400 via-orange-400 to-red-500 bg-clip-text text-transparent leading-tight">
                  Build Your AI Empire
                </h1>

                <p className="text-xl text-slate-300 leading-relaxed">
                  5 professional AI tools + community + education. Generate $10K-$100K/month with zero technical skills.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row gap-4">
                <Button
                  size="lg"
                  className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-black font-bold text-lg px-8 py-6 rounded-xl shadow-lg hover:shadow-2xl transition-all duration-300 group"
                >
                  Get Lifetime Access
                  <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </Button>

                <Button
                  size="lg"
                  variant="outline"
                  className="border-amber-500/50 text-amber-400 hover:bg-amber-500/10 font-bold text-lg px-8 py-6 rounded-xl"
                >
                  <Play className="w-5 h-5 mr-2" />
                  Watch Demo
                </Button>
              </div>

              <div className="flex flex-wrap gap-6 pt-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-green-500 rounded-full" />
                  <span className="text-sm text-slate-300">30-day money-back</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-green-500 rounded-full" />
                  <span className="text-sm text-slate-300">Lifetime updates</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-green-500 rounded-full" />
                  <span className="text-sm text-slate-300">1-on-1 support</span>
                </div>
              </div>
            </div>

            {/* Hero Image */}
            <div className="relative h-96 md:h-full">
              <div className="absolute inset-0 bg-gradient-to-br from-amber-500/20 to-orange-500/20 rounded-3xl blur-3xl" />
              <div className="relative bg-gradient-to-br from-slate-800 to-slate-900 rounded-3xl p-8 border border-amber-500/20 backdrop-blur-sm overflow-hidden">
                <div className="space-y-4">
                  {[1, 2, 3, 4].map(i => (
                    <div
                      key={i}
                      className="h-3 bg-gradient-to-r from-amber-500/50 to-transparent rounded-full"
                      style={{
                        width: `${100 - i * 15}%`,
                        animation: `pulse 2s ease-in-out ${i * 0.2}s infinite`,
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Tools Showcase */}
        <section className="py-20 px-4">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-5xl font-black bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent mb-4">
                5 Powerful AI Tools
              </h2>
              <p className="text-xl text-slate-400">Everything you need to build a 6-7 figure business</p>
            </div>

            <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-6">
              {[
                { icon: Zap, title: 'Social Media', desc: 'AI captions + scheduling' },
                { icon: TrendingUp, title: 'Email Marketing', desc: 'AI copywriting + automation' },
                { icon: Sparkles, title: 'Content Creation', desc: 'Blog, scripts, SEO' },
                { icon: Lock, title: 'AI Automation', desc: 'Workflow builder' },
                { icon: Users, title: 'Lead Generation', desc: 'AI lead scoring' },
              ].map((tool, i) => (
                <div
                  key={i}
                  className="group relative"
                  style={{
                    animation: `slide-up 0.6s ease-out ${i * 0.1}s both`,
                  }}
                >
                  <div className="absolute inset-0 bg-gradient-to-r from-amber-500/20 to-orange-500/20 rounded-2xl blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                  <Card className="relative bg-slate-800/50 border-amber-500/20 hover:border-amber-500/50 backdrop-blur-sm p-6 h-full transition-all duration-300 hover:translate-y-[-4px]">
                    <div className="space-y-4">
                      <tool.icon className="w-8 h-8 text-amber-500 group-hover:scale-110 transition-transform" />
                      <h3 className="font-bold text-lg text-white">{tool.title}</h3>
                      <p className="text-sm text-slate-400">{tool.desc}</p>
                    </div>
                  </Card>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing Section */}
        <section className="py-20 px-4">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-5xl font-black bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent mb-4">
                Simple Pricing
              </h2>
              <p className="text-xl text-slate-400">Choose your path to success</p>
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              {[
                {
                  name: 'Starter',
                  price: '$297',
                  period: 'one-time',
                  features: ['All 5 tools', '100 posts/month', '1K emails/month', 'Community access'],
                  highlighted: false,
                },
                {
                  name: 'Professional',
                  price: '$97',
                  period: '/month',
                  features: ['Everything in Starter', 'Unlimited everything', 'Priority support', 'Advanced analytics'],
                  highlighted: true,
                },
                {
                  name: 'Enterprise',
                  price: '$997',
                  period: '/month',
                  features: ['Everything in Pro', 'Dedicated manager', '1-on-1 sessions', 'Profit sharing (10%)'],
                  highlighted: false,
                },
              ].map((plan, i) => (
                <div
                  key={i}
                  className={`relative group ${plan.highlighted ? 'md:scale-105' : ''}`}
                >
                  {plan.highlighted && (
                    <div className="absolute inset-0 bg-gradient-to-r from-amber-500/30 to-orange-500/30 rounded-2xl blur-xl" />
                  )}
                  <Card
                    className={`relative backdrop-blur-sm transition-all duration-300 ${
                      plan.highlighted
                        ? 'bg-gradient-to-br from-amber-500/20 to-orange-500/10 border-amber-500/50 shadow-2xl'
                        : 'bg-slate-800/50 border-amber-500/20 hover:border-amber-500/30'
                    }`}
                  >
                    <div className="p-8 space-y-6">
                      {plan.highlighted && (
                        <div className="inline-block px-3 py-1 bg-amber-500/20 border border-amber-500/50 rounded-full text-xs font-bold text-amber-400">
                          MOST POPULAR
                        </div>
                      )}

                      <div>
                        <h3 className="text-2xl font-bold text-white">{plan.name}</h3>
                        <div className="mt-2 flex items-baseline gap-1">
                          <span className="text-4xl font-black text-amber-400">{plan.price}</span>
                          <span className="text-slate-400">{plan.period}</span>
                        </div>
                      </div>

                      <ul className="space-y-3">
                        {plan.features.map((feature, j) => (
                          <li key={j} className="flex items-center gap-3 text-slate-300">
                            <div className="w-1.5 h-1.5 bg-amber-500 rounded-full" />
                            {feature}
                          </li>
                        ))}
                      </ul>

                      <Button
                        className={`w-full font-bold py-3 rounded-xl transition-all duration-300 ${
                          plan.highlighted
                            ? 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-black'
                            : 'bg-slate-700 hover:bg-slate-600 text-white'
                        }`}
                      >
                        Get {plan.name}
                      </Button>
                    </div>
                  </Card>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Stats Section */}
        <section className="py-20 px-4">
          <div className="max-w-6xl mx-auto">
            <div className="grid md:grid-cols-3 gap-8">
              {[
                { label: 'Active Users', value: '10K+' },
                { label: 'Revenue Generated', value: '$50M+' },
                { label: 'Satisfaction Rate', value: '98%' },
              ].map((stat, i) => (
                <div key={i} className="text-center">
                  <div className="text-5xl font-black bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent mb-2">
                    {stat.value}
                  </div>
                  <p className="text-slate-400">{stat.label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Final CTA */}
        <section className="py-20 px-4">
          <div className="max-w-2xl mx-auto text-center space-y-8">
            <h2 className="text-5xl font-black bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent">
              Ready to Build Your Empire?
            </h2>
            <p className="text-xl text-slate-300">
              Join thousands of entrepreneurs making $10K-$100K/month with AI.
            </p>
            <Button
              size="lg"
              className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-black font-bold text-lg px-12 py-6 rounded-xl shadow-lg hover:shadow-2xl transition-all duration-300 group"
            >
              Get Lifetime Access - $297
              <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
            </Button>
            <p className="text-sm text-slate-400">30-day money-back guarantee. No questions asked.</p>
          </div>
        </section>
      </div>

      <style>{`
        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slide-up {
          from {
            opacity: 0;
            transform: translateY(40px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes pulse {
          0%, 100% {
            opacity: 0.2;
          }
          50% {
            opacity: 0.8;
          }
        }

        .animate-fade-in {
          animation: fade-in 0.8s ease-out;
        }
      `}</style>
    </div>
  );
}

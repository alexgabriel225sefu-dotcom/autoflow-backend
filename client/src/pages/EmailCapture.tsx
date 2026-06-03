import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Mail, CheckCircle } from 'lucide-react';
import { toast } from 'sonner';

export function EmailCapture() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes('@')) {
      toast.error('Please enter a valid email');
      return;
    }

    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 1000));
    setSubmitted(true);
    toast.success('Check your email for the free guide!');

    // Reset after 3 seconds
    setTimeout(() => {
      setEmail('');
      setSubmitted(false);
    }, 3000);
  };

  if (submitted) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-950 flex items-center justify-center px-4">
        <Card className="w-full max-w-md bg-slate-800 border-green-500/50 p-8 text-center space-y-4">
          <CheckCircle className="w-16 h-16 text-green-500 mx-auto" />
          <h2 className="text-2xl font-bold text-white">Check Your Email!</h2>
          <p className="text-slate-300">
            We've sent you the free guide to building a 6-figure AI business. Check your inbox (and spam folder).
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-950 flex items-center justify-center px-4">
      <Card className="w-full max-w-md bg-slate-800 border-amber-500/50 p-8 space-y-6">
        <div className="text-center space-y-2">
          <Mail className="w-12 h-12 text-amber-500 mx-auto" />
          <h2 className="text-2xl font-bold text-white">Free Guide</h2>
          <p className="text-slate-300">Get the 7-step blueprint to build a 6-figure AI business</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="email"
            placeholder="your@email.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="bg-slate-700 border-slate-600 text-white placeholder-slate-500"
          />
          <Button
            type="submit"
            className="w-full bg-amber-500 hover:bg-amber-600 text-black font-bold"
          >
            Get Free Guide
          </Button>
        </form>

        <div className="bg-slate-700/50 rounded-lg p-4 space-y-2">
          <p className="text-sm text-slate-300 font-medium">You'll also get:</p>
          <ul className="text-sm text-slate-400 space-y-1">
            <li>✓ Weekly AI tips & strategies</li>
            <li>✓ Case studies of 6-7 figure businesses</li>
            <li>✓ Exclusive tools & templates</li>
            <li>✓ Early access to new features</li>
          </ul>
        </div>

        <p className="text-xs text-slate-500 text-center">
          We respect your privacy. Unsubscribe anytime.
        </p>
      </Card>
    </div>
  );
}

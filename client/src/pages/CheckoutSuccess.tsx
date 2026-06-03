import { useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { CheckCircle, Download, Mail } from 'lucide-react';

export function CheckoutSuccess() {
  const [, navigate] = useLocation();

  useEffect(() => {
    const timer = setTimeout(() => {
      navigate('/dashboard');
    }, 5000);
    return () => clearTimeout(timer);
  }, [navigate]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-950 flex items-center justify-center px-4">
      <Card className="w-full max-w-md bg-slate-800 border-amber-500/50 p-8 space-y-6">
        <div className="flex justify-center">
          <CheckCircle className="w-16 h-16 text-green-500" />
        </div>

        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-white">Payment Successful!</h1>
          <p className="text-slate-300">Welcome to AICashSystem</p>
        </div>

        <div className="bg-slate-700/50 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <Mail className="w-5 h-5 text-amber-500" />
            <div>
              <p className="text-sm text-slate-400">Check your email</p>
              <p className="text-white font-medium">Confirmation & access details sent</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Download className="w-5 h-5 text-amber-500" />
            <div>
              <p className="text-sm text-slate-400">Download materials</p>
              <p className="text-white font-medium">All resources available in dashboard</p>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <Button
            onClick={() => navigate('/dashboard')}
            className="w-full bg-amber-500 hover:bg-amber-600 text-black font-bold"
          >
            Go to Dashboard
          </Button>
          <Button
            onClick={() => navigate('/courses')}
            variant="outline"
            className="w-full"
          >
            Start Learning
          </Button>
        </div>

        <p className="text-center text-sm text-slate-400">
          Redirecting to dashboard in 5 seconds...
        </p>
      </Card>
    </div>
  );
}

export function CheckoutCancel() {
  const [, navigate] = useLocation();

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-950 flex items-center justify-center px-4">
      <Card className="w-full max-w-md bg-slate-800 border-red-500/50 p-8 space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-white">Payment Cancelled</h1>
          <p className="text-slate-300">Your payment was not completed</p>
        </div>

        <div className="bg-slate-700/50 rounded-lg p-4">
          <p className="text-slate-300">
            No charges were made to your account. You can try again anytime.
          </p>
        </div>

        <div className="space-y-3">
          <Button
            onClick={() => navigate('/')}
            className="w-full bg-amber-500 hover:bg-amber-600 text-black font-bold"
          >
            Return to Home
          </Button>
          <Button
            onClick={() => navigate('/')}
            variant="outline"
            className="w-full"
          >
            View Pricing Again
          </Button>
        </div>
      </Card>
    </div>
  );
}

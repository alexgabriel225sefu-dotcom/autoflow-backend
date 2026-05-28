import React from 'react';
import { useAuth } from '@/_core/hooks/useAuth';
import { Button } from '@/components/ui/button';
import { Bell, ArrowLeft } from 'lucide-react';
import { useLocation } from 'wouter';
import TelegramAlertLog from '@/components/TelegramAlertLog';

export default function Alerts() {
  const { user, loading: authLoading } = useAuth();
  const [, setLocation] = useLocation();

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mx-auto mb-4"></div>
          <p className="text-slate-300">Loading...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-red-400 mb-4">Authentication required</p>
          <Button>Login</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-bg">
      <div className="trading-dashboard min-h-screen">
        {/* Header */}
        <header className="border-b border-slate-700/50 bg-slate-900/30 backdrop-blur-md sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-6 py-6">
            <div className="flex items-center justify-between">
              <h1 className="text-4xl font-bold gradient-text flex items-center gap-3">
                <Bell className="w-8 h-8" />
                Alert Management
              </h1>
              <Button
                onClick={() => setLocation('/dashboard')}
                variant="outline"
                className="gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to Dashboard
              </Button>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-6 py-8">
          <TelegramAlertLog />
        </main>
      </div>
    </div>
  );
}

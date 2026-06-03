import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Copy, DollarSign, Users, TrendingUp, Download } from 'lucide-react';
import { toast } from 'sonner';

export function Affiliate() {
  const [referralCode] = useState('AICASH2024');
  const [referrals] = useState([
    { id: 1, name: 'John Doe', email: 'john@example.com', tier: 'Professional', commission: '$97', date: '2024-01-15', status: 'Paid' },
    { id: 2, name: 'Jane Smith', email: 'jane@example.com', tier: 'Starter', commission: '$297', date: '2024-01-14', status: 'Pending' },
    { id: 3, name: 'Mike Johnson', email: 'mike@example.com', tier: 'Enterprise', commission: '$997', date: '2024-01-13', status: 'Paid' },
  ]);

  const copyCode = () => {
    navigator.clipboard.writeText(referralCode);
    toast.success('Referral code copied!');
  };

  const copyLink = () => {
    const link = `https://aicashsystem.com/?ref=${referralCode}`;
    navigator.clipboard.writeText(link);
    toast.success('Referral link copied!');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Affiliate Program</h1>
        <p className="text-muted-foreground">Earn 20% commission on every referral</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Earned</p>
                <p className="text-2xl font-bold">$4,891</p>
              </div>
              <DollarSign className="w-8 h-8 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Referrals</p>
                <p className="text-2xl font-bold">23</p>
              </div>
              <Users className="w-8 h-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Conversion Rate</p>
                <p className="text-2xl font-bold">12%</p>
              </div>
              <TrendingUp className="w-8 h-8 text-purple-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Pending Payout</p>
                <p className="text-2xl font-bold">$1,234</p>
              </div>
              <DollarSign className="w-8 h-8 text-orange-500" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Your Referral Code</CardTitle>
              <CardDescription>Share this code with your audience</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input value={referralCode} readOnly className="font-mono" />
                <Button onClick={copyCode} variant="outline">
                  <Copy className="w-4 h-4" />
                </Button>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">Your Referral Link</p>
                <div className="flex gap-2">
                  <Input
                    value={`https://aicashsystem.com/?ref=${referralCode}`}
                    readOnly
                    className="text-sm"
                  />
                  <Button onClick={copyLink} variant="outline">
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent Referrals</CardTitle>
              <CardDescription>Track your referrals and commissions</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {referrals.map(ref => (
                  <div key={ref.id} className="flex items-center justify-between p-4 bg-slate-100 dark:bg-slate-800 rounded-lg">
                    <div>
                      <p className="font-medium">{ref.name}</p>
                      <p className="text-sm text-muted-foreground">{ref.email}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-bold">{ref.commission}</p>
                      <p className={`text-xs ${ref.status === 'Paid' ? 'text-green-600' : 'text-yellow-600'}`}>
                        {ref.status}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Marketing Materials</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" className="w-full justify-start text-left">
                <Download className="w-4 h-4 mr-2" />
                Email Swipes
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                <Download className="w-4 h-4 mr-2" />
                Social Posts
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                <Download className="w-4 h-4 mr-2" />
                Landing Page
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Commission Tiers</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="font-medium">Starter ($297)</p>
                <p className="text-muted-foreground">$59.40 per sale</p>
              </div>
              <div>
                <p className="font-medium">Professional ($97/mo)</p>
                <p className="text-muted-foreground">$19.40 per month</p>
              </div>
              <div>
                <p className="font-medium">Enterprise ($997/mo)</p>
                <p className="text-muted-foreground">$199.40 per month</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

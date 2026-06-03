import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Loader, Mail } from 'lucide-react';
import { toast } from 'sonner';

export function EmailMarketing() {
  const [topic, setTopic] = useState('');
  const [style, setStyle] = useState('promotional');
  const [subjects, setSubjects] = useState('');
  const [loading, setLoading] = useState(false);
  const [campaigns, setCampaigns] = useState<Array<{ id: number; subject: string; recipients: number; sent: string }>>([]);

  const generateSubjects = async () => {
    if (!topic.trim()) {
      toast.error('Enter a topic');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch('/api/trpc/ai.generateEmailSubject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, style }),
      });

      const data = await response.json();
      setSubjects(data.result?.data?.subjects || 'Failed to generate subjects');
      toast.success('Subject lines generated!');
    } catch (error) {
      toast.error('Failed to generate subjects');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const sendCampaign = () => {
    if (!subjects.trim()) {
      toast.error('Generate subject lines first');
      return;
    }

    const newCampaign = {
      id: Date.now(),
      subject: subjects.split('\n')[0],
      recipients: Math.floor(Math.random() * 5000) + 1000,
      sent: new Date().toLocaleDateString(),
    };

    setCampaigns([newCampaign, ...campaigns]);
    setSubjects('');
    setTopic('');
    toast.success('Campaign sent!');
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold">Email Marketing</h1>
        <p className="text-muted-foreground">AI-powered email campaigns</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardContent className="p-6 space-y-4">
              <div>
                <label className="text-sm font-medium">Email Topic</label>
                <Input
                  placeholder="What's your email about?"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  className="mt-2"
                />
              </div>

              <div>
                <label className="text-sm font-medium">Email Style</label>
                <select
                  value={style}
                  onChange={(e) => setStyle(e.target.value)}
                  className="w-full mt-2 px-3 py-2 border rounded-md bg-background"
                >
                  <option value="promotional">Promotional</option>
                  <option value="educational">Educational</option>
                  <option value="nurture">Nurture</option>
                  <option value="urgent">Urgent</option>
                </select>
              </div>

              <Button
                onClick={generateSubjects}
                disabled={loading}
                className="w-full bg-amber-500 hover:bg-amber-600"
              >
                {loading ? (
                  <>
                    <Loader className="w-4 h-4 mr-2 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Mail className="w-4 h-4 mr-2" />
                    Generate Subject Lines
                  </>
                )}
              </Button>

              {subjects && (
                <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4">
                  <p className="text-sm text-muted-foreground mb-2">Generated Subject Lines:</p>
                  <Textarea value={subjects} onChange={(e) => setSubjects(e.target.value)} rows={5} />
                  <Button onClick={sendCampaign} className="w-full mt-4 bg-green-600 hover:bg-green-700">
                    Send Campaign
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div>
          <Card>
            <CardContent className="p-6 space-y-4">
              <h3 className="font-bold">Recent Campaigns</h3>
              <div className="space-y-3">
                {campaigns.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No campaigns sent yet</p>
                ) : (
                  campaigns.map((campaign) => (
                    <div key={campaign.id} className="bg-slate-100 dark:bg-slate-800 rounded p-3 text-sm">
                      <p className="font-medium truncate">{campaign.subject}</p>
                      <p className="text-muted-foreground text-xs mt-1">{campaign.recipients} recipients</p>
                      <p className="text-muted-foreground text-xs">{campaign.sent}</p>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

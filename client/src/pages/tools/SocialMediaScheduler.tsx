import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Calendar, Sparkles, Send, TrendingUp } from 'lucide-react';
import { trpc } from '@/lib/trpc';
import { useAuth } from '@/_core/hooks/useAuth';
import { toast } from 'sonner';

export function SocialMediaScheduler() {
  const { user } = useAuth();
  const [platform, setPlatform] = useState('twitter');
  const [content, setContent] = useState('');
  const [scheduledDate, setScheduledDate] = useState('');
  const [scheduledTime, setScheduledTime] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isScheduling, setIsScheduling] = useState(false);

  const generateCaption = async () => {
    if (!content.trim()) {
      toast.error('Please enter a topic or content');
      return;
    }

    setIsGenerating(true);
    try {
      const response = await fetch('/api/ai/generate-caption', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: content, platform }),
      });

      const data = await response.json();
      if (data.caption) {
        setContent(data.caption);
        toast.success('Caption generated!');
      }
    } catch (error) {
      toast.error('Failed to generate caption');
    } finally {
      setIsGenerating(false);
    }
  };

  const schedulePost = async () => {
    if (!content.trim() || !scheduledDate || !scheduledTime) {
      toast.error('Please fill all fields');
      return;
    }

    setIsScheduling(true);
    try {
      const response = await fetch('/api/social/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          content,
          scheduledDate,
          scheduledTime,
          userId: user?.id,
        }),
      });

      if (response.ok) {
        toast.success('Post scheduled successfully!');
        setContent('');
        setScheduledDate('');
        setScheduledTime('');
      } else {
        toast.error('Failed to schedule post');
      }
    } catch (error) {
      toast.error('Error scheduling post');
    } finally {
      setIsScheduling(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Social Media Scheduler</h1>
        <p className="text-muted-foreground">Schedule posts across all platforms with AI-powered captions</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Editor */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="w-5 h-5" />
                Create Post
              </CardTitle>
              <CardDescription>Write or generate your post content</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium">Platform</label>
                <Select value={platform} onValueChange={setPlatform}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="twitter">Twitter/X</SelectItem>
                    <SelectItem value="linkedin">LinkedIn</SelectItem>
                    <SelectItem value="instagram">Instagram</SelectItem>
                    <SelectItem value="facebook">Facebook</SelectItem>
                    <SelectItem value="tiktok">TikTok</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="text-sm font-medium">Content</label>
                <Textarea
                  placeholder="Write your post or enter a topic for AI to generate..."
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  rows={6}
                  className="resize-none"
                />
                <p className="text-xs text-muted-foreground mt-2">{content.length}/280 characters</p>
              </div>

              <Button
                onClick={generateCaption}
                disabled={isGenerating}
                variant="outline"
                className="w-full"
              >
                <Sparkles className="w-4 h-4 mr-2" />
                {isGenerating ? 'Generating...' : 'Generate with AI'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Calendar className="w-5 h-5" />
                Schedule
              </CardTitle>
              <CardDescription>Choose when to publish</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium">Date</label>
                  <Input
                    type="date"
                    value={scheduledDate}
                    onChange={(e) => setScheduledDate(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Time</label>
                  <Input
                    type="time"
                    value={scheduledTime}
                    onChange={(e) => setScheduledTime(e.target.value)}
                  />
                </div>
              </div>

              <Button
                onClick={schedulePost}
                disabled={isScheduling}
                className="w-full"
              >
                <Send className="w-4 h-4 mr-2" />
                {isScheduling ? 'Scheduling...' : 'Schedule Post'}
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Analytics Sidebar */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <TrendingUp className="w-5 h-5" />
                Analytics
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Posts Scheduled</p>
                <p className="text-2xl font-bold">12</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Total Reach</p>
                <p className="text-2xl font-bold">45.2K</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Engagement Rate</p>
                <p className="text-2xl font-bold">8.3%</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Best Times</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="text-sm">
                <p className="font-medium">Twitter</p>
                <p className="text-muted-foreground">9 AM - 11 AM</p>
              </div>
              <div className="text-sm">
                <p className="font-medium">LinkedIn</p>
                <p className="text-muted-foreground">8 AM - 10 AM</p>
              </div>
              <div className="text-sm">
                <p className="font-medium">Instagram</p>
                <p className="text-muted-foreground">6 PM - 8 PM</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Zap, Loader } from 'lucide-react';
import { toast } from 'sonner';

export function SocialMediaScheduler() {
  const [topic, setTopic] = useState('');
  const [platform, setPlatform] = useState('twitter');
  const [caption, setCaption] = useState('');
  const [loading, setLoading] = useState(false);
  const [posts, setPosts] = useState<Array<{ id: number; caption: string; platform: string; scheduled: string }>>([]);

  const generateCaption = async () => {
    if (!topic.trim()) {
      toast.error('Enter a topic');
      return;
    }

    setLoading(true);
    try {
      // Call AI endpoint
      const response = await fetch('/api/trpc/ai.generateSocialCaption', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, platform }),
      });

      const data = await response.json();
      setCaption(data.result?.data?.caption || 'Failed to generate caption');
      toast.success('Caption generated!');
    } catch (error) {
      toast.error('Failed to generate caption');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const schedulePost = () => {
    if (!caption.trim()) {
      toast.error('Generate a caption first');
      return;
    }

    const newPost = {
      id: Date.now(),
      caption,
      platform,
      scheduled: new Date(Date.now() + 24 * 60 * 60 * 1000).toLocaleDateString(),
    };

    setPosts([newPost, ...posts]);
    setCaption('');
    setTopic('');
    toast.success('Post scheduled!');
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold">Social Media Scheduler</h1>
        <p className="text-muted-foreground">AI-powered social media automation</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardContent className="p-6 space-y-4">
              <div>
                <label className="text-sm font-medium">Topic</label>
                <Input
                  placeholder="What do you want to post about?"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  className="mt-2"
                />
              </div>

              <div>
                <label className="text-sm font-medium">Platform</label>
                <select
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  className="w-full mt-2 px-3 py-2 border rounded-md bg-background"
                >
                  <option value="twitter">Twitter/X</option>
                  <option value="linkedin">LinkedIn</option>
                  <option value="instagram">Instagram</option>
                  <option value="tiktok">TikTok</option>
                </select>
              </div>

              <Button
                onClick={generateCaption}
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
                    <Zap className="w-4 h-4 mr-2" />
                    Generate Caption with AI
                  </>
                )}
              </Button>

              {caption && (
                <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4">
                  <p className="text-sm text-muted-foreground mb-2">Generated Caption:</p>
                  <Textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={4} />
                  <Button onClick={schedulePost} className="w-full mt-4 bg-green-600 hover:bg-green-700">
                    Schedule Post
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div>
          <Card>
            <CardContent className="p-6 space-y-4">
              <h3 className="font-bold">Scheduled Posts</h3>
              <div className="space-y-3">
                {posts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No posts scheduled yet</p>
                ) : (
                  posts.map((post) => (
                    <div key={post.id} className="bg-slate-100 dark:bg-slate-800 rounded p-3 text-sm">
                      <p className="font-medium">{post.platform}</p>
                      <p className="text-muted-foreground text-xs mt-1">{post.scheduled}</p>
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

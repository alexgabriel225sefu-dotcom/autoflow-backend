import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Mail, Sparkles, Send, BarChart3 } from 'lucide-react';
import { toast } from 'sonner';

export function EmailMarketing() {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipientList, setRecipientList] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSending, setIsSending] = useState(false);

  const generateSubject = async () => {
    if (!body.trim()) {
      toast.error('Please enter email body first');
      return;
    }

    setIsGenerating(true);
    try {
      const response = await fetch('/api/ai/generate-email-subject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emailBody: body }),
      });

      const data = await response.json();
      if (data.subject) {
        setSubject(data.subject);
        toast.success('Subject line generated!');
      }
    } catch (error) {
      toast.error('Failed to generate subject');
    } finally {
      setIsGenerating(false);
    }
  };

  const sendEmail = async () => {
    if (!subject.trim() || !body.trim() || !recipientList.trim()) {
      toast.error('Please fill all fields');
      return;
    }

    setIsSending(true);
    try {
      const response = await fetch('/api/email/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject,
          body,
          recipients: recipientList.split('\n').filter(e => e.trim()),
        }),
      });

      if (response.ok) {
        toast.success('Email campaign sent!');
        setSubject('');
        setBody('');
        setRecipientList('');
      } else {
        toast.error('Failed to send email');
      }
    } catch (error) {
      toast.error('Error sending email');
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Email Marketing</h1>
        <p className="text-muted-foreground">Create and send AI-powered email campaigns</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mail className="w-5 h-5" />
                Email Composer
              </CardTitle>
              <CardDescription>Write your email campaign</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium">Subject Line</label>
                <Input
                  placeholder="Enter subject or generate with AI..."
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>

              <div>
                <label className="text-sm font-medium">Email Body</label>
                <Textarea
                  placeholder="Write your email content..."
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={8}
                  className="resize-none"
                />
              </div>

              <Button
                onClick={generateSubject}
                disabled={isGenerating}
                variant="outline"
                className="w-full"
              >
                <Sparkles className="w-4 h-4 mr-2" />
                {isGenerating ? 'Generating...' : 'Generate Subject Line'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recipients</CardTitle>
              <CardDescription>Enter email addresses (one per line)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                placeholder="email1@example.com&#10;email2@example.com&#10;email3@example.com"
                value={recipientList}
                onChange={(e) => setRecipientList(e.target.value)}
                rows={6}
                className="resize-none font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                {recipientList.split('\n').filter(e => e.trim()).length} recipients
              </p>

              <Button
                onClick={sendEmail}
                disabled={isSending}
                className="w-full"
              >
                <Send className="w-4 h-4 mr-2" />
                {isSending ? 'Sending...' : 'Send Campaign'}
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <BarChart3 className="w-5 h-5" />
                Campaign Stats
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Emails Sent</p>
                <p className="text-2xl font-bold">1,245</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Open Rate</p>
                <p className="text-2xl font-bold">32%</p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Click Rate</p>
                <p className="text-2xl font-bold">8.5%</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Templates</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" className="w-full justify-start text-left">
                Welcome Series
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                Product Launch
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                Re-engagement
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

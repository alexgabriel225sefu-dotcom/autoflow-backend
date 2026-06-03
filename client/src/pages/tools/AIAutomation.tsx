import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Zap, Plus, Trash2, Play, Settings } from 'lucide-react';
import { toast } from 'sonner';

export function AIAutomation() {
  const [workflows, setWorkflows] = useState([
    { id: 1, name: 'Welcome Email', trigger: 'New signup', status: 'active' },
    { id: 2, name: 'Lead Nurture', trigger: 'Form submission', status: 'active' },
  ]);

  const [newWorkflow, setNewWorkflow] = useState('');

  const addWorkflow = () => {
    if (!newWorkflow.trim()) {
      toast.error('Enter workflow name');
      return;
    }

    setWorkflows([...workflows, {
      id: Date.now(),
      name: newWorkflow,
      trigger: 'Manual',
      status: 'draft',
    }]);
    setNewWorkflow('');
    toast.success('Workflow created!');
  };

  const deleteWorkflow = (id: number) => {
    setWorkflows(workflows.filter(w => w.id !== id));
    toast.success('Workflow deleted');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">AI Automation</h1>
        <p className="text-muted-foreground">Build powerful workflows without coding</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="w-5 h-5" />
                Create Workflow
              </CardTitle>
              <CardDescription>Automate your business processes</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="Workflow name..."
                  value={newWorkflow}
                  onChange={(e) => setNewWorkflow(e.target.value)}
                />
                <Button onClick={addWorkflow}>
                  <Plus className="w-4 h-4 mr-2" />
                  Create
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Active Workflows</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {workflows.map(workflow => (
                <div key={workflow.id} className="flex items-center justify-between p-4 bg-slate-100 dark:bg-slate-800 rounded-lg">
                  <div>
                    <p className="font-medium">{workflow.name}</p>
                    <p className="text-sm text-muted-foreground">Trigger: {workflow.trigger}</p>
                  </div>
                  <div className="flex gap-2">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${workflow.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                      {workflow.status}
                    </span>
                    <Button size="sm" variant="ghost">
                      <Settings className="w-4 h-4" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => deleteWorkflow(workflow.id)}>
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Popular Integrations</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" className="w-full justify-start text-left">
                Slack
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                Gmail
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                Stripe
              </Button>
              <Button variant="outline" className="w-full justify-start text-left">
                Zapier
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Stats</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <p className="text-sm text-muted-foreground">Workflows Running</p>
                <p className="text-2xl font-bold">5</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Tasks Completed</p>
                <p className="text-2xl font-bold">1,234</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function LeadGeneration() {
  const [forms, setForms] = useState([
    { id: 1, name: 'Newsletter Signup', leads: 234, conversion: '3.2%' },
    { id: 2, name: 'Product Demo', leads: 89, conversion: '1.8%' },
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Lead Generation</h1>
        <p className="text-muted-foreground">Create high-converting lead capture forms</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Your Forms</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {forms.map(form => (
                <div key={form.id} className="flex items-center justify-between p-4 bg-slate-100 dark:bg-slate-800 rounded-lg">
                  <div>
                    <p className="font-medium">{form.name}</p>
                    <p className="text-sm text-muted-foreground">{form.leads} leads collected</p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold">{form.conversion}</p>
                    <p className="text-xs text-muted-foreground">Conversion rate</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Total Leads</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-4xl font-bold">323</p>
              <p className="text-sm text-muted-foreground mt-2">↑ 12% this month</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Bell, Search, Trash2, RefreshCw } from 'lucide-react';
import { trpc } from '@/lib/trpc';
import { toast } from 'sonner';

export default function TelegramAlertLog() {
  const { data: alerts, isLoading, refetch } = trpc.alerts.history.useQuery({ limit: 20 });
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<string | null>(null);

  const getAlertIcon = (type: string) => {
    switch (type) {
      case 'TRADE_OPEN':
        return '📈';
      case 'TRADE_CLOSE':
        return '📉';
      case 'STOP_HIT':
        return '🛑';
      case 'DAILY_LIMIT':
        return '⚠️';
      case 'STRATEGY_STOP':
        return '🚫';
      case 'SIGNAL_FILTERED':
        return '🔇';
      default:
        return '📢';
    }
  };

  const getAlertColor = (type: string) => {
    switch (type) {
      case 'TRADE_OPEN':
        return 'bg-green-900/30 border-green-500/30 text-green-300';
      case 'TRADE_CLOSE':
        return 'bg-blue-900/30 border-blue-500/30 text-blue-300';
      case 'STOP_HIT':
        return 'bg-red-900/30 border-red-500/30 text-red-300';
      case 'DAILY_LIMIT':
        return 'bg-orange-900/30 border-orange-500/30 text-orange-300';
      case 'STRATEGY_STOP':
        return 'bg-red-900/30 border-red-500/30 text-red-300';
      case 'SIGNAL_FILTERED':
        return 'bg-yellow-900/30 border-yellow-500/30 text-yellow-300';
      default:
        return 'bg-slate-900/30 border-slate-500/30 text-slate-300';
    }
  };

  const filteredAlerts = alerts?.filter((alert) => {
    const matchesSearch =
      alert.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      alert.content.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesType = !filterType || alert.type === filterType;
    return matchesSearch && matchesType;
  }) || [];

  const alertTypes = alerts
    ? Array.from(new Set(alerts.map((a) => a.type)))
    : [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <Bell className="w-6 h-6 text-orange-400" />
          Telegram Alert Log
        </h2>
        <Button
          onClick={() => refetch()}
          disabled={isLoading}
          variant="outline"
          size="sm"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Search & Filter */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-4">
        <div className="space-y-4">
          {/* Search Box */}
          <div className="relative">
            <Search className="absolute left-3 top-3 w-4 h-4 text-slate-500" />
            <Input
              placeholder="Search alerts..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 bg-slate-700 border-slate-600 text-white"
            />
          </div>

          {/* Type Filter */}
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => setFilterType(null)}
              variant={filterType === null ? 'default' : 'outline'}
              size="sm"
              className={filterType === null ? 'bg-cyan-600' : ''}
            >
              All
            </Button>
            {alertTypes.map((type) => (
              <Button
                key={type}
                onClick={() => setFilterType(type)}
                variant={filterType === type ? 'default' : 'outline'}
                size="sm"
                className={filterType === type ? 'bg-cyan-600' : ''}
              >
                {type}
              </Button>
            ))}
          </div>
        </div>
      </Card>

      {/* Alert List */}
      <div className="space-y-3">
        {isLoading ? (
          <Card className="bg-slate-900/50 border-slate-700/50 p-8 text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mx-auto"></div>
            <p className="text-slate-400 mt-4">Loading alerts...</p>
          </Card>
        ) : filteredAlerts.length > 0 ? (
          filteredAlerts.map((alert) => (
            <Card
              key={alert.id}
              className={`border p-4 transition-all hover:shadow-lg ${getAlertColor(alert.type)}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3 flex-1">
                  {/* Icon */}
                  <span className="text-2xl mt-1">{getAlertIcon(alert.type)}</span>

                  {/* Content */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-semibold text-white">{alert.title}</h4>
                      <Badge variant="outline" className="text-xs">
                        {alert.type}
                      </Badge>
                    </div>
                    <p className="text-sm opacity-90 leading-relaxed">{alert.content}</p>
                    <p className="text-xs opacity-60 mt-2">
                      {new Date(alert.sentAt).toLocaleString()}
                    </p>
                  </div>
                </div>

                {/* Actions */}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-4 hover:bg-red-900/50"
                  title="Delete alert"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </Card>
          ))
        ) : (
          <Card className="bg-slate-900/50 border-slate-700/50 p-8 text-center">
            <Bell className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400">
              {searchTerm || filterType ? 'No alerts match your filters' : 'No alerts yet'}
            </p>
          </Card>
        )}
      </div>

      {/* Summary Stats */}
      {alerts && alerts.length > 0 && (
        <Card className="bg-gradient-to-r from-cyan-900/20 to-orange-900/20 border border-cyan-500/30 p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
            <div>
              <p className="text-slate-400 text-sm">Total Alerts</p>
              <p className="text-2xl font-bold text-white">{alerts.length}</p>
            </div>
            <div>
              <p className="text-slate-400 text-sm">Trade Opens</p>
              <p className="text-2xl font-bold text-green-400">
                {alerts.filter((a) => a.type === 'TRADE_OPEN').length}
              </p>
            </div>
            <div>
              <p className="text-slate-400 text-sm">Trade Closes</p>
              <p className="text-2xl font-bold text-blue-400">
                {alerts.filter((a) => a.type === 'TRADE_CLOSE').length}
              </p>
            </div>
            <div>
              <p className="text-slate-400 text-sm">Stops Hit</p>
              <p className="text-2xl font-bold text-red-400">
                {alerts.filter((a) => a.type === 'STOP_HIT').length}
              </p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

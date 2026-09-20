import { useEffect, useState } from 'react';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { CostComparison } from '../components/Dashboard/CostComparison';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';

function utcStamp(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export function DashboardPage() {
  // Computed once at render, this froze at mount time and then sat under a
  // "Live telemetry" heading contradicting itself — the longer the tab stayed
  // open, the more wrong it got.
  const [stamp, setStamp] = useState(utcStamp);
  useEffect(() => {
    const id = setInterval(() => setStamp(utcStamp()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              System Overview
            </h1>
            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {stamp}
            </div>
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Live telemetry for the on-device inference engine — power draw, token throughput, and cost savings versus cloud APIs.
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          <EnergyDashboard />
          <CostComparison />
        </div>

        <TraceDebugger />
      </div>
    </div>
  );
}

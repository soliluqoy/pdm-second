/**
 * PREDICT — Driving behavior page (Phase 5)
 * Fleet scorecards + per-vehicle drill-in (score trend, events, trips).
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import type { BehaviorScorecard, Trip } from '../types';

function scoreTone(score: number | null | undefined): 'success' | 'warning' | 'danger' | 'neutral' {
  if (score == null) return 'neutral';
  if (score >= 80) return 'success';
  if (score >= 60) return 'warning';
  return 'danger';
}

function formatDuration(secs?: number | null): string {
  if (secs == null) return '—';
  const m = Math.floor(secs / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  return `${m}m`;
}

export default function DrivingPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const summaryQuery = useQuery({
    queryKey: ['behavior', 'summary'],
    queryFn: () => api.getBehaviorSummary(1),
    refetchInterval: 60_000,
  });

  const cards = summaryQuery.data ?? [];

  useEffect(() => {
    if (selectedId == null && cards.length > 0) {
      setSelectedId(cards[0].vehicle_id);
    }
  }, [cards, selectedId]);

  const detailQuery = useQuery({
    queryKey: ['behavior', 'vehicle', selectedId],
    queryFn: () => api.getVehicleBehavior(selectedId!, 14),
    enabled: selectedId != null,
  });

  const tripsQuery = useQuery({
    queryKey: ['behavior', 'trips', selectedId],
    queryFn: () => api.getVehicleTrips(selectedId!, 30),
    enabled: selectedId != null,
  });

  const chartData = useMemo(
    () =>
      (detailQuery.data?.scores ?? []).map((s) => ({
        date: s.date,
        score: s.score,
      })),
    [detailQuery.data]
  );

  const selectedCard: BehaviorScorecard | undefined = cards.find(
    (c) => c.vehicle_id === selectedId
  );

  if (summaryQuery.isLoading) {
    return <LoadingState message="Loading driving scores…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Driving"
        description="Per-vehicle driving scores, events, and trips (device + derived)"
      />

      {cards.length === 0 ? (
        <EmptyState message="Register a vehicle to see driving analytics." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-2">
            <h2 className="section-title">Fleet scorecards</h2>
            <ul className="panel divide-y divide-gray-100">
              {cards.map((c) => (
                <li key={c.vehicle_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(c.vehicle_id)}
                    className={`w-full text-left px-4 py-3 flex items-center justify-between gap-3 hover:bg-gray-50 ${
                      selectedId === c.vehicle_id ? 'bg-predict-50' : ''
                    }`}
                  >
                    <div className="min-w-0">
                      <p className="font-medium text-gray-900 truncate">{c.vehicle_name}</p>
                      <p className="text-xs text-gray-500">
                        {c.trips} trips · {(c.distance_km ?? 0).toFixed(1)} km
                      </p>
                    </div>
                    <Badge tone={scoreTone(c.score)}>
                      {c.score != null ? Math.round(c.score) : '—'}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-2 space-y-6">
            {selectedCard && (
              <>
                <div className="panel p-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">
                      {selectedCard.vehicle_name}
                    </h2>
                    <p className="text-sm text-gray-500">
                      {selectedCard.license_plate || 'No plate'} ·{' '}
                      <Link
                        to={`/vehicles/${selectedCard.vehicle_id}`}
                        className="text-predict-600 hover:underline"
                      >
                        Vehicle details
                      </Link>
                    </p>
                  </div>
                  <Badge tone={scoreTone(selectedCard.score)}>
                    Score {selectedCard.score != null ? Math.round(selectedCard.score) : '—'}
                  </Badge>
                </div>

                <div className="panel p-4">
                  <h3 className="section-title mb-3">Score trend (14 days)</h3>
                  {chartData.length === 0 ? (
                    <p className="text-sm text-gray-500 py-8 text-center">
                      No scored days yet — complete a trip to generate a score.
                    </p>
                  ) : (
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Line
                            type="monotone"
                            dataKey="score"
                            stroke="#2563eb"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>

                <div className="panel p-4">
                  <h3 className="section-title mb-3">Event breakdown (14 days)</h3>
                  {detailQuery.data && Object.keys(detailQuery.data.event_breakdown).length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(detailQuery.data.event_breakdown).map(([k, v]) => (
                        <Badge key={k} tone="neutral">
                          {k.replace(/_/g, ' ')}: {v}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">No driving events in this window.</p>
                  )}
                </div>

                <div className="panel overflow-x-auto">
                  <h3 className="section-title px-4 pt-4 mb-2">Recent trips</h3>
                  {(tripsQuery.data ?? []).length === 0 ? (
                    <p className="text-sm text-gray-500 px-4 pb-4">No trips recorded yet.</p>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Start</th>
                          <th>Distance</th>
                          <th>Duration</th>
                          <th>Max / avg</th>
                          <th>Idle</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(tripsQuery.data as Trip[]).map((t) => (
                          <tr key={t.id}>
                            <td className="whitespace-nowrap">
                              {new Date(t.start_ts).toLocaleString()}
                            </td>
                            <td>{t.distance_km != null ? `${t.distance_km.toFixed(1)} km` : '—'}</td>
                            <td>{formatDuration(t.duration_seconds)}</td>
                            <td>
                              {t.max_speed != null ? Math.round(t.max_speed) : '—'} /{' '}
                              {t.avg_speed != null ? Math.round(t.avg_speed) : '—'} km/h
                            </td>
                            <td>{formatDuration(t.idle_seconds)}</td>
                            <td>
                              <Badge tone={t.is_open ? 'info' : 'neutral'}>
                                {t.is_open ? 'open' : 'closed'}
                              </Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

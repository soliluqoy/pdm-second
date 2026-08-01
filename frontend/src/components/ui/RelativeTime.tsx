/**
 * PREDICT — RelativeTime
 * "updated 12s ago" text that ticks on its own without re-rendering the
 * parent tree (the old dashboard re-rendered every card every second).
 */
import { memo, useEffect, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';

interface Props {
  timestamp?: string | null;
  prefix?: string;
  className?: string;
  intervalMs?: number;
}

function RelativeTimeInner({ timestamp, prefix, className, intervalMs = 5000 }: Props) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);

  const text = timestamp
    ? formatDistanceToNow(new Date(timestamp), { addSuffix: true })
    : 'never';

  return (
    <span className={className}>
      {prefix ? `${prefix} ` : ''}{text}
    </span>
  );
}

const RelativeTime = memo(RelativeTimeInner);
export default RelativeTime;

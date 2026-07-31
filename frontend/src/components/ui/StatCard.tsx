interface Props {
  label: string;
  value: number | string;
  detail?: React.ReactNode;
}

export default function StatCard({ label, value, detail }: Props) {
  return (
    <div className="stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

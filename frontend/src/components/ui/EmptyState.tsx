interface Props {
  message: string;
}

export default function EmptyState({ message }: Props) {
  return (
    <div className="empty-state">
      <p>{message}</p>
    </div>
  );
}

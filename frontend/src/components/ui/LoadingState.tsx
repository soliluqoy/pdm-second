interface Props {
  message?: string;
}

export default function LoadingState({ message = 'Loading…' }: Props) {
  return (
    <div className="page-content flex items-center justify-center min-h-[40vh]">
      <p className="text-gray-600">{message}</p>
    </div>
  );
}

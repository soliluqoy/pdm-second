type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'purple';

const tones: Record<Tone, string> = {
  neutral: 'bg-gray-100 text-gray-700 border-gray-200',
  success: 'bg-green-100 text-green-800 border-green-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  danger: 'bg-red-100 text-red-800 border-red-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
  purple: 'bg-purple-100 text-purple-800 border-purple-200',
};

interface Props {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}

export default function Badge({ children, tone = 'neutral', className = '' }: Props) {
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

interface FilterOption {
  value: string;
  label: string;
}

interface FilterGroup {
  id: string;
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
}

interface Props {
  filters: FilterGroup[];
}

export default function FilterBar({ filters }: Props) {
  return (
    <div className="filter-bar">
      {filters.map((f) => (
        <label key={f.id} className="filter-group">
          <span className="filter-label">{f.label}</span>
          <select
            value={f.value}
            onChange={(e) => f.onChange(e.target.value)}
            className="filter-select"
          >
            {f.options.map((opt) => (
              <option key={opt.value || 'all'} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}

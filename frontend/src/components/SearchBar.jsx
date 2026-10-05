// Controlled search input. The parent debounces the value before fetching.
export default function SearchBar({ value, onChange, placeholder = 'Search players…' }) {
  return (
    <input
      type="search"
      className="search-bar"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label="Search players"
      maxLength={100}
    />
  )
}

import { NavLink } from 'react-router-dom'

const LINKS = [
  { to: '/players', label: 'Players' },
  { to: '/draft', label: 'Draft Picks' },
  { to: '/trade', label: 'Trade Simulator' },
]

export default function Navbar() {
  return (
    <header className="navbar">
      <NavLink to="/players" className="brand">
        Net<span>Value</span>
      </NavLink>
      <nav>
        {LINKS.map(({ to, label }) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? 'active' : undefined)}>
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}

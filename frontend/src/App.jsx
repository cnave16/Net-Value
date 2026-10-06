import { Navigate, Route, Routes } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import DraftPage from './pages/DraftPage.jsx'
import PlayersPage from './pages/PlayersPage.jsx'
import TradePage from './pages/TradePage.jsx'

export default function App() {
  return (
    <>
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/players" replace />} />
          <Route path="/players" element={<PlayersPage />} />
          <Route path="/draft" element={<DraftPage />} />
          <Route path="/trade" element={<TradePage />} />
          <Route path="*" element={<Navigate to="/players" replace />} />
        </Routes>
      </main>
    </>
  )
}

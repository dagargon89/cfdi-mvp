import { Navigate, Outlet } from 'react-router';
import { useAuth } from './AuthContext';

export function RequireAuth() {
  const { loading, usuario } = useAuth();
  if (loading) return null;
  if (!usuario) return <Navigate to="/login" replace />;
  return <Outlet />;
}

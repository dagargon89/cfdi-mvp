// Árbol de rutas — doc 09 §2 (tabla de rutas por pantalla).
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router';
import { AuthProvider } from '@/auth/AuthContext';
import { RequireAdmin } from '@/auth/RequireAdmin';
import { RequireAuth } from '@/auth/RequireAuth';
import { ToastProvider } from '@/components/ui/ToastProvider';
import { AppShell } from '@/components/layout/AppShell';
import { CurrentEmpresaProvider } from '@/empresa/currentEmpresaStore';
import { EmpresaGate, EmpresaProvider } from '@/empresa/EmpresaContext';
import { ConfigBitacoraPage } from '@/features/admin/ConfigBitacoraPage';
import { UsuariosPage } from '@/features/admin/UsuariosPage';
import { AlertasPage } from '@/features/alertas/AlertasPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { RegistroPage } from '@/features/auth/RegistroPage';
import { SignupPage } from '@/features/auth/SignupPage';
import { ComprobantesPage } from '@/features/comprobantes/ComprobantesPage';
import { DescargasPage } from '@/features/descargas/DescargasPage';
import { EfirmaPage } from '@/features/efirma/EfirmaPage';
import { ConfiguracionEmpresaPage } from '@/features/empresas/ConfiguracionEmpresaPage';
import { EmpresasPage } from '@/features/empresas/EmpresasPage';
import { InformesPage } from '@/features/informes/InformesPage';
import { NotificacionesPage } from '@/features/notificaciones/NotificacionesPage';
import { TableroPage } from '@/features/tablero/TableroPage';
import { queryClient } from '@/lib/queryClient';

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/bootstrap" element={<SignupPage />} />
              <Route path="/registro" element={<RegistroPage />} />
              <Route element={<RequireAuth />}>
                {/* La empresa "pegajosa" del sidebar vive aquí: se resetea sola al cerrar sesión
                    (todo este subárbol se desmonta cuando RequireAuth redirige a /login). */}
                <Route element={<CurrentEmpresaProvider><Outlet /></CurrentEmpresaProvider>}>
                  {/* Rutas sin empresa en la URL: AppShell es la raíz del layout. */}
                  <Route element={<AppShell />}>
                    <Route index element={<Navigate to="/empresas" replace />} />
                    <Route path="empresas" element={<EmpresasPage />} />
                    <Route path="admin" element={<RequireAdmin />}>
                      <Route path="usuarios" element={<UsuariosPage />} />
                      <Route path="config" element={<ConfigBitacoraPage />} />
                      <Route path="bitacora" element={<ConfigBitacoraPage />} />
                      <Route path="correo" element={<ConfigBitacoraPage />} />
                    </Route>
                    {/* La configuración fiscal es política federal: aplica a todas las empresas y
                        el backend la restringe a admin (require_admin). La de cada empresa es
                        política laboral suya y vive en /e/:id/configuracion, abierta a operador.
                        Va en su propio guardián porque **el motivo del bloqueo es distinto** y hay
                        que decirlo: quien llega aquí sin ser admin necesita saber que lo que aquí
                        se captura es federal y a dónde ir por lo suyo. Hornear ese texto en el
                        guardián compartido se lo mostraba también a quien abre /admin/bitacora. */}
                    <Route
                      path="admin"
                      element={
                        <RequireAdmin mensaje="La configuración fiscal (UMA, salarios mínimos, tipo de cambio) es la misma para todas las empresas de esta instalación, así que solo un administrador la captura y la confirma. La configuración de tu organización —zona salarial, aguinaldo, prima vacacional y la clasificación de sus conceptos de nómina— sí está a tu alcance, en Empresa → Configuración." />
                      }
                    >
                      <Route path="fiscal" element={<ConfigBitacoraPage />} />
                    </Route>
                  </Route>
                  {/* Rutas de empresa: EmpresaProvider va ANTES de AppShell para que el Sidebar
                      (montado dentro de AppShell) sí vea el contexto de la empresa actual. */}
                  <Route path="e/:id" element={<EmpresaProvider />}>
                    <Route element={<AppShell />}>
                      <Route element={<EmpresaGate />}>
                        <Route index element={<TableroPage />} />
                        <Route path="efirma" element={<EfirmaPage />} />
                        <Route path="descargas" element={<DescargasPage />} />
                        <Route path="descargas/:job" element={<DescargasPage />} />
                        <Route path="comprobantes" element={<ComprobantesPage />} />
                        <Route path="informes" element={<InformesPage />} />
                        <Route path="configuracion" element={<ConfiguracionEmpresaPage />} />
                        <Route path="alertas" element={<AlertasPage />} />
                        <Route path="notificaciones" element={<NotificacionesPage />} />
                      </Route>
                    </Route>
                  </Route>
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/empresas" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

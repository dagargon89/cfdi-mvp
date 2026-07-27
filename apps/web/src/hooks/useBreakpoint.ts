// demo.html:1013,1030-1032,1143-1144 — breakpoints de doc 08 §4 (640 móvil, 1024 sidebar).
import { useEffect, useState } from 'react';

export function useBreakpoint() {
  const [ancho, setAncho] = useState(() => window.innerWidth);

  useEffect(() => {
    const onResize = () => setAncho(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return {
    ancho,
    esMovil: ancho < 640,
    esCompacto: ancho < 1024,
    esEscritorio: ancho >= 640,
  };
}

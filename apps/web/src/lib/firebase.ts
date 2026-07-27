// Init de Firebase Auth — variables VITE_FIREBASE_* (ver .env.example). Si faltan, `firebaseConfigured`
// queda en false y AuthContext muestra un aviso de configuración pendiente en vez de tronar.
import { initializeApp, type FirebaseApp } from 'firebase/app';
import { getAuth, type Auth } from 'firebase/auth';

const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
};

export const firebaseConfigured = Boolean(cfg.apiKey && cfg.authDomain && cfg.projectId && cfg.appId);

let app: FirebaseApp | null = null;
let authInstance: Auth | null = null;

if (firebaseConfigured) {
  app = initializeApp(cfg);
  authInstance = getAuth(app);
}

/** null si VITE_FIREBASE_* no está configurado — usar junto a `firebaseConfigured` antes de llamar. */
export function getFirebaseAuth(): Auth | null {
  return authInstance;
}

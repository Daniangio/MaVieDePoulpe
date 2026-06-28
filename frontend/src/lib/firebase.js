import { initializeApp } from "firebase/app";
import {
  browserLocalPersistence,
  createUserWithEmailAndPassword,
  getAuth,
  onIdTokenChanged,
  setPersistence,
  signInWithEmailAndPassword,
  signOut,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

export const ensureFirebasePersistence = () => setPersistence(auth, browserLocalPersistence);

export const subscribeToIdTokenChanges = (callback) => onIdTokenChanged(auth, callback);

export const signInWithEmail = (email, password) => signInWithEmailAndPassword(auth, email, password);

export const signUpWithEmail = (email, password) => createUserWithEmailAndPassword(auth, email, password);

export const signOutFirebase = () => signOut(auth);

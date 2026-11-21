import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import DocumentWorkspace from './DocumentWorkspace';
import './styles.css';
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {window.location.pathname.startsWith('/legacy') ? <App /> : <DocumentWorkspace />}
  </React.StrictMode>,
);

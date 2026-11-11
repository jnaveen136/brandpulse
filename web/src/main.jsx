import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ViewProvider } from './state'
import './theme.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ViewProvider>
      <App />
    </ViewProvider>
  </React.StrictMode>,
)

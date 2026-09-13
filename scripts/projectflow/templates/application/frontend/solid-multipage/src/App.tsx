import { Navigate, Route, Router } from "@solidjs/router"
import { Layout } from "./Layout"
import { Page1 } from "./routes/page1"
import { Page2 } from "./routes/page2"
import "./app.css"

export function App() {
  return (
    <Router root={Layout}>
      <Route path="/" component={() => <Navigate href="/page1" />} />
      <Route path="/page1" component={Page1} />
      <Route path="/page2" component={Page2} />
      <Route path="*" component={() => <Navigate href="/page1" />} />
    </Router>
  )
}

import { cleanup, fireEvent, render, screen, waitFor } from "@solidjs/testing-library"
import { afterEach, beforeEach, expect, it } from "vitest"
import { App } from "./App"

beforeEach(() => {
  window.history.replaceState({}, "", "/page1")
  localStorage.setItem("app-theme", "light")
})
afterEach(cleanup)

it("navigates between the two empty pages within one main landmark", async () => {
  render(() => <App />)
  expect(screen.getAllByRole("main")).toHaveLength(1)
  expect(screen.getByRole("heading", { name: "Page 1" })).toBeInTheDocument()
  fireEvent.click(screen.getByRole("link", { name: "Page 2" }))
  await waitFor(() => expect(screen.getByRole("heading", { name: "Page 2" })).toBeInTheDocument())
  expect(window.location.pathname).toBe("/page2")
  expect(screen.getByRole("link", { name: "Page 2" })).toHaveAttribute("aria-current", "page")
})

it("persists theme selection", async () => {
  render(() => <App />)
  fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }))
  await waitFor(() => expect(localStorage.getItem("app-theme")).toBe("dark"))
  expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument()
  cleanup()
  render(() => <App />)
  expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument()
})

it.each(["/", "/missing-page"])("redirects %s to Page 1", async (path) => {
  window.history.replaceState({}, "", path)
  render(() => <App />)
  await waitFor(() => expect(window.location.pathname).toBe("/page1"))
  expect(screen.getByRole("heading", { name: "Page 1" })).toBeInTheDocument()
})

import { ColorModeProvider, ColorModeScript, createLocalStorageManager } from "@kobalte/core"
import type { ParentProps } from "solid-js"
import { SidebarInset, SidebarProvider } from "~/components/ui/sidebar"
import { AppSidebar } from "~/components/AppSidebar"
import { Header } from "~/components/Header"

export function Layout(props: ParentProps) {
  const storageManager = createLocalStorageManager("app-theme")
  return (
    <>
      <ColorModeScript initialColorMode="system" storageKey="app-theme" />
      <ColorModeProvider initialColorMode="system" storageManager={storageManager}>
        <a href="#main-content" class="skip-link">Skip to content</a>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset id="main-content" tabIndex={-1} aria-labelledby="page-title" class="h-svh min-w-0 overflow-hidden">
            <Header />
            <div class="flex-1 overflow-y-auto p-6">{props.children}</div>
          </SidebarInset>
        </SidebarProvider>
      </ColorModeProvider>
    </>
  )
}

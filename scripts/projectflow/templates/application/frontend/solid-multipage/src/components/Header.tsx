import { useLocation } from "@solidjs/router"
import { createEffect } from "solid-js"
import { pages } from "./AppSidebar"
import { ModeToggle } from "./ModeToggle"
import { SidebarTrigger } from "~/components/ui/sidebar"
import { Separator } from "~/components/ui/separator"

export function Header() {
  const location = useLocation()
  const title = () => pages.find((page) => page.href === location.pathname)?.title ?? "Page 1"
  createEffect(() => { document.title = `${title()} · Application` })
  return (
    <header class="flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
      <SidebarTrigger class="-ml-1" />
      <Separator orientation="vertical" class="mr-2 h-4" />
      <h1 id="page-title" class="text-sm font-medium">{title()}</h1>
      <div class="ml-auto"><ModeToggle /></div>
    </header>
  )
}

import { A, useLocation } from "@solidjs/router"
import { File } from "lucide-solid"
import { For } from "solid-js"
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar,
} from "~/components/ui/sidebar"

export const pages = [
  { href: "/page1", title: "Page 1" },
  { href: "/page2", title: "Page 2" },
]

export function AppSidebar() {
  const location = useLocation()
  const { setOpenMobile } = useSidebar()
  return (
    <Sidebar>
      <SidebarHeader class="h-16 justify-center border-b border-sidebar-border px-4">
        <span class="text-sm font-semibold">Application</span>
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label="Main navigation">
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                <For each={pages}>{(page) => (
                  <SidebarMenuItem>
                    <SidebarMenuButton as={A} href={page.href}
                      isActive={location.pathname === page.href}
                      onClick={() => setOpenMobile(false)}>
                      <File aria-hidden="true" /><span>{page.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}</For>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </nav>
      </SidebarContent>
    </Sidebar>
  )
}

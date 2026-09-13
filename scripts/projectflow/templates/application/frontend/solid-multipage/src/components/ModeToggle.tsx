import { useColorMode } from "@kobalte/core"
import { Moon, Sun } from "lucide-solid"
import { Show } from "solid-js"
import { Button } from "~/components/ui/button"

export function ModeToggle() {
  const { colorMode, setColorMode } = useColorMode()
  return (
    <Button type="button" variant="ghost" size="icon"
      aria-label={colorMode() === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setColorMode(colorMode() === "dark" ? "light" : "dark")}>
      <Show when={colorMode() === "dark"} fallback={<Moon class="size-5" aria-hidden="true" />}>
        <Sun class="size-5" aria-hidden="true" />
      </Show>
    </Button>
  )
}

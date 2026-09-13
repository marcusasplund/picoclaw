import '@testing-library/jest-dom/vitest'
import { Storage } from 'happy-dom'
import { vi } from 'vitest'

// Node's native storage globals can shadow happy-dom on newer Node versions.
vi.stubGlobal('localStorage', new Storage())
vi.stubGlobal('sessionStorage', new Storage())

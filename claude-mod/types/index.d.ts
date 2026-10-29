export type AliceStatus = { inbox: number; memories: number; date: string }

declare module 'claude-code' {
  interface PluginState {
    'alice-skin': { status: AliceStatus | null }
  }
}
